from ahirena_core.textnorm import search_key


def test_search_key_turkish():
    assert search_key("İSTANBUL") == search_key("istanbul")
    assert search_key("IŞIK") == "isik"
    assert search_key("Çağrı Öğün") == "cagri ogun"


def test_crud_and_persistence(live):
    with live.client() as c:
        r = c.post("/api/conversations", json={})
        assert r.status_code == 201
        conv = r.json()
        assert conv["title"] == "Yeni oturum"

        r = c.patch(f"/api/conversations/{conv['id']}", json={"title": "Bütçe planı"})
        assert r.json()["title"] == "Bütçe planı"

        r = c.patch(f"/api/conversations/{conv['id']}", json={"archived": True})
        assert r.json()["archived"] is True
        assert c.get("/api/conversations").json() == []
        assert len(c.get("/api/conversations", params={"archived": True}).json()) == 1

        assert c.delete(f"/api/conversations/{conv['id']}").status_code == 200
        assert c.get(f"/api/conversations/{conv['id']}").status_code == 404
        assert c.delete(f"/api/conversations/{conv['id']}").status_code == 404


def test_title_validation(live):
    with live.client() as c:
        conv = c.post("/api/conversations", json={}).json()
        assert c.patch(f"/api/conversations/{conv['id']}", json={"title": ""}).status_code == 422


def test_turkish_search_in_titles_and_messages(live):
    with live.client() as c:
        a = c.post("/api/conversations", json={"title": "İstanbul gezisi"}).json()
        b = c.post("/api/conversations", json={"title": "Diğer"}).json()
        with c.stream("POST", f"/api/conversations/{b['id']}/chat", json={"content": "Işık faturası ne kadar?", "model_id": "fake-model", "provider_id": "fake"}) as r:
            list(r.iter_lines())

        ids = lambda q: {x["id"] for x in c.get("/api/conversations", params={"q": q}).json()}
        assert ids("istanbul") == {a["id"]}
        assert ids("ISTANBUL") == {a["id"]}
        assert ids("ışık") == {b["id"]}
        assert ids("isik") == {b["id"]}
        assert ids("yok-boyle-bir-sey") == set()
        hit = [x for x in c.get("/api/conversations", params={"q": "fatura"}).json() if x["id"] == b["id"]][0]
        assert "faturası" in hit["match_snippet"]


def test_settings_roundtrip(live):
    with live.client() as c:
        s = c.get("/api/settings").json()
        assert s["theme"] == "system"
        s = c.patch("/api/settings", json={"theme": "dark", "default_model": "fake-model"}).json()
        assert s["theme"] == "dark" and s["default_model"] == "fake-model"
        assert c.patch("/api/settings", json={"theme": "mor"}).status_code == 422
