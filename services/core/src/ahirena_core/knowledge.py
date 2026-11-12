"""Kullanıcı hafızası ve belge indeksi.

Konuşma geçmişi buraya yazılmaz. Model tahmini onaylanmış kayıt sayılmaz.
Vektör indeksi yokken arama yalnızca sözcük indeksidir; skor uydurulmaz.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import uuid
from pathlib import Path

from .db import Database, utcnow
from .textnorm import search_key

INDEX_VERSION = "fts-1"
VECTOR_STATE = "yok"
MERGE_RULE = "fts-only"
MAX_BYTES = 200_000
CHUNK_CHARS = 800
TEXT_SUFFIXES = {".txt", ".md", ".markdown"}
REFUSED_SUFFIXES = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".png", ".jpg", ".jpeg", ".gif", ".webp"}


class KnowledgeError(ValueError):
    pass


def _id() -> str:
    return uuid.uuid4().hex


def _require_workspace(db: Database, workspace_id: str) -> None:
    if not db.query_one("SELECT id FROM workspaces WHERE id = ?", (workspace_id,)):
        raise KnowledgeError("Çalışma alanı yok.")


def list_workspaces(db: Database) -> list[dict]:
    rows = db.query("SELECT id, name, created_at, updated_at FROM workspaces ORDER BY name")
    return [dict(r) for r in rows]


def create_workspace(db: Database, name: str) -> dict:
    clean = (name or "").strip()
    if not clean:
        raise KnowledgeError("Çalışma alanı adı boş.")
    now = utcnow()
    wid = _id()
    with db.transaction() as c:
        c.execute(
            "INSERT INTO workspaces (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (wid, clean, now, now),
        )
    return {"id": wid, "name": clean, "created_at": now, "updated_at": now}


def _fts_query(text: str, op: str = "AND") -> str:
    tokens = [re.sub(r"[^0-9a-z]+", "", t) for t in search_key(text).split()]
    tokens = [t for t in tokens if t]
    if not tokens:
        raise KnowledgeError("Arama metni boş.")
    joiner = " AND " if op == "AND" else " OR "
    return joiner.join(f'"{t}"*' for t in tokens)


def _index_meta() -> dict:
    return {"index": INDEX_VERSION, "vector": VECTOR_STATE, "merge": MERGE_RULE}


def list_memory(db: Database, workspace_id: str) -> list[dict]:
    _require_workspace(db, workspace_id)
    rows = db.query(
        """
        SELECT id, workspace_id, body, source_ref, status, verified, created_at, updated_at
        FROM memory_items WHERE workspace_id = ? ORDER BY updated_at DESC
        """,
        (workspace_id,),
    )
    return [dict(r) for r in rows]


def find_similar_memory(db: Database, workspace_id: str, body: str, *, exclude_id: str | None = None, limit: int = 5) -> list[dict]:
    """Aynı alanda benzer aktif kayıtları bulur; üzerine yazma yoktur."""
    _require_workspace(db, workspace_id)
    text = (body or "").strip()
    if not text:
        return []
    tokens = [re.sub(r"[^0-9a-z]+", "", t) for t in search_key(text).split()]
    tokens = [t for t in tokens if len(t) >= 3][:8]
    if not tokens:
        return []
    # OR ile aday bul; tek ortak sözcük yeter (çelişki uyarısı için)
    expr = " OR ".join(f'"{t}"*' for t in tokens)
    rows = db.query(
        """
        SELECT m.id, m.body, m.source_ref, m.status, m.updated_at, bm25(memory_fts) AS rank
        FROM memory_fts
        JOIN memory_items m ON m.id = memory_fts.memory_id
        WHERE memory_fts MATCH ? AND m.workspace_id = ? AND m.status = 'active'
        ORDER BY rank
        LIMIT ?
        """,
        (expr, workspace_id, limit + (1 if exclude_id else 0)),
    )
    out: list[dict] = []
    for r in rows:
        if exclude_id and r["id"] == exclude_id:
            continue
        out.append(
            {
                "id": r["id"],
                "body": r["body"],
                "source_ref": r["source_ref"],
                "status": r["status"],
                "updated_at": r["updated_at"],
            }
        )
        if len(out) >= limit:
            break
    return out


def add_memory(db: Database, workspace_id: str, body: str, source_ref: str) -> dict:
    _require_workspace(db, workspace_id)
    text = (body or "").strip()
    source = (source_ref or "").strip()
    if not text:
        raise KnowledgeError("Hafıza metni boş.")
    if not source:
        raise KnowledgeError("Kaynak zorunlu. Model tahmini kayıt edilmez.")
    similar_before = find_similar_memory(db, workspace_id, text)
    now = utcnow()
    mid = _id()
    with db.transaction() as c:
        c.execute(
            """
            INSERT INTO memory_items (id, workspace_id, body, source_ref, status, verified, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'active', 1, ?, ?)
            """,
            (mid, workspace_id, text, source, now, now),
        )
        c.execute(
            "INSERT INTO memory_fts (search_text, memory_id, workspace_id) VALUES (?, ?, ?)",
            (search_key(text), mid, workspace_id),
        )
    return {
        "id": mid,
        "workspace_id": workspace_id,
        "body": text,
        "source_ref": source,
        "status": "active",
        "verified": 1,
        "created_at": now,
        "updated_at": now,
        "similar": similar_before,
        "note": (
            "Yeni kayıt eklendi; benzer kayıtların üzerine yazılmadı. Kaynaklarıyla birlikte inceleyin."
            if similar_before
            else None
        ),
    }


def update_memory(db: Database, memory_id: str, body: str, source_ref: str) -> dict:
    row = db.query_one("SELECT * FROM memory_items WHERE id = ?", (memory_id,))
    if row is None:
        raise KnowledgeError("Hafıza kaydı yok.")
    text = (body or "").strip()
    source = (source_ref or "").strip()
    if not text or not source:
        raise KnowledgeError("Metin ve kaynak zorunlu.")
    now = utcnow()
    with db.transaction() as c:
        c.execute(
            "UPDATE memory_items SET body = ?, source_ref = ?, updated_at = ? WHERE id = ?",
            (text, source, now, memory_id),
        )
        c.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
        if row["status"] == "active":
            c.execute(
                "INSERT INTO memory_fts (search_text, memory_id, workspace_id) VALUES (?, ?, ?)",
                (search_key(text), memory_id, row["workspace_id"]),
            )
    return {
        "id": memory_id,
        "workspace_id": row["workspace_id"],
        "body": text,
        "source_ref": source,
        "status": row["status"],
        "verified": row["verified"],
        "created_at": row["created_at"],
        "updated_at": now,
    }


def supersede_memory(db: Database, memory_id: str) -> dict:
    row = db.query_one("SELECT * FROM memory_items WHERE id = ?", (memory_id,))
    if row is None:
        raise KnowledgeError("Hafıza kaydı yok.")
    now = utcnow()
    with db.transaction() as c:
        c.execute("UPDATE memory_items SET status = 'superseded', updated_at = ? WHERE id = ?", (now, memory_id))
        c.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
    return {"id": memory_id, "status": "superseded"}


def delete_memory(db: Database, memory_id: str) -> dict:
    row = db.query_one("SELECT id FROM memory_items WHERE id = ?", (memory_id,))
    if row is None:
        raise KnowledgeError("Hafıza kaydı yok.")
    with db.transaction() as c:
        c.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
        c.execute("DELETE FROM memory_items WHERE id = ?", (memory_id,))
    return {"deleted": memory_id}


def search_memory(db: Database, workspace_id: str, query: str, *, op: str = "AND") -> dict:
    _require_workspace(db, workspace_id)
    expr = _fts_query(query, op)
    rows = db.query(
        """
        SELECT m.id, m.body, m.source_ref, m.status, bm25(memory_fts) AS rank
        FROM memory_fts
        JOIN memory_items m ON m.id = memory_fts.memory_id
        WHERE memory_fts MATCH ? AND m.workspace_id = ? AND m.status = 'active'
        ORDER BY rank
        LIMIT 20
        """,
        (expr, workspace_id),
    )
    return {
        **_index_meta(),
        "hits": [
            {"id": r["id"], "body": r["body"], "source_ref": r["source_ref"], "rank": r["rank"]}
            for r in rows
        ],
    }


def _decode(data: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "cp1254"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise KnowledgeError("Metin UTF-8 veya Windows Türkçe (cp1254) değil.")


def _split(text: str) -> list[tuple[int, int, str]]:
    parts: list[tuple[int, int, str]] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_CHARS)
        if end < len(text):
            nl = text.rfind("\n", start, end)
            if nl > start + CHUNK_CHARS // 2:
                end = nl + 1
        piece = text[start:end]
        if piece.strip():
            parts.append((start, end, piece))
        start = end
    if not parts:
        raise KnowledgeError("Dosyada metin yok.")
    return parts


def _read_source(path: str) -> tuple[Path, bytes, str, str]:
    raw = (path or "").strip().strip('"')
    if not raw:
        raise KnowledgeError("Dosya yolu boş.")
    p = Path(raw).expanduser().resolve()
    if not p.is_file():
        raise KnowledgeError(f"Dosya yok: {p}")
    suffix = p.suffix.lower()
    if suffix in REFUSED_SUFFIXES:
        raise KnowledgeError("Bu sürüm yalnızca düz metin ve Markdown ayrıştırır. PDF, ofis ve görüntü indekslenmez.")
    if suffix not in TEXT_SUFFIXES:
        raise KnowledgeError("Desteklenen türler: .txt, .md, .markdown.")
    data = p.read_bytes()
    if not data:
        raise KnowledgeError("Dosya boş.")
    if len(data) > MAX_BYTES:
        raise KnowledgeError(f"Dosya {MAX_BYTES} bayttan büyük.")
    text, encoding = _decode(data)
    return p, data, text, encoding


def _doc_dict(row) -> dict:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "path": row["path"],
        "title": row["title"],
        "media_type": row["media_type"],
        "byte_size": row["byte_size"],
        "content_hash": row["content_hash"],
        "version": row["version"],
        "encoding": row["encoding"],
        "index_version": row["index_version"],
        "deleted_at": row["deleted_at"],
        "vector": VECTOR_STATE,
    }


def _latest_job(db: Database, document_id: str) -> dict | None:
    row = db.query_one(
        """
        SELECT id, state, error, kind, version, updated_at
        FROM index_jobs WHERE document_id = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (document_id,),
    )
    return dict(row) if row else None


