from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import __version__
from .config import Settings
from .db import Database
from .ollama_runtime import OllamaRuntime
from .providers import ChatMessage, ChatOptions, ModelProvider, ProviderError, ProviderRegistry
from .providers.ollama import OllamaProvider
from .runs import RunManager, RunResult
from .schemas import (
    AppSettings,
    AppSettingsUpdate,
    ChatRequest,
    CompareRequest,
    Conversation,
    ConversationCreate,
    ConversationUpdate,
    Message,
)
from .security import LocalGuard
from .store import DEFAULT_TITLE, Store

log = logging.getLogger("ahirena.api")

OUTPUT_RESERVE_TOKENS = 1024
CHARS_PER_TOKEN = 3.0  # Türkçe için temkinli kaba tahmin; kesin sayım sağlayıcıdan gelir


class UnloadRequest(BaseModel):
    provider_id: str = Field(default="ollama", max_length=100)
    model_id: str = Field(min_length=1, max_length=200)


class ChatBody(ChatRequest):
    provider_id: str = Field(default="ollama", max_length=100)


class CompareBody(CompareRequest):
    provider_id: str = Field(default="ollama", max_length=100)


def build_context(
    system_prompt: str, history: list[Message], context_length: int
) -> tuple[list[ChatMessage], int]:
    """Bağlam bütçesine sığan en yeni mesajları seçer; dışarıda kalan sayısını döndürür."""
    usable = [
        m
        for m in history
        if m.role == "user" or (m.role == "assistant" and m.status in ("complete", "cancelled") and m.content)
    ]
    budget = max(256, context_length - OUTPUT_RESERVE_TOKENS) * CHARS_PER_TOKEN - len(system_prompt)
    picked: list[ChatMessage] = []
    used = 0.0
    for m in reversed(usable):
        cost = len(m.content) + 16
        if picked and used + cost > budget:
            break
        picked.append(ChatMessage(m.role, m.content))  # type: ignore[arg-type]
        used += cost
    picked.reverse()
    msgs = ([ChatMessage("system", system_prompt)] if system_prompt.strip() else []) + picked
    return msgs, len(usable) - len(picked)


