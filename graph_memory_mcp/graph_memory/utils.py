"""Utility functions for MCP Graph Memory."""

import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_OWNER_ID_RE = re.compile(r"^[a-zA-Z0-9_@-]+$")
_NODE_ID_RE = re.compile(r"^[a-zA-Z0-9-]{1,64}$")


def new_uid() -> str:
    """Generate a stable public node id (opaque, never reused)."""
    return uuid.uuid4().hex


def normalize_owner_id(owner_id: Optional[str]) -> str:
    """Normalize and validate owner_id; raises ValueError on invalid format."""
    default_owner_id = "default"
    if owner_id is None:
        return default_owner_id
    if isinstance(owner_id, bytes):
        value = owner_id.decode("utf-8", errors="replace").strip()
    elif isinstance(owner_id, str):
        value = owner_id.strip()
    else:
        value = str(owner_id).strip()
    value = value or default_owner_id
    if not _OWNER_ID_RE.match(value):
        raise ValueError("Invalid owner_id format (use alphanumeric, -, _, @)")
    return value


def require_node_id(value: Any, field: str = "node_id") -> str:
    """Validate a public node id; raises ValueError on invalid format."""
    text = ensure_text(value)
    if not text or not _NODE_ID_RE.match(text):
        raise ValueError(f"Invalid {field} format")
    return text


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


def _validate_source_shape(value: Any) -> Optional[str]:
    """Validate source payload used for provenance/upsert."""
    if not isinstance(value, dict):
        return "source must be an object"

    for field in ("ref", "type", "uri", "content_hash"):
        field_value = value.get(field)
        if field_value is None:
            continue
        if ensure_text(field_value) is None:
            return f"source.{field} must be a string"

    updated_at = value.get("updated_at")
    if updated_at is not None and normalize_unix_ms(updated_at) is None:
        return "source.updated_at must be Unix milliseconds"

    version = value.get("version")
    if version is not None:
        if not isinstance(version, int):
            return "source.version must be an integer"
        if version < 1:
            return "source.version must be >= 1"

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
    "source": lambda v, cfg: _validate_source_shape(v),
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
    """Decorator: standard error handling + Prometheus latency/status metrics."""
    import functools
    import time as _time

    from graph_memory_mcp.metrics import observe_handler

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        started = _time.perf_counter()
        try:
            result = func(*args, **kwargs)
        except ValueError as exc:
            result = error_response(exc, code="memory_validation_error")
        except Exception as exc:
            logger.error(f"Failed to execute {func.__name__}: {exc}")
            result = error_response(exc, code="memory_service_error")
        observe_handler(
            func.__name__,
            _time.perf_counter() - started,
            bool(result.get("success", True)) if isinstance(result, dict) else True,
        )
        return result

    return wrapper


def execute_query(db: Any, query: str, params: Optional[Dict] = None) -> Any:
    """Execute query (routed to the owner graph via params) and validate result."""
    result = db.query(query, params=params)

    if not result or not hasattr(result, "result_set") or not result.result_set:
        return None

    return result


def touch_nodes(db: Any, node_ids: List[str], owner_id: str) -> None:
    """Record recall usage: bump access_count / last_accessed_at (best-effort)."""
    if not node_ids:
        return
    try:
        db.query(
            """
            MATCH (n)
            WHERE n.uid IN $node_ids AND n.owner_id = $owner_id
            SET n.access_count = coalesce(n.access_count, 0) + 1,
                n.last_accessed_at = timestamp()
            """,
            params={
                "node_ids": [str(node_id) for node_id in node_ids],
                "owner_id": owner_id,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("touch_nodes failed: %s", exc)
