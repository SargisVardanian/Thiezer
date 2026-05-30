#!/usr/bin/env python3
"""Build semantic edge metadata and derived relation overlays."""

from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pipeline_common import CANONICAL_GRAPH, iso_now, load_graph, stable_hash, write_json


RELATION_CLASS_BY_TYPE = {
    "holds_office_in": "institutional",
    "appointed_to": "institutional",
    "removed_from": "institutional",
    "appointed_by": "political_hierarchy",
    "part_of": "institutional",
    "leads": "political_hierarchy",
    "member_of": "membership",
    "aligned_with": "political_alignment",
    "publicly_supported": "political_alignment",
    "publicly_opposed": "conflict_or_opposition",
    "opposes": "conflict_or_opposition",
    "criticized_by": "conflict_or_opposition",
    "funded_by": "financial_relation",
    "contracted_with_state": "business_relation",
    "owns_or_controls": "business_relation",
    "beneficial_owner_reported": "business_relation",
    "subject_of_legal_case": "legal_relation",
    "investigated_by": "legal_relation",
    "watchdog_allegation": "legal_relation",
    "media_claim_disputed": "media_relation",
    "mentions": "event_co_participation",
}

CLASS_LABELS = {
    "institutional": "institutional relation",
    "membership": "membership relation",
    "political_alignment": "political alignment",
    "political_hierarchy": "political hierarchy",
    "business_relation": "business relation",
    "financial_relation": "financial relation",
    "legal_relation": "legal relation",
    "media_relation": "media relation",
    "family_relation": "family relation",
    "event_co_participation": "event co-participation",
    "conflict_or_opposition": "conflict or opposition",
    "influence_or_patronage": "influence or patronage",
    "unknown_or_weak": "weak or unknown relation",
}


def _entity_map(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}
    for key in ("vertices", "entities", "events", "event_nodes"):
        for item in graph.get(key, []) or []:
            if isinstance(item, dict) and str(item.get("id") or item.get("vertex_id") or "").strip():
                item_id = str(item.get("id") or item.get("vertex_id")).strip()
                nodes.setdefault(item_id, item)
    return nodes


def relation_class_for_type(relation_type: str) -> str:
    relation_type = str(relation_type or "").strip()
    if relation_type in RELATION_CLASS_BY_TYPE:
        return RELATION_CLASS_BY_TYPE[relation_type]
    if any(token in relation_type for token in ("office", "minister", "institution", "appointed", "removed")):
        return "institutional"
    if any(token in relation_type for token in ("ally", "aligned", "supported")):
        return "political_alignment"
    if any(token in relation_type for token in ("opposes", "conflict", "critic")):
        return "conflict_or_opposition"
    if any(token in relation_type for token in ("business", "owns", "contract", "seller", "buyer")):
        return "business_relation"
    return "unknown_or_weak"


def _node_name(node: dict[str, Any] | None, fallback: str) -> str:
    if not node:
        return fallback
    return str(node.get("name") or node.get("label") or fallback).strip() or fallback


def _role_for_node(node: dict[str, Any] | None, relation_type: str, side: str) -> str:
    if not node:
        return side
    category = str(node.get("category") or node.get("kind") or "").strip()
    subtype = str(node.get("subtype") or "").strip()
    if relation_type == "holds_office_in":
        return "office holder" if side == "from" else "office or institution"
    if relation_type == "part_of":
        return "subordinate unit" if side == "from" else "parent institution"
    if relation_type == "member_of":
        return "member" if side == "from" else "membership body"
    if relation_type == "leads":
        return "leader" if side == "from" else "led organization"
    return subtype or category or side


def mechanism_tags_for_type(relation_type: str, relation_class: str) -> list[str]:
    tags = [relation_class]
    mapping = {
        "holds_office_in": ["office holding", "institutional role"],
        "appointed_to": ["appointment", "career change"],
        "removed_from": ["dismissal", "career change"],
        "member_of": ["shared organization", "membership"],
        "leads": ["leadership", "hierarchy"],
        "part_of": ["institutional hierarchy"],
        "aligned_with": ["political alignment"],
        "opposes": ["opposition", "conflict"],
        "criticized_by": ["public criticism", "conflict"],
        "funded_by": ["funding", "financial dependence"],
        "owns_or_controls": ["ownership", "control"],
        "contracted_with_state": ["state contract", "business relation"],
        "investigated_by": ["investigation", "legal process"],
    }
    tags.extend(mapping.get(relation_type, []))
    return list(dict.fromkeys(tag for tag in tags if tag))


