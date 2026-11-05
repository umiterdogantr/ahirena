"""Seçilmiş klasör kökünün dışına çıkan dosya okumasını engeller."""

from __future__ import annotations

import os
from pathlib import Path

MAX_BYTES = 200_000


class FileRejected(ValueError):
    pass


def validate_root(path: str) -> Path:
    raw = (path or "").strip().strip('"')
    if not raw:
        raise FileRejected("Klasör yolu boş.")
    p = Path(raw).expanduser().resolve()
    if not p.is_dir():
        raise FileRejected(f"Klasör yok: {p}")
    if p == Path(p.anchor):
        raise FileRejected("Sürücü kökü izin kökü olamaz.")
    return p


def read_inside(roots: list[str], relative: str) -> dict:
    rel = (relative or "").strip().replace("/", "\\")
    if not rel or rel.startswith("\\") or ":" in rel:
        raise FileRejected("Yol, izin köküne göreli olmalı.")
    parts = Path(rel).parts
    if any(part in ("..", "") for part in parts):
        raise FileRejected("Üst klasöre çıkış kabul edilmez.")
    for root_s in roots:
        root = Path(root_s).resolve()
        candidate = (root / rel).resolve()
        try:
            inside = os.path.commonpath([str(root), str(candidate)]) == str(root)
        except ValueError:
            inside = False
        if not inside:
            continue
        if not candidate.is_file():
            raise FileRejected(f"Dosya yok: {rel}")
        data = candidate.read_bytes()[: MAX_BYTES + 1]
        truncated = len(data) > MAX_BYTES
        text = data[:MAX_BYTES].decode("utf-8", "replace")
        return {"path": str(candidate), "text": text, "truncated": truncated}
    raise FileRejected("Dosya izin verilen klasörlerin dışında.")
