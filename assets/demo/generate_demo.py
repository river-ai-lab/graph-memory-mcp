#!/usr/bin/env python3
"""
Generate demo scenario: graph traversal, supersede decision, contradictions.
Captures real server output from in-process execution.

Requires: ArcadeDB or FalkorDB running (docker compose up -d)
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_memory_mcp.config import load_mcp_server_config
from graph_memory_mcp.server import GraphMemoryMCP


def demo_scenario():
    """Run demo scenario and return formatted output."""
    print("Initializing Graph Memory MCP server...")

    try:
        config = load_mcp_server_config()
        server = GraphMemoryMCP(config)
        server.ensure_vector_indexes()
    except Exception as e:
        return f"ERROR: Failed to initialize: {e}\n\nRun: docker compose up -d"

    owner_id = "demo_team"
    output = []

    output.append("=== Graph Memory Demo ===\n")
    output.append("Scenario: Team decides API gateway component\n")

    # 1. Create initial decision
    output.append("\n1. Alice decides: API gateway uses Component X\n")
    decision_old = server.create_node(
        text="API gateway uses Component X for routing.",
        metadata={"project": "api", "created_by": "alice"},
        owner_id=owner_id,
    )
    old_id = decision_old["node"]["node_id"]
    output.append(f"   Created: {old_id[:8]}... (Component X decision)\n")

    # 2. Create service node
    output.append("\n2. Create service node: API Gateway Service\n")
    service = server.create_node(
        text="API Gateway Service handles external requests.",
        node_type="Entity",
        entity_type="Service",
        metadata={"project": "api"},
        owner_id=owner_id,
    )
    service_id = service["node"]["node_id"]
    output.append(f"   Created: {service_id[:8]}... (API Gateway Service)\n")

    # 3. Link decision to service
    output.append("\n3. Link: decision RELATED_TO service\n")
    server.create_relation(
        from_id=old_id, to_id=service_id, relation_type="RELATED_TO", owner_id=owner_id
    )
    output.append("   Relation: decision → RELATED_TO → service\n")

    # 4. Write-back after search miss
    output.append("\n4. Search miss → write-back loop\n")
    search_miss = server.search(
        query="Which port does the staging database use?", owner_id=owner_id, limit=3
    )
    miss_count = len(search_miss.get("results", []))
    output.append(f"   Search 'staging database port': {miss_count} results\n")

    # Agent finds answer (simulated: from config file)
    output.append("   Agent finds answer: staging DB uses port 5433 (from config)\n")

    # Write back with phrasing close to query
    writeback = server.create_node(
        text="The staging database uses port 5433.",
        metadata={"project": "api", "source": "config/staging.yaml"},
        owner_id=owner_id,
    )
    writeback_id = writeback["node"]["node_id"]
    output.append(f"   Wrote back: {writeback_id[:8]}...\n")

    # Search same query again
    search_hit = server.search(
        query="Which port does the staging database use?", owner_id=owner_id, limit=3
    )
    hit_count = len(search_hit.get("results", []))
    output.append(f"   Search again: {hit_count} results\n")
    if search_hit.get("results"):
        top = search_hit["results"][0]
        top_text = top["text"][:50] + "..." if len(top["text"]) > 50 else top["text"]
        output.append(f"   Top result: {top_text}\n")

    # 5. Get context (traverse)
    output.append("\n5. Get context: what affects the service?\n")
    context = server.get_context(node_id=service_id, owner_id=owner_id, depth=1)
    output.append(
        f"   Found {len(context['nodes'])} nodes, {len(context['edges'])} edges\n"
    )
    for node in context["nodes"]:
        if node["node_id"] != service_id:
            text_short = (
                node["text"][:50] + "..." if len(node["text"]) > 50 else node["text"]
            )
            output.append(f"   → {text_short}\n")

    # 6. New decision supersedes old
    output.append("\n6. Bob migrates to Component Y (supersedes old decision)\n")
    decision_new = server.create_node(
        text="API gateway migrated to Component Y (Oct 2026).",
        metadata={"project": "api", "created_by": "bob"},
        owner_id=owner_id,
    )
    new_id = decision_new["node"]["node_id"]
    output.append(f"   Created: {new_id[:8]}... (Component Y decision)\n")

    # 7. Mark old outdated
    output.append("\n7. Mark old decision outdated\n")
    server.mark_outdated(
        fact_id=old_id, reason="Migrated to Component Y", owner_id=owner_id
    )
    output.append("   Marked outdated: Component X decision\n")

    # 8. Link new -> old (FOLLOWS_FROM: new follows from old context)
    output.append("\n8. Link: new FOLLOWS_FROM old\n")
    server.create_relation(
        from_id=new_id, to_id=old_id, relation_type="FOLLOWS_FROM", owner_id=owner_id
    )
    output.append("   Relation: new → FOLLOWS_FROM → old\n")

    # 9. Search excludes outdated
    output.append("\n9. Search 'API gateway' (excludes outdated by default)\n")
    search_result = server.search(
        query="API gateway component",
        owner_id=owner_id,
        limit=5,
        include_outdated=False,
    )
    output.append(f"   Results: {len(search_result['results'])}\n")
    for i, r in enumerate(search_result["results"][:2], 1):
        status = r.get("status", "active")
        text_short = r["text"][:50] + "..." if len(r["text"]) > 50 else r["text"]
        output.append(f"   [{i}] ({status}) {text_short}\n")

    # 10. Create contradiction
    output.append("\n10. Create contradicting facts: rate limits\n")
    rate1 = server.create_node(
        text="API rate limit is 1000 requests per minute.",
        metadata={"project": "api"},
        owner_id=owner_id,
    )
    rate1_id = rate1["node"]["node_id"]
    output.append(f"   Created: {rate1_id[:8]}... (1000 req/min)\n")

    rate2 = server.create_node(
        text="API rate limit is 500 requests per minute.",
        metadata={"project": "api"},
        owner_id=owner_id,
    )
    rate2_id = rate2["node"]["node_id"]
    output.append(f"   Created: {rate2_id[:8]}... (500 req/min)\n")

    # 11. Agent marks contradiction (creates CONTRADICTS edge explicitly)
    output.append("\n11. Agent marks contradiction: rate1 CONTRADICTS rate2\n")
    server.create_relation(
        from_id=rate1_id, to_id=rate2_id, relation_type="CONTRADICTS", owner_id=owner_id
    )
    output.append("   CONTRADICTS edge created by agent\n")

    # 12. Search returns the contradiction pair
    output.append("\n12. Search 'API rate limit' returns contradiction pair\n")
    search_result2 = server.search(query="API rate limit", owner_id=owner_id, limit=5)
    output.append(f"   Results: {len(search_result2['results'])}\n")
    contradictions = search_result2.get("contradiction_pairs", [])
    output.append(f"   Contradiction pairs: {len(contradictions)}\n")
    if contradictions:
        for pair in contradictions:
            output.append(f"   ⚠  {pair['from_id'][:8]}... ↔ {pair['to_id'][:8]}...\n")

    # 13. Write-time deduplication
    output.append("\n13. Write-time dedup: attempt near-duplicate\n")
    try:
        dup_result = server.create_node(
            text="API gateway migrated to Component Y (October 2026).",
            metadata={"project": "api"},
            owner_id=owner_id,
        )
        if dup_result.get("error"):
            output.append(f"   Refused: {dup_result.get('error', 'duplicate')}\n")
            dups = dup_result.get("possible_duplicates", [])
            if dups:
                sim = dups[0].get("similarity", 0)
                output.append(f"   Similarity: {sim:.3f} (threshold 0.92)\n")
        else:
            output.append("   Accepted (not a near-duplicate)\n")
            dups = dup_result.get("possible_duplicates", [])
            if dups:
                sim = dups[0].get("similarity", 0)
                output.append(f"   Top similarity: {sim:.3f}\n")
    except Exception as e:
        output.append(f"   Exception: {e}\n")

    # Verify checkmarks
    context_has_decision = any(
        "Component X" in node.get("text", "") for node in context["nodes"]
    )
    outdated_excluded = not any(
        "Component X" in r.get("text", "") for r in search_result.get("results", [])
    )
    contradictions_found = len(contradictions) > 0
    writeback_found = (
        search_hit.get("results")
        and search_hit["results"][0].get("node_id") == writeback_id
    )

    output.append("\n=== Demo Complete ===\n")
    output.append(
        f"Write-back after miss: {'✓' if writeback_found else '✗'} (second search found new node)\n"
    )
    output.append(
        f"Graph traversal: {'✓' if context_has_decision else '✗'} (get_context found decision)\n"
    )
    output.append(
        f"Superseded decision: {'✓' if outdated_excluded else '✗'} (outdated excluded from search)\n"
    )
    output.append(
        f"Contradictions: {'✓' if contradictions_found else '✗'} (CONTRADICTS pair surfaced)\n"
    )

    return "".join(output)


if __name__ == "__main__":
    import time

    result = demo_scenario()

    # Print with pauses for readability in terminal recording
    for line in result.split("\n"):
        print(line)
        if line and not line.startswith("   "):
            time.sleep(0.8)  # Pause between major steps
        elif "→" in line or "Created:" in line:
            time.sleep(0.3)  # Brief pause for important lines
