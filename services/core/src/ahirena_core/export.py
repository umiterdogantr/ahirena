"""Kişisel veri dışa aktarımı.

Sırlar, model ağırlıkları ve Ollama tokenı pakete girmez.
İndeks dosyaları yeniden kurulabilir; dışa aktarımda konuşma, hafıza, belge
üstbilgisi, görev özeti ve ayarlar vardır.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

from .artifacts import register_file
from .db import Database, utcnow
from .storage import require_space


class ExportError(ValueError):
    pass


def export_personal(db: Database, data_dir: Path) -> dict:
    require_space(data_dir)
    stamp = utcnow().replace(":", "").replace("+", "z")[:20]
    out = data_dir / "exports" / f"ahirena-export-{stamp}"
    if out.exists():
        raise ExportError("Dışa aktarım klasörü zaten var.")
    out.mkdir(parents=True)

    conversations = [dict(r) for r in db.query("SELECT * FROM conversations ORDER BY updated_at")]
    messages = [dict(r) for r in db.query("SELECT * FROM messages ORDER BY created_at, rowid")]
    memory = [dict(r) for r in db.query("SELECT * FROM memory_items ORDER BY updated_at")]
    documents = [dict(r) for r in db.query("SELECT id, workspace_id, path, title, media_type, byte_size, content_hash, version, deleted_at FROM documents")]
    tasks = [dict(r) for r in db.query("SELECT * FROM tasks ORDER BY updated_at")]
    settings = {r["key"]: json.loads(r["value_json"]) for r in db.query("SELECT key, value_json FROM app_settings")}
    workspaces = [dict(r) for r in db.query("SELECT * FROM workspaces")]
    feedback = [dict(r) for r in db.query("SELECT * FROM feedback_items ORDER BY created_at")]

    payload = {
        "exported_at": utcnow(),
        "format": "ahirena-export",
        "version": 2,
        "includes": ["conversations", "messages", "memory", "documents_meta", "tasks", "settings", "workspaces", "feedback"],
        "excludes": ["secrets", "model_weights", "ollama_token", "search_indexes"],
        "workspaces": workspaces,
        "conversations": conversations,
        "messages": messages,
        "memory_items": memory,
        "documents": documents,
        "tasks": [{k: v for k, v in t.items() if k != "grant_json" or True} for t in tasks],
        "feedback_items": feedback,
        "settings": settings,
    }
    (out / "export.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "README.txt").write_text(
        "Ahirena kişisel dışa aktarım.\n"
        "Bu klasörde sır, model ağırlığı ve uygulama tokenı yoktur.\n"
        "Belge içerikleri yeniden indekslenmelidir; yalnızca üstbilgi vardır.\n"
        f"Oluşturulma: {payload['exported_at']}\n",
        encoding="utf-8",
    )
    cfg = data_dir / "config.json"
    if cfg.exists():
        raw = json.loads(cfg.read_text(encoding="utf-8-sig"))
        safe = {k: v for k, v in raw.items() if k != "token"}
        if isinstance(safe.get("sql"), dict):
            safe["sql"] = {sk: sv for sk, sv in safe["sql"].items() if sk not in ("password", "pwd", "uid")}
        (out / "config.redacted.json").write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = out / "export.json"
    artifact = register_file(db, manifest, kind="export", title=f"Dışa aktarım {stamp}", media_type="application/json")
    return {
        "path": str(out),
        "bytes": sum(p.stat().st_size for p in out.rglob("*") if p.is_file()),
        "files": [p.name for p in out.iterdir()],
        "artifact_id": artifact["id"],
    }


def consistent_backup(db: Database, data_dir: Path) -> dict:
    """SQLite tutarlı kopyası. Arama indeksleri yeniden kurulabilir."""
    require_space(data_dir)
    stamp = utcnow().replace(":", "").replace("+", "z")[:20]
    out = data_dir / "backups" / f"ahirena-backup-{stamp}"
    out.mkdir(parents=True)
    db_path = Path(db.path)
    if not db_path.is_file():
        raise ExportError("Veritabanı yok.")
    dest = out / "ahirena.db"
    target = sqlite3.connect(dest)
    try:
        with db._lock:
            db._conn.backup(target)
    finally:
        target.close()
    cfg = data_dir / "config.json"
    if cfg.exists():
        shutil.copy2(cfg, out / "config.json")
    (out / "README.txt").write_text(
        "Ahirena yedek.\n"
        "Geri yükleme: uygulama kapalıyken ahirena.db dosyasını veri klasörüne kopyalayın.\n"
        "Sırlar düz metin dışa aktarılmaz; config içinde parola alanı yoktur.\n"
        f"Oluşturulma: {utcnow()}\n",
        encoding="utf-8",
    )
    artifact = register_file(db, dest, kind="backup", title=f"Yedek {stamp}", media_type="application/x-sqlite3")
    return {
        "path": str(out),
        "bytes": sum(p.stat().st_size for p in out.rglob("*") if p.is_file()),
        "files": [p.name for p in out.iterdir()],
        "artifact_id": artifact["id"],
    }
