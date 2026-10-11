# Graph Memory MCP Demo

Demo screencast showing key features: decision changes, near-duplicate rejection, and clean recall across sessions.

## Files

- **demo.gif** (641KB) - Optimized demo for README first screen
- **demo_full.gif** (641KB) - Same full demo  
- **demo_recording.cast** - asciinema recording source
- **demo_client.py** - Python script that generates the demo (simulates MCP client interactions)

## Recording

The demo shows realistic MCP tool calls and responses demonstrating:

1. **Session 1: Decision change**
   - Store initial fact: "We store the graph in Postgres"
   - Decision changes: mark_outdated, create new fact, CONTRADICTS relation
   - Near-duplicate rejected: "Our graph lives in ArcadeDB" refused (similarity 0.94)

2. **Session 2: Clean recall**
   - get_brief + search (compact=true)
   - Only current fact returned (ArcadeDB)
   - Outdated Postgres fact hidden by default

## Re-recording

To recreate the demo:

```bash
# Record
cd assets/demo
asciinema rec --overwrite demo_recording.cast --command "python3 demo_client.py"

# Convert to GIF (high quality, optimized)
agg --theme monokai --font-size 18 --line-height 1.4 --cols 100 --rows 30 demo_recording.cast demo.gif
```

## Tool

- **asciinema** 2.4.0 - Terminal recorder
- **agg** 1.4.3 - asciinema GIF generator (Rust-based, high quality)
