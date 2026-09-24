"""Kuzu Cypher for the Vela adapter. Same method names as the Falkor ops."""

from __future__ import annotations

import json
import re
from typing import Any

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
NODE_LABELS = ("Fact", "Entity", "Collection", "FactVersion")
IMPORT_COLUMNS = (
    "owner_id",
    "text",
    "description",
    "status",
    "created_at",
    "updated_at",
    "metadata_str",
    "tags",
    "meta_type",
    "confidence",
    "project",
    "created_by",
    "shared_with_ids",
    "ttl_days",
    "expires_at",
    "last_dedup_at",
    "source_str",
    "source_ref",
    "source_type",
    "source_uri",
    "content_hash",
    "source_updated_at",
    "name_norm",
    "type",
    "access_count",
    "last_accessed_at",
    "merged_into",
    "fact_id",
    "version_timestamp",
    "original_created_at",
)


def ident(name: str) -> str:
    if not _IDENT.match(str(name)):
        raise ValueError(f"Invalid identifier: {name!r}")
    return str(name)


def node_label(name: str) -> str:
    label = ident(name)
    if label not in NODE_LABELS:
        raise ValueError(f"Unsupported node type: {label}")
    return label

_EPOCH = "to_epoch_ms(current_timestamp())"
_REL_PATTERN = re.compile(r"^\[r(?::([A-Za-z_][A-Za-z0-9_]*))?\]$")
_PAGE = re.compile(r"^ SKIP \d+ LIMIT \d+$")


def node_return_fields(alias: str = "n") -> str:
    return f"""
        {alias}.uid,
        label({alias}),
        {alias}.text,
        {alias}.description,
        {alias}.status,
        {alias}.created_at,
        {alias}.updated_at,
        {alias}.metadata_str,
        {alias}.shared_with_ids,
        {alias}.ttl_days,
        {alias}.expires_at,
        {alias}.type,
        {alias}.source_str
    """


def _rel_type_from_pattern(pattern: str) -> str | None:
    match = _REL_PATTERN.match(pattern.strip())
    if not match:
        raise ValueError(f"Unsupported relationship pattern: {pattern!r}")
    return match.group(1)


def _page_clause(page_clause: str) -> str:
    if not page_clause:
        return ""
    if not _PAGE.match(page_clause):
        raise ValueError(f"Unsupported page clause: {page_clause!r}")
    return page_clause


def _props_dict(raw: Any, created_at: Any = None, auto_linked: Any = None) -> dict:
    data: dict[str, Any] = {}
    if isinstance(raw, str) and raw:
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, dict):
            data.update(loaded)
    elif isinstance(raw, dict):
        data.update(raw)
    if created_at is not None:
        data.setdefault("created_at", created_at)
    if auto_linked is not None:
        data.setdefault("auto_linked", auto_linked)
    return data


def _dump_props(props: Any) -> str:
    if not isinstance(props, dict):
        props = {}
    return json.dumps(props, default=str)


