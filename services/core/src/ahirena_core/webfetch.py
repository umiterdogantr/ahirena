"""Salt okunur HTTP get. Yönlendirmeden sonra hedef yeniden denetlenir."""

from __future__ import annotations

from urllib.parse import urljoin

import httpx

from .netpolicy import NetRejected, assert_url_allowed, tor_listening

MAX_BYTES = 200_000
MAX_REDIRECTS = 5


def fetch_url(
    url: str,
    *,
    allowed_hosts: list[str],
    route: str = "direct",
    tor_socks: str = "127.0.0.1:9050",
    offline: bool = False,
    client: httpx.Client | None = None,
    resolver=None,
) -> dict:
    if offline:
        raise NetRejected("Ağ politikası kapalı.")
    kwargs = {"resolver": resolver} if resolver else {}
    host = assert_url_allowed(url, allowed_hosts, **kwargs) if resolver else assert_url_allowed(url, allowed_hosts)
    proxies = None
    if route == "tor":
        if not tor_listening(tor_socks):
            raise NetRejected("Tor rotası istendi ama SOCKS dinlemiyor; doğrudan çıkılmadı.")
        proxies = f"socks5://{tor_socks}"
    elif route != "direct":
        raise NetRejected("Bilinmeyen rota.")

    own = client is None
    http = client or httpx.Client(timeout=10, follow_redirects=False, proxy=proxies, trust_env=False)
    current = url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            if resolver:
                assert_url_allowed(current, allowed_hosts, resolver=resolver)
            else:
                assert_url_allowed(current, allowed_hosts)
            r = http.get(current)
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                current = urljoin(current, r.headers["location"])
                continue
            data = r.content[: MAX_BYTES + 1]
            truncated = len(data) > MAX_BYTES
            text = data[:MAX_BYTES].decode("utf-8", "replace")
            return {
                "url": str(r.url),
                "requested": url,
                "status": r.status_code,
                "host": host,
                "route": route,
                "text": text,
                "truncated": truncated,
            }
        raise NetRejected("Çok fazla yönlendirme.")
    except httpx.RequestError as e:
        raise NetRejected(f"İstek başarısız: {e}") from e
    finally:
        if own:
            http.close()
