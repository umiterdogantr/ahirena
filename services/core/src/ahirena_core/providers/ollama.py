from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from .base import (
    ChatEvent,
    ChatMessage,
    ChatOptions,
    LoadedModel,
    ModelInfo,
    ProviderError,
    ProviderHealth,
)


def _license_name(text: str | None) -> str | None:
    if not text:
        return None
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:120]
    return None


class OllamaProvider:
    """Yerel Ollama sunucusu adaptörü (REST API, resmî SDK'ya bağımlılık yok)."""

    location = "local"

    def __init__(self, base_url: str = "http://127.0.0.1:11434", provider_id: str = "ollama"):
        self.id = provider_id
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(15.0), trust_env=False)
        self._show_cache: dict[str, dict[str, Any]] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get_json(self, method: str, path: str, **kw: Any) -> Any:
        try:
            r = await self._client.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise ProviderError(f"Ollama sunucusuna ulaşılamadı ({self.base_url}): {e.__class__.__name__}") from e
        if r.status_code >= 400:
            raise ProviderError(_error_text(r.status_code, r.text))
        return r.json()

    async def health(self) -> ProviderHealth:
        try:
            data = await self._get_json("GET", "/api/version")
            return ProviderHealth(self.id, "local", True, version=data.get("version"))
        except ProviderError as e:
            return ProviderHealth(self.id, "local", False, error=str(e))

    async def _show(self, model_id: str, digest: str | None = None) -> dict[str, Any]:
        key = f"{model_id}@{digest}"
        if key not in self._show_cache:
            self._show_cache[key] = await self._get_json("POST", "/api/show", json={"model": model_id})
        return self._show_cache[key]

    async def list_models(self) -> list[ModelInfo]:
        data = await self._get_json("GET", "/api/tags")
        out: list[ModelInfo] = []
        for m in data.get("models", []):
            name = m.get("model") or m.get("name")
            if m.get("remote_host") or name.endswith(":cloud") or "-cloud" in name:
                continue
            details = m.get("details") or {}
            info = ModelInfo(
                provider_id=self.id,
                model_id=name,
                location="local",
                digest=m.get("digest"),
                size_bytes=m.get("size"),
                family=details.get("family"),
                parameter_size=details.get("parameter_size"),
                quantization=details.get("quantization_level"),
                modified_at=m.get("modified_at"),
            )
            try:
                show = await self._show(name, info.digest)
                info.capabilities = list(show.get("capabilities") or [])
                info.license_name = _license_name(show.get("license"))
                mi = show.get("model_info") or {}
                arch = mi.get("general.architecture")
                if arch and f"{arch}.context_length" in mi:
                    info.context_length = int(mi[f"{arch}.context_length"])
            except ProviderError:
                pass
            out.append(info)
        out.sort(key=lambda x: x.model_id)
        return out

    async def capabilities(self, model_id: str) -> list[str]:
        show = await self._show(model_id)
        return list(show.get("capabilities") or [])

    async def loaded_models(self) -> list[LoadedModel]:
        data = await self._get_json("GET", "/api/ps")
        return [
            LoadedModel(
                provider_id=self.id,
                model_id=m.get("model") or m.get("name"),
                size_bytes=int(m.get("size") or 0),
                vram_bytes=int(m.get("size_vram") or 0),
                expires_at=m.get("expires_at"),
            )
            for m in data.get("models", [])
        ]

    async def unload(self, model_id: str) -> None:
        await self._get_json("POST", "/api/generate", json={"model": model_id, "keep_alive": 0})

    async def chat_stream(
        self, model_id: str, messages: list[ChatMessage], options: ChatOptions
    ) -> AsyncIterator[ChatEvent]:
        body: dict[str, Any] = {
            "model": model_id,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
        }
        if options.context_length:
            body["options"] = {"num_ctx": options.context_length}
        try:
            caps = await self.capabilities(model_id)
        except ProviderError:
            caps = []
        if "thinking" in caps:
            body["think"] = bool(options.think)

        try:
            async with self._client.stream(
                "POST", "/api/chat", json=body, timeout=httpx.Timeout(15.0, read=None)
            ) as r:
                if r.status_code >= 400:
                    text = (await r.aread()).decode("utf-8", "replace")
                    raise ProviderError(_error_text(r.status_code, text))
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise ProviderError(str(chunk["error"]))
                    msg = chunk.get("message") or {}
                    if msg.get("thinking"):
                        yield ChatEvent("thinking", msg["thinking"])
                    if msg.get("content"):
                        yield ChatEvent("content", msg["content"])
                    if chunk.get("done"):
                        yield ChatEvent("done", stats=_stats(chunk))
                        return
        except httpx.HTTPError as e:
            raise ProviderError(f"Ollama bağlantı hatası: {e.__class__.__name__}") from e
        raise ProviderError("Ollama yanıtı tamamlanmadan kesildi.")


def _error_text(status: int, text: str) -> str:
    try:
        msg = json.loads(text).get("error") or text
    except (ValueError, AttributeError):
        msg = text
    return f"Ollama hatası ({status}): {msg}".strip()


def _stats(chunk: dict[str, Any]) -> dict[str, Any]:
    ns = 1_000_000
    eval_count = chunk.get("eval_count") or 0
    eval_ns = chunk.get("eval_duration") or 0
    return {
        "done_reason": chunk.get("done_reason"),
        "total_ms": round((chunk.get("total_duration") or 0) / ns, 1),
        "load_ms": round((chunk.get("load_duration") or 0) / ns, 1),
        "prompt_tokens": chunk.get("prompt_eval_count"),
        "prompt_eval_ms": round((chunk.get("prompt_eval_duration") or 0) / ns, 1),
        "output_tokens": eval_count,
        "eval_ms": round(eval_ns / ns, 1),
        "tokens_per_s": round(eval_count / (eval_ns / 1e9), 2) if eval_ns else None,
    }
