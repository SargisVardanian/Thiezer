"""Deterministic graph-gap research question generation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pipeline_common import EXPLORATION_QUEUE_FILE, iso_now, stable_hash  # noqa: E402

try:
    from .store import edge_rows, node_rows
except ImportError:  # pragma: no cover
    from living_graph.store import edge_rows, node_rows


QUESTION_TYPES = {
    "biography_completion",
    "office_tenure_completion",
    "party_membership",
    "municipality_roster_completion",
    "company_ownership_control",
    "procurement_contract_relation",
    "legal_case_relation",
    "financial_network_expansion",
    "contradiction_resolution",
    "source_confirmation",
    "stale_information_recheck",
    "subgraph_expansion",
}

BOILERPLATE_LABELS = {
    "site map",
    "sitemap",
    "home",
    "contact",
    "privacy policy",
    "terms of use",
    "search",
}


def entity_kind(entity: dict[str, Any]) -> str:
    return str(entity.get("category") or entity.get("entity_type") or entity.get("kind") or "").strip().upper()


def entity_label(entity: dict[str, Any]) -> str:
    return str(entity.get("name") or entity.get("label") or entity.get("canonical_name") or entity.get("id") or "").strip()


def eligible_entity(entity: dict[str, Any]) -> bool:
    label = entity_label(entity)
    if not label:
        return False
    lowered = label.lower().strip()
    if lowered in BOILERPLATE_LABELS:
        return False
    if lowered.startswith(("read more", "learn more", "print version")):
        return False
    return True


def _edge_type(edge: dict[str, Any]) -> str:
    return str(edge.get("relation_type") or edge.get("type") or "").strip()


def _entity_edges(graph: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_entity: dict[str, list[dict[str, Any]]] = {}
    for edge in edge_rows(graph):
        source = str(edge.get("from") or "").strip()
        target = str(edge.get("to") or "").strip()
        if source:
            by_entity.setdefault(source, []).append(edge)
        if target:
            by_entity.setdefault(target, []).append(edge)
    return by_entity


def _search_queries(label: str, question_type: str) -> dict[str, list[str]]:
    base = label.strip()
    if not base:
        return {"hy": [], "ru": [], "en": []}
    if question_type == "company_ownership_control":
        return {
            "hy": [f"{base} սեփականատեր տնօրեն գրանցամատյան"],
            "ru": [f"{base} владелец директор реестр Армения"],
            "en": [f"{base} owner director Armenia registry"],
        }
    if question_type == "municipality_roster_completion":
        return {
            "hy": [f"{base} համայնք ավագանի քաղաքապետ"],
            "ru": [f"{base} муниципалитет мэр совет Армения"],
            "en": [f"{base} municipality mayor council Armenia"],
        }
    if question_type == "office_tenure_completion":
        return {
            "hy": [f"{base} նշանակվել ազատվել պաշտոն"],
            "ru": [f"{base} назначен освобожден должность Армения"],
            "en": [f"{base} appointed dismissed office Armenia"],
        }
    return {
        "hy": [f"{base} կենսագրություն պաշտոն կուսակցություն"],
        "ru": [f"{base} биография должность партия Армения"],
        "en": [f"{base} biography office party Armenia"],
    }


def _question(
    *,
    question_type: str,
    text: str,
    target_entities: list[str],
    expected_claim_types: list[str],
    priority: float,
    reason: str,
    source_types: list[str],
    label: str,
    budget_pages: int = 6,
) -> dict[str, Any]:
    priority = round(max(0.0, min(1.0, priority)), 3)
    question_id = f"q-{stable_hash(question_type, text, ','.join(target_entities))}"
    return {
        "id": question_id,
        "question_type": question_type,
        "question": text,
        "target_entities": target_entities,
        "expected_claim_types": expected_claim_types,
        "priority_score": priority,
        "reason": reason,
        "suggested_source_types": source_types,
        "search_queries": _search_queries(label, question_type),
        "budget_estimate": {"pages": budget_pages, "max_depth": 2},
        "status": "queued",
        "created_at": iso_now(),
    }


def missing_fields_for_entity(graph: dict[str, Any], entity: dict[str, Any]) -> list[str]:
    kind = entity_kind(entity)
    edges = _entity_edges(graph).get(str(entity.get("id") or ""), [])
    edge_types = {_edge_type(edge) for edge in edges}
    profile = entity.get("profile", {}) if isinstance(entity.get("profile"), dict) else {}
    missing: list[str] = []
    if kind == "PERSON":
        if not profile.get("history_or_biography") and not profile.get("biography"):
            missing.append("biography")
        if "holds_office_in" not in edge_types:
            missing.append("office_history")
        if "member_of" not in edge_types:
            missing.append("party_or_faction_membership")
    elif kind == "OFFICE":
        if "holds_office_in" not in edge_types:
            missing.append("office_holders")
        if not entity.get("valid_from"):
            missing.append("legal_basis_or_creation_date")
    elif kind in {"COMPANY", "LEGAL_ENTITY"}:
        if not ({"owns_or_controls", "beneficial_owner_reported"} & edge_types):
            missing.append("ownership_or_control")
        if "contracted_with_state" not in edge_types:
            missing.append("state_contracts")
    elif kind == "MUNICIPALITY":
        if not ({"leads", "holds_office_in", "member_of"} & edge_types):
            missing.append("mayor_and_council_roster")
    elif kind in {"LEGAL_CASE", "PROCUREMENT_CONTRACT"}:
        if not edges:
            missing.append("linked_parties")
    return missing


def generate_research_questions(graph: dict[str, Any], *, limit: int = 50) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    entities = node_rows(graph)
    edges_by_entity = _entity_edges(graph)
    for entity in entities:
        entity_id = str(entity.get("id") or "").strip()
        if not entity_id or not eligible_entity(entity):
            continue
        kind = entity_kind(entity)
        label = entity_label(entity)
        missing = missing_fields_for_entity(graph, entity)
        if "biography" in missing:
            questions.append(
                _question(
                    question_type="biography_completion",
                    text=f"Complete a source-backed biography profile for {label}.",
                    target_entities=[entity_id],
                    expected_claim_types=["biography_fact", "education", "career_role", "party_membership"],
                    priority=0.72,
                    reason="Person vertex has a thin or missing biography profile.",
                    source_types=["official", "legal", "media"],
                    label=label,
                )
            )
        if "office_history" in missing or "office_holders" in missing:
            questions.append(
                _question(
                    question_type="office_tenure_completion",
                    text=f"Find temporal office-holder claims and dates for {label}.",
                    target_entities=[entity_id],
                    expected_claim_types=["HOLDS_OFFICE", "APPOINTED_TO", "DISMISSED_FROM"],
                    priority=0.86 if kind == "OFFICE" else 0.78,
                    reason="Office/person history is incomplete; country graph needs temporal role edges.",
                    source_types=["official", "legal"],
                    label=label,
                )
            )
        if "party_or_faction_membership" in missing:
            questions.append(
                _question(
                    question_type="party_membership",
                    text=f"Determine party and parliamentary faction membership history for {label}.",
                    target_entities=[entity_id],
                    expected_claim_types=["MEMBER_OF", "LEADS", "LEFT_PARTY"],
                    priority=0.7,
                    reason="Political affiliation is a high-value gap for national graph traversal.",
                    source_types=["official", "party", "media"],
                    label=label,
                )
            )
        if "ownership_or_control" in missing:
            questions.append(
                _question(
                    question_type="company_ownership_control",
                    text=f"Map owners, directors, and control signals for {label}.",
                    target_entities=[entity_id],
                    expected_claim_types=["OWNS_OR_CONTROLS", "DIRECTOR_OF", "BENEFICIAL_OWNER_REPORTED"],
                    priority=0.82,
                    reason="Company vertex lacks ownership/control relations.",
                    source_types=["official_registry", "procurement", "watchdog"],
                    label=label,
                    budget_pages=10,
                )
            )
        if "state_contracts" in missing:
            questions.append(
                _question(
                    question_type="procurement_contract_relation",
                    text=f"Search for public procurement and state contract relations involving {label}.",
                    target_entities=[entity_id],
                    expected_claim_types=["CONTRACTED_WITH_STATE", "BENEFITED_ENTITY", "FUNDED_BY"],
                    priority=0.76,
                    reason="Financial interaction coverage is missing for this company/legal entity.",
                    source_types=["procurement", "official", "watchdog"],
                    label=label,
                    budget_pages=10,
                )
            )
        if "mayor_and_council_roster" in missing:
            questions.append(
                _question(
                    question_type="municipality_roster_completion",
                    text=f"Build the mayor and council roster subgraph for {label}.",
                    target_entities=[entity_id],
                    expected_claim_types=["HOLDS_OFFICE", "MEMBER_OF", "LEADS"],
                    priority=0.74,
                    reason="Municipality vertex lacks local governance roster coverage.",
                    source_types=["official", "municipal", "legal"],
                    label=label,
                    budget_pages=12,
                )
            )
        if len(edges_by_entity.get(entity_id, [])) >= 4:
            questions.append(
                _question(
                    question_type="subgraph_expansion",
                    text=f"Expand and verify the local subgraph around {label}.",
                    target_entities=[entity_id],
                    expected_claim_types=["MENTIONS", "MEMBER_OF", "HOLDS_OFFICE", "OWNS_OR_CONTROLS"],
                    priority=0.55,
                    reason="Entity already has graph density; expansion can reveal missing adjacent actors.",
                    source_types=["official", "media", "watchdog"],
                    label=label,
                )
            )

    for claim in graph.get("claims", []) or []:
        if not isinstance(claim, dict):
            continue
        status = str(claim.get("status") or "").lower()
        claim_id = str(claim.get("id") or "").strip()
        subject = str(claim.get("subject_vertex_id") or "").strip()
        obj = str(claim.get("object_vertex_id") or "").strip()
        statement = str(claim.get("statement") or claim_id)
        if status in {"disputed", "stale", "proposed"}:
            qtype = "contradiction_resolution" if status == "disputed" else "stale_information_recheck" if status == "stale" else "source_confirmation"
            questions.append(
                _question(
                    question_type=qtype,
                    text=f"Re-check claim {claim_id}: {statement}",
                    target_entities=[item for item in [subject, obj] if item],
                    expected_claim_types=[str(claim.get("claim_type") or "source_confirmation")],
                    priority=0.88 if status == "disputed" else 0.68,
                    reason=f"Claim status is {status}; admission needs stronger source evidence.",
                    source_types=["official", "legal", "watchdog", "media"],
                    label=statement[:80],
                    budget_pages=8,
                )
            )

    dedup: dict[str, dict[str, Any]] = {}
    for question in questions:
        dedup[question["id"]] = question
    return sorted(dedup.values(), key=lambda item: (-float(item["priority_score"]), item["id"]))[:limit]


def write_question_queue(questions: list[dict[str, Any]], path: Path = EXPLORATION_QUEUE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for question in questions:
            handle.write(json.dumps(question, ensure_ascii=False, sort_keys=True) + "\n")
