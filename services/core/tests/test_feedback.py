from pathlib import Path

from ahirena_core.db import Database
from ahirena_core.feedback import FeedbackError, create_feedback, export_feedback, list_feedback, set_feedback_status
from ahirena_core.store import Store


def test_feedback_requires_note_and_valid_type(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    try:
        create_feedback(db, {"issue_type": "other", "note": ""})
        assert False, "boş not kabul edilmemeli"
    except FeedbackError:
        pass
    try:
        create_feedback(db, {"issue_type": "uydurma", "note": "x"})
        assert False, "geçersiz tür kabul edilmemeli"
    except FeedbackError:
        pass
    item = create_feedback(db, {"issue_type": "missing_source", "note": "Kaynak yoktu"})
    assert item["trains_model"] is False
    assert item["status"] == "open"
    assert list_feedback(db)[0]["id"] == item["id"]


def test_feedback_ties_to_assistant_message(tmp_path: Path):
    store = Store(Database(tmp_path / "t.db"))
    conv = store.create_conversation("t", "gemma4:e2b-it-qat", "genel")
    user = store.add_message(conv.id, "user", "soru", "complete")
    asst = store.add_message(conv.id, "assistant", "yanlış cevap", "complete")
    bad = create_feedback(
        store.db,
        {
            "issue_type": "wrong_model",
            "note": "Başka model dene",
            "suggested_fix": "Daha küçük model kullan",
            "message_id": asst.id,
        },
    )
    assert bad["conversation_id"] == conv.id
    assert bad["message_id"] == asst.id
    assert bad["suggested_fix"] == "Daha küçük model kullan"
    try:
        create_feedback(store.db, {"issue_type": "other", "note": "x", "message_id": user.id})
        assert False
    except FeedbackError as e:
        assert "asistan" in str(e).lower()


def test_export_feedback(tmp_path: Path):
    data = tmp_path
    (data / "data").mkdir()
    db = Database(data / "data" / "ahirena.db")
    create_feedback(db, {"issue_type": "other", "note": "bir"})
    reviewed = create_feedback(db, {"issue_type": "other", "note": "iki"})
    set_feedback_status(db, reviewed["id"], "reviewed")
    out = export_feedback(db, data, status="open")
    text = Path(out["path"]).read_text(encoding="utf-8")
    assert out["count"] == 1
    assert "bir" in text
    assert "iki" not in text
    db.close()


def test_http_feedback_export(live):
    with live.client() as c:
        created = c.post("/api/feedback", json={"issue_type": "other", "note": "HTTP düzeltme", "suggested_fix": "şöyle olsun"})
        assert created.status_code == 200
        assert created.json()["suggested_fix"] == "şöyle olsun"
        filt = c.get("/api/feedback", params={"status": "open"})
        assert filt.status_code == 200
        assert any(i["note"] == "HTTP düzeltme" for i in filt.json()["items"])
        exp = c.post("/api/feedback/export", params={"status": "open"})
        assert exp.status_code == 200
        assert Path(exp.json()["path"]).is_file()


def test_feedback_to_skill_draft(tmp_path: Path):
    from ahirena_core.feedback import feedback_to_skill_draft

    data = tmp_path
    (data / "data").mkdir()
    db = Database(data / "data" / "ahirena.db")
    item = create_feedback(
        db,
        {
            "issue_type": "bad_instruction",
            "note": "Saat sorusunda yanlış araç",
            "suggested_fix": "Kullanıcı saat sorunca clock.now kullan.",
        },
    )
    out = feedback_to_skill_draft(db, data, item["id"])
    assert out["candidate"]["status"] == "candidate"
    assert out["candidate"]["enabled"] is False
    assert out["feedback"]["status"] == "reviewed"
    assert "clock.now" in out["candidate"]["tools"]
    wrong = create_feedback(db, {"issue_type": "wrong_model", "note": "Başka model dene lütfen"})
    try:
        feedback_to_skill_draft(db, data, wrong["id"])
        assert False, "yanlış model türü taslağa gitmemeli"
    except FeedbackError:
        pass
    db.close()


def test_http_feedback_skill_draft(live):
    with live.client() as c:
        created = c.post(
            "/api/feedback",
            json={
                "issue_type": "tool_failure",
                "note": "Dosya okuma çalışmadı",
                "suggested_fix": "Belge klasöründen dosya oku.",
            },
        )
        assert created.status_code == 200
        fid = created.json()["id"]
        draft = c.post(f"/api/feedback/{fid}/skill-draft")
        assert draft.status_code == 200
        body = draft.json()
        assert body["candidate"]["enabled"] is False
        assert body["feedback"]["status"] == "reviewed"
        again = c.post(f"/api/feedback/{fid}/skill-draft")
        assert again.status_code == 400
