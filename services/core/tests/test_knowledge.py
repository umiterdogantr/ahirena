"""Hafıza ve belge: kaynak, çalışma alanı ayrımı, indeks tutarlılığı."""

from pathlib import Path

from ahirena_core.db import Database
from ahirena_core.knowledge import (
    add_memory,
    create_workspace,
    delete_document,
    delete_memory,
    find_similar_memory,
    import_document,
    search_documents,
    search_memory,
    supersede_memory,
    update_memory,
)


def test_memory_keeps_both_records_and_stays_in_workspace(tmp_path: Path):
    db = Database(tmp_path / "a.db")
    other = create_workspace(db, "İkinci")
    first = add_memory(db, "genel", "Toplantı salı günü.", "kullanıcı 5 Kasım")
    second = add_memory(db, "genel", "Toplantı çarşamba günü.", "kullanıcı düzeltmesi")
    assert second["similar"]
    assert any(s["id"] == first["id"] for s in second["similar"])
    assert second["note"]
    listed = db.query("SELECT body FROM memory_items WHERE workspace_id = 'genel' AND status = 'active'")
    assert len(listed) == 2
    similar = find_similar_memory(db, "genel", "Toplantı salı")
    assert any(s["id"] == first["id"] for s in similar)
    add_memory(db, other["id"], "Toplantı salı günü.", "başka alan")
    genel = search_memory(db, "genel", "toplantı")
    assert len(genel["hits"]) == 2
    assert all(h["source_ref"] != "başka alan" for h in genel["hits"])
    assert genel["vector"] == "yok"
    assert search_memory(db, other["id"], "toplantı")["hits"][0]["source_ref"] == "başka alan"
    db.close()


def test_memory_edit_supersede_and_delete_leave_the_index(tmp_path: Path):
    db = Database(tmp_path / "a.db")
    item = add_memory(db, "genel", "Eski adres Kadıköy.", "kartvizit")
    update_memory(db, item["id"], "Yeni adres Beşiktaş.", "kullanıcı")
    found = search_memory(db, "genel", "besiktas")
    assert found["hits"][0]["body"].startswith("Yeni")
    assert search_memory(db, "genel", "kadikoy")["hits"] == []
    supersede_memory(db, item["id"])
    assert search_memory(db, "genel", "besiktas")["hits"] == []
    assert db.query_one("SELECT status FROM memory_items WHERE id = ?", (item["id"],))["status"] == "superseded"
    delete_memory(db, item["id"])
    assert db.query_one("SELECT COUNT(*) AS n FROM memory_fts")["n"] == 0
    db.close()


def test_turkish_document_search_workspace_and_delete(tmp_path: Path):
    db = Database(tmp_path / "a.db")
    other = create_workspace(db, "Diğer")
    src = tmp_path / "not.txt"
    src.write_text("İstanbul'da yağmur var.\nISPARTA soğuktur.\nKırık kalem masada.\n", encoding="utf-8")
    doc = import_document(db, "genel", str(src))
    same = import_document(db, other["id"], str(src))
    hit = search_documents(db, "genel", "istanbul")
    assert hit["index"] == "fts-1"
    assert hit["vector"] == "yok"
    assert hit["hits"][0]["document_id"] == doc["id"]
    assert hit["hits"][0]["path"] == str(src.resolve())
    assert "İstanbul" in hit["hits"][0]["text"]
    assert search_documents(db, "genel", "ısparta")["hits"][0]["document_id"] == doc["id"]
    assert search_documents(db, "genel", "kirik")["hits"][0]["text"].startswith("Kırık") or "Kırık" in search_documents(db, "genel", "kirik")["hits"][0]["text"]
    assert search_documents(db, other["id"], "istanbul")["hits"][0]["document_id"] == same["id"]
    assert all(h["document_id"] != same["id"] for h in search_documents(db, "genel", "istanbul")["hits"])

    src.write_text("Yalnızca Ankara kaldı.\n", encoding="utf-8")
    import_document(db, "genel", str(src))
    assert search_documents(db, "genel", "istanbul")["hits"] == []
    assert search_documents(db, "genel", "ankara")["hits"][0]["version"] == 2

    delete_document(db, doc["id"])
    assert search_documents(db, "genel", "ankara")["hits"] == []
    assert db.query_one("SELECT COUNT(*) AS n FROM chunks WHERE document_id = ?", (doc["id"],))["n"] == 0
    assert db.query_one("SELECT COUNT(*) AS n FROM chunk_fts WHERE document_id = ?", (doc["id"],))["n"] == 0
    assert search_documents(db, other["id"], "istanbul")["hits"]
    db.close()


