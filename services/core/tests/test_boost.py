from ahirena_core.boost import describe, resolve_context_length


def test_boost_widens_context_with_cap():
    off = resolve_context_length(8192, boost=False)
    assert off["boost"] is False
    assert off["context_length"] == 8192
    assert off["remote"] is False

    on = resolve_context_length(8192, boost=True)
    assert on["boost"] is True
    assert on["context_length"] == 16384
    assert on["remote"] is False
    assert on["profile"]["id"] == "wide_context"

    capped = resolve_context_length(8192, boost=True, model_context=4096)
    assert capped["context_length"] == 4096
    assert capped["capped_by_model"] is True

    already_high = resolve_context_length(20000, boost=True)
    assert already_high["context_length"] == 20000


def test_boost_describe_is_local_only():
    info = describe()
    assert info["remote"] is False
    assert info["larger_model"] is False


def test_http_boost_and_chat(live):
    with live.client() as c:
        prof = c.get("/api/boost")
        assert prof.status_code == 200
        assert prof.json()["remote"] is False
        assert prof.json()["example_effective_context"] >= prof.json()["base_context"]

        created = c.post("/api/conversations", json={"title": "boost", "model_id": "fake-model"})
        cid = created.json()["id"]
        with c.stream(
            "POST",
            f"/api/conversations/{cid}/chat",
            json={"content": "Merhaba", "model_id": "fake-model", "provider_id": "fake", "boost": True},
        ) as r:
            assert r.status_code == 200
            text = "".join(r.iter_text())
        assert "boost" in text
        assert '"boost": true' in text.replace(" ", "") or '"boost":true' in text.replace(" ", "")
        msgs = c.get(f"/api/conversations/{cid}/messages").json()
        assistant = next(m for m in msgs if m["role"] == "assistant")
        assert assistant["metrics"]["boost"] is True
        assert assistant["metrics"]["num_ctx"] >= 8192
