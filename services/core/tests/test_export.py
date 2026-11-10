from pathlib import Path

from ahirena_core.db import Database
from ahirena_core.export import consistent_backup, export_personal
from ahirena_core.feedback import create_feedback
from ahirena_core.knowledge import add_memory


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
    assert "secrets" in text
    assert "AHIRENA_TOKEN" not in text
    backup = consistent_backup(db, tmp_path)
    assert Path(backup["path"], "ahirena.db").is_file()
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
