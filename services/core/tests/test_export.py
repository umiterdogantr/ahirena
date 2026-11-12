import pytest
from pathlib import Path

from ahirena_core.db import Database
from ahirena_core.diagnostics import save_diagnostics
from ahirena_core.export import (
    ExportError,
    apply_pending_restore,
    cancel_pending_restore,
    consistent_backup,
    export_conversation,
    export_personal,
    pending_restore,
    save_comparison,
    schedule_restore,
)
from ahirena_core.feedback import create_feedback
from ahirena_core.knowledge import add_memory
from ahirena_core.store import Store


def test_export_and_backup_omit_indexes(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    db = Database(data / "ahirena.db")
    add_memory(db, "genel", "Tercih Türkçe.", "kullanıcı")
    create_feedback(db, {"issue_type": "other", "note": "Düzeltme örneği"})
    (tmp_path / "config.json").write_text('{"ollama": {"manage": true}, "sql": {"server": "x"}}', encoding="utf-8")
    exported = export_personal(db, tmp_path)
    assert Path(exported["path"], "export.json").is_file()
    text = Path(exported["path"], "export.json").read_text(encoding="utf-8")
    assert "Tercih Türkçe" in text
    assert "Düzeltme örneği" in text
    assert "feedback" in text
    assert "skills_meta" in text or "skills" in text
    assert "prompt_templates" in text
    assert "secrets" in text
    assert "AHIRENA_TOKEN" not in text
    backup = consistent_backup(db, tmp_path)
    assert Path(backup["path"], "ahirena.db").is_file()
    db.close()


def test_schedule_and_apply_restore(tmp_path: Path):
    data = tmp_path
    live_dir = data / "data"
    live_dir.mkdir()
    db = Database(live_dir / "ahirena.db")
    add_memory(db, "genel", "eski içerik", "test")
    backup = consistent_backup(db, data)
    bak_db = Path(backup["path"]) / "ahirena.db"
    with db.transaction() as conn:
        conn.execute("DELETE FROM memory_items")
    db.close()

    with pytest.raises(ExportError, match="confirm"):
        schedule_restore(data, bak_db, confirm=False)
    scheduled = schedule_restore(data, backup["path"], confirm=True)
    assert scheduled["restart_required"] is True
    assert pending_restore(data)["source_db"]
    assert cancel_pending_restore(data)["cancelled"] is True
    assert pending_restore(data) is None

    schedule_restore(data, bak_db, confirm=True)
    result = apply_pending_restore(data)
    assert result and result["ok"] is True
    assert pending_restore(data) is None
    restored = Database(live_dir / "ahirena.db")
    rows = restored.query("SELECT body FROM memory_items")
    assert any("eski içerik" in r["body"] for r in rows)
    restored.close()


def test_export_conversation_and_diagnostics(tmp_path: Path):
    data = tmp_path
    (data / "data").mkdir()
    db = Database(data / "data" / "ahirena.db")
    store = Store(db)
    conv = store.create_conversation("Deneme", "fake-model", "genel")
    store.add_message(conv.id, "user", "Merhaba dünya", "complete")
    out = export_conversation(db, data, conv.id)
    assert Path(out["path"]).is_file()
    text = Path(out["path"]).read_text(encoding="utf-8")
    assert "Merhaba dünya" in text
    assert out["message_count"] >= 1
    saved = save_diagnostics(db, data, active_runs=[], task_counts={"queued": 0})
    assert Path(saved["path"]).is_file()
    assert saved["diagnostics"]["local_first"] is True
    db.close()


def test_save_comparison(tmp_path: Path):
    data = tmp_path
    (data / "data").mkdir()
    db = Database(data / "data" / "ahirena.db")
    out = save_comparison(
        db,
        data,
        prompt="2+2?",
        results=[
            {"model_id": "a", "content": "4", "status": "complete", "error": None, "metrics": {"wall_ms": 10}},
            {"model_id": "b", "content": "dört", "status": "complete", "error": None, "metrics": None},
        ],
        context_length=8192,
    )
    text = Path(out["path"]).read_text(encoding="utf-8")
    assert "2+2?" in text
    assert out["result_count"] == 2
    assert "ahirena-compare" in text or "ahirena-compare" in out["path"]
    db.close()


def test_http_export_backup(live, tmp_path: Path):
    with live.client() as c:
        c.post("/api/memory", json={"workspace_id": "genel", "body": "X", "source_ref": "test"})
        exp = c.post("/api/export")
        assert exp.status_code == 200
        assert Path(exp.json()["path"]).is_dir()
        bak = c.post("/api/backup")
        assert bak.status_code == 200
        assert Path(bak.json()["path"], "ahirena.db").is_file()
        bad = c.post("/api/backup/restore", json={"path": bak.json()["path"], "confirm": False})
        assert bad.status_code == 400
        ok = c.post("/api/backup/restore", json={"path": bak.json()["path"], "confirm": True})
        assert ok.status_code == 200
        assert ok.json()["restart_required"] is True
        pend = c.get("/api/backup/pending")
        assert pend.status_code == 200
        assert pend.json()["pending"]
        cancel = c.request("DELETE", "/api/backup/pending")
        assert cancel.status_code == 200
        assert cancel.json()["cancelled"] is True
        created = c.post("/api/conversations", json={"title": "Aktarım", "model_id": "fake"})
        assert created.status_code == 201
        cid = created.json()["id"]
        cex = c.post(f"/api/conversations/{cid}/export")
        assert cex.status_code == 200
        assert Path(cex.json()["path"]).is_file()
        diag = c.post("/api/diagnostics/save")
        assert diag.status_code == 200
        assert Path(diag.json()["path"]).is_file()
        cmp = c.post(
            "/api/compare/save",
            json={
                "prompt": "Merhaba",
                "results": [{"model_id": "fake-model", "content": "Selam", "status": "complete"}],
            },
        )
        assert cmp.status_code == 200
        assert Path(cmp.json()["path"]).is_file()
