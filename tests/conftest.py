"""
Pytest configuration.

This repository is laid out as a *package directory* (the repo root contains
`__init__.py`). To import it as `graph_memory_mcp.*`, Python needs the *parent*
directory of the repo on `sys.path`.
"""

from __future__ import annotations

import sys
from pathlib import Path


def pytest_configure() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    repo_parent = repo_root.parent
    sys.path.insert(0, str(repo_parent))
