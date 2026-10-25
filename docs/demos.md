# Other demos

Start the server with `uv run graph-memory-mcp --host 127.0.0.1 --port 8000`. The three clips use owner `demo_team` after `uv run python assets/demo/generate_demo.py --scenario seed` ([generate_demo.py](../assets/demo/generate_demo.py)). The README GIF is separate.

<table>
  <tr>
    <td align="center" width="260">
      <a href="../assets/demo/demo_contradictions.gif"><img src="../assets/demo/demo_contradictions.gif" width="260" alt="Search returns both rate-limit facts and the CONTRADICTS edge the seed script created"></a><br>
      Search returns both rate-limit facts and the CONTRADICTS edge the seed script created.
    </td>
    <td align="center" width="260">
      <a href="../assets/demo/demo_lifecycle.gif"><img src="../assets/demo/demo_lifecycle.gif" width="260" alt="Search returns Component Y, leaves outdated Component X out, and the server refuses a near-duplicate"></a><br>
      Search returns Component Y and leaves outdated Component X out, then the server refuses a near-duplicate of Component Y.
    </td>
    <td align="center" width="260">
      <a href="../assets/demo/demo_retrieval.gif"><img src="../assets/demo/demo_retrieval.gif" width="260" alt="Search returns the current gateway decision, then get_context shows the API Gateway Service"></a><br>
      Search returns the current gateway decision, then get_context shows the API Gateway Service linked to it.
    </td>
  </tr>
</table>

## [demo_dense.gif](../assets/demo/demo_dense.gif)

The script runs the gateway story in one session: links, a search miss then a write-back, `mark_outdated`, `FOLLOWS_FROM`, a `CONTRADICTS` edge it creates between two rate limits, and a near-duplicate the server refuses.

```bash
uv run python assets/demo/generate_demo.py --scenario dense
```

The scenario clears owner `demo_team` and builds the story as it runs. Script: [assets/demo/generate_demo.py](../assets/demo/generate_demo.py).

## [demo_cli.gif](../assets/demo/demo_cli.gif)

The Inspector CLI saves "API gateway uses Component Y", then search returns that fact.

```bash
curl -s -X DELETE http://127.0.0.1:8000/admin/owners/default
./assets/demo/cli_demo.sh
```

The delete clears owner `default` and is not in the GIF. Script: [assets/demo/cli_demo.sh](../assets/demo/cli_demo.sh).
