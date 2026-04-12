from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


class SSRFError(Exception):
    pass


_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("fd00::/8"),
]


def _is_private_ip(host: str) -> bool:
    host = host.strip("[]")
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in _PRIVATE_NETWORKS)


def validate_url(
    url: str,
    *,
    allow_http: bool = False,
    allowed_hosts: list[str] | None = None,
) -> None:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()

    if scheme not in ("http", "https"):
        raise SSRFError(f"Unsupported scheme: {scheme}")

    hostname = parsed.hostname or ""
    if not hostname:
        raise SSRFError("No hostname in URL")

    if _is_private_ip(hostname):
        raise SSRFError(f"Host {hostname} resolves to private/reserved IP")

    if not allow_http and scheme == "http":
        raise SSRFError("HTTPS required (set allow_http=True to override)")

    if allowed_hosts is not None and hostname not in allowed_hosts:
        raise SSRFError(f"Host {hostname} not in allowed hosts list")
