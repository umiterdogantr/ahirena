"""Kullanıcı düzeltmelerini aday iyileştirmeye dönüştürür (Aşama 6 / §14.4).

Fine-tuning otomatik başlamaz; önce sorun türü kaydedilir.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from .artifacts import register_file
from .db import Database, utcnow
from .storage import require_space

ISSUE_TYPES = {
    "missing_source": "Kaynak eksikliği",
    "bad_instruction": "Hatalı talimat",
    "tool_failure": "Başarısız araç",
    "wrong_model": "Yanlış model",
    "needs_training": "Eğitim ihtiyacı",
    "other": "Diğer",
}


class FeedbackError(ValueError):
    pass


def list_feedback(db: Database) -> list[dict]:
    rows = db.query("SELECT * FROM feedback_items ORDER BY created_at DESC")
    return [_item(r) for r in rows]


def create_feedback(db: Database, body: dict) -> dict:
    issue = (body.get("issue_type") or "").strip()
    if issue not in ISSUE_TYPES:
        raise FeedbackError(f"Geçersiz sorun türü. İzinliler: {', '.join(ISSUE_TYPES)}")
    note = (body.get("note") or "").strip()
    if not note:
        raise FeedbackError("Düzeltme notu zorunlu.")
    if len(note) > 4000:
        raise FeedbackError("Not en fazla 4000 karakter.")
    suggested = (body.get("suggested_fix") or "").strip()
    if len(suggested) > 8000:
        raise FeedbackError("Önerilen metin en fazla 8000 karakter.")
    conversation_id = (body.get("conversation_id") or "").strip() or None
    message_id = (body.get("message_id") or "").strip() or None
    if message_id:
        row = db.query_one("SELECT id, conversation_id, role FROM messages WHERE id = ?", (message_id,))
        if row is None:
            raise FeedbackError("Mesaj bulunamadı.")
        if row["role"] != "assistant":
            raise FeedbackError("Yalnızca asistan yanıtına düzeltme kaydedilir.")
        conversation_id = row["conversation_id"]
    elif conversation_id and not db.query_one("SELECT id FROM conversations WHERE id = ?", (conversation_id,)):
        raise FeedbackError("Konuşma bulunamadı.")
    now = utcnow()
    fid = uuid.uuid4().hex
    with db.transaction() as c:
        c.execute(
            """INSERT INTO feedback_items (
                id, conversation_id, message_id, issue_type, note, suggested_fix, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'open', ?)""",
            (fid, conversation_id, message_id, issue, note, suggested or None, now),
        )
    return get_feedback(db, fid)


def get_feedback(db: Database, feedback_id: str) -> dict:
    row = db.query_one("SELECT * FROM feedback_items WHERE id = ?", (feedback_id,))
    if row is None:
        raise FeedbackError("Düzeltme kaydı yok.")
    return _item(row)


def set_feedback_status(db: Database, feedback_id: str, status: str) -> dict:
    if status not in ("open", "reviewed", "dismissed"):
        raise FeedbackError("Durum open, reviewed veya dismissed olmalı.")
    get_feedback(db, feedback_id)
    with db.transaction() as c:
        c.execute("UPDATE feedback_items SET status = ? WHERE id = ?", (status, feedback_id))
    return get_feedback(db, feedback_id)


def feedback_to_skill_draft(db: Database, data_dir: Path, feedback_id: str) -> dict:
    """Düzeltmeyi karantina yetenek taslağına çevirir; otomatik etkinleştirmez."""
    item = get_feedback(db, feedback_id)
    if item["status"] != "open":
        raise FeedbackError("Yalnızca açık düzeltmelerden taslak üretilir.")
    if item["issue_type"] not in ("bad_instruction", "tool_failure", "other"):
        raise FeedbackError(
            "Yetenek taslağı yalnızca hatalı talimat, başarısız araç veya diğer türünden üretilebilir."
        )
    text = (item.get("suggested_fix") or "").strip() or (item.get("note") or "").strip()
    if len(text) < 8:
        raise FeedbackError("Taslak için önerilen düzeltme veya not en az 8 karakter olmalı.")
    from .skilldraft import SkillError, draft_skill

    try:
        draft = draft_skill(db, data_dir, text)
    except SkillError as e:
        raise FeedbackError(str(e)) from e
    reviewed = set_feedback_status(db, feedback_id, "reviewed")
    return {
        "feedback": reviewed,
        "candidate": draft,
        "note": "Aday Yetenekler’de karantinada. İçe aktarıp izin vermeden çalışmaz.",
    }


def export_feedback(db: Database, data_dir: Path, *, status: str | None = None) -> dict:
    """Düzeltme adaylarını JSON olarak dışa aktarır (sırlar yok)."""
    require_space(data_dir)
    items = list_feedback(db)
    if status:
        if status not in ("open", "reviewed", "dismissed"):
            raise FeedbackError("Durum open, reviewed veya dismissed olmalı.")
        items = [i for i in items if i["status"] == status]
    stamp = utcnow().replace(":", "").replace("+", "z")[:20]
    out = data_dir / "exports" / f"ahirena-feedback-{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise FeedbackError("Dışa aktarım dosyası zaten var.")
    payload = {
        "exported_at": utcnow(),
        "format": "ahirena-feedback",
        "version": 1,
        "status_filter": status,
        "count": len(items),
        "items": items,
        "excludes": ["secrets", "model_weights", "ollama_token"],
        "note": "Fine-tuning otomatik başlamaz; kayıtlar adaydır.",
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    artifact = register_file(
        db,
        out,
        kind="export",
        title=f"Düzeltmeler {stamp}",
        media_type="application/json",
    )
    return {
        "path": str(out),
        "bytes": out.stat().st_size,
        "artifact_id": artifact["id"],
        "count": len(items),
    }


def _item(row) -> dict:
    return {
        "id": row["id"],
        "conversation_id": row["conversation_id"],
        "message_id": row["message_id"],
        "issue_type": row["issue_type"],
        "issue_label": ISSUE_TYPES.get(row["issue_type"], row["issue_type"]),
        "note": row["note"],
        "suggested_fix": row["suggested_fix"],
        "status": row["status"],
        "created_at": row["created_at"],
        "trains_model": False,
    }
