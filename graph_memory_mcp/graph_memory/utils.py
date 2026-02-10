"""Utility functions for MCP Graph Memory."""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from graph_memory_mcp.config import MCPServerConfig

logger = logging.getLogger(__name__)


def normalize_owner_id(owner_id: Optional[str]) -> str:
    """Normalize owner_id to a valid string."""
    value = (owner_id or MCPServerConfig.default_owner_id).strip()
    return value or MCPServerConfig.default_owner_id


def escape_value(value: Optional[str]) -> str:
    """Escape string values for safe use in Cypher queries."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        val_str = value.decode("utf-8", errors="replace")
    elif not isinstance(value, str):
        val_str = str(value)
    else:
        val_str = value
    return val_str.replace("\\", "\\\\").replace("'", "\\'")


def ensure_text(value: Any) -> Optional[str]:
    """Convert value to text string (handles bytes, str, None)."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value)


def load_json(value: Any, default: Any = None) -> Any:
    """Load JSON from string/bytes."""
    if value is None:
        return default
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def dump_json(value: Any, fallback: str = "{}") -> str:
    """Dump value to JSON string."""
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return fallback


def format_vecf32(embedding: List[float]) -> str:
    """Format embedding as vecf32() for FalkorDB vector index."""
    if not embedding:
        return "vecf32([])"
    values = ", ".join(str(float(v)) for v in embedding)
    return f"vecf32([{values}])"


def parse_embedding_value(embedding: Any) -> List[float]:
    """Parse embedding from various formats."""
    if embedding is None:
        return []
    if isinstance(embedding, list):
        return [float(x) for x in embedding]
    if isinstance(embedding, bytes):
        try:
            import struct

            count = len(embedding) // 4
            return list(struct.unpack(f"{count}f", embedding))
        except Exception:
            return []
    return []


def normalize_unix_ms(value: Optional[int | float]) -> Optional[int]:
    """Normalize timestamp to Unix milliseconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def normalize_entity_name(value: str) -> str:
    """Normalize entity name (lowercase, strip whitespace)."""
    if not value:
        return ""
    return value.strip().lower()


def normalize_predicate_type(predicate: str) -> str:
    """Normalize predicate into an edge type (SNAKE_CASE, A-Z0-9_ only)."""
    if not predicate:
        return "RELATED_TO"
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", predicate.lower()).strip("_")
    if not cleaned:
        cleaned = "RELATED_TO"
    return cleaned.upper()


def success_response(**kwargs: Any) -> dict:
    """Create success response."""
    return {"success": True, **kwargs}


def error_response(error: Any, code: str = "error") -> dict:
    """Create error response."""
    error_msg = str(error) if not isinstance(error, str) else error
    return {"success": False, "error": error_msg, "code": code}


def _validate_text_length(value: str, max_length: int) -> Optional[str]:
    """Validate text length."""
    if len(value) > max_length:
        return f"Text too long (max {max_length} chars)"
    return None


def _validate_metadata_size(value: dict, max_size: int) -> Optional[str]:
    """Validate metadata size."""
    if not value:
        return None
    size = len(dump_json(value))
    if size > max_size:
        return f"Metadata too large (max {max_size} bytes)"
    return None


def _validate_ttl_range(value: float, min_val: float, max_val: float) -> Optional[str]:
    """Validate TTL range."""
    if value <= min_val or value > max_val:
        return f"TTL must be between {min_val} and {max_val} days"
    return None


def _validate_owner_id_format(value: str) -> Optional[str]:
    """Validate owner_id format (alphanumeric + -_@)."""
    if not re.match(r"^[a-zA-Z0-9_@-]+$", value):
        return "Invalid owner_id format (use alphanumeric, -, _, @)"
    return None


def _validate_relation_type_format(value: str) -> Optional[str]:
    """Validate relation_type format (alphanumeric + _)."""
    if not re.match(r"^[a-zA-Z0-9_]+$", value):
        return "Invalid relation_type format (use alphanumeric, _)"
    return None


# Validation registry
VALIDATORS = {
    "text": lambda v, cfg: _validate_text_length(v, cfg.max_text_length),
    "metadata": lambda v, cfg: _validate_metadata_size(v, cfg.max_metadata_size),
    "ttl_days": lambda v, cfg: _validate_ttl_range(
        v, cfg.min_ttl_days, cfg.max_ttl_days
    ),
    "owner_id": lambda v, cfg: _validate_owner_id_format(v),
    "relation_type": lambda v, cfg: _validate_relation_type_format(v),
    "node_type": lambda v, cfg: (
        None if v in {"Fact", "Entity"} else "node_type must be 'Fact' or 'Entity'"
    ),
    "status": lambda v, cfg: (
        None
        if v in {"active", "outdated", "archived"}
        else "status must be one of: active, archived, outdated"
    ),
}


def validate_inputs(inputs: dict[str, Any], config: Any) -> Optional[str]:
    """
    Validate multiple inputs at once.

    Args:
        inputs: Dictionary of field_name -> value (use locals() in handlers)
        config: Config object with validation limits

    Returns:
        Error message if validation fails, None otherwise
    """
    for field, value in inputs.items():
        if value is not None and (validator := VALIDATORS.get(field)):
            if error := validator(value, config):
                return error
    return None


def mcp_handler(func):
    """Decorator for standard error handling in MCP handlers."""
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            logger.error(f"Failed to execute {func.__name__}: {exc}")
            return error_response(exc, code="memory_service_error")

    return wrapper


def execute_query(db: Any, query: str, params: Optional[Dict] = None) -> Any:
    """Execute query and validate result."""
    result = db.graph.query(query, params=params)

    if not result or not hasattr(result, "result_set") or not result.result_set:
        return None

    return result
