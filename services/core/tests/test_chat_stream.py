import threading
import time

from conftest import FakeProvider, LiveServer, parse_sse


def _chat(c, cid, content="Selam", **kw):
    body = {"content": content, "model_id": "fake-model", "provider_id": "fake", **kw}
    with c.stream("POST", f"/api/conversations/{cid}/chat", json=body) as r:
        assert r.status_code == 200
        return parse_sse(list(r.iter_lines()))


def test_stream_events_and_persistence(live):
    with live.client() as c:
        cid = c.post("/api/conversations", json={}).json()["id"]
        events = _chat(c, cid, "Merhaba de")
        kinds = [e for e, _ in events]
        assert kinds[0] == "run" and kinds[-1] == "done"
        assert "".join(d["delta"] for e, d in events if e == "token") == "Merhaba!"
        done = events[-1][1]
        assert done["status"] == "complete"
        assert done["metrics"]["ttft_ms"] >= 0
        assert done["metrics"]["gpu_percent"] == 75

        msgs = c.get(f"/api/conversations/{cid}/messages").json()
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert msgs[1]["content"] == "Merhaba!"
        assert msgs[1]["status"] == "complete"
        assert msgs[1]["model_digest"] == "sha256:fake"
        assert c.get(f"/api/conversations/{cid}").json()["title"] == "Merhaba de"


def test_history_is_sent_with_system_prompt(live):
    with live.client() as c:
        cid = c.post("/api/conversations", json={}).json()["id"]
        _chat(c, cid, "Birinci")
        _chat(c, cid, "İkinci")
        roles = [m.role for m in live.provider.last_messages]
        assert roles == ["system", "user", "assistant", "user"]
        assert live.provider.last_messages[-1].content == "İkinci"


def test_thinking_stream(live):
    with live.client() as c:
        cid = c.post("/api/conversations", json={}).json()["id"]
        events = _chat(c, cid, think=True)
        assert ("thinking", {"delta": "düşünüyorum"}) in events
        assert c.get(f"/api/conversations/{cid}/messages").json()[1]["thinking"] == "düşünüyorum"


def test_unknown_model_rejected(live):
    with live.client() as c:
        cid = c.post("/api/conversations", json={}).json()["id"]
        r = c.post(f"/api/conversations/{cid}/chat", json={"content": "x", "model_id": "yok", "provider_id": "fake"})
        assert r.status_code == 400


def _cancel_midstream(srv: LiveServer, wait_for_token: bool) -> tuple[list, float, dict]:
    with srv.client() as c:
        cid = c.post("/api/conversations", json={}).json()["id"]
        events: list = []
        run_id: dict = {}
        got_run = threading.Event()
        got_token = threading.Event()

        def consume():
            with srv.client(timeout=30) as c2:
                body = {"content": "uzun yaz", "model_id": "fake-model", "provider_id": "fake"}
                with c2.stream("POST", f"/api/conversations/{cid}/chat", json=body) as r:
                    buf = []
                    for line in r.iter_lines():
                        buf.append(line)
                        parsed = parse_sse(buf)
                        if parsed and parsed[-1][0] == "run" and not got_run.is_set():
                            run_id["id"] = parsed[-1][1]["run_id"]
                            got_run.set()
                        if parsed and parsed[-1][0] == "token":
                            got_token.set()
                    events.extend(parse_sse(buf))

        t = threading.Thread(target=consume)
        t.start()
        assert got_run.wait(5)
        if wait_for_token:
            assert got_token.wait(5)
        t0 = time.perf_counter()
        assert c.post(f"/api/runs/{run_id['id']}/cancel").json() == {"cancelled": True}
        t.join(10)
        elapsed = time.perf_counter() - t0
        msgs = c.get(f"/api/conversations/{cid}/messages").json()
        return events, elapsed, msgs[1]


def test_cancel_midstream_keeps_partial(tmp_path):
    srv = LiveServer(tmp_path, FakeProvider(tokens=["a"] * 500, delay=0.02))
    try:
        events, elapsed, assistant = _cancel_midstream(srv, wait_for_token=True)
    finally:
        srv.stop()
    assert events[-1][0] == "done" and events[-1][1]["status"] == "cancelled"
    assert elapsed < 1.0
    assert assistant["status"] == "cancelled"
    assert 0 < len(assistant["content"]) < 500
    assert srv.provider.cancelled.is_set()


def test_cancel_during_model_load(tmp_path):
    """Hiç parça gelmeden (model yüklenirken) iptal de hemen etkili olmalı."""
    srv = LiveServer(tmp_path, FakeProvider(load_delay=30))
    try:
        events, elapsed, assistant = _cancel_midstream(srv, wait_for_token=False)
    finally:
        srv.stop()
    assert events[-1][1]["status"] == "cancelled"
    assert elapsed < 1.0
    assert assistant["status"] == "cancelled"


def test_client_disconnect_cancels_generation(tmp_path):
    srv = LiveServer(tmp_path, FakeProvider(tokens=["a"] * 500, delay=0.02))
    try:
        with srv.client() as c:
            cid = c.post("/api/conversations", json={}).json()["id"]
            body = {"content": "uzun", "model_id": "fake-model", "provider_id": "fake"}
            with c.stream("POST", f"/api/conversations/{cid}/chat", json=body) as r:
                for line in r.iter_lines():
                    if line.startswith("event: token"):
                        break
            assert srv.provider.cancelled.wait(3)
            deadline = time.time() + 3
            while time.time() < deadline:
                status = c.get(f"/api/conversations/{cid}/messages").json()[1]["status"]
                if status != "streaming":
                    break
                time.sleep(0.05)
            assert status == "cancelled"
    finally:
        srv.stop()


def test_interrupted_reply_marked_on_restart(tmp_path):
    from ahirena_core.db import Database
    from ahirena_core.store import Store

    s = Store(Database(tmp_path / "data" / "ahirena.db"))
    conv = s.create_conversation(None, None)
    m = s.add_message(conv.id, "assistant", "yarım", "streaming")
    s.db.close()

    srv = LiveServer(tmp_path, FakeProvider())
    try:
        with srv.client() as c:
            msg = c.get(f"/api/conversations/{conv.id}/messages").json()[0]
    finally:
        srv.stop()
    assert msg["id"] == m.id and msg["status"] == "error" and msg["content"] == "yarım"


def test_compare_does_not_persist(live):
    with live.client() as c:
        with c.stream("POST", "/api/compare", json={"prompt": "x", "model_id": "fake-model", "provider_id": "fake"}) as r:
            events = parse_sse(list(r.iter_lines()))
        assert events[-1][1]["status"] == "complete"
        assert c.get("/api/conversations").json() == []
