"""
Direct Python Integration (No HTTP)
===================================

This example demonstrates how to integrate `GraphMemoryMCP` directly into your
Python application (e.g., LangChain, LangGraph, RAG pipeline) without running
a separate HTTP server.

You can import the server class and call the tool methods directly as Python functions.

Prerequisites:
- `graph-memory-mcp` installed
- FalkorDB running
"""

import asyncio
import logging
import uuid
from pprint import pprint

from graph_memory_mcp.config import load_mcp_server_config

# 1. Import the renamed server class
from graph_memory_mcp.server import GraphMemoryMCP

# Configure logging to see what's happening
logging.basicConfig(level=logging.INFO)


async def main():
    print("🚀 Starting Direct Integration Example\n")

    # 2. Load configuration
    # Loads from env vars (FALKORDB_HOST, etc.) or .env file
    config = load_mcp_server_config()

    # 3. Initialize the server directly
    # This establishes DB connection and loads embedding models
    server = GraphMemoryMCP(config)

    # Check if DB is connected
    if not server._db_connected:
        print("❌ Could not connect to FalkorDB. Make sure it's running.")
        return

    # 4. Use tools as Python methods!
    # The server class exposes all tools as methods:
    # server.create_node(...)
    # server.search(...)
    # server.create_relation(...)

    owner_id = f"demo_user_{uuid.uuid4().hex[:6]}"
    print(f"Using owner_id: {owner_id}\n")

    # --- Create a Fact ---
    print("1️⃣  Creating a fact...")
    result = server.create_node(
        text="FastMCP allows running MCP servers directly in Python.",
        node_type="Fact",
        metadata={"source": "integration_example"},
        owner_id=owner_id,
    )
    fact = result.get("node")
    print(f"   Created Fact ID: {fact['node_id']}")
    print(f"   Text: {fact['text']}\n")

    # --- Create an Entity ---
    print("2️⃣  Creating an entity...")
    result = server.create_node(
        text="Python", node_type="Entity", entity_type="Language", owner_id=owner_id
    )
    entity = result.get("node")
    print(f"   Created Entity ID: {entity['node_id']}")
    print(f"   Text: {entity['text']}\n")

    # --- Create a Relation ---
    print("3️⃣  Linking Fact to Entity...")
    rel = server.create_relation(
        from_id=fact["node_id"],
        to_id=entity["node_id"],
        relation_type="MENTIONS",
        owner_id=owner_id,
    )
    print(f"   Created relation: {rel['relation_type']}\n")

    # --- Semantic Search ---
    print("4️⃣  Searching...")
    # This uses the embedding model loaded in memory
    search_res = server.search(
        query="programmatic mcp usage", owner_id=owner_id, limit=2
    )

    print(f"   Found {len(search_res['results'])} results:")
    for item in search_res["results"]:
        print(f"   - [{item['score']:.4f}] {item['text']}")

    # --- Network Graph (Context) ---
    print("\n5️⃣  Getting Context (Subgraph)...")
    context = server.get_context(node_id=fact["node_id"], owner_id=owner_id, depth=1)
    print(f"   Nodes: {len(context['nodes'])}")
    print(f"   Edges: {len(context['edges'])}")

    print("\n✅ Integration successful!")
    print("You can now pass these functions to LangChain 'StructuredTool' or similar.")


if __name__ == "__main__":
    asyncio.run(main())
