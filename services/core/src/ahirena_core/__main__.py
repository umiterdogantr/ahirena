"""Çekirdeği başlatır.

Masaüstü kabuğu çekirdeği `AHIRENA_TOKEN` ve `AHIRENA_PARENT_PID` ortam
değişkenleriyle çalıştırır. Çekirdek 127.0.0.1 üzerinde işletim sisteminin
verdiği boş bir porta bağlanır ve hazır olduğunda stdout'a tek satır yazar:

    AHIRENA_READY port=<port>
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys
from logging.handlers import RotatingFileHandler

import uvicorn

from .app import create_app
from .config import Settings
from .export import apply_pending_restore


def _setup_logging(settings: Settings) -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(settings.log_dir / "core.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _process_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        SYNCHRONIZE = 0x00100000
        WAIT_TIMEOUT = 0x102
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(SYNCHRONIZE, False, pid)
        if not h:
            return False
        try:
            return k32.WaitForSingleObject(h, 0) == WAIT_TIMEOUT
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


async def _watch_parent(pid: int, server: uvicorn.Server) -> None:
    while not server.should_exit:
        if not _process_alive(pid):
            logging.getLogger("ahirena").warning("Üst süreç (%d) kapandı; çekirdek kapanıyor.", pid)
            server.should_exit = True
            return
        await asyncio.sleep(2)


async def _serve(settings: Settings) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    app = create_app(settings, allowed_hosts={f"127.0.0.1:{port}"})
    config = uvicorn.Config(app, log_config=None, access_log=False, lifespan="on", timeout_graceful_shutdown=3)
    server = uvicorn.Server(config)

    async def announce() -> None:
        while not server.started:
            if server.should_exit:
                return
            await asyncio.sleep(0.05)
        print(f"AHIRENA_READY port={port}", flush=True)

    tasks = [asyncio.create_task(announce())]
    if settings.parent_pid:
        tasks.append(asyncio.create_task(_watch_parent(settings.parent_pid, server)))
    try:
        await server.serve(sockets=[sock])
    finally:
        for t in tasks:
            t.cancel()


def main() -> None:
    settings = Settings.from_env()
    _setup_logging(settings)
    logging.getLogger("ahirena").info("Çekirdek başlıyor; veri klasörü: %s", settings.data_dir)
    restored = apply_pending_restore(settings.data_dir)
    if restored:
        logging.getLogger("ahirena").info("Geri yükleme: %s", restored)
    asyncio.run(_serve(settings))


if __name__ == "__main__":
    main()
