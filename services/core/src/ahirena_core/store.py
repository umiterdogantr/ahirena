from __future__ import annotations

import json
import uuid
from typing import Any

from .db import Database, utcnow
from .schemas import AppSettings, Conversation, Message
from .textnorm import search_key

DEFAULT_TITLE = "Yeni oturum"


def new_id() -> str:
    return str(uuid.uuid4())


def _conversation(row: Any, snippet: str | None = None) -> Conversation:
    return Conversation(
        id=row["id"],
        title=row["title"],
        model_id=row["model_id"],
        archived=bool(row["archived"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        match_snippet=snippet,
    )


def _message(row: Any) -> Message:
    return Message(
        id=row["id"],
        conversation_id=row["conversation_id"],
        role=row["role"],
        content=row["content"],
        thinking=row["thinking"],
        status=row["status"],
        error=row["error"],
        provider_id=row["provider_id"],
        model_id=row["model_id"],
        model_digest=row["model_digest"],
        metrics=json.loads(row["metrics_json"]) if row["metrics_json"] else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _snippet(text: str, key: str, width: int = 80) -> str:
    pos = search_key(text).find(key)
    if pos < 0:
        return text[:width]
    start = max(0, pos - width // 3)
    end = min(len(text), start + width)
    return ("…" if start else "") + text[start:end].replace("\n", " ") + ("…" if end < len(text) else "")


class Store:
    def __init__(self, db: Database):
        self.db = db

    # --- oturumlar ---------------------------------------------------------

    def list_conversations(self, q: str | None = None, archived: bool = False) -> list[Conversation]:
        if not q or not q.strip():
            rows = self.db.query(
                "SELECT * FROM conversations WHERE archived = ? ORDER BY updated_at DESC", (int(archived),)
            )
            return [_conversation(r) for r in rows]
        key = search_key(q.strip())
        like = f"%{key.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')}%"
        rows = self.db.query(
            """
            SELECT c.*, (
                SELECT m.content FROM messages m
                WHERE m.conversation_id = c.id AND search_key(m.content) LIKE :like ESCAPE '\\'
                ORDER BY m.created_at LIMIT 1
            ) AS hit
            FROM conversations c
            WHERE c.archived = :archived AND (
                search_key(c.title) LIKE :like ESCAPE '\\'
                OR EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id
                           AND search_key(m.content) LIKE :like ESCAPE '\\')
            )
            ORDER BY c.updated_at DESC
            """,
            {"like": like, "archived": int(archived)},
        )
        return [_conversation(r, _snippet(r["hit"], key) if r["hit"] else None) for r in rows]

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        row = self.db.query_one("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
        return _conversation(row) if row else None

    def create_conversation(self, title: str | None, model_id: str | None) -> Conversation:
        now = utcnow()
        cid = new_id()
        with self.db.transaction() as c:
            c.execute(
                "INSERT INTO conversations (id, title, model_id, archived, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
                (cid, (title or DEFAULT_TITLE).strip() or DEFAULT_TITLE, model_id, now, now),
            )
        return self.get_conversation(cid)  # type: ignore[return-value]

    def update_conversation(self, conversation_id: str, fields: dict[str, Any]) -> Conversation | None:
        allowed = {k: v for k, v in fields.items() if k in {"title", "archived", "model_id"} and v is not None}
        if "title" in allowed:
            allowed["title"] = allowed["title"].strip()
        if "archived" in allowed:
            allowed["archived"] = int(allowed["archived"])
        if allowed:
            sets = ", ".join(f"{k} = ?" for k in allowed)
            with self.db.transaction() as c:
                c.execute(
                    f"UPDATE conversations SET {sets}, updated_at = ? WHERE id = ?",
                    (*allowed.values(), utcnow(), conversation_id),
                )
        return self.get_conversation(conversation_id)

    def touch_conversation(self, conversation_id: str) -> None:
        with self.db.transaction() as c:
            c.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (utcnow(), conversation_id))

    def delete_conversation(self, conversation_id: str) -> bool:
        with self.db.transaction() as c:
            cur = c.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            return cur.rowcount > 0

    # --- mesajlar ----------------------------------------------------------

    def list_messages(self, conversation_id: str) -> list[Message]:
        rows = self.db.query(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at, rowid", (conversation_id,)
        )
        return [_message(r) for r in rows]

    def get_message(self, message_id: str) -> Message | None:
        row = self.db.query_one("SELECT * FROM messages WHERE id = ?", (message_id,))
        return _message(row) if row else None

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        status: str,
        provider_id: str | None = None,
        model_id: str | None = None,
        model_digest: str | None = None,
    ) -> Message:
        now = utcnow()
        mid = new_id()
        with self.db.transaction() as c:
            c.execute(
                """INSERT INTO messages (id, conversation_id, role, content, status, provider_id, model_id,
                                         model_digest, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (mid, conversation_id, role, content, status, provider_id, model_id, model_digest, now, now),
            )
            c.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        return self.get_message(mid)  # type: ignore[return-value]

    def update_message(
        self,
        message_id: str,
        *,
        content: str,
        thinking: str | None,
        status: str,
        error: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        with self.db.transaction() as c:
            c.execute(
                """UPDATE messages SET content = ?, thinking = ?, status = ?, error = ?, metrics_json = ?,
                                       updated_at = ? WHERE id = ?""",
                (
                    content,
                    thinking or None,
                    status,
                    error,
                    json.dumps(metrics, ensure_ascii=False) if metrics else None,
                    utcnow(),
                    message_id,
                ),
            )

    def recover_interrupted(self) -> int:
        """Çekirdek kapanırken yarım kalan yanıtları dürüstçe işaretle."""
        with self.db.transaction() as c:
            cur = c.execute(
                "UPDATE messages SET status = 'error', error = ?, updated_at = ? WHERE status = 'streaming'",
                ("Uygulama yanıt tamamlanmadan kapandı; yanıt yarım kaldı.", utcnow()),
            )
            return cur.rowcount

    # --- ayarlar -----------------------------------------------------------

    def get_settings(self) -> AppSettings:
        rows = self.db.query("SELECT key, value_json FROM app_settings")
        return AppSettings(**{r["key"]: json.loads(r["value_json"]) for r in rows if r["key"] in AppSettings.model_fields})

    def update_settings(self, values: dict[str, Any]) -> AppSettings:
        now = utcnow()
        with self.db.transaction() as c:
            for k, v in values.items():
                if k in AppSettings.model_fields:
                    c.execute(
                        "INSERT INTO app_settings (key, value_json, updated_at) VALUES (?, ?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
                        (k, json.dumps(v, ensure_ascii=False), now),
                    )
        return self.get_settings()
