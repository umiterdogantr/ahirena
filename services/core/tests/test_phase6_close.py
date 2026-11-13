from pathlib import Path


def test_phase6_holdout_acceptance_and_adapter(live, tmp_path: Path):
    with live.client() as c:
        created = c.post(
            "/api/evaluation/sets",
            json={
                "name": "Holdout örnek",
                "data_version": "t1",
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
        summary = run.json()["summary"]
        assert summary["checked"] == 1
        assert summary["passed"] == 1

        acc = c.post("/api/acceptance/run")
        assert acc.status_code == 200, acc.text
        assert acc.json()["summary"]["failed"] == 0
        assert acc.json()["summary"]["phase6_closed"] is True

        pack = tmp_path / "adapters" / "demo"
        pack.mkdir(parents=True)
        (pack / "adapter_config.json").write_text('{"note":"aday"}', encoding="utf-8")
        reg = c.post(
            "/api/training/adapters",
            json={"path": str(pack), "base_model": "fake-model"},
        )
        assert reg.status_code == 200, reg.text
        aid = reg.json()["id"]
        act = c.post(f"/api/training/adapters/{aid}/activate")
        assert act.status_code == 200, act.text
        assert act.json()["status"] == "active"
        assert act.json()["loaded_in_runtime"] is False
        rb = c.post(f"/api/training/adapters/{aid}/rollback")
        assert rb.status_code == 200
        assert rb.json()["status"] == "rolled_back"

        info = c.get("/api/training").json()
        assert info["phase6"]["product_closed"] is True
        assert info["capability"]["status"] == "planlandı"
