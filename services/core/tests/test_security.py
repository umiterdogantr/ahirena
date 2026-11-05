import httpx


def test_requires_token(live):
    with live.client(token=None) as c:
        assert c.get("/api/health").status_code == 401
    with live.client(token="yanlis" * 10) as c:
        assert c.get("/api/health").status_code == 401
    with live.client() as c:
        assert c.get("/api/health").status_code == 200


def test_rejects_foreign_host(live):
    with live.client() as c:
        r = c.get("/api/health", headers={"Host": "evil.example:80"})
        assert r.status_code == 403
        r = c.get("/api/health", headers={"Host": f"localhost:{live.port}"})
        assert r.status_code == 403


def test_rejects_browser_origin(live):
    with live.client() as c:
        r = c.get("/api/health", headers={"Origin": "http://evil.example"})
        assert r.status_code == 403


def test_rejects_large_body(live):
    with live.client() as c:
        r = c.post("/api/conversations", content=b"{" + b" " * 1_100_000 + b"}", headers={"Content-Type": "application/json"})
        assert r.status_code == 413

        def chunks():
            for _ in range(20):
                yield b" " * 100_000

        r = c.post("/api/conversations", content=chunks(), headers={"Content-Type": "application/json"})
        assert r.status_code == 413


def test_binds_only_loopback(live):
    import socket

    lan_ips = {i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)} - {"127.0.0.1"}
    for ip in lan_ips:
        try:
            httpx.get(f"http://{ip}:{live.port}/api/health", timeout=1, trust_env=False)
        except httpx.HTTPError:
            continue
        raise AssertionError(f"Çekirdek {ip} adresinden erişilebilir durumda")


def test_no_openapi_docs(live):
    with live.client() as c:
        assert c.get("/docs").status_code == 404
        assert c.get("/openapi.json").status_code == 404
