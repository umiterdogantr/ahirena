from ahirena_core.db import Database
from ahirena_core.training import TrainingError, capability, create_run, list_runs
import pytest


def test_training_stays_planned(tmp_path):
    cap = capability(tmp_path)
    assert cap["status"] == "planlandı"
    assert cap["runner"] == "yok"
    db = Database(tmp_path / "t.db")
    run = create_run(db, {"base_model": "gemma4:e2b-it-qat", "goal": "Türkçe tarih formatı", "start": False})
    assert run["status"] == "planned"
    assert run["activated"] is False
    with pytest.raises(TrainingError, match="çalıştırıcısı yok"):
        create_run(db, {"base_model": "x", "goal": "y", "start": True})
    assert len(list_runs(db)) == 1
    db.close()


def test_http_training_endpoint(live):
    with live.client() as c:
        info = c.get("/api/training").json()
        assert info["capability"]["status"] == "planlandı"
        assert "feedback" in info
        bad = c.post("/api/training/runs", json={"base_model": "x", "goal": "y", "start": True})
        assert bad.status_code == 400
        ok = c.post("/api/training/runs", json={"base_model": "gemma4:e2b-it-qat", "goal": "kısa Türkçe tarih"})
        assert ok.status_code == 200
        assert ok.json()["status"] == "planned"
        fb = c.post("/api/feedback", json={"issue_type": "bad_instruction", "note": "Tarih formatı yanlış"})
        assert fb.status_code == 200
        assert fb.json()["trains_model"] is False
        listed = c.get("/api/feedback").json()
        assert any(i["id"] == fb.json()["id"] for i in listed["items"])
        patched = c.patch(f"/api/feedback/{fb.json()['id']}", json={"status": "reviewed"})
        assert patched.status_code == 200
        assert patched.json()["status"] == "reviewed"
