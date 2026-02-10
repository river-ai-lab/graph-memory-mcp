# Examples

This directory contains usage patterns for **graph-memory-mcp** in three integration modes:

- Direct Python integration
- MCP over HTTP/SSE
- External MCP-client configuration

**Prerequisite:** FalkorDB must be running before any example.

```bash
docker run -p 6379:6379 -it --rm falkordb/falkordb
```

Install the package in editable mode:

```bash
pip install -e .
```

---

## Integration Modes

| Mode | When to use | Server process | Transport | Example |
|------|-------------|---------------|----------|--------|
| **Direct Python** | LangGraph / RAG / pipelines inside Python | No | In-process calls | `embedded_python_usage.py` |
| **HTTP MCP Server** | Agents connect to memory service | Yes | HTTP + SSE | `run_server.py` |
| **HTTP MCP Client** | Testing / agent integration | Requires server | HTTP + SSE | `http_client_usage.py` |
| **MCP Client Config** | Cursor / Claude / n8n | External server | MCP runtime | `mcp_servers_config.json` |

---

## 1. Direct Python Integration (Recommended for Python apps)

Runs Graph Memory as a library, not a service. No HTTP, no MCP client — tools are called directly.

**Run example:**
```bash
python examples/embedded_python_usage.py
```

**Concept:**
```mermaid
graph TD
    App[Python App] --> GM[GraphMemoryMCP]
    GM --> DB[(FalkorDB)]
```

**Example call:**
```python
server = GraphMemoryMCP(config)
# Tools are available directly on the server instance
await server.call_tool("create_node", arguments={"text": "Example fact"})
```

**Best for:**
- LangGraph agents
- RAG pipelines
- Batch ingestion
- Tests

---

## 2. HTTP MCP Server

Runs Graph Memory as a standalone MCP service.

**Start server:**
```bash
python examples/run_server.py
```

**Server endpoints:**
- `http://127.0.0.1:8000/mcp/sse`
- `http://127.0.0.1:8000/mcp/messages`

**Concept:**
```mermaid
graph TD
    Agent[Agent / Client] -- HTTP/SSE --> MCP
    MCP[MCP Server] --> GM[GraphMemoryMCP]
    GM --> DB[(FalkorDB)]
```

**Best for:**
- Multi-agent systems
- Remote memory service
- Container deployment
- Service isolation

---

## 3. HTTP MCP Client Example

Demonstrates how to connect to the MCP server using the Python MCP SDK.

**1. Start server first:**
```bash
python examples/run_server.py
```

**2. Then run client:**
```bash
python examples/http_client_usage.py
```

**Example tool call:**
```python
async with ClientSession(read, write) as session:
    await session.call_tool("create_node", arguments={...})
```

---

## 4. MCP Client Configuration

`mcp_servers_config.json` shows how to register Graph Memory in:
- Cursor
- Claude Desktop
- n8n
- Other MCP runtimes

**Example configuration:**
```json
{
  "mcpServers": {
    "graph-memory-mcp": {
      "command": "uv",
      "args": ["run", "graph-memory-mcp"]
    }
  }
}
```

---

## 5. CLI Usage

The server can be run directly using the CLI:

```bash
# Default (port 8000)
graph-memory-mcp

# Custom host/port
graph-memory-mcp --host 0.0.0.0 --port 8100
```

---

## Summary

There are two primary ways to use Graph Memory:
- **As a Python library**: Simplest and fastest. Preferred unless you need process isolation or remote access.
- **As an MCP service**: For agents and distributed systems.
