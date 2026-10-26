"""Policy artifacts are generated from docs/memory_policies_for_LLM.md."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _gen():
    spec = importlib.util.spec_from_file_location(
        "gen_policy", ROOT / "scripts" / "gen_policy.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_policy_artifacts_are_up_to_date() -> None:
    stale = _gen().stale()
    assert not stale, f"run scripts/gen_policy.py: {stale}"


def test_every_rule_reaches_a_target() -> None:
    gen = _gen()
    rules = gen.parse_rules(gen.SOURCE.read_text(encoding="utf-8"))
    assert len({r["id"] for r in rules}) == len(rules) >= 10
    text = gen.CHEATSHEET.read_text(encoding="utf-8")
    assert all(r["summary"] in text for r in rules)
