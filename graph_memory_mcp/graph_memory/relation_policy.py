"""Relation type allowlist and enforcement for graph writes."""

from __future__ import annotations

from typing import Any, Optional

AUTO_LINK_RELATION = "MENTIONS"

# Default allowlist: agent-facing + system + demo/triplet predicates.
DEFAULT_RELATION_ALLOWED_TYPES = (
    "RELATED_TO",
    "MENTIONS",
    "SUMMARIZES",
    "FOLLOWS_FROM",
    "CONTRADICTS",
    "EXTRACTED_FROM",
    "SIMILAR_TO",
    "NEXT_STEP",
    "EXPOSES",
    "CROSS_REF",
    "RUNS_ON",
    "USES",
    "SERVED_BY",
)

# Created by server internals; always permitted even if omitted from allowlist.
SYSTEM_RELATION_TYPES = frozenset({"EXTRACTED_FROM"})

VALID_ENFORCE_MODES = frozenset({"off", "warn", "enforce"})

_DEFAULT_POLICY_CFG: Any | None = None


def effective_relation_config(config: Any | None) -> Any:
    """Use server config from .env when handlers are called without explicit config."""
    global _DEFAULT_POLICY_CFG
    if config is not None:
        return config
    if _DEFAULT_POLICY_CFG is None:
        from graph_memory_mcp.config import load_mcp_server_config

        _DEFAULT_POLICY_CFG = load_mcp_server_config()
    return _DEFAULT_POLICY_CFG


def parse_allowed_relation_types(raw: str | None) -> frozenset[str]:
    if not raw or not str(raw).strip():
        return frozenset(DEFAULT_RELATION_ALLOWED_TYPES)
    parts = frozenset(p.strip().upper() for p in str(raw).split(",") if p.strip())
    if not parts:
        return frozenset(DEFAULT_RELATION_ALLOWED_TYPES)
    return parts


def relation_policy_mode(config: Any | None) -> str:
    cfg = effective_relation_config(config)
    mode = str(getattr(cfg, "relation_policy_enforce", "warn")).strip().lower()
    return mode if mode in VALID_ENFORCE_MODES else "warn"


def allowed_relation_types(config: Any | None) -> frozenset[str]:
    cfg = effective_relation_config(config)
    raw = getattr(cfg, "relation_allowed_types", None)
    if raw is None:
        return frozenset(DEFAULT_RELATION_ALLOWED_TYPES)
    return parse_allowed_relation_types(str(raw))


def evaluate_relation_policy(
    config: Any | None,
    relation_type: str,
    *,
    internal: bool = False,
) -> tuple[bool, Optional[str], Optional[str]]:
    """
    Check relation_type against configured allowlist.

    Returns:
        proceed: whether the write should continue
        warning: set when mode=warn and type is disallowed
        error: set when mode=enforce and type is disallowed
    """
    rel_type = relation_type.upper()
    cfg = effective_relation_config(config)
    mode = relation_policy_mode(cfg)

    if mode == "off":
        return True, None, None

    if internal and rel_type in SYSTEM_RELATION_TYPES:
        return True, None, None

    if rel_type in allowed_relation_types(cfg):
        return True, None, None

    msg = (
        f"Relation type '{rel_type}' is not in RELATION_ALLOWED_TYPES. "
        f"Allowed: {', '.join(sorted(allowed_relation_types(cfg)))}"
    )
    if mode == "enforce":
        return False, None, msg
    return True, msg, None
