#!/usr/bin/env python3
"""
Graph Memory benchmark: seed corpus and run queries via Python API.
Requires FalkorDB running (docker compose up -d).
"""

import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Dict, List

import yaml

from graph_memory_mcp.config import load_mcp_server_config
from graph_memory_mcp.server import GraphMemoryMCP

logging.basicConfig(level=logging.WARNING)


def load_corpus(corpus_path: str) -> List[Dict]:
    """Load corpus from YAML."""
    with open(corpus_path) as f:
        data = yaml.safe_load(f)
    return data["facts"]


def load_queries(queries_path: str) -> List[Dict]:
    """Load queries from YAML."""
    with open(queries_path) as f:
        data = yaml.safe_load(f)
    return data["queries"]


def seed_corpus(server: GraphMemoryMCP, corpus: List[Dict], owner_id: str) -> Dict:
    """Seed corpus into graph. Returns key->node_id mapping and stats."""
    key_to_node = {}
    stats = {
        "written": 0,
        "refused_duplicates": 0,
        "outdated_marked": 0,
        "relations_created": 0,
    }

    print(f"Seeding {len(corpus)} facts...")

    # First pass: create facts (skip should_refuse)
    for fact in corpus:
        key = fact["key"]
        status = fact.get("status", "active")

        if status == "should_refuse":
            # Test duplicate - try to write it
            result = server.create_node(
                text=fact["text"],
                node_type="Fact",
                metadata={"key": key, "test": "duplicate"},
                owner_id=owner_id,
                check_duplicates=True,
            )
            if not result.get("success", True):
                stats["refused_duplicates"] += 1
                print(f"  [{key}] Duplicate refused (expected)")
            continue

        # Create the fact (always create as active first)
        needs_outdating = status == "outdated"
        result = server.create_node(
            text=fact["text"],
            node_type="Fact",
            metadata={
                "key": key,
                "created_at": fact.get("created_at", ""),
                "outdated_at": fact.get("outdated_at", ""),
            },
            owner_id=owner_id,
            check_duplicates=True,
        )

        if result.get("success", True):
            node = result.get("node", {})
            node_id = node.get("node_id")
            key_to_node[key] = node_id
            stats["written"] += 1

            # Mark outdated if needed (separate call)
            if needs_outdating:
                server.mark_outdated(
                    fact_id=node_id,
                    reason=f"Outdated as of {fact.get('outdated_at', 'unknown')}",
                    owner_id=owner_id,
                )
                stats["outdated_marked"] += 1
        elif result.get("status") == "memory_duplicate":
            # Handle duplicate detection
            stats["refused_duplicates"] += 1
            print(
                f"  [{key}] Duplicate detected: {result.get('message', 'no message')}"
            )

    # Second pass: create relations (follows_from, supersedes, contradicts)
    print("Creating relations...")
    for fact in corpus:
        key = fact["key"]
        if key not in key_to_node:
            continue

        from_id = key_to_node[key]

        # FOLLOWS_FROM
        if fact.get("follows_from"):
            to_key = fact["follows_from"]
            if to_key in key_to_node:
                server.create_relation(
                    from_id=from_id,
                    to_id=key_to_node[to_key],
                    relation_type="FOLLOWS_FROM",
                    owner_id=owner_id,
                )
                stats["relations_created"] += 1

        # Supersedes (use FOLLOWS_FROM: newer fact follows from older context)
        if fact.get("supersedes"):
            to_key = fact["supersedes"]
            if to_key in key_to_node:
                server.create_relation(
                    from_id=from_id,
                    to_id=key_to_node[to_key],
                    relation_type="FOLLOWS_FROM",
                    owner_id=owner_id,
                )
                stats["relations_created"] += 1

        # CONTRADICTS
        if fact.get("contradicts"):
            to_key = fact["contradicts"]
            if to_key in key_to_node:
                server.create_relation(
                    from_id=from_id,
                    to_id=key_to_node[to_key],
                    relation_type="CONTRADICTS",
                    owner_id=owner_id,
                )
                stats["relations_created"] += 1

    print(f"Seeded: {stats['written']} facts, {stats['relations_created']} relations")
    print(f"Refused duplicates: {stats['refused_duplicates']}")
    print(f"Marked outdated: {stats['outdated_marked']}\n")

    return key_to_node, stats