def semantic_edge_fields(edge: dict[str, Any], nodes: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    nodes = nodes or {}
    from_id = str(edge.get("from") or "").strip()
    to_id = str(edge.get("to") or "").strip()
    relation_type = str(edge.get("relation_type") or edge.get("type") or "related_to").strip()
    relation_class = str(edge.get("relation_class") or relation_class_for_type(relation_type)).strip()
    source = nodes.get(from_id)
    target = nodes.get(to_id)
    source_name = _node_name(source, from_id)
    target_name = _node_name(target, to_id)
    role_from = str(edge.get("role_from") or _role_for_node(source, relation_type, "from")).strip()
    role_to = str(edge.get("role_to") or _role_for_node(target, relation_type, "to")).strip()
    short_label = str(edge.get("short_label") or edge.get("human_text") or relation_type.replace("_", " ")).strip()
    semantic_summary = str(edge.get("semantic_summary") or edge.get("natural_language_summary") or edge.get("human_text") or "").strip()
    if not semantic_summary:
        semantic_summary = (
            f"{source_name} is connected to {target_name} through a {CLASS_LABELS.get(relation_class, relation_class)} "
            f"of type `{relation_type}`. The edge should be read with its supporting claims and evidence."
        )
    mechanism_tags = edge.get("mechanism_tags")
    if not isinstance(mechanism_tags, list) or not mechanism_tags:
        mechanism_tags = mechanism_tags_for_type(relation_type, relation_class)
    return {
        "relation_class": relation_class,
        "short_label": short_label[:160],
        "semantic_summary": semantic_summary[:1200],
        "role_from": role_from[:120],
        "role_to": role_to[:120],
        "mechanism_tags": mechanism_tags[:12],
        "edge_kind": str(edge.get("edge_kind") or "canonical"),
        "canonical": bool(edge.get("canonical", True)),
    }


def _rows_by_id(rows: list[Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("id") or "").strip(): row
        for row in rows
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }


def _claim_cards(graph: dict[str, Any], relation: dict[str, Any]) -> list[dict[str, Any]]:
    claim_map = _rows_by_id(graph.get("claims", []) or [])
    claim_ids = [str(item).strip() for item in relation.get("claim_ids", []) or [] if str(item).strip()]
    cards = [claim_map[item] for item in claim_ids if item in claim_map]
    if cards:
        return cards[:12]
    from_id = str(relation.get("from") or "").strip()
    to_id = str(relation.get("to") or "").strip()
    relation_type = str(relation.get("relation_type") or relation.get("type") or "").strip()
    for claim in graph.get("claims", []) or []:
        if not isinstance(claim, dict):
            continue
        endpoints = {str(claim.get("subject_vertex_id") or "").strip(), str(claim.get("object_vertex_id") or "").strip()}
        if {from_id, to_id} <= endpoints and (not relation_type or str(claim.get("claim_type") or "") == relation_type):
            cards.append(claim)
    return cards[:12]


def _evidence_cards(graph: dict[str, Any], relation: dict[str, Any]) -> list[dict[str, Any]]:
    evidence_map = _rows_by_id(graph.get("evidence", []) or [])
    source_map = _rows_by_id(graph.get("sources", []) or [])
    evidence_ids = [str(item).strip() for item in relation.get("evidence_ids", []) or [] if str(item).strip()]
    source_ids = [str(item).strip() for item in relation.get("source_ids", []) or [] if str(item).strip()]
    cards: list[dict[str, Any]] = []
    for evidence_id in evidence_ids:
        row = dict(evidence_map.get(evidence_id, {"id": evidence_id}))
        cards.append(row)
    if relation.get("source_url") or relation.get("evidence_quote"):
        cards.append(
            {
                "id": f"evidence-inline-{stable_hash(relation.get('id', ''), relation.get('source_url', ''), relation.get('evidence_quote', ''))}",
                "quote": str(relation.get("evidence_quote") or relation.get("notes") or "").strip(),
                "source_url": str(relation.get("source_url") or "").strip(),
                "source_title": str(relation.get("source_title") or "").strip(),
            }
        )
    for source_id in source_ids:
        source = source_map.get(source_id)
        if source:
            cards.append({"id": source_id, "source": source})
    return cards[:16]


def _basis_paths(graph: dict[str, Any], relation: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    edge_map = _rows_by_id((graph.get("edges", []) or []) + (graph.get("relations", []) or []))
    paths = []
    for path in relation.get("basis_paths", []) or []:
        if not isinstance(path, list):
            continue
        paths.append(
            {
                "node_ids": [str(item) for item in path],
                "labels": [_node_name(nodes.get(str(item)), str(item)) for item in path],
            }
        )
    basis_edges = []
    for edge_id in relation.get("basis_edge_ids", []) or []:
        edge = edge_map.get(str(edge_id))
        if edge:
            basis_edges.append(
                {
                    "id": edge_id,
                    "from": edge.get("from"),
                    "to": edge.get("to"),
                    "relation_type": edge.get("relation_type") or edge.get("type"),
                    "confidence": edge.get("confidence"),
                }
            )
    if not paths and basis_edges:
        paths.append({"node_ids": [], "labels": [], "basis_edges": basis_edges})
    elif paths:
        paths[0]["basis_edges"] = basis_edges
    return paths[:8]


def relationship_dossier(graph: dict[str, Any], relation: dict[str, Any]) -> dict[str, Any]:
    """Build the model-facing RelationshipDossierContract for an edge or derived relation."""
    nodes = _entity_map(graph)
    fields = semantic_edge_fields(relation, nodes)
    from_id = str(relation.get("from") or "").strip()
    to_id = str(relation.get("to") or "").strip()
    from_name = _node_name(nodes.get(from_id), from_id)
    to_name = _node_name(nodes.get(to_id), to_id)
    direct_claims = _claim_cards(graph, relation)
    evidence = _evidence_cards(graph, relation)
    derived_paths = _basis_paths(graph, relation, nodes)
    canonical = bool(fields.get("canonical"))
    raw_status = str(relation.get("status") or ("confirmed" if canonical and evidence else "derived" if not canonical else "unverified"))
    has_claim_refs = bool([item for item in relation.get("claim_ids", []) or [] if str(item).strip()])
    has_evidence_refs = bool(
        [item for item in relation.get("evidence_ids", []) or [] if str(item).strip()]
        or [item for item in relation.get("source_ids", []) or [] if str(item).strip()]
        or str(relation.get("source_url") or relation.get("evidence_quote") or "").strip()
    )
    effective_status = "unverified" if raw_status == "confirmed" and not has_claim_refs and not has_evidence_refs else raw_status
    return {
        "contract": "RelationshipDossierContract.v1",
        "id": str(relation.get("id") or stable_hash(from_id, to_id, relation.get("relation_type") or relation.get("type") or "")),
        "pair_id": "__".join(sorted([from_id, to_id])),
        "from": {"id": from_id, "name": from_name},
        "to": {"id": to_id, "name": to_name},
        "relation_type": str(relation.get("relation_type") or relation.get("type") or "").strip(),
        "relation_class": fields.get("relation_class"),
        "relation_title": str(relation.get("relation_title") or fields.get("short_label") or "").strip(),
        "short_label": fields.get("short_label"),
        "semantic_summary": fields.get("semantic_summary"),
        "role_from": fields.get("role_from"),
        "role_to": fields.get("role_to"),
        "mechanisms": fields.get("mechanism_tags", []),
        "timeline": relation.get("timeline") or [],
        "direct_claims": direct_claims,
        "derived_paths": derived_paths,
        "evidence": evidence,
        "claim_ids": [str(item) for item in relation.get("claim_ids", []) or [] if str(item).strip()],
        "evidence_ids": [str(item) for item in relation.get("evidence_ids", []) or [] if str(item).strip()],
        "source_ids": [str(item) for item in relation.get("source_ids", []) or [] if str(item).strip()],
        "confidence": round(float(relation.get("confidence", 0.0) or 0.0), 3),
        "status": effective_status,
        "canonical_or_derived": "canonical" if canonical else "derived",
        "canonical": canonical,
        "edge_kind": fields.get("edge_kind"),
        "source_url": str(relation.get("source_url") or "").strip(),
        "updated_at": str(relation.get("updated_at") or ""),
    }


def relationship_dossier_for_id(graph: dict[str, Any], relation_id: str) -> dict[str, Any]:
    relation_id = str(relation_id or "").strip()
    for relation in [*(graph.get("edges", []) or []), *(graph.get("relations", []) or []), *(graph.get("derived_relations", []) or [])]:
        if isinstance(relation, dict) and str(relation.get("id") or "").strip() == relation_id:
            return relationship_dossier(graph, relation)
    return {}


def relationship_dossier_for_pair(graph: dict[str, Any], from_id: str, to_id: str) -> dict[str, Any]:
    wanted = {str(from_id or "").strip(), str(to_id or "").strip()}
    if len(wanted) != 2 or not all(wanted):
        return {}
    candidates = []
    for relation in [*(graph.get("edges", []) or []), *(graph.get("relations", []) or []), *(graph.get("derived_relations", []) or [])]:
        if not isinstance(relation, dict):
            continue
        endpoints = {str(relation.get("from") or "").strip(), str(relation.get("to") or "").strip()}
        if endpoints == wanted:
            candidates.append(relation)
    if not candidates:
        return {}

    def support_rank(row: dict[str, Any]) -> tuple[int, float, str]:
        claim_ids = [item for item in row.get("claim_ids", []) or [] if str(item).strip()]
        has_evidence = bool(
            [item for item in row.get("evidence_ids", []) or [] if str(item).strip()]
            or [item for item in row.get("source_ids", []) or [] if str(item).strip()]
            or str(row.get("source_url") or row.get("evidence_quote") or "").strip()
        )
        status = str(row.get("status") or "").strip().lower()
        canonical = bool(row.get("canonical", True))
        if canonical and status == "confirmed" and claim_ids and has_evidence:
            tier = 5
        elif canonical and status == "confirmed" and has_evidence:
            tier = 4
        elif canonical and status in {"observed", "probable"}:
            tier = 3
        elif not canonical or str(row.get("edge_kind") or "") == "derived":
            tier = 2
        else:
            tier = 1
        return (tier, float(row.get("confidence", 0.0) or 0.0), str(row.get("updated_at") or ""))

    candidates.sort(key=support_rank, reverse=True)
    return relationship_dossier(graph, candidates[0])


def enrich_edges(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = _entity_map(graph)
    updated = 0
    for edge in graph.get("edges", []) or []:
        if not isinstance(edge, dict):
            continue
        fields = semantic_edge_fields(edge, nodes)
        for key, value in fields.items():
            if edge.get(key) != value:
                edge[key] = value
                updated += 1
    graph.setdefault("runtime", {})["semantic_edge_builder"] = {
        "updated_at": iso_now(),
        "edges_touched": updated,
        "derived_relations": len(graph.get("derived_relations", []) or []),
    }
    graph["updated_at"] = iso_now()
    return graph


def build_derived_relations(graph: dict[str, Any], *, limit: int = 160) -> list[dict[str, Any]]:
    nodes = _entity_map(graph)
    person_ids = {
        node_id
        for node_id, node in nodes.items()
        if str(node.get("category") or "").strip() == "person"
    }
    hub_edges: dict[str, list[dict[str, Any]]] = {}
    for edge in graph.get("edges", []) or []:
        if not isinstance(edge, dict):
            continue
        relation_type = str(edge.get("relation_type") or edge.get("type") or "").strip()
        if relation_type not in {"member_of", "holds_office_in", "leads", "aligned_with"}:
            continue
        source = str(edge.get("from") or "").strip()
        target = str(edge.get("to") or "").strip()
        if source not in person_ids or not target:
            continue
        hub = nodes.get(target, {})
        hub_category = str(hub.get("category") or hub.get("subtype") or "").strip()
        if hub_category not in {"party", "institution", "organization", "government", "ministry"}:
            continue
        hub_edges.setdefault(target, []).append(edge)

    derived: list[dict[str, Any]] = []
    for hub_id, edges in sorted(hub_edges.items(), key=lambda item: len(item[1]), reverse=True):
        if len(edges) < 2:
            continue
        hub_name = _node_name(nodes.get(hub_id), hub_id)
        for left, right in combinations(edges[:24], 2):
            left_id = str(left.get("from") or "")
            right_id = str(right.get("from") or "")
            if not left_id or not right_id or left_id == right_id:
                continue
            a, b = sorted([left_id, right_id])
            relation_types = {str(left.get("relation_type") or ""), str(right.get("relation_type") or "")}
            relation_class = "political_hierarchy" if "leads" in relation_types else "political_alignment"
            left_name = _node_name(nodes.get(a), a)
            right_name = _node_name(nodes.get(b), b)
            claim_ids = list(dict.fromkeys([*(left.get("claim_ids", []) or []), *(right.get("claim_ids", []) or [])]))
            evidence_ids = list(dict.fromkeys([*(left.get("evidence_ids", []) or []), *(right.get("evidence_ids", []) or [])]))
            confidence = min(float(left.get("confidence", 0.0) or 0.0), float(right.get("confidence", 0.0) or 0.0), 0.82)
            edge_id = f"derived-{stable_hash(a, b, hub_id, ','.join(sorted(relation_types)))}"
            derived.append(
                {
                    "id": edge_id,
                    "from": a,
                    "to": b,
                    "relation_class": relation_class,
                    "relation_type": "derived_shared_institutional_path",
                    "short_label": f"connected via {hub_name}",
                    "semantic_summary": (
                        f"{left_name} and {right_name} are connected through {hub_name}. "
                        "This is a derived semantic relation based on canonical edges, not a separate canonical fact."
                    ),
                    "role_from": "participant in shared structure",
                    "role_to": "participant in shared structure",
                    "mechanism_tags": ["derived relation", "shared institution", relation_class],
                    "basis_paths": [[a, hub_id, b]],
                    "basis_edge_ids": [str(left.get("id") or ""), str(right.get("id") or "")],
                    "claim_ids": claim_ids,
                    "evidence_ids": evidence_ids,
                    "confidence": round(confidence, 3),
                    "canonical": False,
                    "edge_kind": "derived_relation",
                    "status": "derived",
                    "updated_at": iso_now(),
                }
            )
            if len(derived) >= limit:
                return derived
    return derived


def apply_semantic_layer(graph: dict[str, Any]) -> dict[str, Any]:
    graph = enrich_edges(graph)
    graph["derived_relations"] = build_derived_relations(graph)
    graph.setdefault("runtime", {})["semantic_edge_builder"] = {
        "updated_at": iso_now(),
        "edges_touched": len(graph.get("edges", []) or []),
        "derived_relations": len(graph.get("derived_relations", []) or []),
    }
    graph["updated_at"] = iso_now()
    return graph


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enrich graph edges with semantic UI fields and derived relation overlays.")
    parser.add_argument("--graph", type=Path, default=CANONICAL_GRAPH)
    parser.add_argument("--apply", action="store_true", help="Write semantic fields back to the graph.")
    args = parser.parse_args(argv)
    graph = load_graph() if args.graph == CANONICAL_GRAPH else json.loads(args.graph.read_text(encoding="utf-8"))
    graph = apply_semantic_layer(graph)
    payload = {
        "ok": True,
        "edges": len(graph.get("edges", []) or []),
        "derived_relations": len(graph.get("derived_relations", []) or []),
        "sample": graph.get("derived_relations", [])[:3],
    }
    if args.apply:
        write_json(args.graph, graph)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
