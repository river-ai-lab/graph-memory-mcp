"""Headless Explorer smoke. CI skips it: marker ``browser`` and EXPLORER_BROWSER."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest

from graph_memory_mcp.graph_memory.mcp_handlers_nodes import create_node

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "tests" / "explorer_browser_smoke.mjs"


@pytest.mark.skipif(
    os.environ.get("EXPLORER_BROWSER") != "1",
    reason="set EXPLORER_BROWSER=1 to run the headless Playwright smoke",
)
def test_explorer_browser_smoke(memory_backend):
    if memory_backend.config.graph_backend != "falkordb":
        pytest.skip("browser smoke targets the Falkor explorer")
    owner = f"pytest_ui_{uuid.uuid4().hex[:8]}"
    long_token = "X" * 180
    created = create_node(
        memory_backend.db,
        memory_backend.config,
        text=f"Привет, это проверка длинного текста. {long_token} конец.",
        owner_id=owner,
        auto_link=False,
        check_duplicates=False,
        metadata={"note": "юникод"},
    )
    assert created.get("success") is True, created
    env = os.environ.copy()
    env["EXPLORER_UNICODE_OWNER"] = owner
    env.setdefault("NODE_PATH", "/tmp/node_modules")
    env.setdefault("EXPLORER_URL", "http://127.0.0.1:8088")
    env.setdefault("EXPLORER_AUTH_URL", "http://127.0.0.1:8091")
    proc = subprocess.run(
        ["node", str(SMOKE)],
        cwd="/tmp",
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
