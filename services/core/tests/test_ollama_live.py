"""Gerçek yerel Ollama ile uçtan uca denemeler. Çalıştırma:

    uv run pytest -m ollama

Model klasörü ve arka uç kullanıcının `%LOCALAPPDATA%\\com.ahirena.desktop\\config.json`
dosyasından alınır; sunucu her testte boş bir portta ayrıca başlatılır.
`AHIRENA_TEST_MODEL` ile model seçilebilir (varsayılan: gemma4:e2b-it-qat).
"""

import asyncio
import dataclasses
import os
import socket
import subprocess
import sys
import textwrap
import time

import pytest

from ahirena_core.config import Settings
from ahirena_core.ollama_runtime import OllamaRuntime
from ahirena_core.providers import ChatMessage, ChatOptions
from ahirena_core.providers.ollama import OllamaProvider

MODEL = os.environ.get("AHIRENA_TEST_MODEL", "gemma4:e2b-it-qat")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _runtime(tmp_path) -> OllamaRuntime:
    user = Settings.local().ollama
    cfg = dataclasses.replace(user, manage=True, host=f"127.0.0.1:{_free_port()}")
    return OllamaRuntime(cfg, tmp_path / "logs")


def _pid_alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
    return str(pid) in out.stdout


@pytest.mark.ollama
def test_real_local_turkish_answer(tmp_path):
    async def run():
        rt = _runtime(tmp_path)
        assert await rt.ensure(), rt.error
        assert rt.state == "managed"
        p = OllamaProvider(rt.url)
        try:
            models = {m.model_id: m for m in await p.list_models()}
            assert MODEL in models, f"{MODEL} yüklü değil (model klasörü: {rt.cfg.models_dir})"
            text, stats = "", None
            msgs = [ChatMessage("user", "Türkiye'nin başkenti neresidir? Tek cümleyle yanıtla.")]
            async for ev in p.chat_stream(MODEL, msgs, ChatOptions(think=False, context_length=4096)):
                if ev.kind == "content":
                    text += ev.text
                elif ev.kind == "done":
                    stats = ev.stats
            loaded = {m.model_id: m for m in await p.loaded_models()}
            return text, stats, loaded.get(MODEL), rt.log_path.read_text(encoding="utf-8", errors="replace")
        finally:
            await p.aclose()
            rt.stop()

    text, stats, loaded, server_log = asyncio.run(run())
    print("\nYanıt:", text, "\nİstatistik:", stats, "\nGPU payı:", loaded and loaded.gpu_percent)
    assert "Ankara" in text
    assert stats and stats["output_tokens"] > 0
    assert loaded is not None
    assert "Ollama cloud disabled: true" in server_log


@pytest.mark.ollama
def test_managed_ollama_dies_with_core(tmp_path):
    """Çekirdek zorla öldürülse bile başlattığı Ollama sahipsiz kalmamalı."""
    port = _free_port()
    script = textwrap.dedent(
        f"""
        import asyncio, dataclasses, pathlib, time
        from ahirena_core.config import Settings
        from ahirena_core.ollama_runtime import OllamaRuntime
        cfg = dataclasses.replace(Settings.local().ollama, manage=True, host="127.0.0.1:{port}")
        rt = OllamaRuntime(cfg, pathlib.Path(r"{tmp_path}"))
        assert asyncio.run(rt.ensure()), rt.error
        print(rt.proc.pid, flush=True)
        time.sleep(600)
        """
    )
    child = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    line = child.stdout.readline().strip()
    if not line.isdigit():
        child.kill()
        raise AssertionError(f"Ollama başlatılamadı: {line!r} {child.stderr.read()[-2000:]}")
    ollama_pid = int(line)
    assert _pid_alive(ollama_pid)
    child.kill()
    child.wait(10)
    deadline = time.monotonic() + 10
    while _pid_alive(ollama_pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not _pid_alive(ollama_pid), "Ollama, çekirdek öldükten sonra çalışmaya devam ediyor"
