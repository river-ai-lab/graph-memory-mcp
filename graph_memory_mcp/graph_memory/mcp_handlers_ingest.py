"""Document/conversation ingest: one call to persist agent-extracted knowledge.

Extraction stays with the agent (it is the LLM); the server provides a single
reliable, idempotent write: source node, facts with provenance
(`source.ref = "{document.ref}#{fact.ref|hash(text)}"`), EXTRACTED_FROM links,
and triplets. Re-ingesting the same fact ref updates in place instead of duplicating.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, List, Optional

from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.mcp_handlers_nodes import upsert_node
from graph_memory_mcp.graph_memory.mcp_handlers_relations import (
    create_relation,
    create_triplet,
)
from graph_memory_mcp.graph_memory.utils import (
    ensure_text,
    error_response,
    mcp_handler,
    normalize_owner_id,
    success_response,
)

logger = logging.getLogger(__name__)

_INGEST_MAX_FACTS = 200
_INGEST_MAX_TRIPLETS = 200
_FACT_REF_RE = re.compile(r"^[a-zA-Z0-9_.:@/-]{1,128}$")


def _fact_source_ref(doc_ref: str, fact: Dict[str, Any]) -> str:
    """Stable provenance key: explicit fact.ref/id, else hash(text)."""
    explicit = ensure_text(fact.get("ref") or fact.get("id"))
    if explicit:
        explicit = explicit.strip()
        if explicit.startswith(f"{doc_ref}#"):
            return explicit
        if not _FACT_REF_RE.match(explicit):
            raise ValueError(
                "facts[].ref must be alphanumeric plus _.:@/- (or omit for hash)"
            )
        return f"{doc_ref}#{explicit}"
    text = ensure_text(fact.get("text")) or ""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"{doc_ref}#{digest}"


@mcp_handler
def ingest_knowledge(
    db: FalkorDBClient,
    config: Any,
    *,
    document: Dict[str, Any],
    facts: Optional[List[Dict[str, Any]]] = None,
    triplets: Optional[List[Dict[str, Any]]] = None,
    owner_id: str = "default",
    auto_link: bool = False,
) -> Dict:
    """Persist knowledge extracted from one document/conversation.

    document: {ref (required), title?, uri?, type?}
    facts: [{text (required), ref?/id?, metadata?, ttl_days?, description?}]
    triplets: [{subject, predicate, object (all required), metadata?}]
    """
    owner_id = normalize_owner_id(owner_id)
    facts = facts or []
    triplets = triplets or []

    doc_ref = ensure_text((document or {}).get("ref"))
    if not doc_ref or not doc_ref.strip():
        return error_response(
            "document.ref is required", code="memory_validation_error"
        )
    doc_ref = doc_ref.strip()
    if not facts and not triplets:
        return error_response(
            "Nothing to ingest: provide facts and/or triplets",
            code="memory_validation_error",
        )
    if len(facts) > _INGEST_MAX_FACTS:
        return error_response(
            f"Too many facts (max {_INGEST_MAX_FACTS})",
            code="memory_validation_error",
        )
    if len(triplets) > _INGEST_MAX_TRIPLETS:
        return error_response(
            f"Too many triplets (max {_INGEST_MAX_TRIPLETS})",
            code="memory_validation_error",
        )
    for i, fact in enumerate(facts):
        if not isinstance(fact, dict) or not ensure_text(fact.get("text")):
            return error_response(
                f"facts[{i}].text is required", code="memory_validation_error"
            )
    for i, triplet in enumerate(triplets):
        if not isinstance(triplet, dict) or not all(
            ensure_text(triplet.get(k)) for k in ("subject", "predicate", "object")
        ):
            return error_response(
                f"triplets[{i}] requires subject, predicate, object",
                code="memory_validation_error",
            )

    # 1) Source node (Entity), idempotent by document.ref.
    doc_result = upsert_node(
        db,
        config,
        text=ensure_text(document.get("title")) or doc_ref,
        node_type="Entity",
        owner_id=owner_id,
        entity_type=ensure_text(document.get("type")) or "document",
        source={
            "ref": doc_ref,
            "uri": ensure_text(document.get("uri")),
            "type": ensure_text(document.get("type")) or "document",
        },
        auto_link=False,
    )
    if not doc_result.get("success"):
        return doc_result
    document_id = doc_result["node"]["node_id"]

    # 2) Facts, idempotent by stable ref; linked EXTRACTED_FROM -> document.
    fact_results: List[Dict[str, Any]] = []
    link_errors: List[Dict[str, Any]] = []
    for i, fact in enumerate(facts):
        try:
            fact_ref = _fact_source_ref(doc_ref, fact)
        except ValueError as exc:
            return error_response(f"facts[{i}]: {exc}", code="memory_validation_error")
        result = upsert_node(
            db,
            config,
            text=str(fact["text"]),
            description=ensure_text(fact.get("description")),
            node_type="Fact",
            owner_id=owner_id,
            metadata=fact.get("metadata"),
            ttl_days=fact.get("ttl_days"),
            source={"ref": fact_ref, "type": "extracted", "uri": doc_ref},
            auto_link=auto_link,
        )
        if not result.get("success"):
            result["ref"] = fact_ref
            fact_results.append(result)
            continue

        fact_id = result["node"]["node_id"]
        link = create_relation(
            db,
            from_id=fact_id,
            to_id=document_id,
            relation_type="EXTRACTED_FROM",
            owner_id=owner_id,
            config=config,
        )
        if not link.get("success"):
            link_errors.append(
                {"from_id": fact_id, "to_id": document_id, "error": link.get("error")}
            )

        entry: Dict[str, Any] = {
            "node_id": fact_id,
            "ref": fact_ref,
            "operation": result.get("operation"),
        }
        if result.get("possible_duplicates"):
            entry["possible_duplicates"] = result["possible_duplicates"]
        fact_results.append(entry)

    # 3) Triplets (entities merge by normalized name).
    triplet_results: List[Dict[str, Any]] = []
    for triplet in triplets:
        result = create_triplet(
            db,
            subject=str(triplet["subject"]),
            predicate=str(triplet["predicate"]),
            object_value=str(triplet["object"]),
            metadata=triplet.get("metadata"),
            owner_id=owner_id,
            config=config,
        )
        if result.get("success"):
            triplet_results.append(result["triplet"])
        else:
            triplet_results.append({"error": result.get("error"), "triplet": triplet})

    response = success_response(
        document_id=document_id,
        document_operation=doc_result.get("operation"),
        facts=fact_results,
        triplets=triplet_results,
        fact_count=len([f for f in fact_results if "node_id" in f]),
        triplet_count=len([t for t in triplet_results if "error" not in t]),
    )
    if link_errors:
        response["link_errors"] = link_errors
    return response
