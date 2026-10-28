"""IPv4 addresses this machine already owns.

/mcp keeps the loopback list. At startup the server also accepts the IPv4
addresses configured on local interfaces, including a Tailscale address.
Nothing is typed by the operator. A name that is not one of those addresses,
including an attacker hostname, stays rejected. The check that rejects a
loopback Host from a non-loopback peer is unchanged.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path

from mcp.server.transport_security import TransportSecuritySettings

_TRIE = Path("/proc/net/fib_trie")
_LINK_LOCAL = ipaddress.ip_network("169.254.0.0/16")


def machine_host_names(*, trie: str | None = None) -> list[str]:
    """``/32 host LOCAL`` IPv4 addresses, without loopback or link-local."""
    text = trie if trie is not None else _read_trie()
    names: list[str] = []
    seen: set[str] = set()
    previous = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|--") or stripped.startswith("+--"):
            parts = stripped.split()
            previous = parts[1] if len(parts) > 1 else ""
            continue
        if "/32 host LOCAL" not in stripped or not previous:
            continue
        candidate = previous
        previous = ""
        if candidate in seen or not _usable_ipv4(candidate):
            continue
        seen.add(candidate)
        names.append(candidate)
    return names


def build_transport_security(names: list[str]) -> TransportSecuritySettings:
    """Loopback, plus each address on any port. Extra addresses allow http and https."""
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    origins = [
        "http://127.0.0.1:*",
        "http://localhost:*",
        "http://[::1]:*",
    ]
    for name in names:
        hosts.append(name)
        hosts.append(f"{name}:*")
        for scheme in ("http", "https"):
            origins.append(f"{scheme}://{name}")
            origins.append(f"{scheme}://{name}:*")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


def _read_trie() -> str:
    try:
        return _TRIE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _usable_ipv4(value: str) -> bool:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return False
    if (
        addr.version != 4
        or addr.is_loopback
        or addr.is_unspecified
        or addr.is_multicast
    ):
        return False
    return addr not in _LINK_LOCAL
