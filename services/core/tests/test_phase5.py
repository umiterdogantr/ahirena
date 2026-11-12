"""Görev dalı, çevrimdışı oynatma, yetenek taslağı, medya dürüstlüğü."""

from pathlib import Path

from ahirena_core.db import Database
from ahirena_core.media import media_status
from ahirena_core.skilldraft import discard_candidate, draft_skill, list_candidates
from ahirena_core.tasks import TaskEngine


def test_media_status_is_honest_without_whisper():
    status = media_status(vision_models=[])
    assert status["vision"]["available"] is False
    assert status["ocr"]["status"] == "planlandı"
    assert status["speech_output"]["status"] == "planlandı"
    assert status["screen_watch"]["available"] is False


def test_task_branch_and_offline_replay(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    engine = TaskEngine(db)
    clock = engine.create({"kind": "clock.now", "title": "saat"})
    done = engine.run(clock["id"])
    assert done["state"] == "succeeded"
    replay = engine.replay(clock["id"])
    assert replay["mode"] == "offline_replay"
    assert replay["live_tools"] is False
    assert replay["steps"][0]["result"]["utc"]
    branch = engine.branch(clock["id"], {"title": "saat-dal"})
    assert branch["parent_id"] == clock["id"]
    assert branch["state"] == "queued"
    assert branch["steps"] == []
    root = tmp_path / "out"
    root.mkdir()
    write = engine.create(
        {"kind": "files.write", "params": {"relative": "a.txt", "content": "x"}, "grant": {"roots": [str(root)]}}
    )
    engine.approve(write["id"], write["approvals"][0]["id"])
    engine.run(write["id"])
    forked = engine.branch(write["id"])
    assert forked["state"] == "waiting_approval"
    assert forked["approvals"][0]["decision"] == "pending"
    db.close()


def test_skill_draft_stays_disabled(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    draft = draft_skill(db, tmp_path, "Saati söyleyen basit bir yetenek yaz.")
    assert draft["enabled"] is False
    assert draft["status"] == "candidate"
    assert "clock.now" in draft["tools"]
    assert (Path(draft["package_dir"]) / "SKILL.md").is_file()
    assert list_candidates(db)
    discard_candidate(db, draft["id"])
    assert list_candidates(db) == []
    db.close()


def test_http_branch_replay_draft_and_image_without_vision(live, tmp_path: Path):
    png = tmp_path / "x.png"
    png.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    with live.client() as c:
        media = c.get("/api/media").json()
        assert media["ocr"]["status"] == "planlandı"
        created = c.post("/api/tasks", json={"kind": "clock.now"}).json()
        c.post(f"/api/tasks/{created['id']}/run")
        branch = c.post(f"/api/tasks/{created['id']}/branch", json={"title": "dal"})
        assert branch.status_code == 200
        assert branch.json()["parent_id"] == created["id"]
        replay = c.post(f"/api/tasks/{created['id']}/replay")
        assert replay.status_code == 200
        assert replay.json()["live_tools"] is False
        draft = c.post("/api/skills/draft", json={"prompt": "Dosya okuyan bir yetenek tasarla"})
        assert draft.status_code == 200
        body = draft.json()
        assert body["enabled"] is False
        assert "files.read" in body["tools"]
        cid = c.post("/api/conversations", json={}).json()["id"]
        r = c.post(
            f"/api/conversations/{cid}/chat",
            json={"content": "bu ne", "model_id": "fake-model", "provider_id": "fake", "image_path": str(png)},
        )
        assert r.status_code == 400
        assert "vision" in r.json()["detail"].lower() or "Vision" in r.json()["detail"] or "vision" in r.text.lower()
        branched = c.post(f"/api/conversations/{cid}/branch", json={})
        assert branched.status_code == 200


def test_conversation_branch_model_and_checkpoint(live):
    with live.client() as c:
        cid = c.post("/api/conversations", json={"model_id": "fake-model"}).json()["id"]
        with c.stream(
            "POST",
            f"/api/conversations/{cid}/chat",
            json={"content": "bir", "model_id": "fake-model", "provider_id": "fake"},
        ) as r:
            assert r.status_code == 200
            r.read()
        with c.stream(
            "POST",
            f"/api/conversations/{cid}/chat",
            json={"content": "iki", "model_id": "fake-model", "provider_id": "fake"},
        ) as r:
            assert r.status_code == 200
            r.read()
        msgs = c.get(f"/api/conversations/{cid}/messages").json()
        assert len(msgs) >= 4
        checkpoint = msgs[1]["id"]
        branch = c.post(
            f"/api/conversations/{cid}/branch",
            json={"up_to_message_id": checkpoint, "model_id": "other-model"},
        )
        assert branch.status_code == 200, branch.text
        body = branch.json()
        assert body["parent_id"] == cid
        assert body["model_id"] == "other-model"
        assert "other-model" in body["title"]
        branched_msgs = c.get(f"/api/conversations/{body['id']}/messages").json()
        assert len(branched_msgs) == 2
        assert branched_msgs[-1]["id"] != checkpoint
        assert branched_msgs[-1]["content"] == msgs[1]["content"]
        bad = c.post(f"/api/conversations/{cid}/branch", json={"up_to_message_id": "yok"})
        assert bad.status_code == 400
