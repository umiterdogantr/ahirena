"""PyInstaller ile üretilen çekirdek paketinin gerçekten başladığını doğrular.

    uv run pytest -m packaged
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

EXE = Path(__file__).parents[1] / "build" / "dist" / "ahirena-core.exe"
TOKEN = "p" * 48


@pytest.mark.packaged
def test_packaged_core_starts_and_answers(tmp_path):
    assert EXE.exists(), f"Paket yok: {EXE} (önce scripts\\build.cmd)"
    (tmp_path / "config.json").write_text(json.dumps({"ollama": {"manage": False, "host": "127.0.0.1:9"}}), encoding="utf-8")
    env = {**os.environ, "AHIRENA_TOKEN": TOKEN, "AHIRENA_DATA_DIR": str(tmp_path), "AHIRENA_PARENT_PID": str(os.getpid())}
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.Popen([str(EXE)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=flags)
    try:
        started = time.perf_counter()
        line = proc.stdout.readline()
        startup_s = time.perf_counter() - started
        if not line.startswith("AHIRENA_READY port="):
            proc.kill()
            raise AssertionError(f"Hazır satırı gelmedi: {line!r}\n{proc.stderr.read()[-3000:]}")
        port = int(line.strip().split("=")[1])
        r = httpx.get(f"http://127.0.0.1:{port}/api/health", headers={"Authorization": f"Bearer {TOKEN}"}, trust_env=False, timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body["core"]["ok"] is True
        assert body["ollama_runtime"]["url"] == "http://127.0.0.1:9"
        assert (tmp_path / "data" / "ahirena.db").exists()
        print(f"\nPaketli çekirdek {startup_s:.1f} sn'de hazır oldu.")
    finally:
        proc.kill()
        proc.wait(10)
