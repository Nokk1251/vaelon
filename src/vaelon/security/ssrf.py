"""SSRF guard: refuse private/loopback/link-local/metadata targets."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

BLOCKED_HOSTS = {"metadata.google.internal", "169.254.169.254", "100.100.100.200"}


def _bad(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        a = a.ipv4_mapped
    if isinstance(a, ipaddress.IPv6Address) and a in ipaddress.ip_network("64:ff9b::/96"):  # NAT64 wraps IPv4
        a = ipaddress.IPv4Address(int(a) & 0xFFFFFFFF)
    return (not a.is_global or a.is_private or a.is_loopback or a.is_link_local or a.is_multicast or a.is_reserved
            or a.is_unspecified or a in ipaddress.ip_network("100.64.0.0/10"))


def check_url(url: str) -> None:
    """Raises ValueError if the URL is not a safe public http(s) target."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("only public http(s) URLs are allowed")
    if u.hostname.lower() in BLOCKED_HOSTS:
        raise ValueError("blocked host")
    try:
        infos = socket.getaddrinfo(u.hostname, None)
    except socket.gaierror as e:
        raise ValueError(f"cannot resolve host: {e}")
    for info in infos:
        if _bad(info[4][0]):
            raise ValueError("URL resolves to a private/internal address (SSRF blocked)")
