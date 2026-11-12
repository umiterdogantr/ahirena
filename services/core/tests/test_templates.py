from ahirena_core.db import Database
from ahirena_core.templates import TemplateError, create_template, render, restore_version, update_template


def test_render_requires_params():
    out = render("Merhaba {{ad}}, konu: {{konu}}", {"ad": "Ali", "konu": "stok"})
    assert out["text"] == "Merhaba Ali, konu: stok"
    try:
        render("{{ad}}", {})
        assert False
    except TemplateError as e:
        assert "ad" in str(e)


def test_template_version_history(tmp_path):
    db = Database(tmp_path / "t.db")
    item = create_template(db, "Özet", "Hafta {{hafta}} özeti")
    assert item["version"] == 1
    assert item["params"] == ["hafta"]
    updated = update_template(db, item["id"], "Özet", "Ay {{ay}} özeti")
    assert updated["version"] == 2
    assert updated["params"] == ["ay"]
    restored = restore_version(db, item["id"], 1)
    assert restored["version"] == 3
    assert "{{hafta}}" in restored["body"]
    db.close()


def test_http_templates(live):
    with live.client() as c:
        created = c.post("/api/templates", json={"name": "Karşılama", "body": "Merhaba {{kisi}}"})
        assert created.status_code == 200, created.text
        tid = created.json()["id"]
        filled = c.post(f"/api/templates/{tid}/render", json={"params": {"kisi": "Ayşe"}})
        assert filled.status_code == 200
        assert filled.json()["text"] == "Merhaba Ayşe"
        missing = c.post(f"/api/templates/{tid}/render", json={"params": {}})
        assert missing.status_code == 400
        patched = c.patch(f"/api/templates/{tid}", json={"name": "Karşılama", "body": "Selam {{kisi}}"})
        assert patched.status_code == 200
        assert patched.json()["version"] == 2
        versions = c.get(f"/api/templates/{tid}/versions")
        assert versions.status_code == 200
        assert len(versions.json()["versions"]) >= 2
        restored = c.post(f"/api/templates/{tid}/restore", json={"version": 1})
        assert restored.status_code == 200
        assert "Merhaba" in restored.json()["body"]
        assert c.delete(f"/api/templates/{tid}").status_code == 200
        assert c.get("/api/templates").json() == []