def test_pending_index_is_resumed_and_binary_files_are_refused(tmp_path: Path):
    db = Database(tmp_path / "a.db")
    src = tmp_path / "not.md"
    src.write_text("Yarım indeks satırı burada.\n", encoding="utf-8")
    doc = import_document(db, "genel", str(src), process=False)
    assert search_documents(db, "genel", "yarim")["hits"] == []
    from ahirena_core.knowledge import list_documents, list_index_jobs, resume_jobs, retry_failed_jobs

    pending = list_documents(db, "genel")
    assert pending[0]["index_state"] == "pending"
    assert list_index_jobs(db, "genel")
    assert resume_jobs(db) == 1
    assert search_documents(db, "genel", "yarim")["hits"][0]["document_id"] == doc["id"]
    assert list_documents(db, "genel")[0]["index_state"] == "done"
    with db.transaction() as c:
        c.execute(
            "UPDATE index_jobs SET state = 'failed', error = 'test' WHERE document_id = ?",
            (doc["id"],),
        )
    out = retry_failed_jobs(db, "genel")
    assert out["resumed"] >= 1
    assert list_documents(db, "genel")[0]["index_state"] == "done"
    pdf = tmp_path / "rapor.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    try:
        import_document(db, "genel", str(pdf))
        raise AssertionError("pdf kabul edildi")
    except Exception as e:
        assert "PDF" in str(e)
    assert db.query_one("SELECT COUNT(*) AS n FROM documents WHERE path LIKE '%.pdf'")["n"] == 0
    db.close()


def test_chat_uses_only_workspace_sources(live, tmp_path: Path):
    from conftest import parse_sse

    src = tmp_path / "not.txt"
    src.write_text("İstanbul deposu açıktır.\n", encoding="utf-8")
    secret = tmp_path / "gizli.txt"
    secret.write_text("Gizli depo kilitlidir.\n", encoding="utf-8")
    with live.client() as c:
        other = c.post("/api/workspaces", json={"name": "Gizli"}).json()
        assert c.post("/api/memory", json={"workspace_id": "genel", "body": "Açık toplantı salı.", "source_ref": "genel not"}).status_code == 200
        assert c.post("/api/memory", json={"workspace_id": other["id"], "body": "Gizli toplantı cuma.", "source_ref": "gizli not"}).status_code == 200
        doc = c.post("/api/documents/import", json={"workspace_id": "genel", "path": str(src)}).json()
        assert c.post("/api/documents/import", json={"workspace_id": other["id"], "path": str(secret)}).status_code == 200
        cid = c.post("/api/conversations", json={"workspace_id": "genel"}).json()["id"]
        with c.stream(
            "POST",
            f"/api/conversations/{cid}/chat",
            json={"content": "toplantı istanbul", "model_id": "fake-model", "provider_id": "fake"},
        ) as r:
            assert r.status_code == 200
            events = parse_sse(list(r.iter_lines()))
        system = next(m.content for m in live.provider.last_messages if m.role == "system")
        assert "Açık toplantı salı" in system
        assert "İstanbul deposu" in system
        assert "Gizli toplantı" not in system
        assert "Gizli depo" not in system
        run = next(d for e, d in events if e == "run")
        kinds = {s["kind"] for s in run["sources"]}
        assert "memory" in kinds and "document" in kinds
        assert c.get(f"/api/conversations/{cid}/messages").json()[1]["sources"]
        assert c.delete(f"/api/documents/{doc['id']}").status_code == 200
        cid2 = c.post("/api/conversations", json={"workspace_id": "genel"}).json()["id"]
        with c.stream(
            "POST",
            f"/api/conversations/{cid2}/chat",
            json={"content": "istanbul", "model_id": "fake-model", "provider_id": "fake"},
        ) as r:
            assert r.status_code == 200
            r.read()
        system2 = next(m.content for m in live.provider.last_messages if m.role == "system")
        assert "İstanbul deposu" not in system2


def test_chat_does_not_become_memory(live):
    with live.client() as c:
        cid = c.post("/api/conversations", json={}).json()["id"]
        with c.stream(
            "POST",
            f"/api/conversations/{cid}/chat",
            json={"content": "Beni hatırla: adım Ümit", "model_id": "fake-model", "provider_id": "fake"},
        ) as r:
            assert r.status_code == 200
            r.read()
        listed = c.get("/api/memory", params={"workspace_id": "genel"})
        assert listed.status_code == 200
        assert listed.json() == []
        a = c.post("/api/memory", json={"workspace_id": "genel", "body": "Ofis adresi Kadıköy.", "source_ref": "kart"})
        assert a.status_code == 200
        sim = c.get("/api/memory/similar", params={"workspace_id": "genel", "q": "Ofis adresi Beşiktaş"})
        assert sim.status_code == 200
        assert any(s["id"] == a.json()["id"] for s in sim.json()["similar"])
        ws = c.post("/api/workspaces", json={"name": "Proje"})
        assert ws.status_code == 200
        missing = c.get("/api/memory", params={"workspace_id": "yok"})
        assert missing.status_code == 400
