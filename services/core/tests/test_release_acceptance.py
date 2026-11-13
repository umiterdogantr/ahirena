"""Yayın/kabul kapanışı: KAB 01–28 kapsamı."""


def test_release_matrix_covers_all_kabs(live):
    with live.client() as c:
        created = c.post(
            "/api/evaluation/sets",
            json={
                "name": "Release holdout",
                "data_version": "r1",
                "items": [{"prompt": "Merhaba de", "expect_contains": "Mer"}],
            },
        )
        assert created.status_code == 200, created.text
        set_id = created.json()["id"]
        run = c.post(
            "/api/evaluation/runs",
            json={"set_id": set_id, "model_id": "fake-model", "provider_id": "fake"},
        )
        assert run.status_code == 200, run.text

        acc = c.post("/api/acceptance/run")
        assert acc.status_code == 200, acc.text
        body = acc.json()
        summary = body["summary"]
        assert summary["failed"] == 0
        assert summary["phase6_closed"] is True
        assert summary["release_closed"] is True

        ids = {item["id"] for item in body["results"]}
        for i in range(1, 29):
            assert f"KAB {i:02d}" in ids, f"eksik KAB {i:02d}"
        assert "MATRIX" in ids

        skips = [x for x in body["results"] if x["status"] == "skip"]
        assert all(x["status"] != "fail" for x in skips)

        info = c.get("/api/training").json()
        assert info["phase6"]["product_closed"] is True
        assert info["phase6"]["release_closed"] is True
