from __future__ import annotations

import secrets
from contextlib import contextmanager
from typing import Iterator

import redis


class RedisDistributedLock:
    """
    Simple Redis-based distributed lock (SET NX PX) with safe release.

    Notes:
    - This is best-effort and intended for background jobs idempotency.
    - Uses a unique token and Lua compare-and-del to avoid releasing other lock.
    """

    def __init__(
        self,
        client: redis.Redis,
        key: str,
        ttl_seconds: int = 600,
    ) -> None:
        self._client = client
        self._key = key
        self._ttl_ms = max(1, int(ttl_seconds)) * 1000
        self._token: str = secrets.token_hex(16)
        self.acquired: bool = False

    def acquire(self) -> bool:
        ok = self._client.set(self._key, self._token, nx=True, px=self._ttl_ms)
        self.acquired = bool(ok)
        return self.acquired

    def release(self) -> None:
        if not self.acquired:
            return

        # Compare-and-delete (only release if token matches)
        lua = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        try:
            self._client.eval(lua, 1, self._key, self._token)
        finally:
            self.acquired = False


@contextmanager
def job_lock(
    client: redis.Redis,
    key: str,
    ttl_seconds: int = 600,
) -> Iterator[bool]:
    """
    Context manager returning whether lock was acquired.

    Usage:
        with job_lock(redis_client, "lock:key") as acquired:
            if not acquired:
                return
            ...
    """
    lock = RedisDistributedLock(client=client, key=key, ttl_seconds=ttl_seconds)
    acquired = lock.acquire()
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()
