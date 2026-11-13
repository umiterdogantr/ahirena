"""Ayrılmış holdout değerlendirme.

Model kalitesi için uydurma yüzde üretilmez. Yalnızca doğrulanabilir
beklenti (alt metin) ve ölçülen süre/token kaydı tutulur.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .db import Database, utcnow
from .providers import ChatMessage, ChatOptions

MAX_ITEMS = 40


class EvaluationError(ValueError):
    pass


def list_sets(db: Database) -> list[dict]:
    rows = db.query("SELECT * FROM evaluation_sets ORDER BY created_at DESC")
    return [_set(r) for r in rows]


def get_set(db: Database, set_id: str) -> dict:
    row = db.query_one("SELECT * FROM evaluation_sets WHERE id = ?", (set_id,))
    if row is None:
        raise EvaluationError("Değerlendirme kümesi yok.")
    return _set(row)


def create_set(db: Database, name: str, items: list[dict], *, data_version: str = "v1") -> dict:
    name = (name or "").strip()
    if not name or len(name) > 120:
        raise EvaluationError("Küme adı 1–120 karakter olmalı.")
    cleaned = _clean_items(items)
    if not cleaned:
        raise EvaluationError("En az bir holdout maddesi gerekli.")
    sid = uuid.uuid4().hex
    now = utcnow()
    with db.transaction() as c:
        c.execute(
            """INSERT INTO evaluation_sets (id, name, data_version, items_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (sid, name, (data_version or "v1").strip()[:80], json.dumps(cleaned, ensure_ascii=False), now),
        )
    return get_set(db, sid)


def list_runs(db: Database) -> list[dict]:
    rows = db.query("SELECT * FROM evaluation_runs ORDER BY created_at DESC")
    return [_run(r) for r in rows]


def get_run(db: Database, run_id: str) -> dict:
    row = db.query_one("SELECT * FROM evaluation_runs WHERE id = ?", (run_id,))
    if row is None:
        raise EvaluationError("Değerlendirme koşusu yok.")
    return _run(row)


async def run_evaluation(
    db: Database,
    provider,
    *,
    set_id: str,
    model_id: str,
    candidate_id: str | None = None,
) -> dict:
    aset = get_set(db, set_id)
    model_id = (model_id or "").strip()
    if not model_id:
        raise EvaluationError("Model kimliği gerekli.")
    results: list[dict[str, Any]] = []
    checked = 0
    passed = 0
    for i, item in enumerate(aset["items"]):
        prompt = item["prompt"]
        expect = item.get("expect_contains") or ""
        t0 = time.perf_counter()
        content = ""
        error = None
        metrics: dict[str, Any] = {}
        try:
            async for ev in provider.chat_stream(
                model_id,
                [ChatMessage("user", prompt)],
                ChatOptions(think=False),
            ):
                if ev.kind == "content":
                    content += ev.text or ""
                elif ev.kind == "done" and isinstance(ev.stats, dict):
                    metrics = {
                        k: v
                        for k, v in ev.stats.items()
                        if k in ("output_tokens", "tokens_per_s", "prompt_tokens")
                    }
        except Exception as e:  # noqa: BLE001 — madde sonucu kaydedilir
            error = str(e)
        wall_ms = int((time.perf_counter() - t0) * 1000)
        metrics["wall_ms"] = wall_ms
        row: dict[str, Any] = {
            "ordinal": i,
            "prompt": prompt[:500],
            "response": content[:4000],
            "error": error,
            "metrics": metrics,
            "expect_contains": expect or None,
            "match": None,
        }
        if expect and not error:
            checked += 1
            ok = expect.casefold() in content.casefold()
            row["match"] = ok
            if ok:
                passed += 1
        results.append(row)
    summary = {
        "items": len(results),
        "checked": checked,
        "passed": passed,
        "failed": checked - passed,
        "unchecked": len(results) - checked,
        "note": (
            "Uydurma doğruluk yüzdesi yok. "
            "match yalnızca expect_contains alt metin denetimidir."
            if checked
            else "Beklenti metni olmayan maddeler yalnızca çıktı ve süre kaydeder."
        ),
    }
    rid = uuid.uuid4().hex
    now = utcnow()
    with db.transaction() as c:
        c.execute(
            """INSERT INTO evaluation_runs
               (id, set_id, provider_id, model_id, candidate_id, status, results_json, summary_json, created_at)
               VALUES (?, ?, ?, ?, ?, 'complete', ?, ?, ?)""",
            (
                rid,
                set_id,
                getattr(provider, "id", "unknown"),
                model_id,
                (candidate_id or "").strip() or None,
                json.dumps(results, ensure_ascii=False),
                json.dumps(summary, ensure_ascii=False),
                now,
            ),
        )
    return get_run(db, rid)


def _clean_items(items: list[dict]) -> list[dict]:
    if not isinstance(items, list):
        raise EvaluationError("items liste olmalı.")
    if len(items) > MAX_ITEMS:
        raise EvaluationError(f"En fazla {MAX_ITEMS} madde.")
    out = []
    for raw in items:
        if not isinstance(raw, dict):
            raise EvaluationError("Madde nesne olmalı.")
        prompt = str(raw.get("prompt") or "").strip()
        if len(prompt) < 2:
            raise EvaluationError("Her maddede prompt gerekli.")
        expect = str(raw.get("expect_contains") or "").strip()
        note = str(raw.get("note") or "").strip()
        out.append(
            {
                "prompt": prompt[:4000],
                "expect_contains": expect[:500] or None,
                "note": note[:500] or None,
            }
        )
    return out


def _set(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "data_version": row["data_version"],
        "items": json.loads(row["items_json"]),
        "created_at": row["created_at"],
    }


def _run(row) -> dict:
    return {
        "id": row["id"],
        "set_id": row["set_id"],
        "provider_id": row["provider_id"],
        "model_id": row["model_id"],
        "candidate_id": row["candidate_id"],
        "status": row["status"],
        "results": json.loads(row["results_json"]),
        "summary": json.loads(row["summary_json"]),
        "created_at": row["created_at"],
    }
