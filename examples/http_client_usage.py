"""
HTTP Client Example (Pure Python)
=================================

This example demonstrates how to act as an MCP client connecting to the
Graph Memory server over Streamable HTTP.

Architecture:
  [Your Script] -> (Streamable HTTP) -> [Graph Memory Server]

Prerequisites:
  1. Start the server (in a separate terminal):
     $ python examples/run_server.py

  2. Run this client:
     $ python examples/http_client_usage.py

Dependencies:
  pip install mcp
"""

import asyncio

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

SERVER_URL = "http://127.0.0.1:8000/mcp"


def dump_tool_result(res):
    if not getattr(res, "content", None):
        print("   (no content)")
        return
    for i, block in enumerate(res.content):
        t = getattr(block, "type", None)
        if t == "text":
            print(f"   [{i}] text:", block.text)
        elif t == "json":
            print(f"   [{i}] json:", block.json)
        else:
            print(f"   [{i}] block:", block)


async def main():
    async with streamable_http_client(SERVER_URL) as (read, write, get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Connected. Session ID:", get_session_id())

            tools = await session.list_tools()
            print("Tools:", [t.name for t in tools.tools])

            res = await session.call_tool("ensure_vector_indexes", arguments={})
            dump_tool_result(res)

            res = await session.call_tool(
                "create_node",
                arguments={
                    "text": "MCP allows AI models to connect to external data.",
                    "node_type": "Fact",
                    "owner_id": "http_client_demo",
                },
            )
            dump_tool_result(res)

            res = await session.call_tool(
                "search",
                arguments={
                    "query": "MCP allows AI models to connect to external data.",
                    "owner_id": "http_client_demo",
                    "similarity_threshold": 0.3,
                },
            )
            dump_tool_result(res)


if __name__ == "__main__":
    asyncio.run(main())
