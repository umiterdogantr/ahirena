from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from .textnorm import search_key

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE conversations (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            model_id    TEXT,
            archived    INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            created_by  TEXT NOT NULL DEFAULT 'local-user'
        );
        CREATE INDEX ix_conversations_updated ON conversations(updated_at);

        CREATE TABLE messages (
            id               TEXT PRIMARY KEY,
            conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role             TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant')),
            content          TEXT NOT NULL DEFAULT '',
            thinking         TEXT,
            status           TEXT NOT NULL CHECK (status IN ('complete', 'streaming', 'cancelled', 'error')),
            error            TEXT,
            provider_id      TEXT,
            model_id         TEXT,
            model_digest     TEXT,
            metrics_json     TEXT,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL,
            created_by       TEXT NOT NULL DEFAULT 'local-user'
        );
        CREATE INDEX ix_messages_conversation ON messages(conversation_id, created_at);

        CREATE TABLE app_settings (
            key         TEXT PRIMARY KEY,
            value_json  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );
        """,
    ),
    (
        2,
        """
        CREATE TABLE skills (
            id            TEXT PRIMARY KEY,
            version       TEXT NOT NULL,
            name          TEXT NOT NULL,
            description   TEXT NOT NULL,
            enabled       INTEGER NOT NULL DEFAULT 0,
            package_dir   TEXT NOT NULL,
            content_hash  TEXT NOT NULL,
            tools_json    TEXT NOT NULL,
            created_at    TEXT NOT NULL
        );
        CREATE TABLE skill_grants (
            skill_id    TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
            permission  TEXT NOT NULL,
            scope_json  TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (skill_id, permission)
        );
        CREATE TABLE mcp_servers (
            id                 TEXT PRIMARY KEY,
            name               TEXT NOT NULL,
            command            TEXT NOT NULL,
            args_json          TEXT NOT NULL,
            enabled            INTEGER NOT NULL DEFAULT 0,
            protocol_version   TEXT,
            tools_hash         TEXT,
            tools_json         TEXT NOT NULL DEFAULT '[]',
            grants_json        TEXT NOT NULL DEFAULT '[]',
            last_error         TEXT,
            updated_at         TEXT NOT NULL
        );
        CREATE TABLE tool_calls (
            id          TEXT PRIMARY KEY,
            skill_id    TEXT,
            mcp_id      TEXT,
            tool        TEXT NOT NULL,
            ok          INTEGER NOT NULL,
            error       TEXT,
            created_at  TEXT NOT NULL
        );
        """,
    ),
]


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


class Database:
    """Tek süreçli yerel kullanım için kilitli SQLite bağlantısı."""

    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.create_function("search_key", 1, search_key, deterministic=True)
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA busy_timeout = 5000")
        self._migrate()

    def _migrate(self) -> None:
        with self.transaction() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {r[0] for r in c.execute("SELECT version FROM schema_migrations")}
        for version, sql in MIGRATIONS:
            if version in applied:
                continue
            with self._lock:
                self._conn.executescript(f"BEGIN;\n{sql}\nINSERT INTO schema_migrations VALUES ({version}, '{utcnow()}');\nCOMMIT;")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
