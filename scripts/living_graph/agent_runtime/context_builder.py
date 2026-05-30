"""Compact per-item context assembly."""

from __future__ import annotations

from typing import Any

try:
    from ..profiles import card_for_node
    from ..store import load_graph
except ImportError:  # pragma: no cover
    from living_graph.profiles import card_for_node
    from living_graph.store import load_graph


def build_work_item_context(graph: dict[str, Any], item: dict[str, Any], source_texts: list[dict[str, Any]]) -> dict[str, Any]:
    entity_id = str(item.get("entity_id") or "")
    entity_card = card_for_node(graph, entity_id) if entity_id else {}
    known_claims = [
        claim
        for claim in graph.get("claims", []) or []
        if isinstance(claim, dict) and entity_id and entity_id in {str(claim.get("subject_vertex_id") or ""), str(claim.get("object_vertex_id") or "")}
    ][:12]
    neighbor_summary = []
    for relation in graph.get("relations", []) or []:
        if not isinstance(relation, dict):
            continue
        left = str(relation.get("from") or "")
        right = str(relation.get("to") or "")
        if entity_id not in {left, right}:
            continue
        neighbor_summary.append(
            {
                "relation_type": relation.get("relation_type") or relation.get("type") or "",
                "other_id": right if left == entity_id else left,
                "status": relation.get("status") or "",
                "confidence": relation.get("confidence") or 0,
            }
        )
        if len(neighbor_summary) >= 12:
            break
    return {
        "task": {"item_type": item.get("item_type"), "title": item.get("title"), "input": item.get("input_json", {})},
        "entity_card": entity_card,
        "known_claims": known_claims,
        "neighbor_summary": neighbor_summary,
        "source_texts": source_texts[:2],
        "output_schema": {
            "entity": {},
            "profile_update": {},
            "claims": [],
            "edges": [],
        },
    }

