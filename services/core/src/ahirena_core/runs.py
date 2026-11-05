"""Akışlı model çalıştırmaları ve iptal.

Üretim ayrı bir asyncio görevinde yürür ve olayları kuyruğa yazar. İptal görevi
doğrudan iptal ettiği için model henüz belleğe yüklenirken (hiç parça gelmemişken)
bile bağlantı hemen kapanır ve Ollama üretimi durdurur.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

from .providers import ChatMessage, ChatOptions, ModelProvider, ProviderError

log = logging.getLogger("ahirena.runs")

PERSIST_INTERVAL_S = 1.0
_END = object()


@dataclass
class RunResult:
    content: str = ""
    thinking: str = ""
    status: str = "streaming"
    error: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class Run:
    id: str
    task: asyncio.Task | None = None
    cancel_requested_at: float | None = None


def sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


class RunManager:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}

    def active_ids(self) -> list[str]:
        return list(self._runs)

    def cancel(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if not run or not run.task:
            return False
        run.cancel_requested_at = time.perf_counter()
        run.task.cancel()
        return True

    async def stream(
        self,
        provider: ModelProvider,
        model_id: str,
        messages: list[ChatMessage],
        options: ChatOptions,
        *,
        start_payload: dict[str, Any] | None = None,
        on_progress: Callable[[RunResult], Awaitable[None] | None] | None = None,
        on_finish: Callable[[RunResult], Awaitable[None] | None] | None = None,
        after_done: Callable[[RunResult], Awaitable[None]] | None = None,
    ) -> AsyncIterator[bytes]:
        """SSE baytları üretir: run, notice?, thinking*, token*, done."""
        run = Run(id=str(uuid.uuid4()))
        self._runs[run.id] = run
        queue: asyncio.Queue[Any] = asyncio.Queue()
        result = RunResult()
        started = time.perf_counter()

        async def produce() -> None:
            first_token_at: float | None = None
            last_persist = time.perf_counter()
            try:
                async for ev in provider.chat_stream(model_id, messages, options):
                    if ev.kind == "done":
                        result.metrics.update(ev.stats or {})
                        break
                    if first_token_at is None:
                        first_token_at = time.perf_counter()
                        result.metrics["ttft_ms"] = round((first_token_at - started) * 1000, 1)
                    if ev.kind == "thinking":
                        result.thinking += ev.text
                        await queue.put(("thinking", {"delta": ev.text}))
                    else:
                        result.content += ev.text
                        await queue.put(("token", {"delta": ev.text}))
                    if on_progress and time.perf_counter() - last_persist >= PERSIST_INTERVAL_S:
                        last_persist = time.perf_counter()
                        r = on_progress(result)
                        if asyncio.iscoroutine(r):
                            await r
                result.status = "complete"
            except asyncio.CancelledError:
                result.status = "cancelled"
            except ProviderError as e:
                result.status, result.error = "error", str(e)
            except Exception as e:  # beklenmeyen hata da kullanıcıya görünür olmalı
                log.exception("run %s failed", run.id)
                result.status, result.error = "error", f"Beklenmeyen hata: {e.__class__.__name__}: {e}"
            finally:
                result.metrics["wall_ms"] = round((time.perf_counter() - started) * 1000, 1)
                if run.cancel_requested_at is not None:
                    result.metrics["cancel_latency_ms"] = round((time.perf_counter() - run.cancel_requested_at) * 1000, 1)
                await queue.put(_END)

        finished = False

        async def finish() -> None:
            nonlocal finished
            if finished:
                return
            finished = True
            if on_finish:
                r = on_finish(result)
                if asyncio.iscoroutine(r):
                    await r

        try:
            yield sse("run", {"run_id": run.id, "model_id": model_id, **(start_payload or {})})
            run.task = asyncio.create_task(produce())
            while True:
                item = await queue.get()
                if item is _END:
                    break
                event, data = item
                yield sse(event, data)
            if after_done and result.status == "complete":
                try:
                    await after_done(result)
                except Exception:
                    log.warning("after_done failed for run %s", run.id, exc_info=True)
            await finish()
            yield sse(
                "done",
                {"run_id": run.id, "status": result.status, "error": result.error, "metrics": result.metrics},
            )
        finally:
            # İstemci bağlantısı koparsa üretim de durdurulur ve sonuç kaydedilir.
            if run.task and not run.task.done():
                run.task.cancel()
                try:
                    await run.task
                except asyncio.CancelledError:
                    pass
            if result.status == "streaming":
                result.status = "cancelled"
            await finish()
            self._runs.pop(run.id, None)
