"""Seçilmiş klasör kökünün dışına çıkan dosya okuma ve yazmasını engeller."""

from __future__ import annotations

import hashlib
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


def _inside(roots: list[str], relative: str) -> Path:
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
        if inside:
            return candidate
    raise FileRejected("Dosya izin verilen klasörlerin dışında.")


def existing_hash(roots: list[str], relative: str) -> str:
    path = _inside(roots, relative)
    if not path.exists():
        return "missing"
    if not path.is_file():
        raise FileRejected("Hedef bir dosya değil.")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_inside(roots: list[str], relative: str, content: str, *, expected_hash: str) -> dict:
    path = _inside(roots, relative)
    current = existing_hash(roots, relative)
    if current != expected_hash:
        raise FileRejected("Dosya değişmiş; eski onay geçersiz.")
    data = content.encode("utf-8")
    if len(data) > MAX_BYTES:
        raise FileRejected(f"Yazılacak içerik {MAX_BYTES} baytı aşıyor.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.commonpath([str(path.parent.resolve()), str(path.resolve())]) != str(path.parent.resolve()):
        raise FileRejected("Üst klasöre çıkış kabul edilmez.")
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    return {"path": str(path), "bytes": len(data), "content_hash": digest}
