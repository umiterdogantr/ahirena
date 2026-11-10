from pathlib import Path

from ahirena_core.diagnostics import build_diagnostics
from ahirena_core.skilldraft import discard_candidate, draft_skill, list_candidates
from ahirena_core.db import Database
from ahirena_core.skills import SkillRegistry


def test_diagnostics_are_honest(tmp_path: Path):
    d = build_diagnostics(tmp_path, active_runs=[], task_counts={"queued": 0, "running": 0, "waiting_approval": 0, "needs_reconciliation": 0, "attention": 0})
    assert d["local_first"] is True
    assert d["remote_providers"] is False
    assert d["network"]["os_firewall"] is False
    assert d["media"]["ocr"] == "planlandı"
    assert d["training"]["status"] == "planlandı"
    assert d["scripts"] == "kapalı"
    assert d["browser_sessions"] == "kapalı"


def test_candidate_discard_removes_package(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    cand = draft_skill(db, tmp_path, "Saat göstersin lütfen.")
    assert Path(cand["package_dir"]).is_dir()
    out = discard_candidate(db, cand["id"])
    assert out["discarded"] == cand["id"]
    assert not Path(cand["package_dir"]).exists()
    assert list_candidates(db) == []
    db.close()


def test_import_marks_candidate(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    cand = draft_skill(db, tmp_path, "Saat göstersin lütfen.")
    reg = SkillRegistry(db, tmp_path)
    imported = reg.import_dir(cand["package_dir"])
    assert imported["id"]
    assert list_candidates(db) == []
    row = db.query_one("SELECT status FROM skill_candidates WHERE id = ?", (cand["id"],))
    assert row["status"] == "imported"
    db.close()


def test_http_diagnostics_and_cancel_all(live):
    with live.client() as c:
        d = c.get("/api/diagnostics")
        assert d.status_code == 200
        body = d.json()
        assert body["remote_providers"] is False
        assert body["media"]["ocr"] == "planlandı"
        cancelled = c.post("/api/runs/cancel-all")
        assert cancelled.status_code == 200
        assert cancelled.json()["count"] == 0
