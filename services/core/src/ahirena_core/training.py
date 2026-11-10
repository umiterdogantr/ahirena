"""Eğitim ve adaptör kaydı.

GTX 1650 4 GB'ta LoRA/QLoRA hattı doğrulanmadı. Çalıştırıcı yokken eğitim
başlamış gibi gösterilmez; kayıtlar aday veya planlandı durumunda kalır.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from .db import Database, utcnow

# Bu makinede ölçülen VRAM sınırı; eğitim orkestrasyonu ayrıca doğrulanmalı.
MIN_VRAM_MIB_HINT = 8192


class TrainingError(ValueError):
    pass


def capability(data_dir: Path) -> dict:
    report_dir = data_dir / "reports"
    latest = None
    if report_dir.is_dir():
        files = sorted(report_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            try:
                latest = json.loads(files[0].read_text(encoding="utf-8"))
            except (OSError, ValueError):
                latest = None
    gpu = None
    if isinstance(latest, dict):
        gpu = (latest.get("machine") or {}).get("gpu") or latest.get("gpu")
    return {
        "runner": "yok",
        "status": "planlandı",
        "methods": ["PEFT LoRA", "QLoRA"],
        "min_vram_mib_hint": MIN_VRAM_MIB_HINT,
        "note": (
            "Eğitim sohbet sunucusundan ayrı süreçte çalışmalı. "
            "Bu cihazda LoRA hattı doğrulanmadan iş başlatılmaz. "
            "RAG/talimat/araç düzeltmesi önce değerlendirilir."
        ),
        "latest_bench": latest.get("created_at") if isinstance(latest, dict) else None,
        "gpu_hint": gpu,
    }


def list_runs(db: Database) -> list[dict]:
    rows = db.query("SELECT * FROM training_runs ORDER BY created_at DESC")
    return [_run(r) for r in rows]


def create_run(db: Database, body: dict) -> dict:
    base = (body.get("base_model") or "").strip()
    goal = (body.get("goal") or "").strip()
    if not base or not goal:
        raise TrainingError("Temel model ve hedef davranış zorunlu.")
    if body.get("start"):
        raise TrainingError("Eğitim çalıştırıcısı yok; iş başlatılamaz. Kayıt yalnızca planlandı olarak tutulur.")
    now = utcnow()
    rid = uuid.uuid4().hex
    with db.transaction() as c:
        c.execute(
            """INSERT INTO training_runs (
                id, base_model, goal, data_version, status, settings_json, metrics_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'planned', ?, NULL, ?, ?)""",
            (
                rid,
                base,
                goal,
                (body.get("data_version") or "tanımsız").strip(),
                json.dumps(
                    {
                        "method": body.get("method") or "lora",
                        "why_not_rag": body.get("why_not_rag") or "",
                        "holdout": body.get("holdout") or "",
                    },
                    ensure_ascii=False,
                ),
                now,
                now,
            ),
        )
    return get_run(db, rid)


def get_run(db: Database, run_id: str) -> dict:
    row = db.query_one("SELECT * FROM training_runs WHERE id = ?", (run_id,))
    if row is None:
        raise TrainingError("Eğitim kaydı yok.")
    return _run(row)


def list_adapters(db: Database) -> list[dict]:
    rows = db.query("SELECT * FROM adapters ORDER BY created_at DESC")
    return [dict(r) for r in rows]


def _run(row) -> dict:
    return {
        "id": row["id"],
        "base_model": row["base_model"],
        "goal": row["goal"],
        "data_version": row["data_version"],
        "status": row["status"],
        "settings": json.loads(row["settings_json"]) if row["settings_json"] else {},
        "metrics": json.loads(row["metrics_json"]) if row["metrics_json"] else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "activated": False,
    }
