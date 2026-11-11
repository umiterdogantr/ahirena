"""Boost: tanımlanmış yüksek kaynak profili (sahte güç artırımı değil)."""

from __future__ import annotations

# Bu cihaz (GTX 1650 4 GB) için temkinli üst sınır; donanım sınırını kaldırmaz.
BOOST_CONTEXT_CAP = 16_384
BOOST_MULTIPLIER = 2

PROFILE = {
    "id": "wide_context",
    "label": "Boost (geniş bağlam)",
    "effect": "Ayarlanan bağlamın en fazla 2 katı; üst sınır 16384 token ve model kapasitesiyle kısıtlı.",
    "remote": False,
    "extra_validation": False,
    "larger_model": False,
    "note": "Daha fazla RAM/VRAM ve süre kullanabilir. GPU bellek sınırını kaldırmaz; uzak servis açmaz.",
}


def describe() -> dict:
    return {
        **PROFILE,
        "context_cap": BOOST_CONTEXT_CAP,
        "multiplier": BOOST_MULTIPLIER,
    }


def resolve_context_length(
    base: int,
    *,
    boost: bool,
    model_context: int | None = None,
) -> dict:
    """Etkin bağlam uzunluğunu ve kullanıcıya gösterilecek özeti üretir."""
    base = max(1024, int(base))
    if not boost:
        effective = base
        if model_context and model_context > 0:
            effective = min(effective, model_context)
        return {
            "boost": False,
            "base_context": base,
            "context_length": effective,
            "model_context": model_context,
            "capped_by_model": bool(model_context and effective < base),
            "profile": None,
            "remote": False,
        }

    target = min(base * BOOST_MULTIPLIER, BOOST_CONTEXT_CAP)
    effective = max(base, target)
    capped_by_model = False
    if model_context and model_context > 0:
        if effective > model_context:
            capped_by_model = True
        effective = min(effective, model_context)
    return {
        "boost": True,
        "base_context": base,
        "context_length": effective,
        "model_context": model_context,
        "capped_by_model": capped_by_model,
        "profile": describe(),
        "remote": False,
        "note": PROFILE["note"],
    }
