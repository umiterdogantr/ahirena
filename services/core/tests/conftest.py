"""Test altyapısı.

`FakeProvider` yalnızca yazılım sözleşmesini (akış, iptal, kalıcılık, güvenlik)
sınamak içindir; model kalitesi veya hızı hakkında bilgi vermez.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from pathlib import Path
from typing import AsyncIterator

import httpx
import pytest
import uvicorn

from ahirena_core.app import create_app
from ahirena_core.config import Settings
from ahirena_core.providers import ChatEvent, ChatMessage, ChatOptions, LoadedModel, ModelInfo, ProviderHealth

TOKEN = "t" * 48


class FakeProvider:
    id = "fake"
    location = "local"

    def __init__(self, tokens: list[str] | None = None, delay: float = 0.01, load_delay: float = 0.0):
        self.tokens = tokens or ["Mer", "ha", "ba", "!"]
        self.delay = delay
        self.load_delay = load_delay
        self.last_messages: list[ChatMessage] = []
        self.cancelled = threading.Event()

    async def health(self) -> ProviderHealth:
        return ProviderHealth(self.id, "local", True, version="fake-1")

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(self.id, "fake-model", "local", digest="sha256:fake", capabilities=["completion", "thinking"])]

    async def loaded_models(self) -> list[LoadedModel]:
        return [LoadedModel(self.id, "fake-model", 100, 75)]

    async def unload(self, model_id: str) -> None:
        return None

    async def chat_stream(self, model_id: str, messages: list[ChatMessage], options: ChatOptions) -> AsyncIterator[ChatEvent]:
        self.last_messages = messages
        try:
            if self.load_delay:
                await asyncio.sleep(self.load_delay)
            if options.think:
                yield ChatEvent("thinking", "düşünüyorum")
            for t in self.tokens:
                await asyncio.sleep(self.delay)
                yield ChatEvent("content", t)
            yield ChatEvent("done", stats={"output_tokens": len(self.tokens), "tokens_per_s": 99.0})
        except asyncio.CancelledError:
            self.cancelled.set()
            raise

    async def aclose(self) -> None:
        return None


class LiveServer:
    def __init__(self, tmp_path: Path, provider: FakeProvider):
        self.provider = provider
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        self.host = f"127.0.0.1:{self.port}"
        settings = Settings(data_dir=tmp_path, token=TOKEN)
        app = create_app(settings, providers=[provider], allowed_hosts={self.host})
        self.server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False))
        self.thread = threading.Thread(target=lambda: asyncio.run(self.server.serve(sockets=[sock])), daemon=True)
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("test sunucusu başlamadı")
            time.sleep(0.02)
        self.url = f"http://{self.host}"

    def client(self, token: str | None = TOKEN, timeout: float = 10) -> httpx.Client:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return httpx.Client(base_url=self.url, headers=headers, timeout=timeout, trust_env=False)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def live(tmp_path: Path, provider: FakeProvider):
    srv = LiveServer(tmp_path, provider)
    try:
        yield srv
    finally:
        srv.stop()


def parse_sse(lines: list[str]) -> list[tuple[str, dict]]:
    import json

    events: list[tuple[str, dict]] = []
    event = None
    for line in lines:
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: ") and event:
            events.append((event, json.loads(line[6:])))
            event = None
    return events
