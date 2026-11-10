"""Görev, onay, kesinti ve ağ rotası."""

from pathlib import Path

import httpx
import pytest

from ahirena_core.db import Database
from ahirena_core.netpolicy import NetRejected, assert_url_allowed
from ahirena_core.tasks import TaskEngine, TaskError
from ahirena_core.webfetch import fetch_url


def test_private_and_metadata_hosts_are_blocked():
    with pytest.raises(NetRejected, match="Özel"):
        assert_url_allowed("http://127.0.0.1/x", ["127.0.0.1"])
    with pytest.raises(NetRejected, match="Özel"):
        assert_url_allowed("http://192.168.1.1/", ["192.168.1.1"])
    with pytest.raises(NetRejected, match="meta"):
        assert_url_allowed("http://metadata.google.internal/", ["metadata.google.internal"])
    with pytest.raises(NetRejected, match="Özel"):
        assert_url_allowed("http://ok.test/", ["ok.test"], resolver=lambda h: ["169.254.169.254"])
    with pytest.raises(NetRejected, match="ağ izni"):
        assert_url_allowed("http://ok.test/", ["diger.test"], resolver=lambda h: ["8.8.8.8"])


def test_redirect_to_loopback_is_blocked_and_tor_does_not_fallback():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "ok.test" in str(request.url):
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/gizli"})
        return httpx.Response(200, text="sızdı")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, follow_redirects=False) as client:
        with pytest.raises(NetRejected, match="Özel"):
            fetch_url(
                "http://ok.test/a",
                allowed_hosts=["ok.test"],
                client=client,
                resolver=lambda h: ["8.8.8.8"],
            )
    assert calls == ["http://ok.test/a"]

    calls.clear()
    with httpx.Client(transport=transport, follow_redirects=False) as client:
        with pytest.raises(NetRejected, match="Tor"):
            fetch_url(
                "http://ok.test/a",
                allowed_hosts=["ok.test"],
                route="tor",
                tor_socks="127.0.0.1:1",
                client=client,
                resolver=lambda h: ["8.8.8.8"],
            )
    assert calls == []


def test_write_needs_approval_and_stale_grant_fails(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    engine = TaskEngine(db)
    root = tmp_path / "out"
    root.mkdir()
    task = engine.create(
        {
            "kind": "files.write",
            "params": {"relative": "a.txt", "content": "bir"},
            "grant": {"roots": [str(root)]},
        }
    )
    assert task["state"] == "waiting_approval"
    with pytest.raises(TaskError, match="çalıştırılacak"):
        engine.run(task["id"])
    approved = engine.approve(task["id"], task["approvals"][0]["id"])
    assert approved["state"] == "queued"
    (root / "a.txt").write_text("değişti", encoding="utf-8")
    failed = engine.run(task["id"])
    assert failed["state"] == "failed"
    assert "değişmiş" in (failed["last_error"] or "")
    db.close()


def test_approved_write_and_clock(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    engine = TaskEngine(db)
    root = tmp_path / "out"
    root.mkdir()
    task = engine.create(
        {
            "kind": "files.write",
            "title": "yaz",
            "params": {"relative": "a.txt", "content": "tamam"},
            "grant": {"roots": [str(root)]},
        }
    )
    engine.approve(task["id"], task["approvals"][0]["id"])
    done = engine.run(task["id"])
    assert done["state"] == "succeeded"
    assert (root / "a.txt").read_text(encoding="utf-8") == "tamam"
    clock = engine.create({"kind": "clock.now", "title": "saat"})
    ran = engine.run(clock["id"])
    assert ran["state"] == "succeeded"
    assert ran["steps"][0]["result"]["utc"]
    db.close()


def test_running_task_becomes_reconciliation(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    engine = TaskEngine(db)
    task = engine.create({"kind": "clock.now"})
    with db.transaction() as c:
        c.execute("UPDATE tasks SET state = 'running' WHERE id = ?", (task["id"],))
        c.execute(
            """INSERT INTO task_steps (id, task_id, ordinal, tool, intent_json, idempotency_key, state, created_at, updated_at)
               VALUES ('s1', ?, 0, 'clock.now', '{}', 'k', 'intended', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')""",
            (task["id"],),
        )
    assert engine.recover_interrupted() == 1
    got = engine.get(task["id"])
    assert got["state"] == "needs_reconciliation"
    assert got["steps"][0]["state"] == "uncertain"
    cancelled = engine.reconcile(task["id"], "cancel")
    assert cancelled["state"] == "cancelled"
    db.close()


def test_missed_one_shot_is_skipped(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    engine = TaskEngine(db)
    task = engine.create({"kind": "clock.now", "schedule_at": "2020-01-01T00:00:00+00:00", "missed_policy": "skip"})
    engine.recover_interrupted()
    assert engine.get(task["id"])["state"] == "cancelled"
    db.close()


def test_http_clock_and_blocked_fetch(live):
    with live.client() as c:
        created = c.post("/api/tasks", json={"kind": "clock.now", "title": "saat"})
        assert created.status_code == 200
        ran = c.post(f"/api/tasks/{created.json()['id']}/run")
        assert ran.status_code == 200
        assert ran.json()["state"] == "succeeded"
        blocked = c.post(
            "/api/tasks",
            json={"kind": "web.fetch", "params": {"url": "http://127.0.0.1/"}, "grant": {"hosts": ["127.0.0.1"]}},
        )
        assert blocked.status_code == 200
        out = c.post(f"/api/tasks/{blocked.json()['id']}/run")
        assert out.json()["state"] == "failed"
        assert "Özel" in (out.json()["last_error"] or "")
        net = c.get("/api/network").json()
        assert net["os_autostart"] is False
        assert net["worker"] == "cekirdek_acikken"
        assert net["browser_sessions"] == "kapalı"
        health = c.get("/api/health").json()
        assert health["tasks"]["worker"] == "cekirdek_acikken"
        assert "queued" in health["tasks"]
        assert "attention" in health["tasks"]
        probe = c.post("/api/network/tor-probe")
        assert probe.status_code == 200
        assert probe.json()["external_fetch"] is False
        assert probe.json()["direct_fallback"] is False

        saved = c.put("/api/network", json={"offline": True, "tor_socks": "127.0.0.1:9050"})
        assert saved.status_code == 200
        assert saved.json()["offline"] is True
        offline_task = c.post(
            "/api/tasks",
            json={"kind": "web.fetch", "params": {"url": "http://example.com/"}, "grant": {"hosts": ["example.com"]}},
        ).json()
        failed = c.post(f"/api/tasks/{offline_task['id']}/run").json()
        assert failed["state"] == "failed"
        assert "kapalı" in (failed["last_error"] or "").lower()
        c.put("/api/network", json={"offline": False, "tor_socks": "127.0.0.1:9050"})
        assert c.get("/api/tasks", params={"state": "succeeded"}).json()
        active = c.post("/api/tasks", json={"kind": "clock.now", "title": "aktif"}).json()
        assert c.delete(f"/api/tasks/{active['id']}").status_code == 400
        assert c.delete(f"/api/tasks/{created.json()['id']}").json()["removed"] == created.json()["id"]
        purged = c.post("/api/tasks/purge-terminal")
        assert purged.status_code == 200
        assert purged.json()["count"] >= 1
        assert all(t["state"] not in ("succeeded", "failed", "cancelled") for t in c.get("/api/tasks").json())
