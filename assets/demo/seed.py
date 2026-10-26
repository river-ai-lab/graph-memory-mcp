#!/usr/bin/env python3
"""Seed the README demo owner with real MCP tool calls.

The script talks to a running server at ``GRAPH_MEMORY_URL`` (default
``http://127.0.0.1:8000/mcp``). It deletes owner ``readme_demo`` first, then
writes facts only through ``create_node``, ``update_node``, and
``create_relation``.

What the agent stores:

* Two active deadline facts, November 1 and November 15, and a CONTRADICTS
  edge between them. The server does not detect contradictions and does not
  choose a date.
* A beta fact, "Beta ships October 1.", then ``update_node`` with
  ``versioning=true`` and ``status="outdated"``. The server snapshots the
  previous fact because versioning is true. ``VERSIONING_DEFAULT`` is false,
  so the snapshot exists only because this call asked for it.
* "Beta ships October 20." with FOLLOWS_FROM the outdated beta.
* An entity, Release, and RELATED_TO edges from the current beta and from
  both deadline facts.

``valid_from`` and ``valid_until`` are metadata the agent writes. They are
not server columns.

The second deadline and the second beta pass ``check_duplicates=false``.
Those wordings are different facts that sit inside the server's near-duplicate
distance, so the default check would refuse them.

Requires the server::

    uv run graph-memory-mcp --host 127.0.0.1 --port 8000
    uv run python assets/demo/seed.py
"""

from __future__ import annotations

import asyncio
import json
import os

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

SERVER_URL = os.environ.get("GRAPH_MEMORY_URL", "http://127.0.0.1:8000/mcp")
OWNER = "readme_demo"

TEXT_NOV1 = "Deadline is November 1."
TEXT_NOV15 = "Deadline is November 15."
TEXT_BETA_OLD = "Beta ships October 1."
TEXT_BETA_NEW = "Beta ships October 20."
TEXT_RELEASE = "Release"

DATE_NOV1 = "2026-09-01"
DATE_NOV15 = "2026-10-12"
DATE_BETA_OLD = "2026-08-01"
DATE_BETA_UNTIL = "2026-10-01"
DATE_BETA_NEW = "2026-10-01"

QUERY_DEADLINE = "November deadline"
QUERY_BETA = "beta ships"


def as_dict(result) -> dict:
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


def fail(detail: str) -> None:
    raise SystemExit(detail)


def reset_owner() -> None:
    base = SERVER_URL.removesuffix("/mcp")
    try:
        response = httpx.delete(f"{base}/admin/owners/{OWNER}", timeout=30.0)
    except httpx.HTTPError as exc:
        fail(f"reset owner failed: {exc}")
    if response.status_code not in (200, 404):
        fail(f"reset owner failed: {response.status_code} {response.text}")


class Tools:
    def __init__(self, session: ClientSession):
        self.session = session

    async def call(self, name: str, arguments: dict) -> dict:
        result = await self.session.call_tool(name, arguments=arguments)
        payload = as_dict(result)
        if (
            not isinstance(payload, dict)
            or payload.get("success") is False
            or payload.get("error")
        ):
            fail(f"{name} failed: {payload.get('error') or payload}")
        return payload


def node_id(payload: dict, what: str) -> str:
    node = payload.get("node") if isinstance(payload, dict) else None
    found = node.get("node_id") if isinstance(node, dict) else None
    if not found:
        fail(f"{what} returned no node_id: {payload}")
    return str(found)


async def create_fact(
    tools: Tools,
    text: str,
    metadata: dict,
    *,
    check_duplicates: bool,
) -> str:
    created = await tools.call(
        "create_node",
        {
            "text": text,
            "metadata": metadata,
            "owner_id": OWNER,
            "check_duplicates": check_duplicates,
        },
    )
    return node_id(created, text)


async def seed(tools: Tools) -> None:
    reset_owner()
    nov1 = await create_fact(
        tools,
        TEXT_NOV1,
        {"valid_from": DATE_NOV1},
        check_duplicates=True,
    )
    nov15 = await create_fact(
        tools,
        TEXT_NOV15,
        {"valid_from": DATE_NOV15},
        check_duplicates=False,
    )
    await tools.call(
        "create_relation",
        {
            "from_id": nov1,
            "to_id": nov15,
            "relation_type": "CONTRADICTS",
            "owner_id": OWNER,
        },
    )
    beta_old = await create_fact(
        tools,
        TEXT_BETA_OLD,
        {"valid_from": DATE_BETA_OLD},
        check_duplicates=True,
    )
    updated = await tools.call(
        "update_node",
        {
            "node_id": beta_old,
            "owner_id": OWNER,
            "status": "outdated",
            "versioning": True,
            "metadata": {"valid_until": DATE_BETA_UNTIL},
        },
    )
    updated_node = updated.get("node") or {}
    if updated_node.get("status") != "outdated":
        fail(f"update_node did not set outdated: {updated_node}")
    beta_new = await create_fact(
        tools,
        TEXT_BETA_NEW,
        {"valid_from": DATE_BETA_NEW},
        check_duplicates=False,
    )
    release = await tools.call(
        "create_node",
        {
            "text": TEXT_RELEASE,
            "node_type": "Entity",
            "entity_type": "Project",
            "owner_id": OWNER,
        },
    )
    release_id = node_id(release, TEXT_RELEASE)
    for from_id, to_id, relation_type in (
        (beta_new, beta_old, "FOLLOWS_FROM"),
        (beta_new, release_id, "RELATED_TO"),
        (nov15, release_id, "RELATED_TO"),
        (nov1, release_id, "RELATED_TO"),
    ):
        await tools.call(
            "create_relation",
            {
                "from_id": from_id,
                "to_id": to_id,
                "relation_type": relation_type,
                "owner_id": OWNER,
            },
        )
    await check(tools, beta_old)