def list_documents(db: Database, workspace_id: str) -> list[dict]:
    _require_workspace(db, workspace_id)
    rows = db.query(
        """
        SELECT * FROM documents
        WHERE workspace_id = ? AND deleted_at IS NULL
        ORDER BY updated_at DESC
        """,
        (workspace_id,),
    )
    out = []
    for r in rows:
        item = _doc_dict(r)
        job = _latest_job(db, r["id"])
        item["index_state"] = job["state"] if job else "done"
        item["index_error"] = job["error"] if job else None
        out.append(item)
    return out


def list_index_jobs(db: Database, workspace_id: str) -> list[dict]:
    _require_workspace(db, workspace_id)
    rows = db.query(
        """
        SELECT j.id, j.document_id, j.version, j.kind, j.state, j.error, j.created_at, j.updated_at,
               d.title, d.path
        FROM index_jobs j
        JOIN documents d ON d.id = j.document_id
        WHERE d.workspace_id = ? AND j.state IN ('pending', 'failed')
        ORDER BY j.created_at DESC
        LIMIT 50
        """,
        (workspace_id,),
    )
    return [dict(r) for r in rows]


def retry_failed_jobs(db: Database, workspace_id: str) -> dict:
    _require_workspace(db, workspace_id)
    now = utcnow()
    with db.transaction() as c:
        c.execute(
            """
            UPDATE index_jobs
            SET state = 'pending', error = NULL, updated_at = ?
            WHERE state = 'failed'
              AND document_id IN (SELECT id FROM documents WHERE workspace_id = ?)
            """,
            (now, workspace_id),
        )
    resumed = resume_jobs(db)
    return {"resumed": resumed, "open": list_index_jobs(db, workspace_id)}


