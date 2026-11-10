"""Model sağlayıcı sözleşmesi.

Uygulama mantığı yalnızca bu tiplerle konuşur; sağlayıcıya özgü API ayrıntıları
adaptörün içinde kalır. Yeni bir motor eklemek bu protokolü uygulayan bir sınıf
yazmak ve kayıt defterine eklemekten ibarettir.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, AsyncIterator, Literal, Protocol

Location = Literal["local", "remote"]


@dataclass
class ModelInfo:
    provider_id: str
    model_id: str
    location: Location
    digest: str | None = None
    size_bytes: int | None = None
    family: str | None = None
    parameter_size: str | None = None
    quantization: str | None = None
    context_length: int | None = None
    capabilities: list[str] = field(default_factory=list)
    license_name: str | None = None
    modified_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LoadedModel:
    provider_id: str
    model_id: str
    size_bytes: int
    vram_bytes: int
    expires_at: str | None = None

    @property
    def gpu_percent(self) -> int:
        return round(100 * self.vram_bytes / self.size_bytes) if self.size_bytes else 0

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "gpu_percent": self.gpu_percent}


@dataclass
class ProviderHealth:
    provider_id: str
    location: Location
    ok: bool
    version: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str
    images: list[str] | None = None


@dataclass
class ChatOptions:
    think: bool = False
    context_length: int | None = None


@dataclass
class ChatEvent:
    """Akış olayı. `kind`: thinking | content | done."""

    kind: Literal["thinking", "content", "done"]
    text: str = ""
    stats: dict[str, Any] | None = None


class ProviderError(Exception):
    """Kullanıcıya gösterilebilir, normalleştirilmiş sağlayıcı hatası."""


class ModelProvider(Protocol):
    id: str
    location: Location

    async def health(self) -> ProviderHealth: ...

    async def list_models(self) -> list[ModelInfo]: ...

    async def loaded_models(self) -> list[LoadedModel]: ...

    async def unload(self, model_id: str) -> None: ...

    def chat_stream(
        self, model_id: str, messages: list[ChatMessage], options: ChatOptions
    ) -> AsyncIterator[ChatEvent]: ...

    async def aclose(self) -> None: ...
