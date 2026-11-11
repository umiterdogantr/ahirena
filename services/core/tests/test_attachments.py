import uuid
from pathlib import Path

from ahirena_core.db import Database, utcnow
from ahirena_core.store import Store


def test_list_messages_includes_attachments(tmp_path: Path):
    db = Database(tmp_path / "a.db")
    store = Store(db)
    conv = store.create_conversation("ek", "fake-model", "genel")
    msg = store.add_message(conv.id, "user", "görüntüye bak", "complete")
    img = tmp_path / "shot.png"
    img.write_bytes(b"png-bytes")
    aid = uuid.uuid4().hex
    with db.transaction() as c:
        c.execute(
            """INSERT INTO attachments
               (id, conversation_id, message_id, path, media_type, byte_size, content_hash, untrusted, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (aid, conv.id, msg.id, str(img), "image/png", img.stat().st_size, "abc", utcnow()),
        )
    listed = store.list_messages(conv.id)
    assert len(listed) == 1
    assert len(listed[0].attachments) == 1
    att = listed[0].attachments[0]
    assert att.id == aid
    assert att.path == str(img)
    assert att.exists is True
    assert att.untrusted is True
    one = store.get_message(msg.id)
    assert one is not None
    assert one.attachments[0].media_type == "image/png"
    db.close()
