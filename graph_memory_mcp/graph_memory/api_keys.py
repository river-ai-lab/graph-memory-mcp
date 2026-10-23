"""API keys for ``OWNER_SCOPE=token``.

A key is a person (``name``) plus the owner graphs they may use (``projects``).
The file stores a sha256 hash; ``keys create`` prints the raw key once.
The single-owner ``owner`` field from earlier token mode is still read:
``owner`` becomes ``projects=[owner]`` and ``name=owner``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from graph_memory_mcp.graph_memory.utils import require_owner_id_format

logger = logging.getLogger(__name__)

_HASH_LEN = 64
# path -> (mtime_ns, size, key rows). Invalidated on write and on mtime/size change.
_rows_cache: dict[str, tuple[int, int, list]] = {}


class TokenModeConfigError(RuntimeError):
    """OWNER_SCOPE=token is missing a token or a readable keys file."""


@dataclass(frozen=True)
class ApiKeyRecord:
    id: str
    name: str
    projects: tuple[str, ...]
    created_at: str
    revoked: bool


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def bearer_value(authorization: str | None) -> str | None:
    """Return the Bearer token, or None when the header is absent or not Bearer."""
    if not authorization:
        return None
    scheme, _, rest = authorization.strip().partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = rest.strip()
    return token or None


def bearer_matches(authorization: str | None, secret: str) -> bool:
    """Constant-time check of an Authorization Bearer value against a secret."""
    presented = bearer_value(authorization)
    if not secret or presented is None:
        return False
    return hmac.compare_digest(presented.encode(), secret.encode())


def validate_token_mode(*, admin_token: str, keys_file: str) -> None:
    """Refuse to serve token mode when /admin would be open or keys are unusable.

    An empty ADMIN_TOKEN leaves /admin open, and those routes take the owner
    from the path. A missing or unreadable keys file would otherwise answer
    every MCP call with 401 and only a log line.
    """
    if not str(admin_token or "").strip():
        raise TokenModeConfigError(
            "OWNER_SCOPE=token requires ADMIN_TOKEN. "
            "/admin takes the owner from the URL path and must not stay open."
        )
    path = Path(keys_file)
    if not path.is_file():
        raise TokenModeConfigError(
            f"OWNER_SCOPE=token requires an API keys file at {path}. "
            "Create a key with: graph-memory-mcp keys create --name <name> "
            "--projects <p1,p2>"
        )
    try:
        _read(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise TokenModeConfigError(
            f"API keys file {path} cannot be read: {exc}"
        ) from exc


def parse_projects(value: str | list[str] | tuple[str, ...]) -> list[str]:
    """Split a comma list or validate a sequence of owner ids."""
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
    else:
        parts = [str(part).strip() for part in value]
    projects = [require_owner_id_format(part) for part in parts if part]
    if not projects:
        raise ValueError("projects must list at least one owner_id")
    return projects


def key_for_bearer(path: str | Path, authorization: str | None) -> ApiKeyRecord | None:
    """Live key for a Bearer token, or None when missing, unknown, or revoked."""
    raw = bearer_value(authorization)
    if raw is None:
        return None
    digest = hash_key(raw)
    try:
        rows = _cached_key_rows(Path(path))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("API keys file %s cannot be read: %s", path, exc)
        return None
    for row in rows:
        if row.get("revoked"):
            continue
        stored = str(row.get("hash") or "")
        if len(stored) != _HASH_LEN:
            continue
        if hmac.compare_digest(stored, digest):
            record = _record(row)
            if record.name and record.projects:
                return record
    return None


def create_key(
    path: str | Path, name: str, projects: str | list[str] | tuple[str, ...]
) -> tuple[ApiKeyRecord, str]:
    """Append a key. Returns the public record and the raw key (shown once)."""
    person = require_owner_id_format(str(name).strip())
    project_ids = parse_projects(projects)
    raw = "gmk_" + secrets.token_urlsafe(32)
    record = {
        "id": _new_id(),
        "hash": hash_key(raw),
        "name": person,
        "projects": project_ids,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "revoked": False,
    }
    file_path = Path(path)
    with _locked(file_path):
        data = _read(file_path)
        ids = {str(row.get("id")) for row in data["keys"]}
        while record["id"] in ids:
            record["id"] = _new_id()
        data["keys"].append(record)
        _write(file_path, data)
    return _record(record), raw


def list_keys(path: str | Path) -> list[ApiKeyRecord]:
    data = _read(Path(path))
    return [_record(row) for row in data["keys"]]


def set_projects(
    path: str | Path, key_id: str, projects: str | list[str] | tuple[str, ...]
) -> ApiKeyRecord | None:
    """Replace the project list for a key. Returns None when the id is missing."""
    project_ids = parse_projects(projects)
    file_path = Path(path)
    with _locked(file_path):
        data = _read(file_path)
        found = None
        for row in data["keys"]:
            if str(row.get("id")) == key_id:
                row.pop("owner", None)
                row["name"] = _normalized_row(row)["name"]
                row["projects"] = project_ids
                found = row
                break
        if found is None:
            return None
        _write(file_path, data)
    return _record(found)


def revoke_key(path: str | Path, key_id: str) -> ApiKeyRecord | None:
    """Mark a key revoked. Returns None when the id is not in the file."""
    file_path = Path(path)
    with _locked(file_path):
        data = _read(file_path)
        found = None
        for row in data["keys"]:
            if str(row.get("id")) == key_id:
                row["revoked"] = True
                found = row
                break
        if found is None:
            return None
        _write(file_path, data)
    return _record(found)


def _new_id() -> str:
    return "k_" + secrets.token_hex(4)


def _normalized_row(row: dict) -> dict:
    """Accept ``{name, projects}`` and the older ``{owner}`` shape."""
    projects = row.get("projects")
    owner = str(row.get("owner") or "").strip()
    if projects is None:
        project_ids = [owner] if owner else []
        name = str(row.get("name") or owner).strip()
    elif isinstance(projects, str):
        project_ids = [part.strip() for part in projects.split(",") if part.strip()]
        name = str(
            row.get("name") or (project_ids[0] if project_ids else owner)
        ).strip()
    else:
        project_ids = [str(part).strip() for part in projects if str(part).strip()]
        name = str(
            row.get("name") or (project_ids[0] if project_ids else owner)
        ).strip()
    return {
        "id": str(row.get("id") or ""),
        "hash": str(row.get("hash") or ""),
        "name": name,
        "projects": project_ids,
        "created_at": str(row.get("created_at") or ""),
        "revoked": bool(row.get("revoked")),
    }


def _record(row: dict) -> ApiKeyRecord:
    norm = _normalized_row(row)
    return ApiKeyRecord(
        id=norm["id"],
        name=norm["name"],
        projects=tuple(norm["projects"]),
        created_at=norm["created_at"],
        revoked=norm["revoked"],
    )


def _cached_key_rows(path: Path) -> list:
    if not path.is_file():
        _invalidate_cache(path)
        raise FileNotFoundError(path)
    stamp = _file_stamp(path)
    key = _cache_key(path)
    cached = _rows_cache.get(key)
    if cached is not None and cached[0] == stamp[0] and cached[1] == stamp[1]:
        return cached[2]
    rows = _read(path)["keys"]
    _rows_cache[key] = (*_file_stamp(path), rows)
    return rows


def _cache_key(path: Path) -> str:
    return str(path.resolve())


def _file_stamp(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _invalidate_cache(path: Path) -> None:
    _rows_cache.pop(_cache_key(path), None)


def _read(path: Path) -> dict:
    if not path.is_file():
        return {"keys": []}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {"keys": []}
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
        raise ValueError(f"Invalid API keys file: {path}")
    return data


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        os.unlink(tmp)
    except FileNotFoundError:
        pass
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2) + "\n")
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, path)
    _invalidate_cache(path)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with open(lock_path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
