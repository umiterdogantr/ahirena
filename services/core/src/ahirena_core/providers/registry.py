from __future__ import annotations

from .base import ModelProvider, ProviderError


class ProviderRegistry:
    """Etkin sağlayıcıların listesi.

    Uzak sağlayıcılar yalnızca kullanıcı açıkça etkinleştirdiğinde kayda eklenir;
    yerel sağlayıcı hata verdiğinde başka bir sağlayıcıya geçiş yapılmaz.
    """

    def __init__(self, providers: list[ModelProvider]):
        self._providers = {p.id: p for p in providers}

    def get(self, provider_id: str) -> ModelProvider:
        try:
            return self._providers[provider_id]
        except KeyError:
            raise ProviderError(f"Sağlayıcı etkin değil: {provider_id}") from None

    def all(self) -> list[ModelProvider]:
        return list(self._providers.values())

    @property
    def remote_enabled(self) -> bool:
        return any(p.location == "remote" for p in self._providers.values())

    async def aclose(self) -> None:
        for p in self._providers.values():
            await p.aclose()
