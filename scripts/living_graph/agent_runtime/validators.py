"""Guardrails around claim and edge admission."""

from __future__ import annotations

from typing import Any


GENERIC_RELATIONS = {"", "related_to", "relation", "associated_with", "connected_to"}


def validate_claim_has_evidence(claim: dict[str, Any]) -> tuple[bool, str]:
    if not str(claim.get("source_url") or "").strip():
        return False, "missing_source_url"
    if not str(claim.get("evidence_quote") or "").strip():
        return False, "missing_evidence_quote"
    if float(claim.get("confidence", 0.0) or 0.0) <= 0:
        return False, "non_positive_confidence"
    return True, "accepted"


def validate_edge_has_claim(edge: dict[str, Any]) -> tuple[bool, str]:
    if edge.get("canonical_or_derived") == "canonical" and not edge.get("claim_ref"):
        return False, "canonical_edge_without_claim"
    return True, "accepted"


def validate_no_generic_relation(edge: dict[str, Any]) -> tuple[bool, str]:
    if str(edge.get("relation_type") or "").strip() in GENERIC_RELATIONS:
        return False, "generic_relation_type"
    return True, "accepted"


def validate_no_person_clique(edge: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> tuple[bool, str]:
    if edge.get("canonical_or_derived") != "canonical":
        return True, "accepted"
    left = nodes.get(str(edge.get("from_id") or ""), {})
    right = nodes.get(str(edge.get("to_id") or ""), {})
    if left.get("category") == "person" and right.get("category") == "person":
        return False, "direct_person_person_requires_direct_evidence"
    return True, "accepted"


def validate_source_quality(source: dict[str, Any]) -> tuple[bool, str]:
    source_type = str(source.get("source_type") or "").strip()
    if source_type not in {"official_web", "official_web_cached_snapshot", "official"}:
        return False, "low_source_quality"
    return True, "accepted"