def rows(payload: dict) -> list[dict]:
    found = payload.get("results") or []
    if not isinstance(found, list):
        fail(f"search results missing: {payload}")
    return found


async def check(tools: Tools, beta_old: str) -> None:
    deadline = await tools.call(
        "search",
        {
            "query": QUERY_DEADLINE,
            "owner_id": OWNER,
            "limit": 2,
            "node_types": ["Fact"],
        },
    )
    texts = {str(row.get("text") or "") for row in rows(deadline)}
    if TEXT_NOV1 not in texts or TEXT_NOV15 not in texts:
        fail(f"deadline search missing a fact: {sorted(texts)}")
    ids = {
        str(row.get("text")): str(row.get("node_id"))
        for row in rows(deadline)
        if row.get("node_id")
    }
    pair_ok = False
    for pair in deadline.get("contradiction_pairs") or []:
        ends = {str(pair.get("from_id")), str(pair.get("to_id"))}
        if ends == {ids.get(TEXT_NOV1), ids.get(TEXT_NOV15)}:
            pair_ok = pair.get("relation_type") == "CONTRADICTS"
    if not pair_ok:
        fail(f"deadline search has no CONTRADICTS pair: {deadline}")

    beta = await tools.call(
        "search",
        {
            "query": QUERY_BETA,
            "owner_id": OWNER,
            "limit": 2,
            "node_types": ["Fact"],
            "include_outdated": True,
        },
    )
    by_text = {str(row.get("text") or ""): row for row in rows(beta)}
    current = by_text.get(TEXT_BETA_NEW) or {}
    old = by_text.get(TEXT_BETA_OLD) or {}
    if current.get("status") != "active":
        fail(f"current beta is not active: {current}")
    if old.get("status") != "outdated":
        fail(f"old beta is not outdated: {old}")
    old_meta = old.get("metadata") or {}
    if old_meta.get("valid_from") != DATE_BETA_OLD:
        fail(f"old beta metadata: {old_meta}")
    if old_meta.get("valid_until") != DATE_BETA_UNTIL:
        fail(f"old beta metadata: {old_meta}")

    hidden = await tools.call(
        "search",
        {
            "query": QUERY_BETA,
            "owner_id": OWNER,
            "limit": 5,
            "node_types": ["Fact"],
        },
    )
    hidden_texts = {str(row.get("text") or "") for row in rows(hidden)}
    if TEXT_BETA_OLD in hidden_texts:
        fail("default beta search returned the outdated fact")
    if TEXT_BETA_NEW not in hidden_texts:
        fail(f"default beta search missed the current fact: {sorted(hidden_texts)}")

    history = await tools.call(
        "get_node_change_history",
        {"node_id": beta_old, "owner_id": OWNER},
    )
    versions = history.get("versions") or []
    if len(versions) != 1:
        fail(f"expected one snapshot, got {versions}")
    snap = versions[0]
    snap_meta = snap.get("metadata") or {}
    if snap.get("text") != TEXT_BETA_OLD or snap.get("status") != "active":
        fail(f"snapshot is not the previous active fact: {snap}")
    if snap_meta.get("valid_from") != DATE_BETA_OLD or "valid_until" in snap_meta:
        fail(f"snapshot metadata: {snap_meta}")

    print(
        f"seeded {OWNER}: {TEXT_NOV1} CONTRADICTS {TEXT_NOV15}; "
        f"{TEXT_BETA_OLD} outdated with one snapshot; "
        f"{TEXT_BETA_NEW} FOLLOWS_FROM it; RELATED_TO {TEXT_RELEASE}"
    )


async def main() -> None:
    timeout = httpx.Timeout(120.0, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as http_client:
            async with streamable_http_client(SERVER_URL, http_client=http_client) as (
                read,
                write,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    await seed(Tools(session))
    except httpx.ConnectError as exc:
        raise SystemExit(
            f"Cannot reach {SERVER_URL}. Start the server: "
            "uv run graph-memory-mcp --host 127.0.0.1 --port 8000"
        ) from exc


if __name__ == "__main__":
    asyncio.run(main())
