"""Relationship dossier contracts and ranking."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from semantic_edge_builder import (  # noqa: E402
    relationship_dossier,
    relationship_dossier_for_id,
    semantic_edge_fields,
)


def relation_support_level(relation: dict[str, Any]) -> int:
    claim_ids = [item for item in relation.get("claim_ids", []) or [] if str(item).strip()]
    evidence_ids = [item for item in relation.get("evidence_ids", []) or [] if str(item).strip()]
    source_ids = [item for item in relation.get("source_ids", []) or [] if str(item).strip()]
    has_inline_evidence = bool(str(relation.get("source_url") or relation.get("evidence_quote") or "").strip())
    has_evidence = bool(evidence_ids or source_ids or has_inline_evidence)
    status = str(relation.get("status") or "").strip().lower()
    canonical = bool(relation.get("canonical", True))
    if canonical and status == "confirmed" and claim_ids and has_evidence:
        return 5
    if canonical and status == "confirmed" and has_evidence:
        return 4
    if canonical and status in {"observed", "probable"}:
        return 3
    if not canonical or str(relation.get("edge_kind") or "") == "derived":
        return 2
    return 1


def effective_status(relation: dict[str, Any]) -> str:
    status = str(relation.get("status") or "").strip() or "observed"
    claim_ids = [item for item in relation.get("claim_ids", []) or [] if str(item).strip()]
    evidence_ids = [item for item in relation.get("evidence_ids", []) or [] if str(item).strip()]
    source_ids = [item for item in relation.get("source_ids", []) or [] if str(item).strip()]
    has_inline_evidence = bool(str(relation.get("source_url") or relation.get("evidence_quote") or "").strip())
    if status == "confirmed" and not claim_ids and not evidence_ids and not source_ids and not has_inline_evidence:
        return "unverified"
    return status


def dossier_for_pair(graph: dict[str, Any], from_id: str, to_id: str) -> dict[str, Any]:
    wanted = {str(from_id or "").strip(), str(to_id or "").strip()}
    if len(wanted) != 2 or not all(wanted):
        return {}
    candidates: list[dict[str, Any]] = []
    for relation in [*(graph.get("edges", []) or []), *(graph.get("relations", []) or []), *(graph.get("derived_relations", []) or [])]:
        if not isinstance(relation, dict):
            continue
        endpoints = {str(relation.get("from") or "").strip(), str(relation.get("to") or "").strip()}
        if endpoints == wanted:
            candidates.append(relation)
    if not candidates:
        return {}
    candidates.sort(
        key=lambda row: (
            relation_support_level(row),
            float(row.get("confidence", 0.0) or 0.0),
            str(row.get("updated_at") or ""),
        ),
        reverse=True,
    )
    dossier = relationship_dossier(graph, candidates[0])
    dossier["status"] = effective_status(candidates[0])
    return dossier

