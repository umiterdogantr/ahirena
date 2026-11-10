from pathlib import Path

from ahirena_core.db import Database
from ahirena_core.feedback import FeedbackError, create_feedback, list_feedback
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
        {"issue_type": "wrong_model", "note": "Başka model dene", "message_id": asst.id},
    )
    assert bad["conversation_id"] == conv.id
    assert bad["message_id"] == asst.id
    try:
        create_feedback(store.db, {"issue_type": "other", "note": "x", "message_id": user.id})
        assert False
    except FeedbackError as e:
        assert "asistan" in str(e).lower()
