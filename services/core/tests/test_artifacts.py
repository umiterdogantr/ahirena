from pathlib import Path

from ahirena_core.artifacts import preview, register_file
from ahirena_core.db import Database
from ahirena_core.export import export_personal


def test_artifact_registers_export_and_preview(tmp_path: Path):
    data = tmp_path
    db = Database(tmp_path / "data" / "ahirena.db")
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    out = export_personal(db, data)
    assert out["artifact_id"]
    art = preview(db, out["artifact_id"])
    assert art["exists"] is True
    assert "ahirena-export" in art["preview"] or "exported_at" in art["preview"]
    f = tmp_path / "note.txt"
    f.write_text("bir", encoding="utf-8")
    a1 = register_file(db, f, kind="file_write", title="note.txt", media_type="text/plain")
    f.write_text("iki", encoding="utf-8")
    a2 = register_file(db, f, kind="file_write", title="note.txt", media_type="text/plain")
    assert a2["version"] == a1["version"] + 1
    db.close()


def test_http_artifacts(live):
    with live.client() as c:
        exp = c.post("/api/export")
        assert exp.status_code == 200
        listed = c.get("/api/artifacts")
        assert listed.status_code == 200
        assert any(a["kind"] == "export" for a in listed.json())
        aid = next(a["id"] for a in listed.json() if a["kind"] == "export")
        prev = c.get(f"/api/artifacts/{aid}/preview")
        assert prev.status_code == 200
        assert prev.json()["exists"] is True
