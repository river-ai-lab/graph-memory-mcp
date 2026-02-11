from __future__ import annotations

from typing import Any, Dict

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPServerConfig(BaseSettings):
    """
    Memory MCP server configuration (single source of truth).
    """

    default_owner_id: str = "default"

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_ignore_empty=False,
        # If `.env` exists, it will be loaded; if not, defaults + process env vars are used.
        env_file=".env",
        env_file_encoding="utf-8",
        # What this means:
        # - unknown keys are ignored instead of raising validation errors
        extra="ignore",
    )

    # MCP server (top-level)
    enabled: bool = Field(default=True, validation_alias="MCP_SERVER_ENABLED")
    name: str = Field(default="memory", validation_alias="MCP_SERVER_NAME")
    description: str = Field(
        default="Memory MCP server for knowledge graph (FalkorDB)",
        validation_alias="MCP_SERVER_DESCRIPTION",
    )

    # FalkorDB
    falkordb_host: str = "localhost"
    falkordb_port: int = 6379
    falkordb_graph: str = "memory"
    falkordb_password: str = ""

    # Embeddings
    embedding_model: str = "intfloat/multilingual-e5-base"

    # Vector indexes (auto-creation)
    auto_create_indexes: bool = False  # opt-in: create indexes on startup

    # Search/graph defaults
    default_search_limit: int = 10
    semantic_similarity_threshold: float = 0.55

    # Graph/auto-linking
    auto_linking_semantic_threshold: float = 0.75
    neighbours_search_threshold: float = 0.8
    subgraph_default_depth: int = 1
    subgraph_max_depth: int = 3
    subgraph_default_max_nodes: int = 20
    subgraph_max_nodes_limit: int = 50
    duplicate_similarity_threshold: float = 0.85
    duplicate_max_group_size: int = 10
    duplicate_top_k: int = 100
    summary_similarity_threshold: float = 0.7

    # Housekeeping
    cleanup_days_threshold: int = 90
    log_ttl_days: int = 10
    log_cleanup_frequency: int = 10

    # Background jobs (APScheduler) — optional
    jobs_enabled: bool = False
    jobs_owner_ids: str = (
        "default"  # comma-separated list; used when jobs_process_all_owners=false
    )
    jobs_process_all_owners: bool = False  # if true, discover owners from the graph
    jobs_lock_ttl_seconds: int = 600

    # Job: deduplicate_facts (+ entities in the same job)
    job_deduplicate_enabled: bool = False
    job_deduplicate_cron: str = "0 * * * *"
    job_deduplicate_hours_threshold: int = 24
    job_deduplicate_similarity_threshold: float = 0.95

    # Job: archive_old_facts
    job_archive_enabled: bool = False
    job_archive_cron: str = "0 3 * * 0"

    # Job retry/backoff (shared)
    job_retry_max_attempts: int = 3
    job_retry_backoff_base: float = 2.0
    job_retry_backoff_max: float = 30.0

    # Validation limits (configurable via .env)
    max_text_length: int = 10_000  # Maximum text length in characters
    max_metadata_size: int = 100_000  # Maximum metadata size in bytes
    min_ttl_days: float = 0.0  # Minimum TTL in days
    max_ttl_days: float = 3650.0  # Maximum TTL in days (10 years)

    # Cache settings (configurable via .env)
    cache_embeddings_enabled: bool = True
    cache_embeddings_maxsize: int = 1000
    cache_search_enabled: bool = True
    cache_search_maxsize: int = 100
    cache_search_ttl: int = 60  # seconds

    @property
    def config(self) -> Dict[str, Any]:
        """Return the memory config dict (everything except MCP metadata)."""
        return self.model_dump(exclude={"enabled", "name", "description"})


def load_mcp_server_config() -> MCPServerConfig:
    """
    Load server config from environment variables and optional `.env`.

    If `.env` file doesn't exist, defaults + process env vars are used.
    """
    # NOTE: pydantic-settings handles missing `.env` gracefully.
    # This function exists mostly to keep call sites consistent.
    return MCPServerConfig()