def run_query(
    server: GraphMemoryMCP, query: Dict, owner_id: str, key_to_node: Dict
) -> Dict:
    """Run a single query and return results."""
    qid = query["id"]
    text = query["text"]
    category = query.get("category", "unknown")
    compact = query.get("compact", False)

    result = {"query_id": qid, "category": category, "metrics": {}}

    # Determine query type
    if category == "multihop":
        # Use get_trace or get_context with depth
        # For now, use search and check if expected keys are present
        search_result = server.search(
            query=text,
            owner_id=owner_id,
            limit=10,
            include_outdated=False,
            compact=compact,
        )
        results_list = search_result.get("results", [])
        result_keys = [
            node["metadata"].get("key", "")
            for node in results_list
            if "metadata" in node and "key" in node["metadata"]
        ]

    elif category == "compact":
        # Compact search with token budget
        search_result = server.search(
            query=text, owner_id=owner_id, limit=20, compact=True
        )
        results_list = search_result.get("results", [])
        result_keys = [
            node["metadata"].get("key", "")
            for node in results_list
            if "metadata" in node and "key" in node["metadata"]
        ]

        # Measure tokens
        snippets_text = " ".join(
            node.get("text", "") or node.get("snippet", "") for node in results_list
        )
        token_count = len(snippets_text.split())  # Approximation
        result["token_count"] = token_count

    else:
        # Standard search
        search_result = server.search(
            query=text,
            owner_id=owner_id,
            limit=10,
            include_outdated=False,
            compact=compact,
        )
        results_list = search_result.get("results", [])
        result_keys = [
            node["metadata"].get("key", "")
            for node in results_list
            if "metadata" in node and "key" in node["metadata"]
        ]

        # Check for contradictions
        contradiction_pairs = search_result.get("contradiction_pairs", [])
        result["contradiction_found"] = len(contradiction_pairs) > 0

    result["result_keys"] = result_keys[:5]  # Top-5 for display
    result["result_count"] = len(result_keys)

    # Evaluate
    expect_keys = set(query.get("expect_keys", []))
    forbid_keys = set(query.get("forbid_keys", []))
    result_set = set(result_keys)

    correct_in_result = expect_keys & result_set
    recall_at_k = len(correct_in_result) / len(expect_keys) if expect_keys else 0.0

    stale_present = forbid_keys & result_set
    stale_rate = len(stale_present) / len(result_set) if result_set else 0.0

    result["metrics"] = {
        "recall_at_k": recall_at_k,
        "stale_rate": stale_rate,
        "correct_count": len(correct_in_result),
        "expected_count": len(expect_keys),
        "stale_count": len(stale_present),
    }

    return result


def main():
    """Run graph memory benchmark."""
    script_dir = Path(__file__).parent
    corpus_path = script_dir / "corpus.yaml"
    queries_path = script_dir / "queries.yaml"

    print("Loading corpus and queries...")
    corpus = load_corpus(corpus_path)
    queries = load_queries(queries_path)
    print(f"Loaded {len(corpus)} facts, {len(queries)} queries\n")

    # Initialize server
    print("Connecting to graph backend...")
    try:
        config = load_mcp_server_config()
        server = GraphMemoryMCP(config)

        if not server._db_connected:
            print("ERROR: Could not connect to graph backend.")
            print("Make sure FalkorDB is running: docker compose up -d")
            sys.exit(1)

        # Ensure vector indexes
        server.ensure_vector_indexes()

    except Exception as e:
        print(f"ERROR: Failed to initialize server: {e}")
        print(
            "Make sure a backend is running (ArcadeDB by default via env.example, or FalkorDB) and .env is configured."
        )
        sys.exit(1)

    # Create isolated owner for this benchmark run
    owner_id = f"benchmark_{uuid.uuid4().hex[:8]}"
    print(f"Using isolated owner_id: {owner_id}\n")

    # Seed corpus
    key_to_node, seed_stats = seed_corpus(server, corpus, owner_id)

    # Run queries
    results = {"graph_memory": [], "seed_stats": seed_stats}

    print("\n=== Running queries ===")
    for query in queries:
        qid = query["id"]
        text = query["text"]
        category = query.get("category", "unknown")

        # Skip fairness cases (grep-specific)
        if "fairness" in category:
            continue

        print(f"\n{qid} ({category}): {text}")
        query_result = run_query(server, query, owner_id, key_to_node)
        results["graph_memory"].append(query_result)

        metrics = query_result["metrics"]
        print(
            f"  recall@k={metrics['recall_at_k']:.2f}, stale={metrics['stale_rate']:.2f}"
        )

        if "contradiction_found" in query_result:
            print(f"  contradictions_found={query_result['contradiction_found']}")

        if "token_count" in query_result:
            print(f"  tokens={query_result['token_count']}")

    # Write results
    output_path = script_dir / "results_graph.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n\nResults written to {output_path}")

    # Summary statistics
    if results["graph_memory"]:
        avg_recall = sum(
            r["metrics"]["recall_at_k"] for r in results["graph_memory"]
        ) / len(results["graph_memory"])
        avg_stale = sum(
            r["metrics"]["stale_rate"] for r in results["graph_memory"]
        ) / len(results["graph_memory"])
        print(f"\nGraph Memory average: recall={avg_recall:.2f}, stale={avg_stale:.2f}")
        print(f"Duplicates refused: {seed_stats['refused_duplicates']}")


if __name__ == "__main__":
    main()
