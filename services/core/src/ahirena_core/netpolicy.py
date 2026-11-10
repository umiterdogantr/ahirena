"""Ağ hedefi denetimi: özel adres, yönlendirme ve Tor rotası.

Uygulama bayrağı işletim sistemi duvarı değildir. Tor yoksa doğrudan çıkılmaz.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

BLOCKED_HOSTS = {"metadata.google.internal", "metadata.google.internal."}


class NetRejected(ValueError):
    pass


def _host_of(url: str) -> tuple[str, str, str]:
    raw = (url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise NetRejected("Yalnızca http ve https.")
    host = (parsed.hostname or "").strip(".").lower()
    if not host:
        raise NetRejected("Hedef ana bilgisayar yok.")
    return raw, parsed.scheme, host


def is_blocked_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
        or addr in (ipaddress.ip_address("169.254.169.254"), ipaddress.ip_address("::1"))
    )


def resolve_host(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise NetRejected(f"DNS çözülemedi: {host}") from e
    ips = sorted({item[4][0] for item in infos})
    if not ips:
        raise NetRejected(f"DNS sonucu boş: {host}")
    return ips


def assert_host_allowed(host: str, allowed: list[str], *, resolver=resolve_host) -> list[str]:
    host = host.strip(".").lower()
    if host in BLOCKED_HOSTS:
        raise NetRejected("Bulut meta veri adresi kapalı.")
    try:
        ipaddress.ip_address(host)
        ips = [host]
    except ValueError:
        ips = resolver(host)
    for ip in ips:
        if is_blocked_ip(ip):
            raise NetRejected(f"Özel veya yerel adres kapalı: {host} ({ip})")
    names = {h.strip(".").lower() for h in allowed if h}
    if host not in names:
        raise NetRejected(f"Bu alan adı için ağ izni yok: {host}")
    return ips


def assert_url_allowed(url: str, allowed: list[str], *, resolver=resolve_host) -> str:
    _, _, host = _host_of(url)
    assert_host_allowed(host, allowed, resolver=resolver)
    return host


def tor_listening(socks: str, *, timeout: float = 0.4) -> bool:
    raw = (socks or "127.0.0.1:9050").strip()
    if ":" not in raw:
        return False
    host, _, port_s = raw.rpartition(":")
    try:
        port = int(port_s)
    except ValueError:
        return False
    try:
        with socket.create_connection((host or "127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False
