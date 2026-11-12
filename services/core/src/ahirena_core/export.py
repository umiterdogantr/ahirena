"""Kişisel veri dışa aktarımı.

Sırlar, model ağırlıkları ve Ollama tokenı pakete girmez.
İndeks dosyaları yeniden kurulabilir; dışa aktarımda konuşma, hafıza, belge
üstbilgisi, görev özeti, yetenek kaydı, şablonlar ve ayarlar vardır.
Paket dosya içerikleri kopyalanmaz; yalnızca kayıt meta verisi vardır.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from pathlib import Path

from .artifacts import register_file
from .db import Database, utcnow
from .storage import require_space

log = logging.getLogger("ahirena.export")

PENDING_RESTORE = "pending_restore.json"


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
    skills = [
        dict(r)
        for r in db.query(
            "SELECT id, version, name, description, enabled, package_dir, content_hash, tools_json, created_at FROM skills ORDER BY name"
        )
    ]
    skill_grants = [dict(r) for r in db.query("SELECT skill_id, permission, scope_json FROM skill_grants ORDER BY skill_id")]
    templates = [dict(r) for r in db.query("SELECT * FROM prompt_templates ORDER BY updated_at")]
    template_versions = [dict(r) for r in db.query("SELECT * FROM prompt_template_versions ORDER BY template_id, version")]

    payload = {
        "exported_at": utcnow(),
        "format": "ahirena-export",
        "version": 3,
        "includes": [
            "conversations",
            "messages",
            "memory",
            "documents_meta",
            "tasks",
            "settings",
            "workspaces",
            "feedback",
            "skills_meta",
            "skill_grants",
            "prompt_templates",
            "prompt_template_versions",
        ],
        "excludes": ["secrets", "model_weights", "ollama_token", "search_indexes", "skill_package_files"],
        "workspaces": workspaces,
        "conversations": conversations,
        "messages": messages,
        "memory_items": memory,
        "documents": documents,
        "tasks": [{k: v for k, v in t.items() if k != "grant_json" or True} for t in tasks],
        "feedback_items": feedback,
        "skills": skills,
        "skill_grants": skill_grants,
        "prompt_templates": templates,
        "prompt_template_versions": template_versions,
        "settings": settings,
    }
    (out / "export.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "README.txt").write_text(
        "Ahirena kişisel dışa aktarım.\n"
        "Bu klasörde sır, model ağırlığı ve uygulama tokenı yoktur.\n"
        "Belge içerikleri yeniden indekslenmelidir; yalnızca üstbilgi vardır.\n"
        "Yetenek paket dosyaları kopyalanmaz; kayıt ve izin meta verisi vardır.\n"
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


def export_conversation(db: Database, data_dir: Path, conversation_id: str) -> dict:
    """Tek oturumu JSON olarak dışa aktarır (sırlar yok)."""
    require_space(data_dir)
    row = db.query_one("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
    if row is None:
        raise ExportError("Oturum yok.")
    messages = [dict(r) for r in db.query(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at, rowid",
        (conversation_id,),
    )]
    stamp = utcnow().replace(":", "").replace("+", "z")[:20]
    safe_title = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in (row["title"] or "oturum"))[:40].strip() or "oturum"
    out = data_dir / "exports" / f"ahirena-conversation-{safe_title}-{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise ExportError("Dışa aktarım dosyası zaten var.")
    payload = {
        "exported_at": utcnow(),
        "format": "ahirena-conversation",
        "version": 1,
        "conversation": dict(row),
        "messages": messages,
        "excludes": ["secrets", "model_weights", "ollama_token"],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    artifact = register_file(
        db,
        out,
        kind="export",
        title=f"Oturum: {row['title']}",
        media_type="application/json",
    )
    return {
        "path": str(out),
        "bytes": out.stat().st_size,
        "artifact_id": artifact["id"],
        "conversation_id": conversation_id,
        "message_count": len(messages),
    }


def save_comparison(
    db: Database,
    data_dir: Path,
    *,
    prompt: str,
    results: list[dict],
    context_length: int | None = None,
    system_prompt_note: str | None = None,
) -> dict:
    """Model karşılaştırma sonucunu JSON olarak kaydeder (yalnızca gönderilen çıktı)."""
    require_space(data_dir)
    prompt = (prompt or "").strip()
    if not prompt:
        raise ExportError("Karşılaştırma sorusu boş.")
    if not results:
        raise ExportError("Kaydedilecek sonuç yok.")
    cleaned: list[dict] = []
    for r in results:
        if not isinstance(r, dict):
            raise ExportError("Sonuç biçimi geçersiz.")
        model_id = str(r.get("model_id") or "").strip()
        if not model_id:
            raise ExportError("Sonuçta model_id gerekir.")
        cleaned.append(
            {
                "model_id": model_id[:200],
                "content": str(r.get("content") or "")[:200_000],
                "status": str(r.get("status") or "")[:40],
                "error": (str(r["error"])[:2000] if r.get("error") else None),
                "metrics": r.get("metrics") if isinstance(r.get("metrics"), dict) else None,
            }
        )
    stamp = utcnow().replace(":", "").replace("+", "z")[:20]
    out = data_dir / "exports" / f"ahirena-compare-{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise ExportError("Karşılaştırma dosyası zaten var.")
    payload = {
        "exported_at": utcnow(),
        "format": "ahirena-compare",
        "version": 1,
        "prompt": prompt[:50_000],
        "context_length": context_length,
        "system_prompt_note": system_prompt_note
        or "Sistem talimatı ayarlardan geldi; bu dosyada tekrarlanmaz.",
        "results": cleaned,
        "excludes": ["secrets", "model_weights", "ollama_token", "full_system_prompt"],
        "note": "Sonuçlar sırayla üretildi; modeller aynı anda belleğe yüklenmedi.",
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    artifact = register_file(
        db,
        out,
        kind="export",
        title=f"Karşılaştırma {stamp}",
        media_type="application/json",
    )
    return {
        "path": str(out),
        "bytes": out.stat().st_size,
        "artifact_id": artifact["id"],
        "result_count": len(cleaned),
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
        "Geri yükleme: Ayarlar > Yedekten geri yükle, veya uygulama kapalıyken ahirena.db dosyasını data klasörüne kopyalayın.\n"
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


def resolve_backup_source(path: str | Path) -> Path:
    """Yedek klasörü veya ahirena.db dosyasını doğrular."""
    p = Path(path).expanduser().resolve()
    if p.is_dir():
        cand = p / "ahirena.db"
        if not cand.is_file():
            raise ExportError("Klasörde ahirena.db yok.")
        p = cand.resolve()
    if not p.is_file():
        raise ExportError("Yedek veritabanı dosyası yok.")
    try:
        con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as e:
        raise ExportError(f"SQLite açılamadı: {e}") from e
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()
    if "conversations" not in tables or "schema_migrations" not in tables:
        raise ExportError("Dosya Ahirena yedeği gibi görünmüyor.")
    return p


def schedule_restore(data_dir: Path, source: str | Path, *, confirm: bool) -> dict:
    """Canlı DB kilitliyken yalnızca sonraki açılışa planlar."""
    if not confirm:
        raise ExportError("Geri yükleme için confirm=true gerekir.")
    src = resolve_backup_source(source)
    live = (data_dir / "data" / "ahirena.db").resolve()
    if src == live:
        raise ExportError("Canlı veritabanı kendisine geri yüklenemez.")
    payload = {
        "source_db": str(src),
        "scheduled_at": utcnow(),
        "note": "Bir sonraki açılışta uygulanır. Mevcut DB önce backups/pre-restore-* altına kopyalanır.",
    }
    pending = data_dir / PENDING_RESTORE
    pending.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**payload, "pending_path": str(pending), "restart_required": True}


def pending_restore(data_dir: Path) -> dict | None:
    path = data_dir / PENDING_RESTORE
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        return {"error": f"pending_restore.json okunamadı: {e}", "path": str(path)}
    return {**raw, "pending_path": str(path), "restart_required": True}


def cancel_pending_restore(data_dir: Path) -> dict:
    path = data_dir / PENDING_RESTORE
    if path.is_file():
        path.unlink()
        return {"cancelled": True, "note": "Bekleyen geri yükleme iptal edildi."}
    return {"cancelled": False, "note": "Bekleyen geri yükleme yok."}


def apply_pending_restore(data_dir: Path) -> dict | None:
    """Veritabanı açılmadan önce çağrılır. Bekleyen yoksa None."""
    path = data_dir / PENDING_RESTORE
    if not path.is_file():
        return None
    stamp = utcnow().replace(":", "").replace("+", "z")[:20]
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        src = resolve_backup_source(raw["source_db"])
    except (OSError, json.JSONDecodeError, KeyError, ExportError, TypeError) as e:
        failed = data_dir / f"pending_restore.failed-{stamp}.json"
        try:
            path.replace(failed)
        except OSError:
            path.unlink(missing_ok=True)
        log.error("Bekleyen geri yükleme uygulanamadı: %s", e)
        return {"ok": False, "error": str(e), "failed_path": str(failed) if failed.exists() else None}

    live = data_dir / "data" / "ahirena.db"
    live.parent.mkdir(parents=True, exist_ok=True)
    safety = data_dir / "backups" / f"pre-restore-{stamp}"
    safety.mkdir(parents=True)
    if live.is_file():
        shutil.copy2(live, safety / "ahirena.db")
    cfg = data_dir / "config.json"
    if cfg.is_file():
        shutil.copy2(cfg, safety / "config.json")
    shutil.copy2(src, live)
    path.unlink(missing_ok=True)
    log.info("Yedek geri yüklendi: %s -> %s (önceki: %s)", src, live, safety)
    return {
        "ok": True,
        "restored_from": str(src),
        "previous_saved_to": str(safety),
        "note": "Geri yükleme uygulandı. Arama indeksleri yeniden kurulabilir.",
    }
