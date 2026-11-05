"""Ahirena'nın kendi Ollama sunucusunu yönetmesi.

Ollama'nın tepsi uygulaması sunucuyu kullanıcının ortam değişkenleriyle başlatır;
model klasörü, bulut kapatma ve GPU arka ucu Ahirena'nın denetiminde olmaz. Bu
yüzden çekirdek, `config.json` içindeki ayarlarla ayrı bir portta kendi Ollama
örneğini başlatır ve yalnızca kendi başlattığını kapatır.

Komut satırı: `python -m ahirena_core.ollama_runtime pull <model>` gibi Ollama
komutlarını yönetilen örneğe karşı çalıştırır (gerekirse geçici olarak başlatır).
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

from .config import OllamaConfig, Settings

log = logging.getLogger("ahirena.ollama")

READY_TIMEOUT_S = 60.0
LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}


def find_ollama_exe(configured: str | None) -> str | None:
    if configured:
        return configured if Path(configured).is_file() else None
    found = shutil.which("ollama")
    if found:
        return found
    base = os.environ.get("LOCALAPPDATA")
    if base:
        candidate = Path(base) / "Programs" / "Ollama" / "ollama.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def server_env(cfg: OllamaConfig) -> dict[str, str]:
    env = os.environ.copy()
    env["OLLAMA_HOST"] = cfg.host
    env["OLLAMA_NO_CLOUD"] = "1"
    if cfg.models_dir:
        env["OLLAMA_MODELS"] = cfg.models_dir
    if cfg.backend == "vulkan":
        env["OLLAMA_VULKAN"] = "1"
        env["CUDA_VISIBLE_DEVICES"] = "-1"
        env["HIP_VISIBLE_DEVICES"] = "-1"
    return env


class _KillOnCloseJob:
    """Windows iş nesnesi: tutamaç kapanınca (çekirdek ölünce bile) Ollama ve alt süreçleri sonlanır."""

    def __init__(self) -> None:
        self.handle = None
        if sys.platform != "win32":
            return
        import ctypes
        from ctypes import wintypes

        class BASIC(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class EXTENDED(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC),
                ("IoInfo", IO),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._k32 = k32
        handle = k32.CreateJobObjectW(None, None)
        if not handle:
            return
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            k32.CloseHandle(handle)
            return
        self.handle = handle

    def assign(self, proc: subprocess.Popen) -> bool:
        if not self.handle:
            return False
        return bool(self._k32.AssignProcessToJobObject(self.handle, int(proc._handle)))  # type: ignore[attr-defined]

    def close(self) -> None:
        if self.handle:
            self._k32.CloseHandle(self.handle)
            self.handle = None


class OllamaRuntime:
    def __init__(self, cfg: OllamaConfig, log_dir: Path):
        self.cfg = cfg
        self.log_path = log_dir / "ollama.log"
        self.proc: subprocess.Popen | None = None
        self._job: _KillOnCloseJob | None = None
        self._lock = asyncio.Lock()
        self.state = "pending"  # pending | starting | managed | external | unavailable | error
        self.error: str | None = None
        self.exe: str | None = None

    @property
    def url(self) -> str:
        return f"http://{self.cfg.host}"

    def info(self) -> dict:
        return {
            "state": self.state,
            "error": self.error,
            "url": self.url,
            "managed": self.cfg.manage,
            "backend": self.cfg.backend,
            "models_dir": self.cfg.models_dir,
            "exe": self.exe,
            "pid": self.proc.pid if self.proc and self.proc.poll() is None else None,
            "log": str(self.log_path) if self.proc else None,
        }

    async def _reachable(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0, trust_env=False) as c:
                return (await c.get(f"{self.url}/api/version")).status_code == 200
        except httpx.HTTPError:
            return False

    async def ensure(self) -> bool:
        async with self._lock:
            if self.proc and self.proc.poll() is None and await self._reachable():
                return True
            if await self._reachable():
                self.state, self.error = "external", None
                return True
            if not self.cfg.manage:
                self.state, self.error = "unavailable", f"Ollama'ya ulaşılamadı: {self.url}"
                return False
            return await self._start()

    async def _start(self) -> bool:
        hostname = self.cfg.host.rsplit(":", 1)[0]
        if hostname not in LOOPBACK_HOSTS:
            self.state, self.error = "error", f"Yönetilen Ollama yalnızca 127.0.0.1 üzerinde çalışır (ayar: {self.cfg.host})."
            return False
        self.exe = find_ollama_exe(self.cfg.exe)
        if not self.exe:
            self.state, self.error = "error", "ollama.exe bulunamadı. Kurulum: winget install Ollama.Ollama"
            return False
        if self.cfg.models_dir:
            Path(self.cfg.models_dir).mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if self.log_path.exists():
            self.log_path.replace(self.log_path.with_suffix(".prev.log"))

        self.state, self.error = "starting", None
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            with open(self.log_path, "wb") as logf:
                self.proc = subprocess.Popen(
                    [self.exe, "serve"],
                    env=server_env(self.cfg),
                    stdin=subprocess.DEVNULL,
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    creationflags=flags,
                )
        except OSError as e:
            self.state, self.error = "error", f"Ollama başlatılamadı: {e}"
            return False
        self._job = _KillOnCloseJob()
        if not self._job.assign(self.proc):
            log.warning("Ollama iş nesnesine bağlanamadı; çekirdek çökerse elle kapatılması gerekebilir.")
        log.info("Ollama başlatıldı: pid=%d host=%s backend=%s", self.proc.pid, self.cfg.host, self.cfg.backend)

        deadline = time.monotonic() + READY_TIMEOUT_S
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                self.state = "error"
                self.error = f"Ollama kapandı (çıkış {self.proc.returncode}). Günlük: {self.log_path}\n{self._log_tail()}"
                log.error(self.error)
                return False
            if await self._reachable():
                self.state = "managed"
                return True
            await asyncio.sleep(0.25)
        self.state, self.error = "error", f"Ollama {READY_TIMEOUT_S:.0f} sn içinde hazır olmadı. Günlük: {self.log_path}"
        log.error(self.error)
        return False

    def _log_tail(self, lines: int = 8) -> str:
        try:
            return "\n".join(self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
        except OSError:
            return ""

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self._job:
            self._job.close()
            self._job = None
        if self.state == "managed":
            self.state = "pending"


def _cli(argv: list[str]) -> int:
    settings = Settings.local()
    rt = OllamaRuntime(settings.ollama, settings.log_dir)
    if not asyncio.run(rt.ensure()):
        print(rt.error, file=sys.stderr)
        return 1
    exe = rt.exe or find_ollama_exe(settings.ollama.exe)
    if not exe:
        print("ollama.exe bulunamadı.", file=sys.stderr)
        return 1
    print(f"Ollama: {rt.url} ({rt.state}, modeller: {settings.ollama.models_dir or 'varsayılan'})", flush=True)
    try:
        return subprocess.call([exe, *argv], env=server_env(settings.ollama)) if argv else 0
    finally:
        rt.stop()


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
