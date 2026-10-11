#!/usr/bin/env python3
"""
Demo client for Graph Memory MCP - shows realistic tool calls and responses
This simulates an MCP client interaction to demonstrate the key features
"""
import time
import json
from typing import Any, Dict

class Colors:
    """ANSI color codes for terminal output"""
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    
    # Foreground colors
    USER = '\033[38;5;75m'      # Light blue
    AGENT = '\033[38;5;141m'    # Purple
    TOOL = '\033[38;5;220m'     # Yellow
    SUCCESS = '\033[38;5;120m'  # Green
    WARNING = '\033[38;5;208m'  # Orange
    CAPTION = '\033[38;5;245m'  # Gray

def print_caption(text: str):
    """Print a caption/scene marker"""
    print(f"\n{Colors.CAPTION}{Colors.BOLD}═══ {text} ═══{Colors.RESET}\n")
    time.sleep(1.5)

def print_user(text: str):
    """Print a user message"""
    print(f"{Colors.USER}{Colors.BOLD}User:{Colors.RESET} {text}")
    time.sleep(1)

def print_agent_thinking():
    """Print agent thinking indicator"""
    print(f"{Colors.AGENT}Agent: {Colors.DIM}thinking...{Colors.RESET}")
    time.sleep(0.5)

def print_tool_call(tool_name: str, key_args: Dict[str, Any]):
    """Print a tool call"""
    args_str = ", ".join(f"{k}={repr(v)[:50]}" for k, v in key_args.items())
    print(f"{Colors.TOOL}→ {tool_name}({Colors.DIM}{args_str}{Colors.TOOL}){Colors.RESET}")
    time.sleep(0.8)

def print_response(summary: str, warning: bool = False):
    """Print a compact response summary"""
    color = Colors.WARNING if warning else Colors.SUCCESS
    print(f"{color}  ✓ {summary}{Colors.RESET}")
    time.sleep(1)

def demo_session_1():
    """Session 1: Initial fact, then decision change"""
    print_caption("Session 1: Team makes a decision, then changes it")
    
    # Step 1: Store initial decision
    print_user("Remember: we store the graph in Postgres.")
    print_agent_thinking()
    print_tool_call("create_node", {
        "owner_id": "team_platform",
        "node_type": "Fact",
        "text": "We store the graph in Postgres",
    })
    time.sleep(0.5)
    print_response("Created fact node (id: fact_postgres_001)")
    
    time.sleep(1.5)
    
    # Step 2: Decision changes
    print_user("We changed our mind: moving to ArcadeDB. Postgres is no longer used.")
    print_agent_thinking()
    
    # First: mark old fact outdated
    print_tool_call("mark_outdated", {
        "owner_id": "team_platform",
        "node_id": "fact_postgres_001",
        "reason": "Decision changed: migrating to ArcadeDB"
    })
    time.sleep(0.5)
    print_response("Marked outdated (not deleted; stays in history)")
    
    time.sleep(0.8)
    
    # Second: create new fact
    print_tool_call("create_node", {
        "owner_id": "team_platform",
        "node_type": "Fact",
        "text": "We store the graph in ArcadeDB",
    })
    time.sleep(0.5)
    print_response("Created fact node (id: fact_arcadedb_001)")
    
    time.sleep(0.8)
    
    # Third: link contradiction
    print_tool_call("create_relation", {
        "owner_id": "team_platform",
        "from_id": "fact_arcadedb_001",
        "to_id": "fact_postgres_001",
        "relation_type": "CONTRADICTS"
    })
    time.sleep(0.5)
    print_response("Created CONTRADICTS relation")
    
    time.sleep(1.5)
    
    # Step 3: Attempted duplicate
    print_user("Note that our graph lives in ArcadeDB.")
    print_agent_thinking()
    print_tool_call("create_node", {
        "owner_id": "team_platform",
        "node_type": "Fact",
        "text": "Our graph lives in ArcadeDB",
    })
    time.sleep(0.5)
    print_response(
        "⚠ Refused: near-duplicate of fact_arcadedb_001 (similarity: 0.94)", 
        warning=True
    )
    print(f"{Colors.DIM}  → No duplicates piling up{Colors.RESET}")

def demo_session_2():
    """Session 2: Fresh context, queries current state"""
    print_caption("Next day — New session, empty context")
    
    # Agent starts fresh - calls get_brief
    print_user("Where do we store the graph?")
    print_agent_thinking()
    print_tool_call("get_brief", {
        "owner_id": "team_platform"
    })
    time.sleep(0.5)
    print_response("Retrieved: 1 active recent fact (Postgres fact omitted: outdated)")
    
    time.sleep(0.8)
    
    # Then searches with compact=true
    print_tool_call("search", {
        "owner_id": "team_platform",
        "query": "where do we store the graph",
        "compact": True,
        "limit": 3
    })
    time.sleep(0.8)
    
    # Show compact result
    print(f"\n{Colors.SUCCESS}Search results (compact, under token budget):{Colors.RESET}")
    print(f"{Colors.DIM}  1. We store the graph in ArcadeDB  [score: 0.89]{Colors.RESET}")
    print(f"{Colors.DIM}     snippet: \"...graph in ArcadeDB\" (full text 6 tokens)")
    print(f"{Colors.DIM}     status: active{Colors.RESET}")
    print(f"{Colors.DIM}  ")
    print(f"{Colors.DIM}  Outdated/TTL facts hidden by default.{Colors.RESET}")
    print(f"{Colors.DIM}  Old Postgres decision stays in history (mark_outdated), not deleted.{Colors.RESET}")
    time.sleep(2)
    
    # Agent has the right answer
    print(f"\n{Colors.AGENT}Agent:{Colors.RESET} Based on the current decision, we store the graph in ArcadeDB.")

def demo_final_card():
    """Show final positioning card"""
    print_caption("Graph Memory MCP")
    print()
    print(f"{Colors.BOLD}Memory for your team and its agents that doesn't turn into a dump{Colors.RESET}")
    print()
    print(f"{Colors.DIM}  • The text in the graph is what the agent wrote")
    print(f"  • Near-duplicates refused on write")
    print(f"  • mark_outdated + CONTRADICTS keep history clean")
    print(f"  • One owner_id = one physically isolated graph")
    print(f"  • No LLM calls on the server (free, fast, offline){Colors.RESET}")
    print()
    print(f"{Colors.USER}Install:{Colors.RESET}")
    print(f"  docker compose up -d && uv run graph-memory-mcp")
    print()
    print(f"{Colors.DIM}  https://github.com/river-ai-lab/graph-memory-mcp{Colors.RESET}")
    print()
    time.sleep(3)

def main():
    """Run the full demo"""
    print("\033[2J\033[H")  # Clear screen
    time.sleep(0.5)
    
    demo_session_1()
    time.sleep(2)
    
    demo_session_2()
    time.sleep(2)
    
    demo_final_card()
    time.sleep(1)

if __name__ == "__main__":
    main()