class VelaOps:
    """Query methods mixed into ``VelaClient``."""

    def embedding_literal(self, param: str, present: bool) -> str:
        return f"${param}" if present else "NULL"

    def updated_at_assignment(self) -> str:
        return f"n.updated_at = {_EPOCH}"

    def touch_nodes(self, node_ids: list, owner_id: str) -> None:
        if not node_ids:
            return
        self.query(
            f"""
            MATCH (n)
            WHERE n.uid IN $node_ids AND n.owner_id = $owner_id
            SET n.access_count = coalesce(n.access_count, 0) + 1,
                n.last_accessed_at = {_EPOCH}
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
        del entity_type
        owner_id = str(params["owner_id"])
        label = node_label(node_type)
        bound = dict(params)
        for key, default in (
            ("description", None),
            ("metadata_str", "{}"),
            ("tags", None),
            ("meta_type", None),
            ("confidence", None),
            ("project", None),
            ("created_by", None),
            ("shared_with_ids", []),
            ("ttl_days", None),
            ("expires_at", None),
            ("source_str", None),
            ("source_ref", None),
            ("source_type", None),
            ("source_uri", None),
            ("content_hash", None),
            ("source_updated_at", None),
            ("name_norm", None),
            ("entity_type", None),
        ):
            bound.setdefault(key, default)
        embedding_clause = ""
        if has_embedding and bound.get("embedding"):
            self.ensure_embedding(owner_id, len(bound["embedding"]))
            embedding_clause = "embedding: $embedding,"
        elif self.embedding_ready(owner_id):
            embedding_clause = "embedding: NULL,"
        query = f"""
        CREATE (n:{label} {{
            uid: $uid,
            owner_id: $owner_id,
            text: $text,
            description: $description,
            {embedding_clause}
            status: $status,
            created_at: {_EPOCH},
            updated_at: {_EPOCH},
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
            source_updated_at: $source_updated_at,
            name_norm: $name_norm,
            type: $entity_type
        }})
        RETURN {node_return_fields()}
        """
        return self.rows(query, bound)

    def create_nodes_bulk(self, *, node_type: str, rows: list, owner_id: str) -> list:
        if not rows:
            return []
        label = node_label(node_type)
        self.ensure_embedding(owner_id, len(rows[0]["emb"]))
        query = f"""
        UNWIND $rows AS row
        CREATE (n:{label} {{
            uid: row.uid,
            owner_id: $owner_id,
            text: row.text,
            description: row.description,
            embedding: row.emb,
            status: row.status,
            created_at: {_EPOCH},
            updated_at: {_EPOCH},
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
        return self.rows(
            f"""
            MATCH (n)
            WHERE n.uid = $node_id AND n.owner_id = $owner_id
            RETURN {node_return_fields()}
            """,
            {"node_id": node_id, "owner_id": owner_id},
        )

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
            f"""
            MATCH (n:Fact)
            WHERE n.uid = $node_id AND n.owner_id = $owner_id
            CREATE (v:FactVersion {{
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
                version_timestamp: {_EPOCH},
                original_created_at: n.created_at
            }})
            RETURN v.uid
            """,
            params={
                "node_id": node_id,
                "owner_id": owner_id,
                "version_uid": version_uid,
            },
        )

    def apply_node_update(self, *, set_clauses: list[str], params: dict) -> list:
        owner_id = str(params.get("owner_id") or "")
        clauses = list(set_clauses)
        if params.get("embedding"):
            self.ensure_embedding(owner_id, len(params["embedding"]))
        elif not self.embedding_ready(owner_id):
            clauses = [clause for clause in clauses if "n.embedding" not in clause]
        if not clauses:
            return self.fetch_node_row(str(params["node_id"]), owner_id)
        query = f"""
        MATCH (n)
        WHERE n.uid = $node_id AND n.owner_id = $owner_id
        SET {", ".join(clauses)}
        RETURN {node_return_fields()}
        """
        return self.rows(query, params)

    def delete_fact_versions(self, node_id: str, owner_id: str) -> Any:
        return self.query(
            """
            MATCH (v:FactVersion)
            WHERE v.fact_id = $node_id AND v.owner_id = $owner_id
            DETACH DELETE v
            """,
            params={"node_id": node_id, "owner_id": owner_id},
        )

    def delete_node_row(self, node_id: str, owner_id: str) -> list:
        return self.rows(
            """
            MATCH (n)
            WHERE n.uid = $node_id AND n.owner_id = $owner_id
            DETACH DELETE n
            RETURN count(n)
            """,
            {"node_id": node_id, "owner_id": owner_id},
        )

    def list_fact_versions(self, node_id: str, owner_id: str) -> list:
        return self.rows(
            """
            MATCH (v:FactVersion)
            WHERE v.fact_id = $node_id AND v.owner_id = $owner_id
            RETURN
                v.uid,
                v.text,
                v.metadata_str,
                v.source_str,
                v.status,
                v.ttl_days,
                v.version_timestamp,
                v.original_created_at
            ORDER BY v.version_timestamp DESC
            """,
            {"node_id": node_id, "owner_id": owner_id},
        )

    def fetch_by_source_ref(
        self, *, node_type: str, owner_id: str, source_ref: str
    ) -> list:
        label = node_label(node_type)
        return self.rows(
            f"""
            MATCH (n:{label})
            WHERE n.owner_id = $owner_id AND n.source_ref = $source_ref
            RETURN {node_return_fields()}
            LIMIT 1
            """,
            {"owner_id": owner_id, "source_ref": source_ref},
        )

    def auto_link_mentions(
        self,
        *,
        relation: str,
        owner_id: str,
        embedding: list,
        max_distance: float,
        node_id: str,
    ) -> Any:
        if not embedding or not self.embedding_ready(owner_id):
            return None
        rel = ident(relation)
        self.ensure_rel(owner_id, rel, "Fact", "Entity")
        candidates = self.rows(
            """
            MATCH (node:Entity)
            WHERE node.owner_id = $owner_id
              AND node.embedding IS NOT NULL
              AND (node.status IS NULL OR node.status = 'active')
            WITH node, 1.0 - array_cosine_similarity(node.embedding, $embedding) AS score
            WHERE score IS NOT NULL AND score <= $max_distance
            RETURN node.uid
            ORDER BY score ASC
            LIMIT 10
            """,
            {
                "owner_id": owner_id,
                "embedding": [float(v) for v in embedding],
                "max_distance": float(max_distance),
            },
        )
        linked = 0
        for row in candidates:
            created = self.rows(
                f"""
                MATCH (f:Fact), (node:Entity)
                WHERE f.uid = $node_id AND node.uid = $entity_id
                  AND f.owner_id = $owner_id AND node.owner_id = $owner_id
                MERGE (f)-[r:{rel}]->(node)
                ON CREATE SET r.created_at = {_EPOCH},
                              r.auto_linked = true,
                              r.props = '{{}}'
                RETURN r.created_at
                """,
                {
                    "node_id": node_id,
                    "entity_id": str(row[0]),
                    "owner_id": owner_id,
                },
            )
            linked += len(created)
        return linked

    def add_to_collection(self, node_id: str, collection_id: str, owner_id: str) -> list:
        rows = self.rows(
            """
            MATCH (n)
            WHERE n.uid = $node_id AND n.owner_id = $owner_id
            RETURN label(n)
            """,
            {"node_id": node_id, "owner_id": owner_id},
        )
        if not rows:
            return []
        self.ensure_rel(owner_id, "CONTAINS", "Collection", str(rows[0][0]))
        return self.rows(
            f"""
            MATCH (c:Collection), (n)
            WHERE c.uid = $collection_id AND n.uid = $node_id
              AND c.owner_id = $owner_id AND n.owner_id = $owner_id
            MERGE (c)-[r:CONTAINS]->(n)
            ON CREATE SET r.created_at = {_EPOCH}, r.auto_linked = false, r.props = '{{}}'
            RETURN count(r)
            """,
            {
                "collection_id": collection_id,
                "node_id": node_id,
                "owner_id": owner_id,
            },
        )

    def _endpoint_label(self, node_id: str, owner_id: str) -> str | None:
        rows = self.rows(
            """
            MATCH (n)
            WHERE n.uid = $node_id AND n.owner_id = $owner_id
            RETURN label(n)
            """,
            {"node_id": node_id, "owner_id": owner_id},
        )
        if not rows:
            return None
        return str(rows[0][0])

    def merge_relation(
        self,
        *,
        rel_type: str,
        params: dict,
        prop_assignments: str,
    ) -> list:
        del prop_assignments
        rel = ident(rel_type)
        owner_id = str(params["owner_id"])
        src = self._endpoint_label(str(params["from_id"]), owner_id)
        dst = self._endpoint_label(str(params["to_id"]), owner_id)
        if not src or not dst:
            return []
        self.ensure_rel(owner_id, rel, src, dst)
        extra = {
            key: value
            for key, value in params.items()
            if key not in {"from_id", "to_id", "owner_id"}
        }
        return self.rows(
            f"""
            MATCH (a:{src}), (b:{dst})
            WHERE a.uid = $from_id AND b.uid = $to_id
              AND a.owner_id = $owner_id AND b.owner_id = $owner_id
            MERGE (a)-[r:{rel}]->(b)
            ON CREATE SET r.created_at = {_EPOCH},
                          r.auto_linked = false,
                          r.props = $props
            RETURN r.created_at
            """,
            {
                "from_id": params["from_id"],
                "to_id": params["to_id"],
                "owner_id": owner_id,
                "props": _dump_props(extra),
            },
        )

    def _upsert_entity(
        self,
        *,
        uid: str,
        name_norm: str,
        owner_id: str,
        text: str,
        embedding: list | None,
        metadata_str: str,
        project: Any,
        created_by: Any,
        tags: Any,
        meta_type: Any,
        confidence: Any,
    ) -> str:
        found = self.rows(
            """
            MATCH (s:Entity)
            WHERE s.name_norm = $name_norm AND s.owner_id = $owner_id
            RETURN s.uid
            LIMIT 1
            """,
            {"name_norm": name_norm, "owner_id": owner_id},
        )
        if found:
            existing = str(found[0][0])
            self.query(
                """
                MATCH (s:Entity)
                WHERE s.uid = $uid AND s.owner_id = $owner_id
                SET s.project = CASE WHEN $project IS NULL THEN s.project ELSE $project END,
                    s.created_by = CASE WHEN $created_by IS NULL THEN s.created_by ELSE $created_by END,
                    s.tags = CASE WHEN $tags IS NULL THEN s.tags ELSE $tags END,
                    s.meta_type = CASE WHEN $meta_type IS NULL THEN s.meta_type ELSE $meta_type END,
                    s.confidence = CASE WHEN $confidence IS NULL THEN s.confidence ELSE $confidence END
                """,
                {
                    "uid": existing,
                    "owner_id": owner_id,
                    "project": project,
                    "created_by": created_by,
                    "tags": tags,
                    "meta_type": meta_type,
                    "confidence": confidence,
                },
            )
            return existing
        fields = [
            "uid: $uid",
            "owner_id: $owner_id",
            "text: $text",
            "name_norm: $name_norm",
            f"created_at: {_EPOCH}",
            f"updated_at: {_EPOCH}",
            "status: 'active'",
            "metadata_str: $metadata_str",
            "project: $project",
            "created_by: $created_by",
            "tags: $tags",
            "meta_type: $meta_type",
            "confidence: $confidence",
        ]
        bound: dict[str, Any] = {
            "uid": uid,
            "owner_id": owner_id,
            "text": text,
            "name_norm": name_norm,
            "metadata_str": metadata_str,
            "project": project,
            "created_by": created_by,
            "tags": tags,
            "meta_type": meta_type,
            "confidence": confidence,
        }
        if embedding:
            self.ensure_embedding(owner_id, len(embedding))
            fields.append("embedding: $embedding")
            bound["embedding"] = [float(v) for v in embedding]
        elif self.embedding_ready(owner_id):
            fields.append("embedding: NULL")
        self.query(
            f"CREATE (s:Entity {{{', '.join(fields)}}})",
            bound,
        )
        return uid

    def merge_triplet(
        self,
        *,
        rel_type: str,
        params: dict,
        subj_emb_expr: str,
        obj_emb_expr: str,
    ) -> list:
        del subj_emb_expr, obj_emb_expr
        rel = ident(rel_type)
        owner_id = str(params["owner_id"])
        subject_id = self._upsert_entity(
            uid=str(params["subj_uid"]),
            name_norm=str(params["subject_norm"]),
            owner_id=owner_id,
            text=str(params["subject"]),
            embedding=params.get("subj_emb"),
            metadata_str=params.get("metadata_str") or "{}",
            project=params.get("project"),
            created_by=params.get("created_by"),
            tags=params.get("tags"),
            meta_type=params.get("meta_type"),
            confidence=params.get("confidence"),
        )
        object_id = self._upsert_entity(
            uid=str(params["obj_uid"]),
            name_norm=str(params["object_norm"]),
            owner_id=owner_id,
            text=str(params["object"]),
            embedding=params.get("obj_emb"),
            metadata_str=params.get("metadata_str") or "{}",
            project=params.get("project"),
            created_by=params.get("created_by"),
            tags=params.get("tags"),
            meta_type=params.get("meta_type"),
            confidence=params.get("confidence"),
        )
        self.ensure_rel(owner_id, rel, "Entity", "Entity")
        rows = self.rows(
            f"""
            MATCH (s:Entity), (o:Entity)
            WHERE s.uid = $subject_id AND o.uid = $object_id
              AND s.owner_id = $owner_id AND o.owner_id = $owner_id
            MERGE (s)-[r:{rel}]->(o)
            ON CREATE SET r.created_at = {_EPOCH}, r.auto_linked = false, r.props = '{{}}'
            RETURN s.uid, o.uid
            """,
            {
                "subject_id": subject_id,
                "object_id": object_id,
                "owner_id": owner_id,
            },
        )
        if not rows:
            return []
        return [[rows[0][0], rows[0][1], f"{rows[0][0]}:{rel}:{rows[0][1]}"]]

    def link_extracted_from(
        self, *, fact_id: str, subject_id: str, owner_id: str
    ) -> Any:
        self.ensure_rel(owner_id, "EXTRACTED_FROM", "Fact", "Entity")
        return self.query(
            f"""
            MATCH (f:Fact), (s:Entity)
            WHERE f.uid = $fact_id AND s.uid = $subject_id
              AND f.owner_id = $owner_id AND s.owner_id = $owner_id
            MERGE (f)-[r:EXTRACTED_FROM]->(s)
            ON CREATE SET r.created_at = {_EPOCH}, r.auto_linked = false, r.props = '{{}}'
            """,
            params={
                "fact_id": fact_id,
                "subject_id": subject_id,
                "owner_id": owner_id,
            },
        )

    def search_triplet_rows(
        self, *, rel_pattern: str, where_sql: str, params: dict, limit: int
    ) -> list:
        rel = _rel_type_from_pattern(rel_pattern)
        owner_id = str(params.get("owner_id") or "")
        if rel is not None and not self.has_table(owner_id, rel):
            return []
        hop = f"[r:{ident(rel)}]" if rel else "[r]"
        return self.rows(
            f"""
            MATCH (s:Entity)-{hop}->(o:Entity)
            WHERE {where_sql}
            RETURN s.uid, s.text, label(r), o.uid, o.text, s.uid
            LIMIT {int(limit)}
            """,
            params,
        )

    def unlink_relation(self, *, rel_pattern: str, params: dict) -> list:
        rel = _rel_type_from_pattern(rel_pattern)
        owner_id = str(params.get("owner_id") or "")
        if rel is not None and not self.has_table(owner_id, rel):
            return [[0]]
        hop = f"[r:{ident(rel)}]" if rel else "[r]"
        return self.rows(
            f"""
            MATCH (a)-{hop}->(b)
            WHERE a.uid = $from_id AND b.uid = $to_id
              AND a.owner_id = $owner_id AND b.owner_id = $owner_id
            DELETE r
            RETURN count(r)
            """,
            params,
        )

    def edges_between(self, node_ids: list[str], owner_id: str) -> list:
        raw = self.rows(
            """
            MATCH (n)-[r]->(m)
            WHERE n.uid IN $node_ids AND m.uid IN $node_ids
              AND n.owner_id = $owner_id AND m.owner_id = $owner_id
            RETURN n.uid, label(r), m.uid, r.props, r.created_at, r.auto_linked
            """,
            {
                "node_ids": [str(node_id) for node_id in node_ids],
                "owner_id": owner_id,
            },
        )
        edges = []
        seen: set[tuple[Any, ...]] = set()
        for row in raw:
            key = (row[0], row[1], row[2])
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                [row[0], row[1], row[2], _props_dict(row[3], row[4], row[5])]
            )
        return edges

    def bfs_init_rows(self, ids: list, owner_id: str) -> list:
        if not ids:
            return []
        return self.rows(
            """
            MATCH (n)
            WHERE n.uid IN $ids AND n.owner_id = $owner_id
            RETURN n.uid, label(n), n.text,
                   coalesce(n.updated_at, n.created_at), coalesce(n.access_count, 0)
            """,
            {"ids": [str(item) for item in ids], "owner_id": owner_id},
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
        if not frontier or remaining <= 0:
            return []
        status_filter = ""
        if not include_outdated:
            status_filter = (
                " AND (coalesce(m.status, 'active') = 'active' "
                f"AND (m.expires_at IS NULL OR m.expires_at > {_EPOCH}))"
            )
        return self.rows(
            f"""
            MATCH (n)-[r]-(m)
            WHERE n.uid IN $frontier AND m.owner_id = $owner_id
              AND NOT m.uid IN $seen{status_filter}
            WITH m, collect(DISTINCT n.uid) AS parents
            RETURN m.uid, label(m), m.text,
                   coalesce(m.updated_at, m.created_at), coalesce(m.access_count, 0),
                   parents
            LIMIT {int(remaining)}
            """,
            {
                "frontier": [str(item) for item in frontier],
                "seen": [str(item) for item in seen],
                "owner_id": owner_id,
            },
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
                f" AND (connected.expires_at IS NULL OR connected.expires_at > {_EPOCH}))"
            )
        )
        return self.rows(
            f"""
            MATCH (center)
            WHERE center.uid = $node_id AND center.owner_id = $owner_id
            MATCH (center)-[*0..{int(depth)}]-(connected)
            WHERE connected.owner_id = $owner_id
              AND (connected.uid = center.uid OR {neighbor_ok})
            WITH DISTINCT connected
            ORDER BY connected.uid
            SKIP {int(offset)}
            LIMIT {int(limit)}
            RETURN connected.uid, label(connected), connected.text
            """,
            {"node_id": node_id, "owner_id": owner_id},
        )

    def shortest_path_row(
        self,
        *,
        directed: bool,
        max_depth: int,
        from_id: str,
        to_id: str,
        owner_id: str,
    ) -> list:
        if from_id == to_id:
            rows = self.rows(
                """
                MATCH (a)
                WHERE a.uid = $from_id AND a.owner_id = $owner_id
                RETURN a
                """,
                {"from_id": from_id, "owner_id": owner_id},
            )
            if not rows:
                return []
            return [_project_path([rows[0][0]], [])]
        hop = f"[*1..{int(max_depth)}]->" if directed else f"[*1..{int(max_depth)}]-"
        rows = self.rows(
            f"""
            MATCH path = (a)-{hop}(b)
            WHERE a.uid = $from_id AND b.uid = $to_id
              AND a.owner_id = $owner_id AND b.owner_id = $owner_id
            RETURN nodes(path), rels(path)
            ORDER BY length(path) ASC
            LIMIT 1
            """,
            {"from_id": from_id, "to_id": to_id, "owner_id": owner_id},
        )
        if not rows:
            return []
        return [_project_path(rows[0][0], rows[0][1])]

    def label_counts(self, owner_id: str) -> list:
        return self.rows(
            """
            MATCH (n)
            WHERE n.owner_id = $owner_id
              AND (label(n) = 'Fact' OR label(n) = 'Entity')
            RETURN label(n), count(n)
            """,
            {"owner_id": owner_id},
        )

    def fact_status_counts(self, owner_id: str) -> list:
        return self.rows(
            """
            MATCH (f:Fact)
            WHERE f.owner_id = $owner_id
            RETURN f.status, count(f)
            """,
            {"owner_id": owner_id},
        )

    def relation_count(self, owner_id: str) -> list:
        return self.rows(
            """
            MATCH (a)-[r]->(b)
            WHERE a.owner_id = $owner_id AND b.owner_id = $owner_id
            RETURN count(r)
            """,
            {"owner_id": owner_id},
        )

    def brief_top_facts(self, owner_id: str, limit: int) -> list:
        return self.rows(
            f"""
            MATCH (f:Fact)
            WHERE f.owner_id = $owner_id
              AND (f.status IS NULL OR f.status = 'active')
            OPTIONAL MATCH (f)-[r]-()
            WITH f, count(r) AS degree
            ORDER BY degree DESC, f.created_at DESC
            LIMIT {int(limit)}
            RETURN f.uid, f.text, degree, f.created_at
            """,
            {"owner_id": owner_id},
        )

    def brief_contradictions(self, owner_id: str) -> list:
        if not self.has_table(owner_id, "CONTRADICTS"):
            return []
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
        raw = self.rows(
            f"""
            MATCH (n)
            WHERE n.owner_id = $owner_id
              AND label(n) IN ['Fact', 'Entity', 'FactVersion']
            RETURN label(n), n
            ORDER BY n.uid{_page_clause(page_clause)}
            """,
            {"owner_id": owner_id},
        )
        exported = []
        for row in raw:
            node = row[1] if isinstance(row[1], dict) else {}
            props = {key: value for key, value in node.items() if not str(key).startswith("_")}
            exported.append([row[0], props])
        return exported

    def export_relation_rows(self, owner_id: str, page_clause: str) -> list:
        raw = self.rows(
            f"""
            MATCH (a)-[r]->(b)
            WHERE a.owner_id = $owner_id AND b.owner_id = $owner_id
            RETURN a.uid, label(r), b.uid, r.props, r.created_at, r.auto_linked
            ORDER BY a.uid, b.uid{_page_clause(page_clause)}
            """,
            {"owner_id": owner_id},
        )
        return [
            [row[0], row[1], row[2], _props_dict(row[3], row[4], row[5])] for row in raw
        ]

    def import_node_batch(
        self, *, label: str, has_emb: bool, rows: list, owner_id: str
    ) -> Any:
        node = node_label(label)
        if has_emb:
            for row in rows:
                emb = row.get("emb")
                if emb:
                    self.ensure_embedding(owner_id, len(emb))
                    break
        flat = []
        for row in rows:
            props = dict(row.get("props") or {})
            item = {column: props.get(column) for column in IMPORT_COLUMNS}
            for column in ("tags", "shared_with_ids"):
                if not isinstance(item.get(column), list):
                    item[column] = []
            item["uid"] = row["uid"]
            item["owner_id"] = owner_id
            if has_emb:
                item["emb"] = row.get("emb")
            flat.append(item)
        numeric = {
            "created_at": "INT64",
            "updated_at": "INT64",
            "expires_at": "INT64",
            "last_dedup_at": "INT64",
            "source_updated_at": "INT64",
            "access_count": "INT64",
            "last_accessed_at": "INT64",
            "version_timestamp": "INT64",
            "original_created_at": "INT64",
            "confidence": "DOUBLE",
            "ttl_days": "DOUBLE",
        }
        assignments = ", ".join(
            (
                f"n.{column} = CAST(row.{column} AS {numeric[column]})"
                if column in numeric
                else f"n.{column} = row.{column}"
            )
            for column in IMPORT_COLUMNS
        )
        emb_clause = ", n.embedding = row.emb" if has_emb else ""
        return self.query(
            f"""
            UNWIND $rows AS row
            MERGE (n:{node} {{uid: row.uid}})
            ON CREATE SET {assignments}{emb_clause}
            ON MATCH SET {assignments}{emb_clause}
            """,
            params={"rows": flat, "owner_id": owner_id},
        )

    def import_relation_batch(
        self, *, rel_type: str, rows: list, owner_id: str
    ) -> Any:
        rel = ident(rel_type)
        for row in rows:
            src = self._endpoint_label(str(row["from_id"]), owner_id)
            dst = self._endpoint_label(str(row["to_id"]), owner_id)
            if src and dst:
                self.ensure_rel(owner_id, rel, src, dst)
        prepared = []
        for row in rows:
            props = dict(row.get("props") or {})
            created_at = props.get("created_at")
            auto_linked = props.get("auto_linked")
            prepared.append(
                {
                    "from_id": row["from_id"],
                    "to_id": row["to_id"],
                    "props": _dump_props(props),
                    "created_at": created_at if isinstance(created_at, int) else None,
                    "auto_linked": bool(auto_linked) if auto_linked is not None else False,
                }
            )
        if not prepared:
            return None
        return self.query(
            f"""
            UNWIND $rows AS row
            MATCH (a), (b)
            WHERE a.uid = row.from_id AND b.uid = row.to_id
              AND a.owner_id = $owner_id AND b.owner_id = $owner_id
            MERGE (a)-[r:{rel}]->(b)
            ON CREATE SET r.props = row.props,
                          r.created_at = row.created_at,
                          r.auto_linked = row.auto_linked
            """,
            params={"rows": prepared, "owner_id": owner_id},
        )

    def graph_size_rows(self, owner_id: str) -> list:
        return self.rows(
            """
            MATCH (n)
            WHERE label(n) = 'Fact' OR label(n) = 'Entity'
            RETURN label(n), count(n)
            """,
            owner_id=owner_id,
        )

    def dedup_candidate_rows(
        self, *, label: str, owner_id: str, limit: int, touched_filter: str
    ) -> list:
        node = node_label(label)
        if touched_filter and not re.fullmatch(r"[\sANDOR0-9n._<=>$a-zA-Z()+-]*", touched_filter):
            raise ValueError("Unsupported dedup filter")
        return self.rows(
            f"""
            MATCH (n:{node})
            WHERE n.owner_id = $owner_id
              AND (n.status IS NULL OR n.status = 'active')
              AND n.embedding IS NOT NULL
              AND (
                n.last_dedup_at IS NULL
                OR n.last_dedup_at < coalesce(n.updated_at, n.created_at)
              )
              {touched_filter}
            RETURN
              n.uid,
              n.text,
              n.created_at,
              coalesce(n.updated_at, n.created_at),
              n.embedding
            ORDER BY coalesce(n.updated_at, n.created_at) ASC, n.created_at ASC, n.uid ASC
            LIMIT {int(limit)}
            """,
            {"owner_id": owner_id},
        )

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
        del ann_k
        node = node_label(label)
        if not self.embedding_ready(owner_id):
            return []
        return self.rows(
            f"""
            MATCH (node:{node})
            WHERE node.owner_id = $owner_id
              AND node.embedding IS NOT NULL
              AND node.uid <> $node_id
              AND (node.status IS NULL OR node.status = 'active')
            WITH node, 1.0 - array_cosine_similarity(node.embedding, $embedding) AS score
            WHERE score IS NOT NULL AND score <= $max_distance
            RETURN node.uid, node.created_at, score
            ORDER BY score ASC, node.created_at ASC, node.uid ASC
            LIMIT {int(top_k)}
            """,
            {
                "embedding": [float(v) for v in embedding],
                "max_distance": float(max_distance),
                "owner_id": owner_id,
                "node_id": node_id,
            },
        )

    def mark_deduped(self, *, label: str, node_ids: list, owner_id: str) -> Any:
        node = node_label(label)
        return self.query(
            f"""
            MATCH (n:{node})
            WHERE n.uid IN $node_ids AND n.owner_id = $owner_id
            SET n.last_dedup_at = {_EPOCH}
            RETURN count(n)
            """,
            params={"node_ids": node_ids, "owner_id": owner_id},
        )

    def rels_out(self, *, label: str, dup_id: str, owner_id: str) -> list:
        node = node_label(label)
        raw = self.rows(
            f"""
            MATCH (dup:{node})-[r]->(target)
            WHERE dup.uid = $dup_id AND dup.owner_id = $owner_id
            RETURN label(r), r.props, r.created_at, r.auto_linked, target.uid
            """,
            {"dup_id": dup_id, "owner_id": owner_id},
        )
        return [[row[0], _props_dict(row[1], row[2], row[3]), row[4]] for row in raw]

    def copy_rel_out(self, *, label: str, rel_type: str, params: dict) -> Any:
        return self._copy_rel(label=label, rel_type=rel_type, params=params, outgoing=True)

    def delete_rels_out(self, *, label: str, dup_id: str, owner_id: str) -> Any:
        node = node_label(label)
        return self.query(
            f"""
            MATCH (dup:{node})-[r]->()
            WHERE dup.uid = $dup_id AND dup.owner_id = $owner_id
            DELETE r
            """,
            params={"dup_id": dup_id, "owner_id": owner_id},
        )

    def rels_in(self, *, label: str, dup_id: str, owner_id: str) -> list:
        node = node_label(label)
        raw = self.rows(
            f"""
            MATCH (source)-[r]->(dup:{node})
            WHERE dup.uid = $dup_id AND dup.owner_id = $owner_id
            RETURN label(r), r.props, r.created_at, r.auto_linked, source.uid
            """,
            {"dup_id": dup_id, "owner_id": owner_id},
        )
        return [[row[0], _props_dict(row[1], row[2], row[3]), row[4]] for row in raw]

    def copy_rel_in(self, *, label: str, rel_type: str, params: dict) -> Any:
        return self._copy_rel(label=label, rel_type=rel_type, params=params, outgoing=False)

    def _copy_rel(self, *, label: str, rel_type: str, params: dict, outgoing: bool) -> Any:
        rel = ident(rel_type)
        node = node_label(label)
        owner_id = str(params["owner_id"])
        props = params.get("props") if isinstance(params.get("props"), dict) else {}
        if outgoing:
            src = self._endpoint_label(str(params["primary_id"]), owner_id) or node
            dst = self._endpoint_label(str(params["target_id"]), owner_id)
            if dst is None:
                return None
            self.ensure_rel(owner_id, rel, src, dst)
            match = f"""
            MATCH (p:{src}), (t:{dst})
            WHERE p.uid = $primary_id AND t.uid = $target_id
              AND p.owner_id = $owner_id AND t.owner_id = $owner_id
            MERGE (p)-[new_r:{rel}]->(t)
            """
            bound = {
                "primary_id": params["primary_id"],
                "target_id": params["target_id"],
                "owner_id": owner_id,
            }
        else:
            dst = self._endpoint_label(str(params["primary_id"]), owner_id) or node
            src = self._endpoint_label(str(params["source_id"]), owner_id)
            if src is None:
                return None
            self.ensure_rel(owner_id, rel, src, dst)
            match = f"""
            MATCH (s:{src}), (p:{dst})
            WHERE s.uid = $source_id AND p.uid = $primary_id
              AND s.owner_id = $owner_id AND p.owner_id = $owner_id
            MERGE (s)-[new_r:{rel}]->(p)
            """
            bound = {
                "source_id": params["source_id"],
                "primary_id": params["primary_id"],
                "owner_id": owner_id,
            }
        created_at = props.get("created_at")
        bound["props"] = _dump_props(props)
        bound["created_at"] = created_at if isinstance(created_at, int) else None
        bound["auto_linked"] = bool(props.get("auto_linked"))
        return self.query(
            match
            + """
            ON CREATE SET new_r.props = $props,
                          new_r.created_at = $created_at,
                          new_r.auto_linked = $auto_linked
            """,
            params=bound,
        )

    def delete_rels_in(self, *, label: str, dup_id: str, owner_id: str) -> Any:
        node = node_label(label)
        return self.query(
            f"""
            MATCH ()-[r]->(dup:{node})
            WHERE dup.uid = $dup_id AND dup.owner_id = $owner_id
            DELETE r
            """,
            params={"dup_id": dup_id, "owner_id": owner_id},
        )

    def mark_merged(
        self, *, label: str, dup_id: str, primary_id: str, owner_id: str
    ) -> Any:
        node = node_label(label)
        return self.query(
            f"""
            MATCH (n:{node})
            WHERE n.uid = $dup_id AND n.owner_id = $owner_id
            SET n.status = 'outdated',
                n.merged_into = $primary_id,
                n.metadata_str = coalesce(n.metadata_str, '{{}}')
            """,
            params={"dup_id": dup_id, "primary_id": primary_id, "owner_id": owner_id},
        )

    def touch_dedup_primary(self, *, label: str, primary_id: str, owner_id: str) -> Any:
        node = node_label(label)
        return self.query(
            f"""
            MATCH (n:{node})
            WHERE n.uid = $primary_id AND n.owner_id = $owner_id
            SET n.last_dedup_at = {_EPOCH}
            """,
            params={"primary_id": primary_id, "owner_id": owner_id},
        )

    def expired_fact_ids(self, owner_id: str, now_ms: int) -> list:
        return self.rows(
            """
            MATCH (f:Fact)
            WHERE f.owner_id = $owner_id
              AND (f.status IS NULL OR f.status = 'active')
              AND f.expires_at IS NOT NULL AND f.expires_at <= $now_ms
            RETURN f.uid
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
            RETURN f.uid
            """,
            {"owner_id": owner_id, "cutoff_ms": cutoff_ms},
        )

    def fact_neighbor_rows(self, fact_id: str) -> list:
        found: list = []
        for owner_id in self.list_owners():
            rows = self.rows(
                """
                MATCH (f:Fact)-[r]-(n)
                WHERE f.uid = $raw_id
                RETURN label(n), n.status
                """,
                {"raw_id": fact_id, "owner_id": owner_id},
            )
            found.extend(rows)
        return found


def _project_path(nodes: Any, rels: Any) -> list:
    node_maps = []
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        node_maps.append(
            {
                "node_id": node.get("uid"),
                "node_type": node.get("_LABEL"),
                "text": node.get("text"),
            }
        )
    rel_maps = []
    for rel in rels or []:
        if isinstance(rel, dict):
            rel_maps.append({"relation_type": rel.get("_LABEL")})
    return [node_maps, rel_maps]
