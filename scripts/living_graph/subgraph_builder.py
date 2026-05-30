"""Build compact source-aware subgraphs for research expansion."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pipeline_common import ROOT, iso_now, stable_hash  # noqa: E402

try:
    from .question_generator import generate_research_questions, missing_fields_for_entity
    from .store import edge_rows, node_rows
except ImportError:  # pragma: no cover
    from living_graph.question_generator import generate_research_questions, missing_fields_for_entity
    from living_graph.store import edge_rows, node_rows


SUBGRAPH_DIR = ROOT / "content" / "system" / "subgraphs"
LATEST_SUBGRAPHS_FILE = SUBGRAPH_DIR / "latest.json"


def _canonical_edge(edge: dict[str, Any]) -> bool:
    return str(edge.get("layer") or "canonical").lower() == "canonical" and str(edge.get("status") or "").lower() not in {"rejected"}


def _claim_active(claim: dict[str, Any]) -> bool:
    return str(claim.get("status") or "").lower() in {"proposed", "candidate", "confirmed", "admitted", "disputed", "stale"}


def build_subgraph(graph: dict[str, Any], seed_entity_id: str, *, depth: int = 1, max_nodes: int = 40) -> dict[str, Any]:
    entities = {str(entity.get("id") or ""): entity for entity in node_rows(graph) if str(entity.get("id") or "").strip()}
    if seed_entity_id not in entities:
        return {
            "id": f"subgraph-{stable_hash(seed_entity_id, 'missing')}",
            "seed_entity_id": seed_entity_id,
            "status": "missing_seed",
            "generated_at": iso_now(),
            "nodes": [],
            "canonical_edges": [],
            "active_claims": [],
            "disputed_claims": [],
            "evidence": [],
            "missing_fields": [],
            "expansion_questions": [],
        }

    selected = {seed_entity_id}
    frontier = {seed_entity_id}
    all_edges = edge_rows(graph)
    selected_edges: list[dict[str, Any]] = []
    for _ in range(max(0, depth)):
        next_frontier: set[str] = set()
        for edge in all_edges:
            source = str(edge.get("from") or "").strip()
            target = str(edge.get("to") or "").strip()
            if source in frontier or target in frontier:
                if _canonical_edge(edge):
                    selected_edges.append(edge)
                for node_id in (source, target):
                    if node_id and node_id in entities and len(selected) < max_nodes:
                        next_frontier.add(node_id)
        selected.update(next_frontier)
        frontier = next_frontier - selected
        if not frontier:
            break

    claim_ids = {claim_id for edge in selected_edges for claim_id in edge.get("claim_ids", []) if str(claim_id).strip()}
    evidence_ids = {evidence_id for edge in selected_edges for evidence_id in edge.get("evidence_ids", []) if str(evidence_id).strip()}
    active_claims: list[dict[str, Any]] = []
    disputed_claims: list[dict[str, Any]] = []
    for claim in graph.get("claims", []) or []:
        if not isinstance(claim, dict) or not _claim_active(claim):
            continue
        claim_id = str(claim.get("id") or "")
        subject = str(claim.get("subject_vertex_id") or "")
        obj = str(claim.get("object_vertex_id") or "")
        if claim_id in claim_ids or subject in selected or obj in selected:
            target = disputed_claims if str(claim.get("status") or "").lower() == "disputed" else active_claims
            target.append(claim)
            for evidence_id in claim.get("evidence_ids", []) or []:
                evidence_ids.add(str(evidence_id))
    evidence = [
        row for row in graph.get("evidence", []) or []
        if isinstance(row, dict) and str(row.get("id") or "") in evidence_ids
    ]
    questions = [
        item for item in generate_research_questions(graph, limit=100)
        if seed_entity_id in item.get("target_entities", [])
    ][:8]
    return {
        "id": f"subgraph-{stable_hash(seed_entity_id, str(depth), str(max_nodes))}",
        "seed_entity_id": seed_entity_id,
        "seed_label": str(entities[seed_entity_id].get("name") or entities[seed_entity_id].get("label") or seed_entity_id),
        "status": "ready",
        "generated_at": iso_now(),
        "depth": depth,
        "nodes": [entities[node_id] for node_id in sorted(selected) if node_id in entities],
        "canonical_edges": selected_edges,
        "active_claims": active_claims,
        "disputed_claims": disputed_claims,
        "evidence": evidence,
        "missing_fields": missing_fields_for_entity(graph, entities[seed_entity_id]),
        "expansion_questions": questions,
    }


def build_priority_subgraphs(graph: dict[str, Any], questions: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
    seen: set[str] = set()
    subgraphs: list[dict[str, Any]] = []
    for question in questions:
        for entity_id in question.get("target_entities", []) or []:
            entity_id = str(entity_id)
            if not entity_id or entity_id in seen:
                continue
            seen.add(entity_id)
            subgraphs.append(build_subgraph(graph, entity_id, depth=1))
            if len(subgraphs) >= limit:
                return subgraphs
    return subgraphs


def write_subgraph_bundle(subgraphs: list[dict[str, Any]], path: Path = LATEST_SUBGRAPHS_FILE) -> dict[str, Any]:
    bundle = {
        "contract": "NationalSubgraphBundle.v1",
        "generated_at": iso_now(),
        "subgraph_count": len(subgraphs),
        "subgraphs": subgraphs,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return bundle
