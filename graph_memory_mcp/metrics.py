"""Prometheus metrics for MCP Graph Memory (handler latency, cache, graph size)."""

from __future__ import annotations

import logging
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

logger = logging.getLogger(__name__)

HANDLER_SECONDS = Histogram(
    "graph_memory_handler_seconds",
    "Handler execution time",
    ["handler"],
)
HANDLER_TOTAL = Counter(
    "graph_memory_handler_total",
    "Handler invocations",
    ["handler", "success"],
)
CACHE_OPS = Counter(
    "graph_memory_cache_ops_total",
    "Cache lookups",
    ["cache", "result"],
)
GRAPH_NODES = Gauge(
    "graph_memory_nodes",
    "Node count by label (sum over all owner graphs)",
    ["label"],
)
OWNER_GRAPHS = Gauge(
    "graph_memory_owner_graphs",
    "Number of per-owner graphs",
)
JOB_SECONDS = Histogram(
    "graph_memory_job_seconds",
    "Background job execution time",
    ["job"],
)
JOB_TOTAL = Counter(
    "graph_memory_job_total",
    "Background job runs",
    ["job", "success"],
)

_GRAPH_SIZE_TTL_SECONDS = 60.0
_graph_size_refreshed_at = 0.0


def observe_handler(handler: str, seconds: float, success: bool) -> None:
    try:
        HANDLER_SECONDS.labels(handler=handler).observe(seconds)
        HANDLER_TOTAL.labels(handler=handler, success=str(success).lower()).inc()
    except Exception:  # noqa: BLE001 — metrics must never break handlers
        pass


def observe_cache(cache: str, hit: bool) -> None:
    try:
        CACHE_OPS.labels(cache=cache, result="hit" if hit else "miss").inc()
    except Exception:  # noqa: BLE001
        pass


def observe_job(job: str, seconds: float, success: bool) -> None:
    try:
        JOB_SECONDS.labels(job=job).observe(seconds)
        JOB_TOTAL.labels(job=job, success=str(success).lower()).inc()
    except Exception:  # noqa: BLE001
        pass


def _refresh_graph_size_gauges(db: Any) -> None:
    """Walk owner graphs at most once per TTL — cheap scrapes in between."""
    import time

    global _graph_size_refreshed_at
    if time.monotonic() - _graph_size_refreshed_at < _GRAPH_SIZE_TTL_SECONDS:
        return
    _graph_size_refreshed_at = time.monotonic()

    owners = db.list_owners()
    OWNER_GRAPHS.set(len(owners))
    totals: dict[str, int] = {}
    for owner_id in owners:
        result = db.query(
            "MATCH (n) WHERE n:Fact OR n:Entity "
            "RETURN labels(n)[0] as label, count(n)",
            owner_id=owner_id,
        )
        for row in getattr(result, "result_set", None) or []:
            totals[str(row[0])] = totals.get(str(row[0]), 0) + int(row[1])
    for label, count in totals.items():
        GRAPH_NODES.labels(label=label).set(count)


def metrics_response(db: Any = None):
    """Starlette response with current metrics; refreshes graph size gauges."""
    from starlette.responses import Response

    if db is not None:
        try:
            _refresh_graph_size_gauges(db)
        except Exception as exc:  # noqa: BLE001
            logger.debug("graph size gauge refresh failed: %s", exc)

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
