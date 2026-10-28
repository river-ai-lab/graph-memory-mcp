"""This machine's own addresses are accepted. Other Host values stay rejected."""

from __future__ import annotations

import asyncio

from mcp.server.transport_security import TransportSecurityMiddleware

from graph_memory_mcp.graph_memory.host_allowlist import (
    build_transport_security,
    machine_host_names,
)

_TRIE = """
        |-- 100.76.183.54
           /32 host LOCAL
              |-- 127.0.0.1
                 /32 host LOCAL
        |-- 169.254.1.1
           /32 host LOCAL
        |-- 172.17.0.1
           /32 host LOCAL
        |-- 192.168.68.112
           /32 host LOCAL
"""


def test_trie_keeps_this_machines_ipv4_and_drops_loopback():
    assert machine_host_names(trie=_TRIE) == [
        "100.76.183.54",
        "172.17.0.1",
        "192.168.68.112",
    ]


def test_own_names_pass_and_an_attacker_host_does_not():
    settings = build_transport_security(["100.76.183.54", "192.168.68.112"])
    mw = TransportSecurityMiddleware(settings)
    assert mw._validate_host("127.0.0.1:8000")
    assert mw._validate_host("100.76.183.54:8000")
    assert mw._validate_origin("https://100.76.183.54")
    assert mw._validate_origin("http://127.0.0.1:8000")
    assert not mw._validate_host("evil.example:8000")
    assert not mw._validate_origin("https://evil.example")
    assert not mw._validate_origin("https://127.0.0.1")


def test_app_accepts_an_own_address_and_still_rejects_spoof(memory_backend):
    import httpx

    from graph_memory_mcp.server import GraphMemoryMCP

    own = next(iter(machine_host_names()))
    cfg = memory_backend.config.model_copy(
        update={"owner_scope": "client", "allow_insecure_client": False}
    )
    server = GraphMemoryMCP(cfg)
    app = server.get_mcp_app()

    async def status(peer: str, base: str) -> int:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=(peer, 50123)),
            base_url=base,
        ) as client:
            response = await client.post("/mcp", json={})
            return response.status_code

    async def statuses():
        async with server.mcp.session_manager.run():
            spoof = await status("192.168.68.20", "http://127.0.0.1:8000")
            evil = await status("127.0.0.1", "http://evil.example:8000")
            local = await status("127.0.0.1", "http://127.0.0.1:8000")
            mesh = await status("127.0.0.1", f"http://{own}:8000")
        return spoof, evil, local, mesh

    spoof, evil, local, mesh = asyncio.run(statuses())
    assert spoof == 421
    assert evil == 421
    assert local != 421
    assert mesh != 421