def import_document(db: Database, workspace_id: str, path: str, *, process: bool = True) -> dict:
    from .storage import require_space

    _require_workspace(db, workspace_id)
    p, data, text, encoding = _read_source(path)
    require_space(p.parent)
    digest = hashlib.sha256(data).hexdigest()
    now = utcnow()
    parts = _split(text)
    with db.transaction() as c:
        row = c.execute(
            "SELECT * FROM documents WHERE workspace_id = ? AND path = ?",
            (workspace_id, str(p)),
        ).fetchone()
        if row and row["deleted_at"] is None and row["content_hash"] == digest:
            doc_id = row["id"]
            version = row["version"]
            unchanged = True
        else:
            unchanged = False
            if row:
                doc_id = row["id"]
                version = int(row["version"]) + 1
                c.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
                c.execute("DELETE FROM chunk_fts WHERE document_id = ?", (doc_id,))
                c.execute(
                    """
                    UPDATE documents
                    SET title = ?, byte_size = ?, content_hash = ?, version = ?, encoding = ?,
                        index_version = ?, deleted_at = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (p.name, len(data), digest, version, encoding, INDEX_VERSION, now, doc_id),
                )
            else:
                doc_id = _id()
                version = 1
                c.execute(
                    """
                    INSERT INTO documents (
                        id, workspace_id, path, title, media_type, byte_size, content_hash, version,
                        encoding, index_version, deleted_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'text', ?, ?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (doc_id, workspace_id, str(p), p.name, len(data), digest, version, encoding, INDEX_VERSION, now, now),
                )
            for ordinal, (start, end, piece) in enumerate(parts):
                c.execute(
                    """
                    INSERT INTO chunks (id, document_id, version, ordinal, text, search_text, start_char, end_char, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (_id(), doc_id, version, ordinal, piece, search_key(piece), start, end, now),
                )
            c.execute(
                """
                INSERT INTO index_jobs (id, document_id, version, kind, state, error, created_at, updated_at)
                VALUES (?, ?, ?, 'index', 'pending', NULL, ?, ?)
                """,
                (_id(), doc_id, version, now, now),
            )
    if not unchanged and process:
        resume_jobs(db)
    fresh = db.query_one("SELECT * FROM documents WHERE id = ?", (doc_id,))
    out = _doc_dict(fresh)
    out["unchanged"] = unchanged
    return out


def delete_document(db: Database, document_id: str) -> dict:
    row = db.query_one("SELECT * FROM documents WHERE id = ? AND deleted_at IS NULL", (document_id,))
    if row is None:
        raise KnowledgeError("Belge yok.")
    now = utcnow()
    with db.transaction() as c:
        c.execute("UPDATE documents SET deleted_at = ?, updated_at = ? WHERE id = ?", (now, now, document_id))
        c.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        c.execute("DELETE FROM chunk_fts WHERE document_id = ?", (document_id,))
        c.execute(
            """
            INSERT INTO index_jobs (id, document_id, version, kind, state, error, created_at, updated_at)
            VALUES (?, ?, ?, 'purge', 'done', NULL, ?, ?)
            """,
            (_id(), document_id, row["version"], now, now),
        )
    return {"deleted": document_id, "path_on_disk": row["path"]}


def resume_jobs(db: Database) -> int:
    jobs = db.query("SELECT * FROM index_jobs WHERE state = 'pending' ORDER BY created_at")
    done = 0
    for job in jobs:
        try:
            rows = db.query(
                "SELECT id, search_text, document_id FROM chunks WHERE document_id = ? AND version = ?",
                (job["document_id"], job["version"]),
            )
            doc = db.query_one("SELECT workspace_id, deleted_at FROM documents WHERE id = ?", (job["document_id"],))
            with db.transaction() as c:
                c.execute("DELETE FROM chunk_fts WHERE document_id = ?", (job["document_id"],))
                if doc and doc["deleted_at"] is None:
                    for row in rows:
                        c.execute(
                            "INSERT INTO chunk_fts (search_text, chunk_id, document_id, workspace_id) VALUES (?, ?, ?, ?)",
                            (row["search_text"], row["id"], row["document_id"], doc["workspace_id"]),
                        )
                c.execute(
                    "UPDATE index_jobs SET state = 'done', updated_at = ? WHERE id = ?",
                    (utcnow(), job["id"]),
                )
            done += 1
        except Exception as e:  # noqa: BLE001 — iş kuyruğu bir kaydı düşürüp devam eder
            with db.transaction() as c:
                c.execute(
                    "UPDATE index_jobs SET state = 'failed', error = ?, updated_at = ? WHERE id = ?",
                    (str(e), utcnow(), job["id"]),
                )
    return done


def search_documents(db: Database, workspace_id: str, query: str, *, op: str = "AND") -> dict:
    _require_workspace(db, workspace_id)
    expr = _fts_query(query, op)
    rows = db.query(
        """
        SELECT d.id AS document_id, d.title, d.path, d.version, c.start_char, c.end_char, c.text,
               bm25(chunk_fts) AS rank
        FROM chunk_fts
        JOIN chunks c ON c.id = chunk_fts.chunk_id
        JOIN documents d ON d.id = c.document_id AND d.version = c.version AND d.deleted_at IS NULL
        WHERE chunk_fts MATCH ? AND d.workspace_id = ?
        ORDER BY rank
        LIMIT 8
        """,
        (expr, workspace_id),
    )
    return {
        **_index_meta(),
        "hits": [
            {
                "document_id": r["document_id"],
                "title": r["title"],
                "path": r["path"],
                "version": r["version"],
                "start_char": r["start_char"],
                "end_char": r["end_char"],
                "text": r["text"],
                "rank": r["rank"],
            }
            for r in rows
        ],
    }


def retrieve_for_chat(db: Database, workspace_id: str, query: str) -> dict:
    """Çalışma alanındaki adayları seçer; yetkisiz kaydı modele göndermez."""
    _require_workspace(db, workspace_id)
    sources: list[dict] = []
    blocks: list[str] = []
    try:
        for hit in search_memory(db, workspace_id, query, op="OR")["hits"][:4]:
            sources.append(
                {
                    "kind": "memory",
                    "id": hit["id"],
                    "title": hit["source_ref"],
                    "path": None,
                    "text": hit["body"][:400],
                }
            )
            blocks.append(f"[Hafıza · kaynak: {hit['source_ref']}]\n{hit['body'][:800]}")
    except (KnowledgeError, sqlite3.OperationalError):
        pass
    try:
        for hit in search_documents(db, workspace_id, query, op="OR")["hits"][:4]:
            sources.append(
                {
                    "kind": "document",
                    "id": hit["document_id"],
                    "title": hit["title"],
                    "path": hit["path"],
                    "text": hit["text"][:400],
                    "version": hit["version"],
                    "start_char": hit["start_char"],
                    "end_char": hit["end_char"],
                }
            )
            loc = f"{hit['path']} · sürüm {hit['version']} · karakter {hit['start_char']}-{hit['end_char']}"
            blocks.append(f"[Belge · {loc}]\n{hit['text'][:800]}")
    except (KnowledgeError, sqlite3.OperationalError):
        pass
    prompt = ""
    if blocks:
        prompt = (
            "Aşağıdakiler kullanıcının bu çalışma alanında onayladığı hafıza ve indekslenmiş belgelerdir. "
            f"İndeks {INDEX_VERSION}; vektör indeksi {VECTOR_STATE}. "
            "Bu blokta olmayan bilgiyi belgelenmiş gerçek gibi yazma.\n\n" + "\n\n".join(blocks)
        )
    meta = _index_meta()
    sources.insert(
        0,
        {
            "kind": "index",
            "id": meta["index"],
            "title": f"Arama indeksi {meta['index']}",
            "path": None,
            "text": f"vektör: {meta['vector']} · birleştirme: {meta['merge']}",
        },
    )
    return {**meta, "workspace_id": workspace_id, "sources": sources, "prompt": prompt}


def locate_document_source(
    db: Database,
    document_id: str,
    *,
    version: int | None = None,
    start_char: int | None = None,
    end_char: int | None = None,
) -> dict:
    """Kaynak bağlantısının belge sürümünü ve karakter aralığını doğrular."""
    row = db.query_one("SELECT * FROM documents WHERE id = ?", (document_id,))
    if row is None:
        raise KnowledgeError("Belge kaydı yok.")
    deleted = bool(row["deleted_at"])
    current_version = int(row["version"])
    requested = int(version) if version is not None else current_version
    path = Path(row["path"])
    exists = path.is_file()
    version_match = requested == current_version and not deleted
    excerpt = ""
    chunk = db.query_one(
        """
        SELECT text, start_char, end_char, version FROM chunks
        WHERE document_id = ? AND version = ?
          AND (? IS NULL OR start_char = ?)
        ORDER BY ordinal LIMIT 1
        """,
        (document_id, requested, start_char, start_char),
    )
    if chunk is None and start_char is not None:
        chunk = db.query_one(
            """
            SELECT text, start_char, end_char, version FROM chunks
            WHERE document_id = ? AND version = ?
              AND start_char <= ? AND end_char >= ?
            ORDER BY ordinal LIMIT 1
            """,
            (document_id, requested, start_char, start_char),
        )
    if chunk:
        excerpt = chunk["text"][:500]
        if start_char is None:
            start_char = chunk["start_char"]
        if end_char is None:
            end_char = chunk["end_char"]
    notes: list[str] = []
    if deleted:
        notes.append("Belge silinmiş; cevap bağlamına yeni istekte dönmez.")
    elif not version_match:
        notes.append(f"İstenen sürüm {requested}; güncel sürüm {current_version}.")
    if not exists:
        notes.append("Dosya diskte yok.")
    if not excerpt and version_match:
        notes.append("Bu konumda parça bulunamadı.")
    ok = exists and version_match and not deleted
    return {
        "document_id": document_id,
        "title": row["title"],
        "path": row["path"],
        "exists": exists,
        "deleted": deleted,
        "requested_version": requested,
        "current_version": current_version,
        "version_match": version_match,
        "start_char": start_char,
        "end_char": end_char,
        "excerpt": excerpt,
        "ok": ok,
        "note": " ".join(notes) if notes else "Belge sürümü ve konum doğrulandı.",
    }
