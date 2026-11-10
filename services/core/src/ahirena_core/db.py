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
    (
        3,
        """
        CREATE TABLE workspaces (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            created_by  TEXT NOT NULL DEFAULT 'local-user'
        );
        INSERT INTO workspaces (id, name, created_at, updated_at)
        VALUES ('genel', 'Genel', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00');

        CREATE TABLE memory_items (
            id            TEXT PRIMARY KEY,
            workspace_id  TEXT NOT NULL REFERENCES workspaces(id),
            body          TEXT NOT NULL,
            source_ref    TEXT NOT NULL,
            status        TEXT NOT NULL CHECK (status IN ('active', 'superseded')),
            verified      INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL,
            created_by    TEXT NOT NULL DEFAULT 'local-user'
        );
        CREATE INDEX ix_memory_ws ON memory_items(workspace_id, status);
        CREATE VIRTUAL TABLE memory_fts USING fts5(
            search_text,
            memory_id UNINDEXED,
            workspace_id UNINDEXED,
            tokenize = "unicode61 remove_diacritics 0"
        );

        CREATE TABLE documents (
            id             TEXT PRIMARY KEY,
            workspace_id   TEXT NOT NULL REFERENCES workspaces(id),
            path           TEXT NOT NULL,
            title          TEXT NOT NULL,
            media_type     TEXT NOT NULL,
            byte_size      INTEGER NOT NULL,
            content_hash   TEXT NOT NULL,
            version        INTEGER NOT NULL,
            encoding       TEXT NOT NULL,
            index_version  TEXT NOT NULL,
            deleted_at     TEXT,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL,
            created_by     TEXT NOT NULL DEFAULT 'local-user',
            UNIQUE (workspace_id, path)
        );
        CREATE TABLE chunks (
            id            TEXT PRIMARY KEY,
            document_id   TEXT NOT NULL REFERENCES documents(id),
            version       INTEGER NOT NULL,
            ordinal       INTEGER NOT NULL,
            text          TEXT NOT NULL,
            search_text   TEXT NOT NULL,
            start_char    INTEGER NOT NULL,
            end_char      INTEGER NOT NULL,
            created_at    TEXT NOT NULL
        );
        CREATE INDEX ix_chunks_doc ON chunks(document_id, version);
        CREATE VIRTUAL TABLE chunk_fts USING fts5(
            search_text,
            chunk_id UNINDEXED,
            document_id UNINDEXED,
            workspace_id UNINDEXED,
            tokenize = "unicode61 remove_diacritics 0"
        );
        CREATE TABLE index_jobs (
            id            TEXT PRIMARY KEY,
            document_id   TEXT NOT NULL,
            version       INTEGER NOT NULL,
            kind          TEXT NOT NULL CHECK (kind IN ('index', 'purge')),
            state         TEXT NOT NULL CHECK (state IN ('pending', 'done', 'failed')),
            error         TEXT,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        );
        """,
    ),
    (
        4,
        """
        ALTER TABLE conversations ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'genel';
        ALTER TABLE messages ADD COLUMN sources_json TEXT;
        """,
    ),
    (
        5,
        """
        CREATE TABLE tasks (
            id                 TEXT PRIMARY KEY,
            title              TEXT NOT NULL,
            kind               TEXT NOT NULL,
            state              TEXT NOT NULL CHECK (state IN (
                'queued','running','waiting_approval','paused','succeeded','failed','cancelled','needs_reconciliation'
            )),
            workspace_id       TEXT NOT NULL DEFAULT 'genel',
            params_json        TEXT NOT NULL,
            grant_json         TEXT NOT NULL DEFAULT '{}',
            route              TEXT NOT NULL DEFAULT 'direct' CHECK (route IN ('direct','tor')),
            schedule_at        TEXT,
            interval_seconds   INTEGER,
            timezone           TEXT NOT NULL DEFAULT 'Europe/Istanbul',
            missed_policy      TEXT NOT NULL DEFAULT 'skip' CHECK (missed_policy IN ('skip','run_once')),
            checkpoint_json    TEXT,
            last_error         TEXT,
            created_at         TEXT NOT NULL,
            updated_at         TEXT NOT NULL
        );
        CREATE INDEX ix_tasks_state ON tasks(state, schedule_at);
        CREATE TABLE task_steps (
            id               TEXT PRIMARY KEY,
            task_id          TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            ordinal          INTEGER NOT NULL,
            tool             TEXT NOT NULL,
            intent_json      TEXT NOT NULL,
            idempotency_key  TEXT NOT NULL,
            state            TEXT NOT NULL CHECK (state IN ('intended','applied','verified','uncertain','skipped')),
            result_json      TEXT,
            error            TEXT,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL
        );
        CREATE TABLE approvals (
            id             TEXT PRIMARY KEY,
            task_id        TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            action         TEXT NOT NULL,
            target_summary TEXT NOT NULL,
            params_hash    TEXT NOT NULL,
            decision       TEXT NOT NULL CHECK (decision IN ('pending','granted','denied')),
            created_at     TEXT NOT NULL,
            decided_at     TEXT
        );
        """,
    ),
    (
        6,
        """
        ALTER TABLE tasks ADD COLUMN parent_id TEXT REFERENCES tasks(id);
        ALTER TABLE conversations ADD COLUMN parent_id TEXT REFERENCES conversations(id);
        CREATE TABLE skill_candidates (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            description   TEXT NOT NULL,
            tools_json    TEXT NOT NULL,
            package_dir   TEXT NOT NULL,
            content_hash  TEXT NOT NULL,
            prompt        TEXT NOT NULL,
            status        TEXT NOT NULL CHECK (status IN ('candidate','discarded','imported')),
            created_at    TEXT NOT NULL
        );
        CREATE TABLE attachments (
            id               TEXT PRIMARY KEY,
            conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            message_id       TEXT,
            path             TEXT NOT NULL,
            media_type       TEXT NOT NULL,
            byte_size        INTEGER NOT NULL,
            content_hash     TEXT NOT NULL,
            untrusted        INTEGER NOT NULL DEFAULT 1,
            created_at       TEXT NOT NULL
        );
        """,
    ),
    (
        7,
        """
        CREATE TABLE training_runs (
            id            TEXT PRIMARY KEY,
            base_model    TEXT NOT NULL,
            goal          TEXT NOT NULL,
            data_version  TEXT NOT NULL,
            status        TEXT NOT NULL CHECK (status IN ('planned','running','failed','evaluated','approved','rejected')),
            settings_json TEXT NOT NULL,
            metrics_json  TEXT,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        );
        CREATE TABLE adapters (
            id             TEXT PRIMARY KEY,
            training_id    TEXT REFERENCES training_runs(id),
            base_model     TEXT NOT NULL,
            path           TEXT NOT NULL,
            status         TEXT NOT NULL CHECK (status IN ('candidate','approved','active','rolled_back')),
            created_at     TEXT NOT NULL
        );
        """,
    ),
    (
        8,
        """
        CREATE TABLE artifacts (
            id            TEXT PRIMARY KEY,
            kind          TEXT NOT NULL,
            title         TEXT NOT NULL,
            path          TEXT NOT NULL,
            media_type    TEXT NOT NULL,
            byte_size     INTEGER NOT NULL,
            content_hash  TEXT NOT NULL,
            task_id       TEXT,
            version       INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT NOT NULL
        );
        CREATE INDEX ix_artifacts_created ON artifacts(created_at);
        """,
    ),
    (
        9,
        """
        CREATE TABLE feedback_items (
            id               TEXT PRIMARY KEY,
            conversation_id  TEXT REFERENCES conversations(id) ON DELETE SET NULL,
            message_id       TEXT,
            issue_type       TEXT NOT NULL CHECK (issue_type IN (
                'missing_source','bad_instruction','tool_failure','wrong_model','needs_training','other'
            )),
            note             TEXT NOT NULL,
            suggested_fix   TEXT,
            status           TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','reviewed','dismissed')),
            created_at       TEXT NOT NULL
        );
        CREATE INDEX ix_feedback_created ON feedback_items(created_at);
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
