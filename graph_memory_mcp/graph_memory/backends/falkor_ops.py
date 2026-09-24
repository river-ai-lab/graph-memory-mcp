"""Falkor Cypher for nodes, edges, traversal, admin, and jobs."""

from __future__ import annotations

from typing import Any


def node_return_fields(alias: str = "n") -> str:
    return f"""
        {alias}.uid as node_id,
        labels({alias})[0] as node_type,
        {alias}.text as text,
        {alias}.description as description,
        {alias}.status as status,
        {alias}.created_at as created_at,
        {alias}.updated_at as updated_at,
        {alias}.metadata_str as metadata_str,
        {alias}.shared_with_ids as shared_with_ids,
        {alias}.ttl_days as ttl_days,
        {alias}.expires_at as expires_at,
        {alias}.type as entity_type,
        {alias}.source_str as source_str
    """


class FalkorOps:
    """Query methods mixed into the Falkor client. Each one calls ``query``."""

    def embedding_literal(self, param: str, present: bool) -> str:
        return f"vecf32(${param})" if present else "NULL"

    def updated_at_assignment(self) -> str:
        return "n.updated_at = timestamp()"

    def touch_nodes(self, node_ids: list, owner_id: str) -> None:
        """Bump access_count / last_accessed_at. A failed write is not swallowed."""
        if not node_ids:
            return
        self.query(
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

    def create_node_row(
        self,
        *,
        node_type: str,
        params: dict[str, Any],
        has_embedding: bool,
        entity_type: str | None,
    ) -> list[list[Any]]:
        type_prop = ""
        if node_type == "Entity":
            type_prop = ", name_norm: $name_norm"
            if entity_type:
                type_prop += ", type: $entity_type"
        embedding_expr = "vecf32($embedding)" if has_embedding else "NULL"
        query = f"""
    CREATE (n:{node_type} {{
        uid: $uid,
        owner_id: $owner_id,
        text: $text,
        description: $description,
        embedding: {embedding_expr},
        status: $status,
        created_at: timestamp(),
        updated_at: timestamp(),
        metadata_str: $metadata_str,
        tags: $tags,
        meta_type: $meta_type,
        confidence: $confidence,
        project: $project,
        created_by: $created_by,
        shared_with_ids: $shared_with_ids,
        ttl_days: $ttl_days,
        expires_at: $expires_at,
        last_dedup_at: NULL,
        source_str: $source_str,
        source_ref: $source_ref,
        source_type: $source_type,
        source_uri: $source_uri,
        content_hash: $content_hash,
        source_updated_at: $source_updated_at{type_prop}
    }})
    RETURN {node_return_fields()}
    """
        return self.rows(query, params)

    def create_nodes_bulk(self, *, node_type: str, rows: list, owner_id: str) -> list:
        query = f"""
    UNWIND $rows AS row
    CREATE (n:{node_type} {{
        uid: row.uid,
        owner_id: $owner_id,
        text: row.text,
        description: row.description,
        embedding: vecf32(row.emb),
        status: row.status,
        created_at: timestamp(),
        updated_at: timestamp(),
        metadata_str: row.metadata_str,
        tags: row.tags,
        meta_type: row.meta_type,
        confidence: row.confidence,
        project: row.project,
        created_by: row.created_by,
        ttl_days: row.ttl_days,
        expires_at: row.expires_at,
        name_norm: row.name_norm,
        last_dedup_at: NULL
    }})
    RETURN n.uid
    """
        return self.rows(query, {"rows": rows, "owner_id": owner_id})

    def fetch_node_row(self, node_id: str, owner_id: str) -> list[list[Any]]:
        query = f"""
    MATCH (n)
    WHERE n.uid = $node_id AND n.owner_id = $owner_id
    RETURN {node_return_fields()}
    """
        return self.rows(query, {"node_id": node_id, "owner_id": owner_id})

    def fetch_version_after(self, node_id: str, owner_id: str, as_of: int) -> list:
        return self.rows(
            """
        MATCH (v:FactVersion)
        WHERE v.fact_id = $node_id AND v.owner_id = $owner_id
          AND v.version_timestamp > $as_of
        RETURN v.text, v.description, v.metadata_str, v.source_str,
               v.status, v.ttl_days, v.expires_at, v.version_timestamp
        ORDER BY v.version_timestamp ASC
        LIMIT 1
        """,
            {"node_id": node_id, "owner_id": owner_id, "as_of": as_of},
        )

    def snapshot_fact(self, *, node_id: str, owner_id: str, version_uid: str) -> Any:
        return self.query(
            """
        MATCH (n:Fact)
        WHERE n.uid = $node_id AND n.owner_id = $owner_id
        CREATE (v:FactVersion {
            uid: $version_uid,
            fact_id: n.uid,
            owner_id: n.owner_id,
            text: n.text,
            description: n.description,
            metadata_str: n.metadata_str,
            source_str: n.source_str,
            shared_with_ids: n.shared_with_ids,
            status: n.status,
            ttl_days: n.ttl_days,
            expires_at: n.expires_at,
            version_timestamp: timestamp(),
            original_created_at: n.created_at
        })
        RETURN v.uid as version_id
        """,
            params={
                "node_id": node_id,
                "owner_id": owner_id,
                "version_uid": version_uid,
            },
        )

    def apply_node_update(self, *, set_clauses: list[str], params: dict) -> list:
        query = f"""
    MATCH (n)
    WHERE n.uid = $node_id AND n.owner_id = $owner_id
    SET {", ".join(set_clauses)}
    RETURN {node_return_fields()}
    """
        return self.rows(query, params)

    def delete_fact_versions(self, node_id: str, owner_id: str) -> Any:
        return self.query(
            """
        MATCH (v:FactVersion)
        WHERE v.fact_id = $node_id AND v.owner_id = $owner_id
        DELETE v
        """,
            params={"node_id": node_id, "owner_id": owner_id},
        )

    def delete_node_row(self, node_id: str, owner_id: str) -> list:
        return self.rows(
            """
    MATCH (n)
    WHERE n.uid = $node_id AND n.owner_id = $owner_id
    DETACH DELETE n
    RETURN count(n) as deleted
    """,
            {"node_id": node_id, "owner_id": owner_id},
        )

    def list_fact_versions(self, node_id: str, owner_id: str) -> list:
        return self.rows(
            """
    MATCH (v:FactVersion)
    WHERE v.fact_id = $node_id AND v.owner_id = $owner_id
    RETURN
        id(v) as version_id,
        v.text as text,
        v.metadata_str as metadata_str,
        v.source_str as source_str,
        v.status as status,
        v.ttl_days as ttl_days,
        v.version_timestamp as version_timestamp,
        v.original_created_at as original_created_at
    ORDER BY v.version_timestamp DESC
    """,
            {"node_id": node_id, "owner_id": owner_id},
        )

    def fetch_by_source_ref(self, *, node_type: str, owner_id: str, source_ref: str) -> list:
        query = f"""
    MATCH (n:{node_type})
    WHERE n.owner_id = $owner_id AND n.source_ref = $source_ref
    RETURN {node_return_fields()}
    LIMIT 1
    """
        return self.rows(query, {"owner_id": owner_id, "source_ref": source_ref})

    def auto_link_mentions(
        self,
        *,
        relation: str,
        owner_id: str,
        embedding: list,
        max_distance: float,
        node_id: str,
    ) -> Any:
        query = f"""
        MATCH (node:Entity)
        WHERE node.owner_id = $owner_id
          AND node.embedding IS NOT NULL
          AND (node.status IS NULL OR node.status = 'active')
        WITH node, vec.cosineDistance(node.embedding, vecf32($embedding)) AS score
        WHERE score <= $max_distance
        WITH node
        ORDER BY score ASC
        LIMIT 10
        MATCH (f)
        WHERE f.uid = $node_id
        MERGE (f)-[r:{relation}]->(node)
        ON CREATE SET r.created_at = timestamp(), r.auto_linked = true
        RETURN count(r) as links_created
        """
        return self.query(
            query,
            params={
                "owner_id": owner_id,
                "embedding": embedding,
                "max_distance": max_distance,
                "node_id": node_id,
            },
        )

    def add_to_collection(self, node_id: str, collection_id: str, owner_id: str) -> list:
        return self.rows(
            """
    MATCH (c:Collection), (n)
    WHERE c.uid = $collection_id AND n.uid = $node_id
      AND c.owner_id = $owner_id AND n.owner_id = $owner_id
    MERGE (c)-[r:CONTAINS]->(n)
    ON CREATE SET r.created_at = timestamp()
    RETURN count(r) as created
    """,
            {
                "collection_id": collection_id,
                "node_id": node_id,
                "owner_id": owner_id,
            },
        )

    def merge_relation(
        self,
        *,
        rel_type: str,
        params: dict,
        prop_assignments: str,
    ) -> list:
        query = f"""
    MATCH (a), (b)
    WHERE a.uid = $from_id AND b.uid = $to_id
        AND a.owner_id = $owner_id AND b.owner_id = $owner_id
    MERGE (a)-[r:{rel_type}]->(b)
    ON CREATE SET r.created_at = timestamp(){prop_assignments}
    RETURN id(r) as rel_id
    """
        return self.rows(query, params)

    def merge_triplet(self, *, rel_type: str, params: dict, subj_emb_expr: str, obj_emb_expr: str) -> list:
        query = f"""
    MERGE (s:Entity {{name_norm: $subject_norm, owner_id: $owner_id}})
    ON CREATE SET
        s.uid = $subj_uid,
        s.text = $subject,
        s.created_at = timestamp(),
        s.embedding = {subj_emb_expr},
        s.status = 'active',
        s.metadata_str = $metadata_str,
        s.project = $project,
        s.created_by = $created_by,
        s.tags = $tags,
        s.meta_type = $meta_type,
        s.confidence = $confidence
    ON MATCH SET
        s.project = CASE WHEN $project IS NULL THEN s.project ELSE $project END,
        s.created_by = CASE WHEN $created_by IS NULL THEN s.created_by ELSE $created_by END,
        s.tags = CASE WHEN $tags IS NULL THEN s.tags ELSE $tags END,
        s.meta_type = CASE WHEN $meta_type IS NULL THEN s.meta_type ELSE $meta_type END,
        s.confidence = CASE WHEN $confidence IS NULL THEN s.confidence ELSE $confidence END
    MERGE (o:Entity {{name_norm: $object_norm, owner_id: $owner_id}})
    ON CREATE SET
        o.uid = $obj_uid,
        o.text = $object,
        o.created_at = timestamp(),
        o.embedding = {obj_emb_expr},
        o.status = 'active',
        o.metadata_str = $metadata_str,
        o.project = $project,
        o.created_by = $created_by,
        o.tags = $tags,
        o.meta_type = $meta_type,
        o.confidence = $confidence
    ON MATCH SET
        o.project = CASE WHEN $project IS NULL THEN o.project ELSE $project END,
        o.created_by = CASE WHEN $created_by IS NULL THEN o.created_by ELSE $created_by END,
        o.tags = CASE WHEN $tags IS NULL THEN o.tags ELSE $tags END,
        o.meta_type = CASE WHEN $meta_type IS NULL THEN o.meta_type ELSE $meta_type END,
        o.confidence = CASE WHEN $confidence IS NULL THEN o.confidence ELSE $confidence END
    MERGE (s)-[r:{rel_type}]->(o)
    ON CREATE SET r.created_at = timestamp()
    RETURN s.uid as subject_id, o.uid as object_id, id(r) as relation_id
    """
        return self.rows(query, params)

    def link_extracted_from(self, *, fact_id: str, subject_id: str, owner_id: str) -> Any:
        return self.query(
            """
        MATCH (f:Fact), (s:Entity)
        WHERE f.uid = $fact_id AND s.uid = $subject_id
            AND f.owner_id = $owner_id AND s.owner_id = $owner_id
        MERGE (f)-[r:EXTRACTED_FROM]->(s)
        ON CREATE SET r.created_at = timestamp()
        """,
            params={
                "fact_id": fact_id,
                "subject_id": subject_id,
                "owner_id": owner_id,
            },
        )

    def search_triplet_rows(self, *, rel_pattern: str, where_sql: str, params: dict, limit: int) -> list:
        query = f"""
    MATCH (s:Entity)-{rel_pattern}->(o:Entity)
    WHERE {where_sql}
    RETURN
        s.uid as subject_id,
        s.text as subject,
        type(r) as predicate,
        o.uid as object_id,
        o.text as object,
        id(r) as relation_id
    LIMIT {int(limit)}
    """
        return self.rows(query, params)

    def unlink_relation(self, *, rel_pattern: str, params: dict) -> list:
        query = f"""
    MATCH (a)-{rel_pattern}->(b)
    WHERE a.uid = $from_id AND b.uid = $to_id
        AND a.owner_id = $owner_id AND b.owner_id = $owner_id
    DELETE r
    RETURN count(r) as deleted
    """
        return self.rows(query, params)

    def edges_between(self, node_ids: list[str], owner_id: str) -> list:
        return self.rows(
            """
    MATCH (n)-[r]->(m)
    WHERE n.uid IN $node_ids AND m.uid IN $node_ids
      AND n.owner_id = $owner_id AND m.owner_id = $owner_id
    RETURN DISTINCT
        n.uid as from_id,
        type(r) as relation_type,
        m.uid as to_id,
        properties(r) as relation_props
    """,
            {
                "node_ids": [str(node_id) for node_id in node_ids],
                "owner_id": owner_id,
            },
        )

    def bfs_init_rows(self, ids: list, owner_id: str) -> list:
        return self.rows(
            """
    MATCH (n)
    WHERE n.uid IN $ids AND n.owner_id = $owner_id
    RETURN n.uid, labels(n)[0], n.text,
           coalesce(n.updated_at, n.created_at), coalesce(n.access_count, 0)
""",
            {"ids": ids, "owner_id": owner_id},
        )

    def bfs_step_rows(
        self,
        *,
        frontier: list,
        seen: list,
        owner_id: str,
        remaining: int,
        include_outdated: bool,
    ) -> list:
        status_filter = ""
        if not include_outdated:
            status_filter = (
                " AND (coalesce(m.status, 'active') = 'active' "
                "AND (m.expires_at IS NULL OR m.expires_at > timestamp()))"
            )
        query = f"""
    MATCH (n)-[r]-(m)
    WHERE n.uid IN $frontier AND m.owner_id = $owner_id
      AND NOT m.uid IN $seen{status_filter}
    WITH m, collect(DISTINCT n.uid) AS parents
    RETURN m.uid, labels(m)[0], m.text,
           coalesce(m.updated_at, m.created_at), coalesce(m.access_count, 0),
           parents
    LIMIT {int(remaining)}
    """
        return self.rows(
            query,
            {"frontier": frontier, "seen": seen, "owner_id": owner_id},
        )

    def context_page_rows(
        self,
        *,
        depth: int,
        offset: int,
        limit: int,
        include_outdated: bool,
        node_id: str,
        owner_id: str,
    ) -> list:
        neighbor_ok = (
            "true"
            if include_outdated
            else (
                "(coalesce(connected.status, 'active') = 'active'"
                " AND (connected.expires_at IS NULL OR connected.expires_at > timestamp()))"
            )
        )
        query = f"""
    MATCH path = (center)-[*0..{depth}]-(connected)
    WHERE center.uid = $node_id
      AND center.owner_id = $owner_id
      AND connected.owner_id = $owner_id
      AND (connected.uid = center.uid OR {neighbor_ok})
    WITH DISTINCT connected
    ORDER BY id(connected)
    SKIP {offset}
    LIMIT {limit}
    RETURN
        connected.uid as node_id,
        labels(connected)[0] as node_type,
        connected.text as text
    """
        return self.rows(query, {"node_id": node_id, "owner_id": owner_id})

    def shortest_path_row(
        self,
        *,
        directed: bool,
        max_depth: int,
        from_id: str,
        to_id: str,
        owner_id: str,
    ) -> list:
        if directed:
            query = f"""
    MATCH (a), (b)
    WHERE a.uid = $from_id AND b.uid = $to_id
      AND a.owner_id = $owner_id AND b.owner_id = $owner_id
    WITH shortestPath((a)-[*..{int(max_depth)}]->(b)) as path
    RETURN [n in nodes(path) | {{
        node_id: n.uid,
        node_type: labels(n)[0],
        text: n.text
    }}] as nodes,
    [r in relationships(path) | {{
        relation_type: type(r)
    }}] as relations
    """
        else:
            query = f"""
    MATCH path = (a)-[*..{int(max_depth)}]-(b)
    WHERE a.uid = $from_id AND b.uid = $to_id
      AND a.owner_id = $owner_id AND b.owner_id = $owner_id
    WITH path
    ORDER BY length(path) ASC
    LIMIT 1
    RETURN [n in nodes(path) | {{
        node_id: n.uid,
        node_type: labels(n)[0],
        text: n.text
    }}] as nodes,
    [r in relationships(path) | {{
        relation_type: type(r)
    }}] as relations
    """
        return self.rows(
            query,
            {"from_id": from_id, "to_id": to_id, "owner_id": owner_id},
        )

    def label_counts(self, owner_id: str) -> list:
        return self.rows(
            """
    MATCH (n)
    WHERE n.owner_id = $owner_id AND (n:Fact OR n:Entity)
    WITH labels(n)[0] as label, count(n) as count
    RETURN label, count
    """,
            {"owner_id": owner_id},
        )

    def fact_status_counts(self, owner_id: str) -> list:
        return self.rows(
            """
    MATCH (f:Fact)
    WHERE f.owner_id = $owner_id
    WITH f.status as status, count(f) as count
    RETURN status, count
    """,
            {"owner_id": owner_id},
        )

    def relation_count(self, owner_id: str) -> list:
        return self.rows(
            """
    MATCH (a)-[r]->(b)
    WHERE a.owner_id = $owner_id
      AND b.owner_id = $owner_id
    RETURN count(r) as total_relations
    """,
            {"owner_id": owner_id},
        )

    def brief_top_facts(self, owner_id: str, limit: int) -> list:
        query = f"""
    MATCH (f:Fact)
    WHERE f.owner_id = $owner_id
      AND (f.status IS NULL OR f.status = 'active')
    OPTIONAL MATCH (f)-[r]-()
    WITH f, count(r) as degree
    ORDER BY degree DESC, f.created_at DESC
    LIMIT {int(limit)}
    RETURN f.uid as node_id, f.text as text, degree, f.created_at as created_at
    """
        return self.rows(query, {"owner_id": owner_id})

    def brief_contradictions(self, owner_id: str) -> list:
        return self.rows(
            """
    MATCH (a)-[r:CONTRADICTS]-(b)
    WHERE a.owner_id = $owner_id AND b.owner_id = $owner_id
      AND a.uid < b.uid
    RETURN a.uid, a.text, b.uid, b.text
    LIMIT 10
    """,
            {"owner_id": owner_id},
        )

    def brief_stale_facts(self, owner_id: str, cutoff_ms: int) -> list:
        return self.rows(
            """
    MATCH (f:Fact)
    WHERE f.owner_id = $owner_id
      AND (f.status IS NULL OR f.status = 'active')
      AND coalesce(f.last_accessed_at, f.created_at) < $cutoff_ms
    RETURN f.uid, f.text, f.last_accessed_at, f.access_count
    ORDER BY coalesce(f.last_accessed_at, f.created_at) ASC
    LIMIT 10
    """,
            {"owner_id": owner_id, "cutoff_ms": cutoff_ms},
        )

    def export_node_rows(self, owner_id: str, page_clause: str) -> list:
        return self.rows(
            f"""
            MATCH (n)
            WHERE n.owner_id = $owner_id AND (n:Fact OR n:Entity OR n:FactVersion)
            RETURN labels(n)[0], properties(n)
            ORDER BY n.uid{page_clause}
            """,
            {"owner_id": owner_id},
        )

    def export_relation_rows(self, owner_id: str, page_clause: str) -> list:
        return self.rows(
            f"""
            MATCH (a)-[r]->(b)
            WHERE a.owner_id = $owner_id AND b.owner_id = $owner_id
            RETURN a.uid, type(r), b.uid, properties(r)
            ORDER BY a.uid, b.uid{page_clause}
            """,
            {"owner_id": owner_id},
        )

    def import_node_batch(self, *, label: str, has_emb: bool, rows: list, owner_id: str) -> Any:
        emb_clause = ", n.embedding = vecf32(row.emb)" if has_emb else ""
        return self.query(
            f"""
                UNWIND $rows AS row
                MERGE (n:{label} {{uid: row.uid}})
                SET n = row.props{emb_clause}
                """,
            params={"rows": rows, "owner_id": owner_id},
        )

    def import_relation_batch(self, *, rel_type: str, rows: list, owner_id: str) -> Any:
        return self.query(
            f"""
                UNWIND $rows AS row
                MATCH (a), (b)
                WHERE a.uid = row.from_id AND b.uid = row.to_id
                  AND a.owner_id = $owner_id AND b.owner_id = $owner_id
                MERGE (a)-[r:{rel_type}]->(b)
                SET r = row.props
                """,
            params={"rows": rows, "owner_id": owner_id},
        )

    def graph_size_rows(self, owner_id: str) -> list:
        return self.rows(
            "MATCH (n) WHERE n:Fact OR n:Entity "
            "RETURN labels(n)[0] as label, count(n)",
            owner_id=owner_id,
        )

    def dedup_candidate_rows(
        self, *, label: str, owner_id: str, limit: int, touched_filter: str
    ) -> list:
        query = f"""
    MATCH (n:{label})
    WHERE n.owner_id = $owner_id
      AND (n.status IS NULL OR n.status = 'active')
      AND n.embedding IS NOT NULL
      AND (
        n.last_dedup_at IS NULL
        OR n.last_dedup_at < coalesce(n.updated_at, n.created_at)
      )
      {touched_filter}
    RETURN
      n.uid as node_id,
      n.text as text,
      n.created_at as created_at,
      coalesce(n.updated_at, n.created_at) as touched_at,
      n.embedding as embedding
    ORDER BY touched_at ASC, created_at ASC, node_id ASC
    LIMIT {int(limit)}
    """
        return self.rows(query, {"owner_id": owner_id})

    def dedup_similar_rows(
        self,
        *,
        label: str,
        embedding: list,
        max_distance: float,
        owner_id: str,
        node_id: str,
        ann_k: int,
        top_k: int,
    ) -> list:
        query = f"""
    CALL db.idx.vector.queryNodes('{label}', 'embedding', {int(ann_k)}, vecf32($embedding))
    YIELD node, score
    WHERE score <= $max_distance
      AND node.owner_id = $owner_id
      AND node.uid <> $node_id
      AND (node.status IS NULL OR node.status = 'active')
    RETURN node.uid, node.created_at, score
    ORDER BY score ASC, node.created_at ASC, node.uid ASC
    LIMIT {int(top_k)}
    """
        return self.rows(
            query,
            {
                "embedding": embedding,
                "max_distance": max_distance,
                "owner_id": owner_id,
                "node_id": node_id,
            },
        )

    def mark_deduped(self, *, label: str, node_ids: list, owner_id: str) -> Any:
        query = f"""
    MATCH (n:{label})
    WHERE n.uid IN $node_ids AND n.owner_id = $owner_id
    SET n.last_dedup_at = timestamp()
    RETURN count(n) as updated
    """
        return self.query(query, params={"node_ids": node_ids, "owner_id": owner_id})

    def rels_out(self, *, label: str, dup_id: str, owner_id: str) -> list:
        return self.rows(
            f"""
                MATCH (dup:{label})-[r]->(target)
                WHERE dup.uid = $dup_id
                  AND (dup.owner_id = $owner_id OR dup.owner_id IS NULL)
                RETURN type(r) as rel_type, properties(r) as props, target.uid as target_id
                """,
            {"dup_id": dup_id, "owner_id": owner_id},
        )

    def copy_rel_out(self, *, label: str, rel_type: str, params: dict) -> Any:
        return self.query(
            f"""
                        MATCH (p:{label}), (t)
                        WHERE p.uid = $primary_id AND t.uid = $target_id
                        MERGE (p)-[new_r:{rel_type}]->(t)
                        SET new_r = $props
                        """,
            params=params,
        )

    def delete_rels_out(self, *, label: str, dup_id: str, owner_id: str) -> Any:
        return self.query(
            f"MATCH (dup:{label})-[r]->() WHERE dup.uid = $dup_id DELETE r",
            params={"dup_id": dup_id, "owner_id": owner_id},
        )

    def rels_in(self, *, label: str, dup_id: str, owner_id: str) -> list:
        return self.rows(
            f"""
                MATCH (source)-[r]->(dup:{label})
                WHERE dup.uid = $dup_id
                  AND (dup.owner_id = $owner_id OR dup.owner_id IS NULL)
                RETURN type(r) as rel_type, properties(r) as props, source.uid as source_id
                """,
            {"dup_id": dup_id, "owner_id": owner_id},
        )

    def copy_rel_in(self, *, label: str, rel_type: str, params: dict) -> Any:
        return self.query(
            f"""
                        MATCH (s), (p:{label})
                        WHERE s.uid = $source_id AND p.uid = $primary_id
                        MERGE (s)-[new_r:{rel_type}]->(p)
                        SET new_r = $props
                        """,
            params=params,
        )

    def delete_rels_in(self, *, label: str, dup_id: str, owner_id: str) -> Any:
        return self.query(
            f"MATCH ()-[r]->(dup:{label}) WHERE dup.uid = $dup_id DELETE r",
            params={"dup_id": dup_id, "owner_id": owner_id},
        )

    def mark_merged(self, *, label: str, dup_id: str, primary_id: str, owner_id: str) -> Any:
        return self.query(
            f"""
                MATCH (n:{label})
                WHERE n.uid = $dup_id AND n.owner_id = $owner_id
                SET n.status = 'outdated',
                    n.merged_into = $primary_id,
                    n.metadata_str = coalesce(n.metadata_str, '{{}}')
                """,
            params={"dup_id": dup_id, "primary_id": primary_id, "owner_id": owner_id},
        )

    def touch_dedup_primary(self, *, label: str, primary_id: str, owner_id: str) -> Any:
        return self.query(
            f"""
            MATCH (n:{label})
            WHERE n.uid = $primary_id AND n.owner_id = $owner_id
            SET n.last_dedup_at = timestamp()
            """,
            params={"primary_id": primary_id, "owner_id": owner_id},
        )

    def expired_fact_ids(self, owner_id: str, now_ms: int) -> list:
        return self.rows(
            """
            MATCH (f:Fact)
            WHERE f.owner_id = $owner_id
              AND (f.status IS NULL OR f.status = 'active')
              AND (f.expires_at IS NOT NULL AND f.expires_at <= $now_ms)
            RETURN f.uid as fact_id
            """,
            {"owner_id": owner_id, "now_ms": now_ms},
        )

    def stale_fact_ids(self, owner_id: str, cutoff_ms: int) -> list:
        return self.rows(
            """
                MATCH (f:Fact)
                WHERE f.owner_id = $owner_id
                  AND (f.status IS NULL OR f.status = 'active')
                  AND coalesce(f.last_accessed_at, f.created_at) < $cutoff_ms
                RETURN f.uid as fact_id
                """,
            {"owner_id": owner_id, "cutoff_ms": cutoff_ms},
        )

    def fact_neighbor_rows(self, fact_id: str) -> list:
        return self.rows(
            """
                MATCH (f:Fact)-[r]-(n)
                WHERE f.uid = $raw_id
                RETURN labels(n) as n_labels, n.status as n_status
                """,
            {"raw_id": fact_id},
        )
