# Atlas Implementation Status

## ✅ Completed (This PR)

### Core Infrastructure
1. **Shared-graph mode**: `ARCADE_SHARED_GRAPH` config flag
   - Single ArcadeDB database for all owners
   - Maintains backward compatibility with per-owner mode
   - Extended server requires ArcadeDB + shared-graph mode (fail-fast)

2. **ACL Token System**
   - `compute_acl_tokens()`: Generates token arrays from owner/user/collection/project IDs
   - `expand_principal_tokens()`: Computes viewer's accessible tokens (stub for traversal)
   - Tokens stored on every node: `["owner:id", "user:id", "coll:id", "proj:id", "ALL"]`
   - Schema updates: `acl_tokens` property + NOTUNIQUE index on all vertex types

3. **Filter-First Vector Search**
   - Server-side ACL filtering via `acl_tokens CONTAINSANY :acl_check` in WHERE clause
   - Pre-computes RID list before HNSW walk (no Python post-filtering)
   - Integrated into `arcade_search.neighbor_rows()` with `acl_tokens` parameter
   - Search plan tracking includes `acl_filtered` flag

4. **VectorStore Protocol**
   - Abstract protocol in `backends/vector_store.py`
   - `ArcadeVectorStore` adapter (thin wrapper around arcade_search)
   - Ready for Qdrant/Milvus implementation without handler changes

### Atlas Features (Extended Server)

5. **Node Types**
   - `Collection`, `User`, `Project` in VERTEX_TYPES
   - Already supported in create_node/upsert_node (extended server)

6. **Default Collection Invariant**
   - `ensure_default_collection()`: Auto-creates one default collection per user
   - User node auto-created if missing
   - Default collection linked via `HAS_ACCESS` edge
   - Nodes without `collection_id` → default collection (handler-level)

7. **Collection Operations**
   - `add_to_collection()`: Creates CONTAINS edge (collection → node)
   - `remove_from_collection()`: Deletes CONTAINS edge
   - `list_collections()`: Returns ACL-filtered collections for viewer
   - `get_collection_contents()`: Depth-based traversal with ACL checks
   - `share_collection()`: Adds HAS_ACCESS edges + updates acl_tokens

8. **Weighted Relations**
   - `create_relation_with_weight()`: Extends create_relation with optional `weight` property
   - `update_relation_weight()`: Updates existing edge weight
   - Tools exposed in extended server: `create_relation_ext`, `update_relation_weight`

9. **ACL Integration**
   - `collection_id` passed through node params for ACL token computation
   - Vector search respects acl_tokens
   - Collection operations filter by ACL

### Testing

10. **Test Suite** (`tests/test_atlas_shared_graph.py`)
    - ACL token computation (owner, user, collection, public)
    - Shared-graph isolation (different users, same database)
    - Filter-first vector search with ACL filtering
    - Default collection creation + idempotency
    - Collection add/remove/list/contents
    - Multi-tenant isolation (different owners)
    - Collection → ACL token propagation

### Documentation

11. **README Updates**
    - Two ArcadeDB layouts: database-per-owner vs shared-graph
    - Shared-graph architecture explanation
    - ACL token model
    - Atlas tools reference
    - Filter-first vector search description

12. **Config & Docker**
    - `ARCADE_SHARED_GRAPH` documented
    - ArcadeDB >= 26.10.2 requirement in docker-compose.yml
    - Extended server backend validation

---

## 🚧 Remaining Work (Out of Scope)

### High Priority

1. **Full HAS_ACCESS Traversal**
   - Current: `expand_principal_tokens()` is a stub (only returns `user:id` + `owner:id`)
   - Needed: BFS from User → HAS_ACCESS → Collection/Project → CONTAINS → transitive collections
   - Impact: Shared collections not fully visible yet

2. **ACL Token Propagation on Membership Changes**
   - When `share_collection()` adds HAS_ACCESS, update `acl_tokens` on:
     - Collection node
     - All nodes in CONTAINS tree (recursive update)
   - When removing access, reverse the process
   - Performance: Bulk update query or background job

3. **Graph Traversal ACL Filtering**
   - `get_context()`: Filter neighbors by ACL before returning
   - `recall_context()`: ACL-filtered BFS expansion
   - `get_trace()`: Ensure path nodes are all visible to viewer

4. **ACL Checks in Handlers**
   - `get_node()`: Check `node.acl_tokens ∩ viewer_tokens` before returning
   - `update_node()`: Verify `owner:id` in viewer tokens (write access = owner only)
   - `delete_node()`: Same owner-only check
   - `create_relation()`: Check both endpoints visible + from_node owned

