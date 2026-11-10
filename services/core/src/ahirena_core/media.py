"""Görüntü ve ses yetenek durumu.

Doğrulanmayan OCR veya ses motoru çalışır gibi gösterilmez.
Görüntü, modele yalnızca vision yetenekli model seçildiyse gider; içerik güvenilmez kaynaktır.
"""

from __future__ import annotations

import base64
import hashlib
import shutil
from pathlib import Path

IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
MAX_IMAGE_BYTES = 4_000_000


class MediaError(ValueError):
    pass


def whisper_available() -> bool | str:
    for name in ("whisper-cli", "whisper", "main"):
        found = shutil.which(name)
        if found and "whisper" in Path(found).name.lower():
            return found
    for candidate in (
        Path(r"D:\AI\AhirenaData\whisper\whisper-cli.exe"),
        Path(r"D:\AI\AhirenaData\whisper\main.exe"),
    ):
        if candidate.is_file():
            return str(candidate)
    return False


def media_status(*, vision_models: list[str]) -> dict:
    whisper = whisper_available()
    return {
        "vision": {
            "available": bool(vision_models),
            "models": vision_models,
            "note": "Görüntü yalnızca vision yetenekli modele gider; metin OCR değildir.",
        },
        "ocr": {
            "available": False,
            "status": "planlandı",
            "note": "Ayrı OCR motoru doğrulanmadı.",
        },
        "speech_input": {
            "available": bool(whisper),
            "status": "hazır" if whisper else "planlandı",
            "engine": whisper or None,
            "note": "whisper.cpp adayıdır; Türkçe ölçümü yapılmadan sürekli mikrofon açılmaz.",
        },
        "speech_output": {
            "available": False,
            "status": "planlandı",
            "note": "TTS motoru ve ses lisansı keşifte seçilir.",
        },
        "screen_watch": {
            "available": False,
            "status": "kapalı",
            "note": "Sürekli ekran izleme varsayılan değildir.",
        },
    }


def load_image(path: str) -> dict:
    raw = (path or "").strip().strip('"')
    if not raw:
        raise MediaError("Görüntü yolu boş.")
    p = Path(raw).expanduser().resolve()
    if not p.is_file():
        raise MediaError(f"Görüntü yok: {p}")
    suffix = p.suffix.lower()
    if suffix not in IMAGE_TYPES:
        raise MediaError("Desteklenen görüntüler: png, jpg, jpeg, webp, gif.")
    data = p.read_bytes()
    if not data:
        raise MediaError("Görüntü boş.")
    if len(data) > MAX_IMAGE_BYTES:
        raise MediaError(f"Görüntü {MAX_IMAGE_BYTES} baytı aşıyor.")
    return {
        "path": str(p),
        "media_type": IMAGE_TYPES[suffix],
        "byte_size": len(data),
        "content_hash": hashlib.sha256(data).hexdigest(),
        "base64": base64.b64encode(data).decode("ascii"),
        "untrusted": True,
    }