def create_app(
    settings: Settings,
    *,
    providers: list[ModelProvider] | None = None,
    allowed_hosts: set[str] | None = None,
    db: Database | None = None,
) -> FastAPI:
    hosts: set[str] = set(allowed_hosts or ())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = db or Database(settings.db_path)
        store = Store(database)
        recovered = store.recover_interrupted()
        if recovered:
            log.warning("%d yarım kalmış yanıt 'error' olarak işaretlendi", recovered)
        app.state.store = store
        runtime: OllamaRuntime | None = None
        starter: asyncio.Task | None = None
        if providers is None:
            runtime = OllamaRuntime(settings.ollama, settings.log_dir)
            starter = asyncio.create_task(runtime.ensure())
            app.state.registry = ProviderRegistry([OllamaProvider(runtime.url)])
        else:
            app.state.registry = ProviderRegistry(providers)
        app.state.runtime = runtime
        app.state.runs = RunManager()
        try:
            yield
        finally:
            for task in (starter, getattr(app.state, "restart_task", None)):
                if task:
                    task.cancel()
            await app.state.registry.aclose()
            if runtime:
                runtime.stop()
            database.close()

    app = FastAPI(title="Ahirena Core", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.allowed_hosts = hosts
    app.add_middleware(LocalGuard, token=settings.token, allowed_hosts=lambda: app.state.allowed_hosts, max_body_bytes=settings.max_body_bytes)

    def store() -> Store:
        return app.state.store

    def registry() -> ProviderRegistry:
        return app.state.registry

    def provider(provider_id: str) -> ModelProvider:
        try:
            return registry().get(provider_id)
        except ProviderError as e:
            raise HTTPException(400, str(e)) from e

    def conversation_or_404(cid: str) -> Conversation:
        conv = store().get_conversation(cid)
        if not conv:
            raise HTTPException(404, "Oturum bulunamadı.")
        return conv

    async def model_digest(p: ModelProvider, model_id: str) -> str | None:
        try:
            for m in await p.list_models():
                if m.model_id == model_id:
                    return m.digest
        except ProviderError:
            return None
        raise HTTPException(400, f"Model yüklü değil veya bulunamadı: {model_id}")

    async def placement(p: ModelProvider, model_id: str, result: RunResult) -> None:
        for lm in await p.loaded_models():
            if lm.model_id == model_id:
                result.metrics.update(
                    gpu_percent=lm.gpu_percent, model_memory_bytes=lm.size_bytes, model_vram_bytes=lm.vram_bytes
                )

    # --- sistem ---------------------------------------------------------------

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        provs = [(await p.health()).to_dict() for p in registry().all()]
        runtime: OllamaRuntime | None = app.state.runtime
        restarting = getattr(app.state, "restart_task", None)
        if (
            runtime
            and runtime.state in ("managed", "external", "unavailable")
            and not any(p["ok"] for p in provs)
            and (restarting is None or restarting.done())
        ):
            app.state.restart_task = asyncio.create_task(runtime.ensure())
        return {
            "core": {"ok": True, "version": __version__},
            "providers": provs,
            "ollama_runtime": runtime.info() if runtime else None,
            "privacy": {
                "remote_providers_enabled": registry().remote_enabled,
                # Yalnızca Ahirena'nın başlattığı örnekte bulutun kapalı olduğu kesindir.
                "ollama_cloud_disabled": True if runtime and runtime.state == "managed" else None,
                "conversation_storage": "local-sqlite",
            },
            "config_path": str(settings.config_path),
            "data_dir": str(settings.data_dir),
            "active_runs": app.state.runs.active_ids(),
        }

    @app.get("/api/settings")
    async def get_settings() -> AppSettings:
        return store().get_settings()

    @app.patch("/api/settings")
    async def patch_settings(body: AppSettingsUpdate) -> AppSettings:
        return store().update_settings(body.model_dump(exclude_unset=True))

    # --- modeller -------------------------------------------------------------

    @app.get("/api/models")
    async def list_models() -> dict[str, Any]:
        models: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for p in registry().all():
            try:
                models += [m.to_dict() for m in await p.list_models()]
            except ProviderError as e:
                errors.append({"provider_id": p.id, "error": str(e)})
        return {"models": models, "errors": errors}

    @app.get("/api/models/loaded")
    async def loaded_models() -> dict[str, Any]:
        out: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for p in registry().all():
            try:
                out += [m.to_dict() for m in await p.loaded_models()]
            except ProviderError as e:
                errors.append({"provider_id": p.id, "error": str(e)})
        return {"models": out, "errors": errors}

    @app.post("/api/models/unload")
    async def unload_model(body: UnloadRequest) -> dict[str, bool]:
        try:
            await provider(body.provider_id).unload(body.model_id)
        except ProviderError as e:
            raise HTTPException(502, str(e)) from e
        return {"ok": True}

    @app.get("/api/benchmarks")
    async def benchmarks() -> dict[str, Any]:
        reports = sorted(settings.reports_dir.glob("bench-*.json"), reverse=True)
        if not reports:
            return {"report": None, "path": None}
        try:
            return {"report": json.loads(reports[0].read_text(encoding="utf-8")), "path": str(reports[0])}
        except (OSError, ValueError) as e:
            raise HTTPException(500, f"Ölçüm raporu okunamadı: {e}") from e

    # --- oturumlar ------------------------------------------------------------

    @app.get("/api/conversations")
    async def list_conversations(q: str | None = Query(default=None, max_length=200), archived: bool = False) -> list[Conversation]:
        return store().list_conversations(q, archived)

    @app.post("/api/conversations", status_code=201)
    async def create_conversation(body: ConversationCreate) -> Conversation:
        return store().create_conversation(body.title, body.model_id)

    @app.get("/api/conversations/{cid}")
    async def get_conversation(cid: str) -> Conversation:
        return conversation_or_404(cid)

    @app.patch("/api/conversations/{cid}")
    async def update_conversation(cid: str, body: ConversationUpdate) -> Conversation:
        conversation_or_404(cid)
        return store().update_conversation(cid, body.model_dump(exclude_unset=True))  # type: ignore[return-value]

    @app.delete("/api/conversations/{cid}")
    async def delete_conversation(cid: str) -> dict[str, bool]:
        if not store().delete_conversation(cid):
            raise HTTPException(404, "Oturum bulunamadı.")
        return {"ok": True}

    @app.get("/api/conversations/{cid}/messages")
    async def list_messages(cid: str) -> list[Message]:
        conversation_or_404(cid)
        return store().list_messages(cid)

    @app.post("/api/conversations/{cid}/chat")
    async def chat(cid: str, body: ChatBody) -> StreamingResponse:
        conv = conversation_or_404(cid)
        p = provider(body.provider_id)
        digest = await model_digest(p, body.model_id)
        cfg = store().get_settings()
        s = store()

        history = s.list_messages(cid)
        user_msg = s.add_message(cid, "user", body.content, "complete")
        fields: dict[str, Any] = {"model_id": body.model_id}
        if conv.title == DEFAULT_TITLE and not history:
            fields["title"] = " ".join(body.content.split())[:60] or DEFAULT_TITLE
        s.update_conversation(cid, fields)
        assistant = s.add_message(cid, "assistant", "", "streaming", p.id, body.model_id, digest)
        messages, dropped = build_context(cfg.system_prompt, history + [user_msg], cfg.context_length)

        def progress(r: RunResult) -> None:
            s.update_message(assistant.id, content=r.content, thinking=r.thinking, status="streaming")

        def finish(r: RunResult) -> None:
            s.update_message(
                assistant.id,
                content=r.content,
                thinking=r.thinking,
                status=r.status if r.status != "streaming" else "error",
                error=r.error,
                metrics={**r.metrics, "context_dropped_messages": dropped, "num_ctx": cfg.context_length},
            )
            s.touch_conversation(cid)

        async def after(r: RunResult) -> None:
            await placement(p, body.model_id, r)

        stream = app.state.runs.stream(
            p,
            body.model_id,
            messages,
            ChatOptions(think=body.think, context_length=cfg.context_length),
            start_payload={
                "user_message": user_msg.model_dump(),
                "assistant_message_id": assistant.id,
                "context_dropped_messages": dropped,
            },
            on_progress=progress,
            on_finish=finish,
            after_done=after,
        )
        return StreamingResponse(stream, media_type="text/event-stream", headers={"Cache-Control": "no-store"})

    @app.post("/api/compare")
    async def compare(body: CompareBody) -> StreamingResponse:
        p = provider(body.provider_id)
        await model_digest(p, body.model_id)
        cfg = store().get_settings()
        messages = ([ChatMessage("system", cfg.system_prompt)] if cfg.system_prompt.strip() else []) + [
            ChatMessage("user", body.prompt)
        ]

        async def after(r: RunResult) -> None:
            await placement(p, body.model_id, r)

        stream = app.state.runs.stream(
            p,
            body.model_id,
            messages,
            ChatOptions(think=body.think, context_length=cfg.context_length),
            after_done=after,
        )
        return StreamingResponse(stream, media_type="text/event-stream", headers={"Cache-Control": "no-store"})

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> dict[str, bool]:
        return {"cancelled": app.state.runs.cancel(run_id)}

    return app