5. **Relation Filters by Type/Attributes**
   - `get_context()` and `recall_context()` already support `relation_priority` + `exclude_relation_types`
   - Add: `edge_attribute_filter` (e.g., `weight >= 0.8`)
   - Weighted shortest path: `get_trace()` with `weight_threshold`

### Medium Priority

6. **Qdrant VectorStore Implementation**
   - Implement `VectorStore` protocol with Qdrant client
   - Config: `VECTOR_BACKEND=qdrant` (separate from `GRAPH_BACKEND`)
   - Qdrant payload filters for ACL tokens + metadata
   - Migration: Export embeddings from ArcadeDB → Qdrant collection

7. **Performance Benchmarks**
   - Shared-graph vs per-owner mode (search latency, throughput)
   - ACL filter selectivity impact on HNSW walk
   - RID list size vs efSearch tuning
   - Large-scale multi-tenant stress test (1000+ owners, 1M+ nodes)

8. **ACL Token Index Optimization**
   - Current: NOTUNIQUE index on `acl_tokens` (array)
   - Test: Composite index vs separate token expansion
   - ArcadeDB specifics: LSM vs HNSW index interaction

### Low Priority / Future

9. **Audit Logging**
   - Record ACL changes (share/revoke) with timestamp + actor
   - Access event log (who read what, when)
   - Compliance: GDPR/HIPAA audit trails

10. **Advanced Sharing**
    - Time-limited access (ACL token expiry)
    - Permission levels (read-only vs read-write via separate edge type)
    - Inheritance: Collections nested in Collections with ACL propagation

11. **Schema Migration Tool**
    - Backfill `acl_tokens` on existing nodes (owner-only by default)
    - Per-owner → shared-graph migration script
    - Reverse migration (shared-graph → split back into per-owner databases)

---

## 📋 Testing Checklist

### Covered ✅
- [x] ACL token computation
- [x] Shared-graph node creation with correct tokens
- [x] Filter-first vector search (alice sees only alice's + public)
- [x] Default collection creation + idempotency
- [x] add_to_collection (CONTAINS edge)
- [x] Multi-tenant isolation (different owners in same DB)

### Not Covered Yet ❌
- [ ] Full HAS_ACCESS traversal (mocked in tests)
- [ ] share_collection end-to-end (requires HAS_ACCESS walk)
- [ ] get_collection_contents with nested collections (depth > 1)
- [ ] ACL-filtered get_context/recall_context
- [ ] Weighted relation filtering
- [ ] Performance: search latency with 1000+ owners
- [ ] Migration: per-owner → shared-graph with data preservation

---

## 🎯 Next Steps (Prioritized)

1. **Implement Full `expand_principal_tokens()`**
   - BFS from User node via HAS_ACCESS edges
   - Collect all reachable Collection/Project IDs
   - Add `coll:id` and `proj:id` to principal tokens
   - Test: shared collection visibility

2. **Add ACL Checks to Read Handlers**
   - `get_node()`: Reject if not visible
   - `update_node()`: Reject if not owner
   - Return `memory_access_denied` error code

3. **Propagate ACL Tokens on Share**
   - `share_collection()`: Recursive UPDATE on CONTAINS tree
   - Test: share collection → contained nodes become visible

4. **Graph Traversal ACL**
   - `get_context()`: Filter BFS results by ACL
   - `recall_context()`: Same filtering
   - Test: traversal stops at invisible nodes

5. **Qdrant VectorStore**
   - Implement protocol with qdrant-client
   - Payload: `{\"acl_tokens\": [...], \"metadata\": {...}}`
   - Test: search with Qdrant filter vs ArcadeDB

6. **Benchmarks**
   - Generate large shared-graph dataset
   - Measure search P50/P95/P99 vs owner count
   - Tune efSearch heuristic

---

## 📚 References

- **Spec**: Atlas TODO docs (referenced in task, not committed)
- **Architecture**: Agreed with Marat (task summary)
- **ArcadeDB**: >= 26.10.2 (vector index fixes)
- **Protocol**: `backends/vector_store.py`
- **Tests**: `tests/test_atlas_shared_graph.py`
- **Handlers**: `graph_memory/mcp_handlers_atlas.py`

---

**Done when**: PR merged with above ✅ items. Remaining 🚧 items tracked in follow-up issues.
