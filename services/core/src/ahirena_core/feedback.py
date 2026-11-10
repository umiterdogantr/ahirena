"""Kullanıcı düzeltmelerini aday iyileştirmeye dönüştürür (Aşama 6 / §14.4).

Fine-tuning otomatik başlamaz; önce sorun türü kaydedilir.
"""

from __future__ import annotations

import uuid

from .db import Database, utcnow

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
