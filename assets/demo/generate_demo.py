#!/usr/bin/env python3
"""Demo scenario against a running Graph Memory MCP server.

Requires ArcadeDB (docker compose up -d arcadedb) and the MCP server:

    uv run graph-memory-mcp --host 127.0.0.1 --port 8000

Shows an agent saving a fact, linking it, and later recalling it with search,
then the same graph moves the README describes: write-back, traversal,
outdating, contradictions, and write-time dedup.

``--prepare`` warms embeddings and indexes on a throwaway owner.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

SERVER_URL = os.environ.get("GRAPH_MEMORY_URL", "http://127.0.0.1:8000/mcp")
OWNER = "demo_team"
WARM_OWNER = "demo_warm"

RST = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
WHITE = "\033[97m"

PAUSE_STEP = float(os.environ.get("DEMO_PAUSE_STEP", "0.55"))
PAUSE_BEAT = float(os.environ.get("DEMO_PAUSE_BEAT", "0.18"))
PAUSE_END = float(os.environ.get("DEMO_PAUSE_END", "1.6"))


def say(text: str = "", pause: float = 0.0) -> None:
    print(text, flush=True)
    if pause:
        time.sleep(pause)


def short_id(node_id: str) -> str:
    return node_id[:8]


def counted(n: int, singular: str, plural: str | None = None) -> str:
    word = singular if n == 1 else (plural or f"{singular}s")
    return f"{n} {word}"


def clip(text: str, limit: int = 62) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def as_dict(result) -> dict:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    for block in getattr(result, "content", None) or []:
        data = getattr(block, "json", None)
        if isinstance(data, dict):
            return data
        text = getattr(block, "text", None)
        if isinstance(text, str):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return {"raw": text}
            if isinstance(parsed, dict):
                return parsed
    if getattr(result, "isError", False):
        return {"success": False, "error": "tool call failed"}
    return {"raw": repr(result)}


class Tools:
    def __init__(self, session: ClientSession):
        self.session = session

    async def call(self, name: str, arguments: dict) -> dict:
        result = await self.session.call_tool(name, arguments=arguments)
        return as_dict(result)


def require_node(payload: dict, what: str) -> str:
    node = payload.get("node") if isinstance(payload, dict) else None
    node_id = node.get("node_id") if isinstance(node, dict) else None
    if not node_id:
        raise SystemExit(f"{what} failed: {payload.get('error') or payload}")
    return str(node_id)


async def prepare(tools: Tools) -> None:
    health = await tools.call("health_check", {})
    if not health.get("healthy", health.get("success")):
        raise SystemExit(f"health_check failed: {health}")
    created = await tools.call(
        "create_node",
        {
            "text": "Warmup fact so the embedding model and indexes are ready.",
            "owner_id": WARM_OWNER,
            "check_duplicates": False,
        },
    )
    require_node(created, "warmup create_node")


async def scenario(tools: Tools) -> None:
    say("\033[?25l\033[2J\033[H", 0)
    say(f"{BOLD}{WHITE}Graph Memory MCP{RST}", 0.15)
    say(f"{DIM}{SERVER_URL}    owner {OWNER}{RST}", 0.25)
    say("Scenario: Team decides API gateway component", 0.35)

    say("")
    say(f"{BOLD}{CYAN} 1  Alice decides: API gateway uses Component X{RST}", PAUSE_STEP)
    say(f"{DIM}    create_node{RST}", PAUSE_BEAT)
    decision_old = await tools.call(
        "create_node",
        {
            "text": "API gateway uses Component X for routing.",
            "metadata": {"project": "api", "created_by": "alice"},
            "owner_id": OWNER,
        },
    )
    old_id = require_node(decision_old, "create_node decision")
    say('    "API gateway uses Component X for routing."', PAUSE_BEAT)
    say(f"    {GREEN}✓{RST}  saved {short_id(old_id)}", PAUSE_BEAT)

    say("")
    say(f"{BOLD}{CYAN} 2  Create service node: API Gateway Service{RST}", PAUSE_STEP)
    say(f"{DIM}    create_node  Entity{RST}", PAUSE_BEAT)
    service = await tools.call(
        "create_node",
        {
            "text": "API Gateway Service handles external requests.",
            "node_type": "Entity",
            "entity_type": "Service",
            "metadata": {"project": "api"},
            "owner_id": OWNER,
        },
    )
    service_id = require_node(service, "create_node service")
    say(f"    {GREEN}✓{RST}  saved {short_id(service_id)}", PAUSE_BEAT)

    say("")
    say(f"{BOLD}{CYAN} 3  Link: decision RELATED_TO service{RST}", PAUSE_STEP)
    say(f"{DIM}    create_relation{RST}", PAUSE_BEAT)
    linked = await tools.call(
        "create_relation",
        {
            "from_id": old_id,
            "to_id": service_id,
            "relation_type": "RELATED_TO",
            "owner_id": OWNER,
        },
    )
    if not linked.get("success", True) and linked.get("error"):
        raise SystemExit(f"create_relation failed: {linked}")
    say(
        f"    {short_id(old_id)}  {CYAN}→ RELATED_TO →{RST}  {short_id(service_id)}",
        PAUSE_BEAT,
    )
    say(f"    {GREEN}✓{RST}  linked", PAUSE_BEAT)

    say("")
    say(f"{BOLD}{CYAN} 4  Search miss → write-back loop{RST}", PAUSE_STEP)
    query_port = "Which port does the staging database use?"
    say(f"{DIM}    search{RST}  threshold 0.80", PAUSE_BEAT)
    say(f'    "{query_port}"', PAUSE_BEAT)
    search_miss = await tools.call(
        "search",
        {
            "query": query_port,
            "owner_id": OWNER,
            "limit": 3,
            "similarity_threshold": 0.80,
        },
    )
    miss_count = len(search_miss.get("results") or [])
    say(f"    {counted(miss_count, 'result')}", PAUSE_BEAT)
    say(f"{DIM}    create_node{RST}  write the answer back", PAUSE_BEAT)
    writeback = await tools.call(
        "create_node",
        {
            "text": "The staging database uses port 5433.",
            "metadata": {"project": "api", "source": "config/staging.yaml"},
            "owner_id": OWNER,
        },
    )
    writeback_id = require_node(writeback, "write-back create_node")
    say(f"    {GREEN}✓{RST}  saved {short_id(writeback_id)}", PAUSE_BEAT)
    say(f"{DIM}    search{RST}  same question", PAUSE_BEAT)
    search_hit = await tools.call(
        "search",
        {
            "query": query_port,
            "owner_id": OWNER,
            "limit": 3,
            "similarity_threshold": 0.80,
        },
    )
    hits = search_hit.get("results") or []
    say(f"    {counted(len(hits), 'result')}", PAUSE_BEAT)
    if hits:
        say(f"    {WHITE}{clip(str(hits[0].get('text', '')))}{RST}", 0.45)

    say("")
    say(f"{BOLD}{CYAN} 5  Get context: what affects the service?{RST}", PAUSE_STEP)
    say(f"{DIM}    get_context{RST}", PAUSE_BEAT)
    context = await tools.call(
        "get_context",
        {"node_id": service_id, "owner_id": OWNER, "depth": 1},
    )
    nodes = context.get("nodes") or []
    edges = context.get("edges") or []
    say(
        f"    {counted(len(nodes), 'node')}, {counted(len(edges), 'edge')}",
        PAUSE_BEAT,
    )
    for node in nodes:
        if node.get("node_id") != service_id:
            say(f"    {CYAN}→{RST}  {clip(str(node.get('text', '')))}", PAUSE_BEAT)

    say("")
    say(f"{BOLD}{CYAN} 6  Bob migrates to Component Y{RST}", PAUSE_STEP)
    say(f"{DIM}    create_node{RST}", PAUSE_BEAT)
    decision_new = await tools.call(
        "create_node",
        {
            "text": "API gateway migrated to Component Y (Oct 2026).",
            "metadata": {"project": "api", "created_by": "bob"},
            "owner_id": OWNER,
        },
    )
    new_id = require_node(decision_new, "create_node Component Y")
    say(f"    {GREEN}✓{RST}  saved {short_id(new_id)}", PAUSE_BEAT)

    say("")
    say(f"{BOLD}{CYAN} 7  Mark old decision outdated{RST}", PAUSE_STEP)
    say(f"{DIM}    mark_outdated{RST}", PAUSE_BEAT)
    outdated = await tools.call(
        "mark_outdated",
        {
            "fact_id": old_id,
            "reason": "Migrated to Component Y",
            "owner_id": OWNER,
        },
    )
    if outdated.get("success") is False:
        raise SystemExit(f"mark_outdated failed: {outdated}")
    say(f"    {YELLOW}outdated{RST}  {short_id(old_id)}", PAUSE_BEAT)

    say("")
    say(f"{BOLD}{CYAN} 8  Link: new FOLLOWS_FROM old{RST}", PAUSE_STEP)
    say(f"{DIM}    create_relation{RST}", PAUSE_BEAT)
    follows = await tools.call(
        "create_relation",
        {
            "from_id": new_id,
            "to_id": old_id,
            "relation_type": "FOLLOWS_FROM",
            "owner_id": OWNER,
        },
    )
    if follows.get("success") is False:
        raise SystemExit(f"create_relation FOLLOWS_FROM failed: {follows}")
    say(
        f"    {short_id(new_id)}  {CYAN}→ FOLLOWS_FROM →{RST}  {short_id(old_id)}",
        PAUSE_BEAT,
    )

    say("")
    say(f"{BOLD}{CYAN} 9  Search 'API gateway' excludes outdated{RST}", PAUSE_STEP)
    say(f"{DIM}    search{RST}", PAUSE_BEAT)
    search_gateway = await tools.call(
        "search",
        {
            "query": "API gateway component",
            "owner_id": OWNER,
            "limit": 5,
            "include_outdated": False,
        },
    )
    gateway_hits = search_gateway.get("results") or []
    say(f"    {counted(len(gateway_hits), 'result')}", PAUSE_BEAT)
    for index, row in enumerate(gateway_hits[:2], 1):
        status = row.get("status") or "active"
        say(
            f"    [{index}] ({status}) {clip(str(row.get('text', '')), 52)}", PAUSE_BEAT
        )

    say("")
    say(f"{BOLD}{CYAN}10  Contradicting facts: rate limits{RST}", PAUSE_STEP)
    say(f"{DIM}    create_node{RST}", PAUSE_BEAT)
    rate1 = await tools.call(
        "create_node",
        {
            "text": "API rate limit is 1000 requests per minute.",
            "metadata": {"project": "api"},
            "owner_id": OWNER,
        },
    )
    rate1_id = require_node(rate1, "create_node rate 1000")
    say(f"    {GREEN}✓{RST}  {short_id(rate1_id)}  1000 req/min", PAUSE_BEAT)
    rate2 = await tools.call(
        "create_node",
        {
            "text": "API rate limit is 500 requests per minute.",
            "metadata": {"project": "api"},
            "owner_id": OWNER,
            "check_duplicates": False,
        },
    )
    rate2_id = require_node(rate2, "create_node rate 500")
    say(f"    {GREEN}✓{RST}  {short_id(rate2_id)}  500 req/min", PAUSE_BEAT)

    say("")
    say(f"{BOLD}{CYAN}11  Agent marks contradiction{RST}", PAUSE_STEP)
    say(f"{DIM}    create_relation  CONTRADICTS{RST}", PAUSE_BEAT)
    contradicts = await tools.call(
        "create_relation",
        {
            "from_id": rate1_id,
            "to_id": rate2_id,
            "relation_type": "CONTRADICTS",
            "owner_id": OWNER,
        },
    )
    if contradicts.get("success") is False:
        raise SystemExit(f"create_relation CONTRADICTS failed: {contradicts}")
    say(
        f"    {short_id(rate1_id)}  {YELLOW}↔{RST}  {short_id(rate2_id)}",
        PAUSE_BEAT,
    )

    say("")
    say(f"{BOLD}{CYAN}12  Search returns the contradiction pair{RST}", PAUSE_STEP)
    say(f"{DIM}    search{RST}", PAUSE_BEAT)
    search_rates = await tools.call(
        "search",
        {"query": "API rate limit", "owner_id": OWNER, "limit": 5},
    )
    pairs = search_rates.get("contradiction_pairs") or []
    say(
        f"    {counted(len(search_rates.get('results') or []), 'result')}, "
        f"{counted(len(pairs), 'contradiction pair', 'contradiction pairs')}",
        PAUSE_BEAT,
    )
    for pair in pairs:
        say(
            f"    {YELLOW}⚠{RST}  {short_id(str(pair.get('from_id', '')))}"
            f"  ↔  {short_id(str(pair.get('to_id', '')))}",
            PAUSE_BEAT,
        )

    say("")
    say(f"{BOLD}{CYAN}13  Write-time dedup: near-duplicate{RST}", PAUSE_STEP)
    say(f"{DIM}    create_node{RST}", PAUSE_BEAT)
    duplicate = await tools.call(
        "create_node",
        {
            "text": "API gateway migrated to Component Y (October 2026).",
            "metadata": {"project": "api"},
            "owner_id": OWNER,
        },
    )
    dups = duplicate.get("possible_duplicates") or []
    similarity = float(dups[0].get("similarity") or 0) if dups else 0.0
    if duplicate.get("node"):
        say("    accepted (not a near-duplicate)", PAUSE_BEAT)
        if dups:
            say(f"    top similarity {similarity:.3f}", PAUSE_BEAT)
    else:
        say(
            f"    {YELLOW}refused{RST}  {duplicate.get('code') or 'duplicate'}",
            PAUSE_BEAT,
        )
        if dups:
            say(f"    similarity {similarity:.3f}  threshold 0.92", 0.4)

    context_has_decision = any(
        "Component X" in str(node.get("text", "")) for node in nodes
    )
    outdated_excluded = not any(
        "Component X" in str(row.get("text", "")) for row in gateway_hits
    )
    writeback_found = bool(hits) and hits[0].get("node_id") == writeback_id
    contradictions_found = len(pairs) > 0

    def mark(ok: bool) -> str:
        return f"{GREEN}✓{RST}" if ok else f"{YELLOW}✗{RST}"

    say("")
    say(f"{BOLD}Demo complete{RST}", 0.2)
    say(f"    write-back after miss   {mark(writeback_found)}", 0.12)
    say(f"    graph traversal         {mark(context_has_decision)}", 0.12)
    say(f"    outdated excluded       {mark(outdated_excluded)}", 0.12)
    say(f"    contradiction surfaced  {mark(contradictions_found)}", PAUSE_END)

    if not all(
        [writeback_found, context_has_decision, outdated_excluded, contradictions_found]
    ):
        raise SystemExit("demo checks failed")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Graph Memory MCP demo client")
    parser.add_argument(
        "--prepare",
        action="store_true",
        help="Warm the running server, then exit",
    )
    args = parser.parse_args()

    timeout = httpx.Timeout(120.0, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as http_client:
            async with streamable_http_client(SERVER_URL, http_client=http_client) as (
                read,
                write,
                _session_id,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = Tools(session)
                    if args.prepare:
                        await prepare(tools)
                        return
                    await scenario(tools)
    except httpx.ConnectError as exc:
        raise SystemExit(
            f"Cannot reach {SERVER_URL}. Start the server: "
            "uv run graph-memory-mcp --host 127.0.0.1 --port 8000"
        ) from exc


if __name__ == "__main__":
    asyncio.run(main())
