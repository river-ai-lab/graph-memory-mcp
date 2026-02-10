# Roadmap & Future Considerations

## Features

**Hybrid Memory/Disk Database** - Specialized backend supporting hybrid memory/disk operation (active data in memory, archived data on disk). Enables handling datasets larger than RAM without eviction.

**BM25 Hybrid Search** - May be implemented via database backend with native BM25 support (Qdrant, Weaviate, or future FalkorDB features).

**Batch Operations** - Bulk create/update/delete for large data volumes.

**Custom Embedding Models/Spaces** - Multiple embedding spaces per domain via metadata (code embeddings vs natural language).

**Owner Groups & Multi-Ownership** - Support for owner groups combining multiple `owner_id`s.

**Temporal Queries** - Enhanced time-based filtering and sorting.

**Enhanced Search** - Faceted search, query expansion, multi-language support.

**Versioning Improvements** - Tracks `change_reason` and `changed_by` when versioning is enabled.

**Access Tracking & Analytics** - Implement append-only access events with TTL (instead of a single mutable `last_accessed_at` field) to avoid write-amplification and enable richer analytics.

## Infrastructure

**Performance Optimizations** - Connection pooling, query tuning

**Monitoring & Observability** - Prometheus metrics expansion, distributed tracing, deeper query analytics.

**API Enhancements** - GraphQL endpoint, REST wrapper, WebSocket support, API versioning.

---

**Note:** This roadmap is subject to change based on user feedback and priorities.
