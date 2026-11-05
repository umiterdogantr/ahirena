from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger("ahirena.config")

BACKENDS = ("auto", "vulkan")


APP_ID = "com.ahirena.desktop"
LEGACY_DIR_NAME = "Ahirena"  # kurulum klasörüyle çakıştığı için bırakıldı
LEGACY_ITEMS = ("data", "logs", "reports", "config.json")


def default_data_dir() -> Path:
    explicit = os.environ.get("AHIRENA_DATA_DIR")
    if explicit:
        return Path(explicit)
    base = Path(os.environ.get("LOCALAPPDATA") or str(Path.home()))
    target = base / APP_ID
    _migrate_legacy(base / LEGACY_DIR_NAME, target)
    return target


def _migrate_legacy(old: Path, new: Path) -> None:
    """Eski `%LOCALAPPDATA%\\Ahirena` verisini bir kez yeni klasöre taşır; yeni klasörde olanın üzerine yazmaz."""
    if not old.is_dir():
        return
    for name in LEGACY_ITEMS:
        src, dst = old / name, new / name
        if src.exists() and not dst.exists():
            new.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(src), str(dst))
                log.info("Eski veri taşındı: %s -> %s", src, dst)
            except OSError as e:
                log.warning("Eski veri taşınamadı (%s): %s", src, e)


@dataclass(frozen=True)
class OllamaConfig:
    manage: bool = True
    host: str = "127.0.0.1:11435"
    exe: str | None = None
    models_dir: str | None = None
    backend: str = "auto"

    @classmethod
    def from_dict(cls, raw: dict) -> "OllamaConfig":
        known = {k: raw[k] for k in cls.__dataclass_fields__ if k in raw}
        cfg = cls(**known)
        if cfg.backend not in BACKENDS:
            raise ValueError(f"ollama.backend şunlardan biri olmalı: {', '.join(BACKENDS)}")
        return cfg


def load_ollama_config(data_dir: Path) -> OllamaConfig:
    """`<veri klasörü>/config.json` dosyasını okur; yoksa varsayılanlarla oluşturur."""
    path = data_dir / "config.json"
    if not path.exists():
        data_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"ollama": asdict(OllamaConfig())}, indent=2), encoding="utf-8")
        return OllamaConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        return OllamaConfig.from_dict(raw.get("ollama") or {})
    except (OSError, ValueError, TypeError) as e:
        raise SystemExit(f"Ayar dosyası okunamadı ({path}): {e}") from e


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    token: str
    max_body_bytes: int = 1_000_000
    parent_pid: int | None = None
    ollama: OllamaConfig = field(default_factory=OllamaConfig)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "data" / "ahirena.db"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def config_path(self) -> Path:
        return self.data_dir / "config.json"

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.environ.get("AHIRENA_TOKEN", "")
        if len(token) < 32:
            raise SystemExit("AHIRENA_TOKEN ortam değişkeni en az 32 karakter olmalı.")
        parent = os.environ.get("AHIRENA_PARENT_PID")
        data_dir = default_data_dir()
        return cls(
            data_dir=data_dir,
            token=token,
            parent_pid=int(parent) if parent else None,
            ollama=load_ollama_config(data_dir),
        )

    @classmethod
    def local(cls) -> "Settings":
        """Komut satırı araçları için (HTTP sunucusu açmayan, belirteç gerektirmeyen)."""
        data_dir = default_data_dir()
        return cls(data_dir=data_dir, token="", ollama=load_ollama_config(data_dir))
