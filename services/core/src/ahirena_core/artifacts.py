"""Üretilmiş çıktı kayıtları.

Dosya yoksa bağlantı üretilmez. Önizleme yalnızca mevcut dosya içindir.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from .db import Database, utcnow

PREVIEW_BYTES = 8_000


class ArtifactError(ValueError):
    pass


def register_file(
    db: Database,
    path: str | Path,
    *,
    kind: str,
    title: str | None = None,
    media_type: str = "application/octet-stream",
    task_id: str | None = None,
) -> dict:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise ArtifactError(f"Çıktı dosyası yok: {p}")
    data = p.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    existing = db.query_one(
        "SELECT * FROM artifacts WHERE path = ? AND content_hash = ? ORDER BY version DESC",
        (str(p), digest),
    )
    if existing:
        return _row(existing, exists=True)
    prev = db.query_one("SELECT MAX(version) AS v FROM artifacts WHERE path = ?", (str(p),))
    version = int(prev["v"] or 0) + 1 if prev else 1
    now = utcnow()
    aid = uuid.uuid4().hex
    with db.transaction() as c:
        c.execute(
            """INSERT INTO artifacts
               (id, kind, title, path, media_type, byte_size, content_hash, task_id, version, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (aid, kind, title or p.name, str(p), media_type, len(data), digest, task_id, version, now),
        )
    return get(db, aid)


def list_artifacts(db: Database) -> list[dict]:
    rows = db.query("SELECT * FROM artifacts ORDER BY created_at DESC")
    return [_row(r) for r in rows]


def get(db: Database, artifact_id: str) -> dict:
    row = db.query_one("SELECT * FROM artifacts WHERE id = ?", (artifact_id,))
    if row is None:
        raise ArtifactError("Çıktı yok.")
    return _row(row)


def preview(db: Database, artifact_id: str) -> dict:
    art = get(db, artifact_id)
    p = Path(art["path"])
    if not p.is_file():
        raise ArtifactError("Dosya diskte yok; bağlantı geçersiz.")
    raw = p.read_bytes()[: PREVIEW_BYTES + 1]
    truncated = len(raw) > PREVIEW_BYTES
    text = raw[:PREVIEW_BYTES].decode("utf-8", "replace")
    return {**art, "exists": True, "preview": text, "preview_truncated": truncated}


def diff(db: Database, artifact_id: str) -> dict:
    art = get(db, artifact_id)
    rows = db.query(
        "SELECT id, version, content_hash, byte_size, created_at FROM artifacts WHERE path = ? ORDER BY version",
        (art["path"],),
    )
    return {
        "path": art["path"],
        "versions": [dict(r) for r in rows],
        "note": "İçerik farkı yalnızca özet düzeyindedir; satır satır diff üretilmez.",
    }


def _row(row, *, exists: bool | None = None) -> dict:
    path = Path(row["path"])
    on_disk = path.is_file() if exists is None else exists
    return {
        "id": row["id"],
        "kind": row["kind"],
        "title": row["title"],
        "path": row["path"],
        "media_type": row["media_type"],
        "byte_size": row["byte_size"],
        "content_hash": row["content_hash"],
        "task_id": row["task_id"],
        "version": row["version"],
        "created_at": row["created_at"],
        "exists": on_disk,
    }
