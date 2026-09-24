"""Compatibility shim. Falkor search Cypher lives in the Falkor adapter."""

from graph_memory_mcp.graph_memory.backends.falkor_search import (
    SearchType,
    build_metadata_filter_clauses,
    build_owner_scoped_similarity_query,
    normalize_search_type,
)

__all__ = [
    "SearchType",
    "build_metadata_filter_clauses",
    "build_owner_scoped_similarity_query",
    "normalize_search_type",
]
