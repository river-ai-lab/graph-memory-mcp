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
        # Allow constructing with field names (not only env aliases), e.g. in tests.
        populate_by_name=True,
        # If `.env` exists, it will be loaded; if not, defaults + process env vars are used.
        env_file=".env",
        env_file_encoding="utf-8",
        # What this means:
        # - unknown keys are ignored instead of raising validation errors
        extra="ignore",
    )

    # MCP server (top-level)
    enabled: bool = Field(default=True, validation_alias="MCP_SERVER_ENABLED")
    # Admin/agent separation: admin operations live on HTTP /admin/* routes.
    # Set true to additionally expose them as MCP tools (legacy behavior).
    mcp_expose_admin_tools: bool = Field(
        default=False, validation_alias="MCP_EXPOSE_ADMIN_TOOLS"
    )
    admin_token: str = Field(default="", validation_alias="ADMIN_TOKEN")
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
    # Model prompt prefixes (e5-family: "query: " / "passage: "). Empty = none.
    # Changing prefixes (like changing the model) requires re-embedding the corpus.
    embedding_query_prefix: str = Field(
        default="", validation_alias="EMBEDDING_QUERY_PREFIX"
    )
    embedding_passage_prefix: str = Field(
        default="", validation_alias="EMBEDDING_PASSAGE_PREFIX"
    )

    # Vector indexes (auto-creation)
    auto_create_indexes: bool = False  # opt-in: create indexes on startup

    # Search/graph defaults
    default_search_limit: int = 10
    max_search_limit: int = 100  # hard cap for limit on search-like tools
    semantic_similarity_threshold: float = 0.55
    default_search_type: str = Field(
        default="pre_filter",
        validation_alias="SEARCH_TYPE",
        description="Default search_type when MCP search omits it: pre_filter | post_filter",
    )
    post_filter_ann_k_min: int = Field(
        default=100,
        validation_alias="POST_FILTER_ANN_K_MIN",
        description="Minimum global ANN candidates for post_filter search (queryNodes k)",
    )
    post_filter_ann_k_max: int = Field(
        default=2000,
        validation_alias="POST_FILTER_ANN_K_MAX",
        description="Maximum global ANN candidates for post_filter search (queryNodes k)",
    )

    # Graph/auto-linking
    auto_linking_semantic_threshold: float = 0.75
    neighbours_search_threshold: float = 0.8
    subgraph_default_depth: int = 1
    subgraph_max_depth: int = 3
    subgraph_default_max_nodes: int = 20
    subgraph_max_nodes_limit: int = 50
    recall_context_default_depth: int = Field(
        default=2,
        validation_alias="RECALL_CONTEXT_DEFAULT_DEPTH",
    )
    recall_context_default_seed_limit: int = Field(
        default=5,
        validation_alias="RECALL_CONTEXT_SEED_LIMIT",
    )
    recall_context_hop_decay: float = Field(
        default=0.7,
        validation_alias="RECALL_CONTEXT_HOP_DECAY",
    )
    # Time-aware recall: score ×= (1-w) + w * 0.5^(age_days/half_life) and
    # ×= (1-w) + w * usage. Weights 0 disable the corresponding factor.
    recall_recency_weight: float = Field(
        default=0.2, validation_alias="RECALL_RECENCY_WEIGHT"
    )
    recall_recency_half_life_days: float = Field(
        default=30.0, validation_alias="RECALL_RECENCY_HALF_LIFE_DAYS"
    )
    recall_usage_weight: float = Field(
        default=0.1, validation_alias="RECALL_USAGE_WEIGHT"
    )
    duplicate_similarity_threshold: float = 0.85
    duplicate_max_group_size: int = 10
    duplicate_top_k: int = 100
    summary_similarity_threshold: float = 0.7

    # Relation policy (create_relation, create_node links, create_triplet predicates)
    relation_policy_enforce: str = Field(
        default="warn",
        validation_alias="RELATION_POLICY_ENFORCE",
        description="off | warn | enforce — allowlist for relation types",
    )
    relation_allowed_types: str = Field(
        default=(
            "RELATED_TO,MENTIONS,SUMMARIZES,FOLLOWS_FROM,CONTRADICTS,"
            "EXTRACTED_FROM,SIMILAR_TO,NEXT_STEP,EXPOSES,CROSS_REF,"
            "RUNS_ON,USES,SERVED_BY"
        ),
        validation_alias="RELATION_ALLOWED_TYPES",
    )

    # Housekeeping
    cleanup_days_threshold: int = 90
    stale_facts_days: int = 30  # get_brief: facts not recalled for N days
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
    # Also archive active facts not recalled for `stale_facts_days` (opt-in)
    job_archive_stale_enabled: bool = Field(
        default=False, validation_alias="JOB_ARCHIVE_STALE_ENABLED"
    )

    # Job retry/backoff (shared)
    job_retry_max_attempts: int = 3
    job_retry_backoff_base: float = 2.0
    job_retry_backoff_max: float = 30.0

    # Versioning: snapshot before update when the caller omits `versioning`
    versioning_default: bool = Field(
        default=False, validation_alias="VERSIONING_DEFAULT"
    )

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
