"""Kalıcı görevler: onay, checkpoint, belirsiz işlem, zamanlama.

Yazma onay ister. Kesinti sonrası çalışan görev otomatik tekrarlanmaz.
Zamanlanmış iş yalnızca çekirdek açıkken yürür; Windows açılış hizmeti kurulmaz.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from .artifacts import register_file
from .db import Database, utcnow
from .filesafe import FileRejected, existing_hash, write_inside
from .netpolicy import NetRejected
from .webfetch import fetch_url

STATES = (
    "queued",
    "running",
    "waiting_approval",
    "paused",
    "succeeded",
    "failed",
    "cancelled",
    "needs_reconciliation",
)
KINDS = ("clock.now", "web.fetch", "files.write")


class TaskError(ValueError):
    pass


def _id() -> str:
    return uuid.uuid4().hex


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _row(task, steps=None, approvals=None) -> dict:
    out = dict(task)
    out["params"] = json.loads(task["params_json"])
    out["grant"] = json.loads(task["grant_json"])
    out["checkpoint"] = json.loads(task["checkpoint_json"]) if task["checkpoint_json"] else None
    del out["params_json"]
    del out["grant_json"]
    del out["checkpoint_json"]
    if steps is not None:
        out["steps"] = [
            {
                **{k: s[k] for k in ("id", "ordinal", "tool", "idempotency_key", "state", "error", "created_at", "updated_at")},
                "intent": json.loads(s["intent_json"]),
                "result": json.loads(s["result_json"]) if s["result_json"] else None,
            }
            for s in steps
        ]
    if approvals is not None:
        out["approvals"] = [dict(a) for a in approvals]
    return out


class TaskEngine:
    def __init__(self, db: Database, *, fetch=fetch_url, tor_socks: str = "127.0.0.1:9050", offline: bool = False):
        self.db = db
        self.fetch = fetch
        self.tor_socks = tor_socks
        self.offline = offline

    def recover_interrupted(self) -> int:
        now = utcnow()
        n = 0
        with self.db.transaction() as c:
            rows = c.execute("SELECT id FROM tasks WHERE state = 'running'").fetchall()
            for row in rows:
                c.execute(
                    "UPDATE tasks SET state = 'needs_reconciliation', last_error = ?, updated_at = ? WHERE id = ?",
                    ("Kesinti: dış işlemin tamamlandığı varsayılmaz.", now, row["id"]),
                )
                c.execute(
                    """UPDATE task_steps SET state = 'uncertain', error = ?, updated_at = ?
                       WHERE task_id = ? AND state IN ('intended','applied')""",
                    ("Kesinti; sonuç belirsiz.", now, row["id"]),
                )
                n += 1
            due = c.execute(
                "SELECT * FROM tasks WHERE state = 'queued' AND schedule_at IS NOT NULL AND schedule_at < ?",
                (now,),
            ).fetchall()
            for row in due:
                if row["missed_policy"] == "skip":
                    nxt = self._next_time(row, now)
                    if nxt and row["interval_seconds"]:
                        c.execute(
                            "UPDATE tasks SET schedule_at = ?, updated_at = ? WHERE id = ?",
                            (nxt, now, row["id"]),
                        )
                    else:
                        c.execute(
                            "UPDATE tasks SET state = 'cancelled', last_error = ?, updated_at = ? WHERE id = ?",
                            ("Kaçırılan tek seferlik çalışma atlandı.", now, row["id"]),
                        )
        return n

    def list(self, *, state: str | None = None) -> list[dict]:
        if state:
            rows = self.db.query("SELECT * FROM tasks WHERE state = ? ORDER BY updated_at DESC", (state,))
        else:
            rows = self.db.query("SELECT * FROM tasks ORDER BY updated_at DESC")
        out = []
        for r in rows:
            steps = self.db.query("SELECT * FROM task_steps WHERE task_id = ? ORDER BY ordinal", (r["id"],))
            approvals = self.db.query("SELECT * FROM approvals WHERE task_id = ? ORDER BY created_at", (r["id"],))
            out.append(_row(r, steps, approvals))
        return out

    def get(self, task_id: str) -> dict:
        row = self.db.query_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if row is None:
            raise TaskError("Görev yok.")
        steps = self.db.query("SELECT * FROM task_steps WHERE task_id = ? ORDER BY ordinal", (task_id,))
        approvals = self.db.query("SELECT * FROM approvals WHERE task_id = ? ORDER BY created_at", (task_id,))
        return _row(row, steps, approvals)

    def create(self, body: dict) -> dict:
        kind = body.get("kind")
        if kind not in KINDS:
            raise TaskError("Desteklenen türler: clock.now, web.fetch, files.write.")
        route = body.get("route") or "direct"
        if route not in ("direct", "tor"):
            raise TaskError("Rota direct veya tor olmalı.")
        params = body.get("params") or {}
        grant = body.get("grant") or {}
        title = (body.get("title") or kind).strip()
        now = utcnow()
        tid = _id()
        state = "queued"
        approval = None
        if kind == "files.write":
            roots = grant.get("roots") or []
            rel = str(params.get("relative") or "")
            content = str(params.get("content") or "")
            if not roots or not rel:
                raise TaskError("Yazma için kök ve göreli yol gerekir.")
            expected = existing_hash(roots, rel)
            params = {**params, "expected_hash": expected}
            state = "waiting_approval"
            approval = {
                "id": _id(),
                "action": "files.write",
                "target_summary": f"{rel} @ {roots}",
                "params_hash": _hash({"relative": rel, "content": content, "roots": roots, "expected_hash": expected}),
            }
        if kind == "web.fetch":
            if not (grant.get("hosts") or []):
                raise TaskError("web.fetch için izinli alan adı gerekir.")
            if not params.get("url"):
                raise TaskError("url gerekir.")
        schedule_at = body.get("schedule_at")
        if schedule_at and state == "queued":
            pass
        with self.db.transaction() as c:
            c.execute(
                """INSERT INTO tasks (
                    id, title, kind, state, workspace_id, params_json, grant_json, route,
                    schedule_at, interval_seconds, timezone, missed_policy, checkpoint_json,
                    last_error, created_at, updated_at, parent_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)""",
                (
                    tid,
                    title,
                    kind,
                    state,
                    body.get("workspace_id") or "genel",
                    json.dumps(params, ensure_ascii=False),
                    json.dumps(grant, ensure_ascii=False),
                    route,
                    schedule_at,
                    body.get("interval_seconds"),
                    body.get("timezone") or "Europe/Istanbul",
                    body.get("missed_policy") or "skip",
                    now,
                    now,
                    body.get("parent_id"),
                ),
            )
            if approval:
                c.execute(
                    """INSERT INTO approvals (id, task_id, action, target_summary, params_hash, decision, created_at, decided_at)
                       VALUES (?, ?, ?, ?, ?, 'pending', ?, NULL)""",
                    (approval["id"], tid, approval["action"], approval["target_summary"], approval["params_hash"], now),
                )
        return self.get(tid)

    def approve(self, task_id: str, approval_id: str) -> dict:
        task = self.get(task_id)
        row = self.db.query_one("SELECT * FROM approvals WHERE id = ? AND task_id = ?", (approval_id, task_id))
        if row is None:
            raise TaskError("Onay kaydı yok.")
        if row["decision"] != "pending":
            raise TaskError("Onay zaten karara bağlandı.")
        current = _hash(
            {
                "relative": task["params"].get("relative"),
                "content": task["params"].get("content"),
                "roots": task["grant"].get("roots"),
                "expected_hash": task["params"].get("expected_hash"),
            }
        )
        if current != row["params_hash"]:
            raise TaskError("Hedef veya içerik değişmiş; eski onay kullanılamaz.")
        now = utcnow()
        with self.db.transaction() as c:
            c.execute(
                "UPDATE approvals SET decision = 'granted', decided_at = ? WHERE id = ?",
                (now, approval_id),
            )
            c.execute("UPDATE tasks SET state = 'queued', updated_at = ? WHERE id = ?", (now, task_id))
        return self.get(task_id)

    def deny(self, task_id: str, approval_id: str) -> dict:
        now = utcnow()
        with self.db.transaction() as c:
            cur = c.execute(
                "UPDATE approvals SET decision = 'denied', decided_at = ? WHERE id = ? AND task_id = ? AND decision = 'pending'",
                (now, approval_id, task_id),
            )
            if cur.rowcount == 0:
                raise TaskError("Onay kaydı yok.")
            c.execute(
                "UPDATE tasks SET state = 'cancelled', last_error = ?, updated_at = ? WHERE id = ?",
                ("Onay reddedildi.", now, task_id),
            )
        return self.get(task_id)

    def branch(self, task_id: str, overrides: dict | None = None) -> dict:
        """Checkpoint'ten yeni dal. Eski yazma onayı ve adımlar taşınmaz."""
        parent = self.get(task_id)
        overrides = overrides or {}
        body = {
            "title": overrides.get("title") or f"{parent['title']} · dal",
            "kind": parent["kind"],
            "params": overrides.get("params") or dict(parent["params"]),
            "grant": overrides.get("grant") or dict(parent["grant"]),
            "route": overrides.get("route") or parent["route"],
            "workspace_id": parent["workspace_id"],
            "parent_id": parent["id"],
        }
        if parent["kind"] == "files.write" and "expected_hash" in body["params"]:
            # Yeni dosya durumuna göre yeniden hesaplanır.
            body["params"].pop("expected_hash", None)
        return self.create(body)

    def replay(self, task_id: str) -> dict:
        """Doğrulanmış adımları yeniden oynatır; dış yazma veya ağı tekrarlamaz."""
        task = self.get(task_id)
        verified = [s for s in task.get("steps") or [] if s["state"] == "verified" and s.get("result") is not None]
        if not verified:
            raise TaskError("Yeniden oynatılacak doğrulanmış adım yok.")
        return {
            "mode": "offline_replay",
            "live_tools": False,
            "task_id": task_id,
            "steps": [{"ordinal": s["ordinal"], "tool": s["tool"], "result": s["result"]} for s in verified],
            "note": "Canlı araç yürütmesi değildir; kayıtlı sonuçlar okundu.",
        }

    def cancel(self, task_id: str) -> dict:
        row = self.db.query_one("SELECT state FROM tasks WHERE id = ?", (task_id,))
        if row is None:
            raise TaskError("Görev yok.")
        if row["state"] in ("succeeded", "cancelled"):
            raise TaskError("Görev zaten kapandı.")
        now = utcnow()
        with self.db.transaction() as c:
            c.execute("UPDATE tasks SET state = 'cancelled', updated_at = ? WHERE id = ?", (now, task_id))
        return self.get(task_id)

    def delete(self, task_id: str) -> dict:
        row = self.db.query_one("SELECT state FROM tasks WHERE id = ?", (task_id,))
        if row is None:
            raise TaskError("Görev yok.")
        if row["state"] not in ("succeeded", "failed", "cancelled"):
            raise TaskError("Yalnızca bitti, hata veya iptal durumundaki görev silinir.")
        with self.db.transaction() as c:
            c.execute("UPDATE tasks SET parent_id = NULL WHERE parent_id = ?", (task_id,))
            c.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return {"removed": task_id}

    def purge_terminal(self) -> dict:
        rows = self.db.query(
            "SELECT id FROM tasks WHERE state IN ('succeeded', 'failed', 'cancelled') ORDER BY updated_at"
        )
        removed = []
        for row in rows:
            try:
                self.delete(row["id"])
                removed.append(row["id"])
            except TaskError:
                continue
        return {"removed": removed, "count": len(removed)}

    def reconcile(self, task_id: str, decision: str) -> dict:
        task = self.get(task_id)
        if task["state"] != "needs_reconciliation":
            raise TaskError("Uzlaştırma bekleyen görev değil.")
        now = utcnow()
        if decision == "cancel":
            with self.db.transaction() as c:
                c.execute("UPDATE tasks SET state = 'cancelled', updated_at = ? WHERE id = ?", (now, task_id))
            return self.get(task_id)
        if decision == "verified":
            with self.db.transaction() as c:
                c.execute(
                    "UPDATE task_steps SET state = 'verified', updated_at = ? WHERE task_id = ? AND state = 'uncertain'",
                    (now, task_id),
                )
                c.execute("UPDATE tasks SET state = 'succeeded', last_error = NULL, updated_at = ? WHERE id = ?", (now, task_id))
            return self.get(task_id)
        if decision == "retry":
            with self.db.transaction() as c:
                c.execute("DELETE FROM task_steps WHERE task_id = ? AND state IN ('uncertain','intended','applied')", (task_id,))
                c.execute("UPDATE tasks SET state = 'queued', last_error = NULL, updated_at = ? WHERE id = ?", (now, task_id))
            return self.run(task_id)
        raise TaskError("Karar verified, retry veya cancel olmalı.")

    def tick(self, now: str | None = None) -> int:
        stamp = now or utcnow()
        n = 0
        rows = self.db.query(
            """SELECT id FROM tasks
               WHERE state = 'queued' AND (schedule_at IS NULL OR schedule_at <= ?)
               ORDER BY created_at LIMIT 5""",
            (stamp,),
        )
        for row in rows:
            locked = self.db.query_one("SELECT id FROM tasks WHERE id = ? AND state = 'queued'", (row["id"],))
            if not locked:
                continue
            try:
                self.run(row["id"])
                n += 1
            except TaskError:
                continue
        return n

    def run(self, task_id: str) -> dict:
        task = self.get(task_id)
        if task["state"] not in ("queued",):
            raise TaskError("Görev çalıştırılacak durumda değil.")
        busy = self.db.query_one("SELECT id FROM tasks WHERE id = ? AND state = 'running'", (task_id,))
        if busy:
            raise TaskError("Aynı görev zaten çalışıyor.")
        now = utcnow()
        with self.db.transaction() as c:
            c.execute("UPDATE tasks SET state = 'running', updated_at = ? WHERE id = ? AND state = 'queued'", (now, task_id))
        try:
            result = self._execute(task)
            now = utcnow()
            nxt = self._next_time(task, now) if task.get("interval_seconds") else None
            with self.db.transaction() as c:
                if nxt:
                    c.execute(
                        "UPDATE tasks SET state = 'queued', schedule_at = ?, checkpoint_json = ?, last_error = NULL, updated_at = ? WHERE id = ?",
                        (nxt, json.dumps({"last": result}, ensure_ascii=False), now, task_id),
                    )
                else:
                    c.execute(
                        "UPDATE tasks SET state = 'succeeded', checkpoint_json = ?, last_error = NULL, updated_at = ? WHERE id = ?",
                        (json.dumps({"last": result}, ensure_ascii=False), now, task_id),
                    )
        except (TaskError, FileRejected, NetRejected) as e:
            now = utcnow()
            with self.db.transaction() as c:
                c.execute(
                    "UPDATE tasks SET state = 'failed', last_error = ?, updated_at = ? WHERE id = ?",
                    (str(e), now, task_id),
                )
        except Exception as e:  # yazma belirsiz kalabilir
            now = utcnow()
            with self.db.transaction() as c:
                c.execute(
                    "UPDATE tasks SET state = 'needs_reconciliation', last_error = ?, updated_at = ? WHERE id = ?",
                    (f"Belirsiz sonuç: {e}", now, task_id),
                )
                c.execute(
                    """UPDATE task_steps SET state = 'uncertain', error = ?, updated_at = ?
                       WHERE task_id = ? AND state IN ('intended','applied')""",
                    (str(e), now, task_id),
                )
        return self.get(task_id)

    def _next_time(self, task, now: str) -> str | None:
        seconds = task["interval_seconds"] if isinstance(task, dict) else task["interval_seconds"]
        if not seconds:
            return None
        try:
            base = datetime.fromisoformat((now or utcnow()).replace("Z", "+00:00"))
        except ValueError:
            base = datetime.now(UTC)
        return (base + timedelta(seconds=int(seconds))).isoformat()

    def _add_step(self, task_id: str, ordinal: int, tool: str, intent: dict, key: str) -> str:
        now = utcnow()
        sid = _id()
        with self.db.transaction() as c:
            c.execute(
                """INSERT INTO task_steps (id, task_id, ordinal, tool, intent_json, idempotency_key, state, result_json, error, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'intended', NULL, NULL, ?, ?)""",
                (sid, task_id, ordinal, tool, json.dumps(intent, ensure_ascii=False), key, now, now),
            )
            c.execute(
                "UPDATE tasks SET checkpoint_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps({"step": ordinal, "tool": tool}, ensure_ascii=False), now, task_id),
            )
        return sid

    def _finish_step(self, step_id: str, result: dict) -> None:
        now = utcnow()
        with self.db.transaction() as c:
            c.execute(
                "UPDATE task_steps SET state = 'verified', result_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(result, ensure_ascii=False), now, step_id),
            )

    def _execute(self, task: dict) -> dict:
        kind = task["kind"]
        params = task["params"]
        grant = task["grant"]
        prior = self.db.query_one(
            "SELECT * FROM task_steps WHERE task_id = ? AND state = 'verified' ORDER BY ordinal DESC",
            (task["id"],),
        )
        if prior:
            return json.loads(prior["result_json"])
        key = _hash({"task": task["id"], "kind": kind, "params": params})
        sid = self._add_step(task["id"], 0, kind, params, key)
        if kind == "clock.now":
            result = {"utc": datetime.now(UTC).isoformat()}
        elif kind == "web.fetch":
            result = self.fetch(
                params["url"],
                allowed_hosts=grant.get("hosts") or [],
                route=task["route"],
                tor_socks=self.tor_socks,
                offline=self.offline,
            )
        elif kind == "files.write":
            pending = self.db.query_one(
                "SELECT id FROM approvals WHERE task_id = ? AND decision = 'granted' ORDER BY decided_at DESC",
                (task["id"],),
            )
            if pending is None:
                raise TaskError("Yazma onayı yok.")
            result = write_inside(
                grant.get("roots") or [],
                params["relative"],
                params.get("content") or "",
                expected_hash=params.get("expected_hash") or "missing",
            )
            try:
                art = register_file(
                    self.db,
                    result["path"],
                    kind="file_write",
                    title=params["relative"],
                    media_type="text/plain",
                    task_id=task["id"],
                )
                result["artifact_id"] = art["id"]
            except Exception:
                pass
        else:
            raise TaskError("Bilinmeyen tür.")
        self._finish_step(sid, result)
        return result
