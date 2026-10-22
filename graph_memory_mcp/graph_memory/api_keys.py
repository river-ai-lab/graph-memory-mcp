"""API keys for ``OWNER_SCOPE=token``.

The file stores a sha256 hash and the owner. ``keys create`` prints the raw
key once and does not write it.
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


@dataclass(frozen=True)
class ApiKeyRecord:
    id: str
    owner: str
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


def owner_for_bearer(path: str | Path, authorization: str | None) -> str | None:
    """Owner of a live key, or None when the key is missing, unknown, or revoked."""
    raw = bearer_value(authorization)
    if raw is None:
        return None
    digest = hash_key(raw)
    try:
        rows = _read(Path(path))["keys"]
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
            owner = str(row.get("owner") or "").strip()
            return owner or None
    return None


def create_key(path: str | Path, owner: str) -> tuple[ApiKeyRecord, str]:
    """Append a key. Returns the public record and the raw key (shown once)."""
    owner_id = require_owner_id_format(owner.strip())
    raw = "gmk_" + secrets.token_urlsafe(32)
    record = {
        "id": _new_id(),
        "owner": owner_id,
        "hash": hash_key(raw),
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


def _record(row: dict) -> ApiKeyRecord:
    return ApiKeyRecord(
        id=str(row.get("id") or ""),
        owner=str(row.get("owner") or ""),
        created_at=str(row.get("created_at") or ""),
        revoked=bool(row.get("revoked")),
    )


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
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


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
