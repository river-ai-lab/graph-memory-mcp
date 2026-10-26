"""Files the wheel must ship for a server installed from PyPI."""

from pathlib import Path


def test_packaged_agent_policies_match_docs() -> None:
    root = Path(__file__).resolve().parents[1]
    docs = root / "docs" / "memory_policies_for_LLM.md"
    packaged = root / "graph_memory_mcp" / "resources" / "memory_policies_for_LLM.md"
    assert packaged.read_bytes() == docs.read_bytes()
