import pytest
from pathlib import Path

from ahirena_core.artifacts import ArtifactError, forget, list_artifacts, preview, register_file
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


def test_forget_keeps_file_by_default(tmp_path: Path):
    db = Database(tmp_path / "ahirena.db")
    f = tmp_path / "keep.txt"
    f.write_text("kal", encoding="utf-8")
    art = register_file(db, f, kind="file", title="keep.txt", media_type="text/plain")
    out = forget(db, art["id"], delete_file=False)
    assert out["file_deleted"] is False
    assert f.is_file()
    assert list_artifacts(db) == []
    db.close()


def test_forget_deletes_only_under_data_dir(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    db = Database(data / "ahirena.db")
    inside = data / "exports" / "in.txt"
    inside.parent.mkdir(parents=True)
    inside.write_text("iç", encoding="utf-8")
    outside = tmp_path / "out.txt"
    outside.write_text("dış", encoding="utf-8")
    a_in = register_file(db, inside, kind="export", title="in.txt", media_type="text/plain")
    a_out = register_file(db, outside, kind="file", title="out.txt", media_type="text/plain")
    assert forget(db, a_in["id"], delete_file=True, data_dir=data)["file_deleted"] is True
    assert not inside.is_file()
    with pytest.raises(ArtifactError, match="veri klasörü"):
        forget(db, a_out["id"], delete_file=True, data_dir=data)
    assert outside.is_file()
    assert list_artifacts(db, kind="file")[0]["id"] == a_out["id"]
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
        filt = c.get("/api/artifacts", params={"kind": "export"})
        assert filt.status_code == 200
        assert all(a["kind"] == "export" for a in filt.json())
        gone = c.request("DELETE", f"/api/artifacts/{aid}", json={"delete_file": False})
        assert gone.status_code == 200
        assert gone.json()["file_deleted"] is False
        assert c.get(f"/api/artifacts/{aid}/preview").status_code == 404
