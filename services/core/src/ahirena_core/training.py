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
    return [_adapter(r) for r in rows]


def register_adapter(
    db: Database,
    data_dir: Path,
    *,
    path: str,
    base_model: str,
    training_id: str | None = None,
) -> dict:
    """Adaptör dosya kaydı. Çıkarım motoruna yüklemez."""
    base_model = (base_model or "").strip()
    if not base_model:
        raise TrainingError("Temel model gerekli.")
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise TrainingError(f"Adaptör yolu yok: {p}")
    root = data_dir.resolve()
    try:
        p.relative_to(root)
    except ValueError as e:
        raise TrainingError("Adaptör yalnızca uygulama veri klasörü altında kayıt edilir.") from e
    if training_id:
        if not db.query_one("SELECT id FROM training_runs WHERE id = ?", (training_id,)):
            raise TrainingError("Eğitim kaydı yok.")
    aid = uuid.uuid4().hex
    now = utcnow()
    with db.transaction() as c:
        c.execute(
            """INSERT INTO adapters (id, training_id, base_model, path, status, created_at)
               VALUES (?, ?, ?, ?, 'candidate', ?)""",
            (aid, training_id or None, base_model, str(p), now),
        )
    return get_adapter(db, aid)


def get_adapter(db: Database, adapter_id: str) -> dict:
    row = db.query_one("SELECT * FROM adapters WHERE id = ?", (adapter_id,))
    if row is None:
        raise TrainingError("Adaptör yok.")
    return _adapter(row)


def activate_adapter(db: Database, adapter_id: str) -> dict:
    """Kayıtta etkin işaretler; Ollama/PEFT yüklemesi bu sürümde yok."""
    item = get_adapter(db, adapter_id)
    if not Path(item["path"]).exists():
        raise TrainingError("Adaptör dosyası diskte yok; etkinleştirilmez.")
    with db.transaction() as c:
        c.execute(
            "UPDATE adapters SET status = 'rolled_back' WHERE status = 'active' AND id != ?",
            (adapter_id,),
        )
        c.execute("UPDATE adapters SET status = 'active' WHERE id = ?", (adapter_id,))
    out = get_adapter(db, adapter_id)
    out["note"] = (
        "Kayıt etkin. Bu sürüm Ollama'ya PEFT adaptörü yüklemez; "
        "çıkarım motoru desteği ayrıca doğrulanmalıdır."
    )
    return out


def rollback_adapter(db: Database, adapter_id: str) -> dict:
    item = get_adapter(db, adapter_id)
    if item["status"] != "active":
        raise TrainingError("Yalnızca etkin adaptör geri alınır.")
    with db.transaction() as c:
        c.execute("UPDATE adapters SET status = 'rolled_back' WHERE id = ?", (adapter_id,))
    out = get_adapter(db, adapter_id)
    out["note"] = "Etkin işaret kaldırıldı; önceki temel modele dönüş kayıt düzeyinde."
    return out


def phase6_status(data_dir: Path, db: Database) -> dict:
    """Aşama 6 ürün kapanış özeti (LoRA çalıştırıcı ayrı)."""
    cap = capability(data_dir)
    eval_n = db.query_one("SELECT COUNT(*) AS n FROM evaluation_runs")
    acc_n = db.query_one("SELECT COUNT(*) AS n FROM acceptance_reports")
    latest_acc = db.query_one("SELECT summary_json FROM acceptance_reports ORDER BY created_at DESC LIMIT 1")
    closed = False
    release = False
    if latest_acc:
        try:
            summary = json.loads(latest_acc["summary_json"])
            closed = bool(summary.get("phase6_closed"))
            release = bool(summary.get("release_closed"))
        except ValueError:
            closed = False
            release = False
    product = closed and int(eval_n["n"] or 0) > 0
    return {
        "stage": 6,
        "product_closed": product,
        "release_closed": release and product,
        "training_runner": cap["status"],
        "evaluation_runs": int(eval_n["n"] or 0),
        "acceptance_reports": int(acc_n["n"] or 0),
        "note": (
            "Yayın/kabul kapanışı: KAB matrisi + holdout tamam. LoRA/OCR/TTS planlandı."
            if release and product
            else (
                "Aşama 6 ürün kapanışı: holdout + kabul matrisi tamam."
                if product
                else "Holdout değerlendirme ve başarılı kabul matrisi çalıştırılmalı."
            )
        ),
    }


def _adapter(row) -> dict:
    path = row["path"]
    return {
        "id": row["id"],
        "training_id": row["training_id"],
        "base_model": row["base_model"],
        "path": path,
        "status": row["status"],
        "created_at": row["created_at"],
        "exists": Path(path).exists(),
        "loaded_in_runtime": False,
    }


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
