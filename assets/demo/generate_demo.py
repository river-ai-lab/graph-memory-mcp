#!/usr/bin/env python3
"""Demo scenarios against a running Graph Memory MCP server.

The GIF types this client at a shell prompt. It connects to the live server,
prints ``initialize`` (server name and version) and the ``list_tools`` count,
then each tool call with the arguments that were sent and a trimmed excerpt of
the JSON response.

Requires ArcadeDB (``docker compose up -d arcadedb``) and the MCP server::

    uv run graph-memory-mcp --host 127.0.0.1 --port 8000

Scenarios
---------
sparse
    README take. Save a decision, link it to a service, migrate and mark the
    old fact outdated, search returns the current decision, near-duplicate
    refused.
dense
    Full 13-step take (write-back, traversal, outdating, contradictions, dedup).
seed
    Load the shared API-gateway story used by the landing-page clips. No GIF.
contradictions
    Search surfaces a CONTRADICTS edge the agent created. The server does not
    detect contradictions.
lifecycle
    Search leaves out the outdated decision. A near-duplicate is refused.
retrieval
    Search, then get_context shows the related service.

``--prepare`` warms embeddings on a throwaway owner.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import PaginatedRequestParams

SERVER_URL = os.environ.get("GRAPH_MEMORY_URL", "http://127.0.0.1:8000/mcp")
OWNER = "demo_team"
WARM_OWNER = "demo_warm"
STATUS_FILE = os.environ.get("DEMO_STATUS_FILE", "")

TEXT_X = "API gateway uses Component X for routing."
TEXT_SERVICE = "API Gateway Service handles external requests."
TEXT_Y = "API gateway migrated to Component Y (Oct 2026)."
TEXT_Y_DUP = "API gateway migrated to Component Y (October 2026)."
TEXT_RATE_HI = "API rate limit is 1000 requests per minute."
TEXT_RATE_LO = "API rate limit is 500 requests per minute."
TEXT_PORT = "The staging database uses port 5433."
QUERY_PORT = "Which port does the staging database use?"
QUERY_GATEWAY = "API gateway component"
QUERY_RATE = "API rate limit"

RST = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
WHITE = "\033[97m"

PAUSE_STEP = 0.55
PAUSE_BEAT = 0.18
PAUSE_END = 1.6

SCENARIOS = (
    "sparse",
    "dense",
    "seed",
    "contradictions",
    "lifecycle",
    "retrieval",
)

_ARG_ORDER = (
    "text",
    "query",
    "metadata",
    "node_type",
    "entity_type",
    "from_id",
    "to_id",
    "relation_type",
    "fact_id",
    "reason",
    "node_id",
    "depth",
    "limit",
    "node_types",
    "similarity_threshold",
    "include_outdated",
    "check_duplicates",
    "source",
)


def configure_pace(step: float, beat: float, end: float) -> None:
    global PAUSE_STEP, PAUSE_BEAT, PAUSE_END
    PAUSE_STEP = float(os.environ.get("DEMO_PAUSE_STEP", step))
    PAUSE_BEAT = float(os.environ.get("DEMO_PAUSE_BEAT", beat))
    PAUSE_END = float(os.environ.get("DEMO_PAUSE_END", end))


def header_pause() -> float:
    return float(os.environ.get("DEMO_PAUSE_HEADER", "0.45"))


def say(text: str = "", pause: float = 0.0) -> None:
    print(text, flush=True)
    if pause:
        time.sleep(pause)


def hold(scale: float) -> None:
    delay = PAUSE_BEAT * scale
    if delay > 0:
        time.sleep(delay)


def set_status(ok: bool, detail: str = "") -> None:
    if not STATUS_FILE:
        return
    text = "ok\n" if ok else f"fail\n{detail}\n"
    Path(STATUS_FILE).write_text(text, encoding="utf-8")


def fail(detail: str) -> None:
    set_status(False, detail)
    raise SystemExit(detail)


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


def rounded(value: object) -> float:
    return float(f"{float(value):.3f}")


def dumps(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(", ", ": "))


def terminal_columns() -> int:
    width = shutil.get_terminal_size(fallback=(108, 40)).columns
    return max(72, width)


def wrap_text(text: str) -> list[str]:
    cols = terminal_columns()
    lines: list[str] = []
    rest = text
    while rest:
        if len(rest) <= cols:
            lines.append(rest)
            break
        if len(lines) == 3:
            lines.append(clip(rest, cols))
            break
        window = rest[:cols]
        cut = window.rfind(", ")
        if cut < 24:
            cut = window.rfind(" ")
        if cut < 24:
            lines.append(clip(rest, cols))
            break
        lines.append(rest[: cut + 1])
        rest = "      " + rest[cut + 2 :]
    return lines


def emit(text: str, color: str) -> None:
    for line in wrap_text(text):
        say(f"{color}{line}{RST}")


def display_args(arguments: dict) -> dict:
    shown: dict = {}
    for key in _ARG_ORDER:
        if key not in arguments:
            continue
        value = arguments[key]
        if value is None:
            continue
        if key == "check_duplicates" and value is True:
            continue
        if key == "include_outdated" and value is False:
            continue
        if key in {"from_id", "to_id", "fact_id", "node_id"} and isinstance(value, str):
            value = value[:8] + "…"
        if key == "similarity_threshold" and isinstance(value, float):
            value = rounded(value)
        shown[key] = value
    return shown


def response_excerpt(name: str, payload: dict) -> dict:
    if payload.get("code") == "memory_duplicate":
        dups = payload.get("possible_duplicates") or []
        excerpt: dict = {"code": "memory_duplicate"}
        if dups and dups[0].get("similarity") is not None:
            excerpt["similarity"] = rounded(dups[0]["similarity"])
        return excerpt
    if name == "search":
        raw_rows = (payload.get("results") or [])[:2]
        shown_ids = {str(row.get("node_id")) for row in raw_rows if row.get("node_id")}
        rows = []
        for row in raw_rows:
            item: dict = {"text": clip(str(row.get("text") or ""), 56)}
            if row.get("similarity") is not None:
                item["similarity"] = rounded(row["similarity"])
            if row.get("status") not in (None, "active"):
                item["status"] = row.get("status")
            rows.append(item)
        excerpt = {"results": rows}
        pairs = []
        for pair in payload.get("contradiction_pairs") or []:
            ends = {str(pair.get("from_id")), str(pair.get("to_id"))}
            if ends <= shown_ids:
                pairs.append(
                    {"relation_type": pair.get("relation_type") or "CONTRADICTS"}
                )
        if pairs:
            excerpt["contradiction_pairs"] = pairs
        return excerpt
    if name == "get_context":
        nodes = [
            {"text": clip(str(node.get("text") or ""), 48)}
            for node in (payload.get("nodes") or [])[:3]
        ]
        edges = [
            {"relation_type": edge.get("relation_type")}
            for edge in (payload.get("edges") or [])[:2]
        ]
        return {"nodes": nodes, "edges": edges}
    if name == "create_node":
        node = payload.get("node") or {}
        if node:
            shown = {"text": clip(str(node.get("text") or ""), 56)}
            if node.get("node_type") not in (None, "Fact"):
                shown["node_type"] = node.get("node_type")
            if node.get("status"):
                shown["status"] = node.get("status")
            return {"node": shown}
    if name == "mark_outdated":
        node = payload.get("node") or {}
        return {"success": True, "status": node.get("status") or "outdated"}
    if name == "create_relation":
        return {
            "success": bool(payload.get("success", True)),
            "relation_type": payload.get("relation_type"),
        }
    if payload.get("success") is False or payload.get("error"):
        excerpt = {"success": False}
        if payload.get("code"):
            excerpt["code"] = payload.get("code")
        if payload.get("error"):
            excerpt["error"] = clip(str(payload.get("error")), 72)
        return excerpt
    return {"success": bool(payload.get("success", True))}


def render_request(name: str, arguments: dict) -> None:
    body = display_args(arguments)
    call = f"{name} {dumps(body)}" if body else name
    emit(f"    → {call}", CYAN)


def render_response(name: str, payload: dict) -> None:
    emit(f"    ← {dumps(response_excerpt(name, payload))}", DIM)


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
    def __init__(self, session: ClientSession, *, show: bool = False):
        self.session = session
        self.show = show

    async def call(self, name: str, arguments: dict) -> dict:
        if self.show:
            render_request(name, arguments)
            hold(0.45)
        result = await self.session.call_tool(name, arguments=arguments)
        payload = as_dict(result)
        if self.show:
            render_response(name, payload)
            hold(0.55)
        return payload


def require_node(payload: dict, what: str) -> str:
    node = payload.get("node") if isinstance(payload, dict) else None
    node_id = node.get("node_id") if isinstance(node, dict) else None
    if not node_id:
        fail(f"{what} failed: {payload.get('error') or payload}")
    return str(node_id)


def require_ok(payload: dict, what: str) -> None:
    if (
        not isinstance(payload, dict)
        or payload.get("success") is False
        or payload.get("error")
    ):
        fail(f"{what} failed: {payload.get('error') or payload}")


def result_rows(payload: dict) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("success") is False:
        fail(f"search failed: {payload}")
    rows = payload.get("results") or []
    if not isinstance(rows, list):
        fail(f"search results missing: {payload}")
    return rows


def row_text(row: dict) -> str:
    return str(row.get("text") or "")


def begin(title: str, subtitle: str = "") -> None:
    say("")
    say(f"{BOLD}{WHITE}{title}{RST}", PAUSE_STEP)
    if subtitle:
        say(f"{DIM}{subtitle}{RST}", PAUSE_BEAT)


def step(number: int, title: str) -> None:
    say("")
    say(f"{BOLD}{CYAN}{number:>2}  {title}{RST}", PAUSE_STEP)


def reset_owner() -> None:
    base = SERVER_URL.removesuffix("/mcp")
    try:
        response = httpx.delete(f"{base}/admin/owners/{OWNER}", timeout=30.0)
    except httpx.HTTPError as exc:
        fail(f"reset owner failed: {exc}")
    if response.status_code not in (200, 404):
        fail(f"reset owner failed: {response.status_code} {response.text}")


async def list_tool_count(session: ClientSession) -> int:
    count = 0
    cursor = None
    while True:
        if cursor is None:
            page = await session.list_tools()
        else:
            page = await session.list_tools(
                params=PaginatedRequestParams(cursor=cursor)
            )
        count += len(page.tools)
        cursor = getattr(page, "nextCursor", None)
        if cursor is None:
            cursor = getattr(page, "next_cursor", None)
        if not cursor:
            return count


async def announce(session: ClientSession, init) -> None:
    """Print the live initialize result and tool count. No screen clear."""
    info = getattr(init, "serverInfo", None)
    if info is None:
        info = getattr(init, "server_info", None)
    name = str(getattr(info, "name", "") or "")
    version = str(getattr(info, "version", "") or "")
    if not name or not version:
        fail(f"initialize missing serverInfo: {info!r}")
    print("\033[?25l", end="", flush=True)
    pause = header_pause()
    say(f"{BOLD}MCP client{RST}  →  graph-memory-mcp  {SERVER_URL}", pause)
    say(f"{DIM}serverInfo{RST}     name={dumps(name)}  version={dumps(version)}", pause)
    count = await list_tool_count(session)
    if count < 1:
        fail("list_tools returned no tools")
    say(f"{DIM}list_tools{RST}     {count} tools", pause)
    say(
        f"{DIM}server{RST}         already running · "
        "uv run graph-memory-mcp --host 127.0.0.1 --port 8000",
        pause,
    )


async def prepare(tools: Tools) -> None:
    health = await tools.call("health_check", {})
    if not health.get("healthy", health.get("success")):
        fail(f"health_check failed: {health}")
    created = await tools.call(
        "create_node",
        {
            "text": "Warmup fact so the embedding model and indexes are ready.",
            "owner_id": WARM_OWNER,
            "check_duplicates": False,
        },
    )
    require_node(created, "warmup create_node")


async def create_fact(
    tools: Tools,
    text: str,
    *,
    created_by: str | None = None,
    check_duplicates: bool = True,
    source: str | None = None,
) -> str:
    metadata: dict = {"project": "api"}
    if created_by:
        metadata["created_by"] = created_by
    if source:
        metadata["source"] = source
    created = await tools.call(
        "create_node",
        {
            "text": text,
            "metadata": metadata,
            "owner_id": OWNER,
            "check_duplicates": check_duplicates,
        },
    )
    return require_node(created, "create_node")


async def create_service(tools: Tools) -> str:
    created = await tools.call(
        "create_node",
        {
            "text": TEXT_SERVICE,
            "node_type": "Entity",
            "entity_type": "Service",
            "metadata": {"project": "api"},
            "owner_id": OWNER,
        },
    )
    return require_node(created, "create_node service")


async def link(tools: Tools, from_id: str, to_id: str, relation_type: str) -> None:
    linked = await tools.call(
        "create_relation",
        {
            "from_id": from_id,
            "to_id": to_id,
            "relation_type": relation_type,
            "owner_id": OWNER,
        },
    )
    require_ok(linked, f"create_relation {relation_type}")


async def mark_old(tools: Tools, fact_id: str) -> None:
    outdated = await tools.call(
        "mark_outdated",
        {
            "fact_id": fact_id,
            "reason": "Migrated to Component Y",
            "owner_id": OWNER,
        },
    )
    require_ok(outdated, "mark_outdated")


async def search(
    tools: Tools,
    query: str,
    *,
    limit: int = 5,
    include_outdated: bool = False,
    node_types: list[str] | None = None,
    similarity_threshold: float | None = None,
) -> dict:
    arguments: dict = {
        "query": query,
        "owner_id": OWNER,
        "limit": limit,
        "include_outdated": include_outdated,
    }
    if node_types is not None:
        arguments["node_types"] = node_types
    if similarity_threshold is not None:
        arguments["similarity_threshold"] = similarity_threshold
    return await tools.call("search", arguments)


async def seed_story(tools: Tools) -> None:
    """Shared landing-page dataset. Same owner, same API-gateway story.

    The agent (this seed) marks Component X outdated and creates the
    CONTRADICTS edge. The server does not detect contradictions.
    """
    reset_owner()
    old_id = await create_fact(tools, TEXT_X, created_by="alice")
    service_id = await create_service(tools)
    await link(tools, old_id, service_id, "RELATED_TO")
    new_id = await create_fact(tools, TEXT_Y, created_by="bob")
    await mark_old(tools, old_id)
    await link(tools, new_id, old_id, "FOLLOWS_FROM")
    await link(tools, new_id, service_id, "RELATED_TO")
    rate_hi = await create_fact(tools, TEXT_RATE_HI)
    rate_lo = await create_fact(tools, TEXT_RATE_LO, check_duplicates=False)
    await link(tools, rate_hi, rate_lo, "CONTRADICTS")
    print("seeded", file=sys.stderr)


def texts_of(rows: list[dict]) -> list[str]:
    return [row_text(row) for row in rows]


def require_current_only(rows: list[dict], *, what: str) -> None:
    texts = texts_of(rows)
    if not any(TEXT_Y in text for text in texts):
        fail(f"{what}: current decision missing from {texts}")
    if any("Component X" in text for text in texts):
        fail(f"{what}: outdated Component X was returned")


def _refused_similarity(duplicate: dict, *, what: str) -> float:
    if duplicate.get("node"):
        fail(f"{what}: near-duplicate was stored")
    if duplicate.get("code") != "memory_duplicate":
        fail(f"{what}: expected memory_duplicate, got {duplicate}")
    dups = duplicate.get("possible_duplicates") or []
    similarity = float(dups[0].get("similarity") or 0) if dups else 0.0
    if similarity < 0.92:
        fail(f"{what}: similarity {similarity:.3f} is below 0.92")
    return similarity


async def scenario_contradictions(tools: Tools) -> None:
    configure_pace(1.4, 1.15, 1.5)
    begin(
        "Contradiction the agent marked",
        "The agent created CONTRADICTS. The server does not detect it.",
    )
    step(1, "Search returns both rate limits")
    found = await search(tools, QUERY_RATE, limit=5, node_types=["Fact"])
    rows = result_rows(found)
    shown = [row for row in rows if "rate limit" in row_text(row).lower()]
    if len(shown) < 2:
        shown = rows
    pairs = found.get("contradiction_pairs") or []
    if len(pairs) < 1:
        fail(f"contradictions: no pair in search results {texts_of(rows)}")
    rate_ids = {
        str(row.get("node_id")) for row in rows if "rate limit" in row_text(row).lower()
    }
    pair_ids = {str(pairs[0].get("from_id")), str(pairs[0].get("to_id"))}
    if not pair_ids <= rate_ids and rate_ids:
        fail(f"contradictions: pair {pair_ids} is not the rate-limit facts {rate_ids}")
    if not any(TEXT_RATE_HI in text for text in texts_of(rows)):
        fail("contradictions: 1000 req/min missing")
    if not any(TEXT_RATE_LO in text for text in texts_of(rows)):
        fail("contradictions: 500 req/min missing")
    say(
        f"    {YELLOW}⚠{RST}  {counted(len(pairs), 'pair')} · agent marked CONTRADICTS",
        PAUSE_END,
    )
    set_status(True)


async def scenario_lifecycle(tools: Tools) -> None:
    configure_pace(0.95, 0.75, 1.05)
    begin("Outdating and dedup")
    step(1, "Search returns the current decision")
    found = await search(
        tools,
        QUERY_GATEWAY,
        limit=5,
        node_types=["Fact"],
        similarity_threshold=0.80,
    )
    rows = result_rows(found)
    require_current_only(rows, what="lifecycle search")
    say(f"    {GREEN}✓{RST}  current decision", PAUSE_BEAT * 0.35)

    step(2, "Component X is stored as outdated")
    hidden = await search(
        tools,
        "Component X for routing",
        limit=2,
        include_outdated=True,
        node_types=["Fact"],
    )
    hidden_rows = result_rows(hidden)
    outdated = [
        row
        for row in hidden_rows
        if "Component X" in row_text(row) and row.get("status") == "outdated"
    ]
    if not outdated:
        fail(
            f"lifecycle: Component X is not stored as outdated ({texts_of(hidden_rows)})"
        )
    say("    the first search leaves it out", PAUSE_BEAT * 0.35)

    step(3, "Near-duplicate refused")
    duplicate = await tools.call(
        "create_node",
        {
            "text": TEXT_Y_DUP,
            "metadata": {"project": "api"},
            "owner_id": OWNER,
        },
    )
    similarity = _refused_similarity(duplicate, what="lifecycle dedup")
    say(f"    {YELLOW}refused{RST}  similarity {rounded(similarity):.3f}", PAUSE_END)
    set_status(True)


async def scenario_retrieval(tools: Tools) -> None:
    configure_pace(1.15, 0.95, 1.25)
    begin("Search, then the graph")
    step(1, "Search for the gateway decision")
    found = await search(
        tools,
        QUERY_GATEWAY,
        limit=5,
        node_types=["Fact"],
        similarity_threshold=0.80,
    )
    rows = result_rows(found)
    require_current_only(rows, what="retrieval search")
    current = next(row for row in rows if TEXT_Y in row_text(row))
    say(f"    {GREEN}✓{RST}  current decision", PAUSE_BEAT * 0.35)

    step(2, "get_context shows the related service")
    context = await tools.call(
        "get_context",
        {"node_id": current["node_id"], "owner_id": OWNER, "depth": 1},
    )
    if context.get("success") is False:
        fail(f"get_context failed: {context}")
    nodes = context.get("nodes") or []
    edges = context.get("edges") or []
    neighbor_texts = [
        str(node.get("text") or "")
        for node in nodes
        if node.get("node_id") != current["node_id"]
    ]
    if TEXT_SERVICE not in neighbor_texts:
        fail(f"retrieval: service not in context {neighbor_texts}")
    if any("Component X" in text for text in neighbor_texts):
        fail("retrieval: outdated Component X was included")
    if len(edges) < 1:
        fail("retrieval: context has no edges")
    say(f"    {GREEN}✓{RST}  {counted(len(edges), 'edge')} · {TEXT_SERVICE}", PAUSE_END)
    set_status(True)


async def scenario_dense(tools: Tools) -> None:
    configure_pace(0.42, 0.14, 1.2)
    begin("Graph Memory MCP")
    say("Scenario: Team decides API gateway component", PAUSE_BEAT)
    reset_owner()

    step(1, "Alice decides: API gateway uses Component X")
    decision_old = await tools.call(
        "create_node",
        {
            "text": TEXT_X,
            "metadata": {"project": "api", "created_by": "alice"},
            "owner_id": OWNER,
        },
    )
    old_id = require_node(decision_old, "create_node decision")
    say(f"    {GREEN}✓{RST}  saved {short_id(old_id)}", PAUSE_BEAT * 0.4)

    step(2, "Create service node: API Gateway Service")
    service_id = await create_service(tools)
    say(f"    {GREEN}✓{RST}  saved {short_id(service_id)}", PAUSE_BEAT * 0.4)

    step(3, "Link: decision RELATED_TO service")
    await link(tools, old_id, service_id, "RELATED_TO")
    say(
        f"    {short_id(old_id)}  {CYAN}→ RELATED_TO →{RST}  {short_id(service_id)}",
        PAUSE_BEAT * 0.4,
    )

    step(4, "Search miss → write-back loop")
    search_miss = await search(
        tools,
        QUERY_PORT,
        limit=3,
        similarity_threshold=0.80,
    )
    miss_rows = result_rows(search_miss)
    say(f"    {counted(len(miss_rows), 'result')}", PAUSE_BEAT * 0.3)
    writeback_id = await create_fact(tools, TEXT_PORT, source="config/staging.yaml")
    say(f"    {GREEN}✓{RST}  saved {short_id(writeback_id)}", PAUSE_BEAT * 0.3)
    search_hit = await search(
        tools,
        QUERY_PORT,
        limit=3,
        similarity_threshold=0.80,
    )
    hits = result_rows(search_hit)
    say(f"    {counted(len(hits), 'result')}", PAUSE_BEAT * 0.3)
    if hits:
        say(f"    {WHITE}{clip(row_text(hits[0]))}{RST}", PAUSE_BEAT * 0.4)
    if len(miss_rows) != 0:
        fail(f"dense: expected a search miss, got {texts_of(miss_rows)}")
    if not hits or hits[0].get("node_id") != writeback_id:
        fail("dense: write-back was not the top search hit")

    step(5, "Get context: what affects the service?")
    context = await tools.call(
        "get_context",
        {"node_id": service_id, "owner_id": OWNER, "depth": 1},
    )
    if context.get("success") is False:
        fail(f"get_context failed: {context}")
    nodes = context.get("nodes") or []
    edges = context.get("edges") or []
    say(
        f"    {counted(len(nodes), 'node')}, {counted(len(edges), 'edge')}",
        PAUSE_BEAT * 0.4,
    )
    for node in nodes:
        if node.get("node_id") != service_id:
            say(
                f"    {CYAN}→{RST}  {clip(str(node.get('text', '')))}", PAUSE_BEAT * 0.3
            )

    step(6, "Bob migrates to Component Y")
    new_id = await create_fact(tools, TEXT_Y, created_by="bob")
    say(f"    {GREEN}✓{RST}  saved {short_id(new_id)}", PAUSE_BEAT * 0.3)

    step(7, "Mark old decision outdated")
    await mark_old(tools, old_id)
    say(f"    {YELLOW}outdated{RST}  {short_id(old_id)}", PAUSE_BEAT * 0.3)

    step(8, "Link: new FOLLOWS_FROM old")
    await link(tools, new_id, old_id, "FOLLOWS_FROM")
    say(
        f"    {short_id(new_id)}  {CYAN}→ FOLLOWS_FROM →{RST}  {short_id(old_id)}",
        PAUSE_BEAT * 0.3,
    )

    step(9, "Search 'API gateway' excludes outdated")
    search_gateway = await search(tools, QUERY_GATEWAY, limit=5, include_outdated=False)
    gateway_hits = result_rows(search_gateway)
    say(f"    {counted(len(gateway_hits), 'result')}", PAUSE_BEAT * 0.25)
    for index, row in enumerate(gateway_hits[:2], 1):
        status = row.get("status") or "active"
        say(
            f"    [{index}] ({status}) {clip(row_text(row), 52)}",
            PAUSE_BEAT * 0.25,
        )

    step(10, "Contradicting facts: rate limits")
    rate1_id = await create_fact(tools, TEXT_RATE_HI)
    say(f"    {GREEN}✓{RST}  {short_id(rate1_id)}  1000 req/min", PAUSE_BEAT * 0.25)
    rate2_id = await create_fact(tools, TEXT_RATE_LO, check_duplicates=False)
    say(f"    {GREEN}✓{RST}  {short_id(rate2_id)}  500 req/min", PAUSE_BEAT * 0.25)

    step(11, "Agent marks contradiction")
    await link(tools, rate1_id, rate2_id, "CONTRADICTS")
    say(
        f"    {short_id(rate1_id)}  {YELLOW}↔{RST}  {short_id(rate2_id)}",
        PAUSE_BEAT * 0.3,
    )

    step(12, "Search returns the contradiction pair")
    search_rates = await search(tools, QUERY_RATE, limit=5)
    rate_rows = result_rows(search_rates)
    pairs = search_rates.get("contradiction_pairs") or []
    say(
        f"    {counted(len(rate_rows), 'result')}, "
        f"{counted(len(pairs), 'contradiction pair', 'contradiction pairs')}",
        PAUSE_BEAT * 0.3,
    )
    for pair in pairs:
        say(
            f"    {YELLOW}⚠{RST}  {short_id(str(pair.get('from_id', '')))}"
            f"  ↔  {short_id(str(pair.get('to_id', '')))}",
            PAUSE_BEAT * 0.25,
        )

    step(13, "Write-time dedup: near-duplicate")
    duplicate = await tools.call(
        "create_node",
        {
            "text": TEXT_Y_DUP,
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
            PAUSE_BEAT * 0.4,
        )
        if dups:
            say(f"    similarity {rounded(similarity):.3f}  threshold 0.92", PAUSE_BEAT)

    context_has_decision = any(
        "Component X" in str(node.get("text", "")) for node in nodes
    )
    outdated_excluded = not any("Component X" in row_text(row) for row in gateway_hits)
    contradictions_found = len(pairs) > 0
    dedup_refused = not duplicate.get("node") and similarity >= 0.92

    def mark(ok: bool) -> str:
        return f"{GREEN}✓{RST}" if ok else f"{YELLOW}✗{RST}"

    say("")
    say(f"{BOLD}Demo complete{RST}", 0.15)
    say(f"    write-back after miss   {mark(True)}", 0.08)
    say(f"    graph traversal         {mark(context_has_decision)}", 0.08)
    say(f"    outdated excluded       {mark(outdated_excluded)}", 0.08)
    say(f"    contradiction surfaced  {mark(contradictions_found)}", 0.08)
    say(f"    near-duplicate refused  {mark(dedup_refused)}", PAUSE_END)

    if not all(
        [
            context_has_decision,
            outdated_excluded,
            contradictions_found,
            dedup_refused,
        ]
    ):
        fail("dense checks failed")
    set_status(True)


async def scenario_sparse_run(tools: Tools) -> None:
    configure_pace(1.4, 0.95, 1.5)
    begin("Graph Memory MCP")
    reset_owner()

    step(1, "Save the decision")
    old_id = await create_fact(tools, TEXT_X, created_by="alice")
    say(f"    {GREEN}✓{RST}  saved", PAUSE_BEAT * 0.35)

    step(2, "Link it to the service")
    service_id = await create_service(tools)
    await link(tools, old_id, service_id, "RELATED_TO")
    say(f"    decision  {CYAN}→ RELATED_TO →{RST}  service", PAUSE_BEAT * 0.35)

    step(3, "Migrate and mark the old one outdated")
    await create_fact(tools, TEXT_Y, created_by="bob")
    await mark_old(tools, old_id)
    say(f"    {YELLOW}outdated{RST}  Component X", PAUSE_BEAT * 0.35)

    step(4, "Search returns only the current decision")
    found = await search(
        tools,
        QUERY_GATEWAY,
        limit=5,
        node_types=["Fact"],
    )
    rows = result_rows(found)
    require_current_only(rows, what="sparse search")
    say(f"    {GREEN}✓{RST}  current decision", PAUSE_BEAT * 0.35)

    step(5, "Near-duplicate refused")
    duplicate = await tools.call(
        "create_node",
        {
            "text": TEXT_Y_DUP,
            "metadata": {"project": "api"},
            "owner_id": OWNER,
        },
    )
    similarity = _refused_similarity(duplicate, what="sparse dedup")
    say(f"    {YELLOW}refused{RST}  similarity {rounded(similarity):.3f}", PAUSE_END)
    set_status(True)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Graph Memory MCP demo client")
    parser.add_argument(
        "--prepare",
        action="store_true",
        help="Warm the running server, then exit",
    )
    parser.add_argument(
        "--scenario",
        choices=SCENARIOS,
        help="Which demo to run",
    )
    args = parser.parse_args()
    if not args.prepare and not args.scenario:
        parser.error("--scenario is required unless --prepare is set")

    runners = {
        "sparse": scenario_sparse_run,
        "dense": scenario_dense,
        "seed": seed_story,
        "contradictions": scenario_contradictions,
        "lifecycle": scenario_lifecycle,
        "retrieval": scenario_retrieval,
    }
    recorded = bool(args.scenario) and args.scenario != "seed" and not args.prepare

    timeout = httpx.Timeout(120.0, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as http_client:
            async with streamable_http_client(SERVER_URL, http_client=http_client) as (
                read,
                write,
            ):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    tools = Tools(session, show=recorded)
                    if recorded:
                        await announce(session, init)
                    if args.prepare:
                        await prepare(tools)
                        return
                    await runners[args.scenario](tools)
    except httpx.ConnectError as exc:
        detail = (
            f"Cannot reach {SERVER_URL}. Start the server: "
            "uv run graph-memory-mcp --host 127.0.0.1 --port 8000"
        )
        set_status(False, detail)
        raise SystemExit(detail) from exc


if __name__ == "__main__":
    asyncio.run(main())
