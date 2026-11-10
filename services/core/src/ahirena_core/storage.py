"""Yerel disk alanı denetimi (KAB 21). Sessiz uzak geçiş yok."""

from __future__ import annotations

import shutil
from pathlib import Path

# Yedek/aktarım öncesi asgari boş alan; cihaz ölçümü değil, kontrollü hata eşiği.
MIN_FREE_BYTES = 50 * 1024 * 1024


class StorageError(ValueError):
    pass


def disk_status(path: Path) -> dict:
    root = path if path.exists() else path.parent
    root.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(root)
    return {
        "path": str(root.resolve()),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "free_mib": round(usage.free / (1024 * 1024), 1),
        "min_free_bytes": MIN_FREE_BYTES,
        "ok": usage.free >= MIN_FREE_BYTES,
    }


def require_space(path: Path, *, need: int = MIN_FREE_BYTES) -> dict:
    status = disk_status(path)
    if status["free_bytes"] < need:
        raise StorageError(
            f"Disk dolmak üzere: {status['free_mib']} MiB boş "
            f"(en az {round(need / (1024 * 1024), 1)} MiB gerekir). "
            "Uzak modele geçilmez."
        )
    return status
