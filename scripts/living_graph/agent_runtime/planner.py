"""Query classification and initial work-item planning."""

from __future__ import annotations

import re
from typing import Any

try:
    from .task_db import enqueue_item
    from ..research_tools import extract_year_range
except ImportError:  # pragma: no cover
    from living_graph.agent_runtime.task_db import enqueue_item
    from living_graph.research_tools import extract_year_range


ROLE_HISTORY_MARKERS = [
    "руководител",
    "руководитель аппарата",
    "глава аппарата",
    "chief of staff",
    "head of staff",
    "head of the prime minister",
    "prime minister's staff",
    "prime minister staff",
    "վարչապետի աշխատակազմի ղեկավար",
    "աշխատակազմի ղեկավար",
    "аппарата",
    "ղեկավար",
]
PARLIAMENT_MARKERS = ["депутат", "парламент", "фракция", "պատգամավոր", "խորհրդարան", "deputy", "parliament", "faction", "mp"]
GOVERNMENT_MARKERS = [
    "minister",
    "ministers",
    "cabinet",
    "government of armenia",
    "government team members",
    "gov-members",
    "prime minister",
    "министр",
    "министры",
    "кабинет",
    "правительство",
    "նախարար",
    "նախարարներ",
    "կառավարություն",
]

ROLE_HISTORY_PERSON_MARKERS = (
    "nikol pashinyan",
    "նիկոլ պաշինյան",
    "пашинян",
    "pashinyan",
)

ROLE_HISTORY_ROLE_GROUPS = [
    "Chief of Staff",
    "Deputy Chief of Staff",
    "Chief Adviser",
    "Adviser",
    "Assistant",
    "Press Secretary",
    "Chief Protocol Officer",
    "Head of Department",
    "Head of Division",
]


def _contains_marker(text: str, marker: str) -> bool:
    marker = marker.lower().strip()
    if not marker:
        return False
    if re.fullmatch(r"[a-z0-9]+", marker):
        return bool(re.search(rf"\b{re.escape(marker)}\b", text))
    return marker in text


def _contains_any_marker(text: str, markers: list[str] | tuple[str, ...]) -> bool:
    return any(_contains_marker(text, marker) for marker in markers)


def extract_role_history_context(query: str) -> dict[str, Any]:
    blob = query.lower()
    date_from, date_to = extract_year_range(query)
    context_person = "Nikol Pashinyan" if any(marker in blob for marker in ROLE_HISTORY_PERSON_MARKERS) else ""
    if any(token in blob for token in ("minister", "government team members", "gov-members", "cabinet")):
        target_role = "Member/Minister of the Government of Armenia"
    else:
        target_role = "Head/Chief of Staff of the Prime Minister of Armenia"
    requested_entities = ["persons", "offices", "institutions", "companies", "parties"]
    requested_roles = [target_role, *ROLE_HISTORY_ROLE_GROUPS]
    temporal_granularity = "year"
    if re.search(r"\b\d{4}[-/]\d{2}\b", query):
        temporal_granularity = "month"
    if re.search(r"\b\d{4}[-/]\d{2}[-/]\d{2}\b", query):
        temporal_granularity = "day"
    return {
        "target_role": target_role,
        "date_from": date_from,
        "date_to": date_to,
        "context_person": context_person,
        "requested_entities": requested_entities,
        "requested_roles": requested_roles,
        "temporal_granularity": temporal_granularity,
        "target_entity": target_role,
        "target_type": "role_history",
    }


def classify_user_query(query: str) -> str:
    lowered = query.lower()
    if _contains_any_marker(lowered, ROLE_HISTORY_MARKERS):
        return "role_history_enrichment"
    if _contains_any_marker(lowered, GOVERNMENT_MARKERS):
        return "government_ministers_enrichment"
    if _contains_any_marker(lowered, PARLIAMENT_MARKERS):
        return "parliament_roster_enrichment"
    return "generic_topic_research"


def create_initial_plan(query: str, run_id: str, budget_json: dict[str, Any] | None = None) -> dict[str, Any]:
    run_type = classify_user_query(query)
    budget = dict(budget_json or {})
    stages: list[str]
    if run_type == "role_history_enrichment":
        stages = [
            "resolve_target_office",
            "build_multilingual_queries",
            "search_official_sources",
            "fetch_candidate_pages",
            "extract_role_tenure_claims",
            "resolve_person_entities",
            "enrich_person_profiles",
            "extract_associations",
            "admit_claims",
            "merge_graph",
            "render_graph_diff",
        ]
        enqueue_item(run_id, "discover_role_history", "Discover role history", {"query": query}, priority=10)
    elif run_type == "government_ministers_enrichment":
        stages = [
            "discover_government_ministers",
            "fetch_minister_profiles",
            "extract_minister_claims",
            "link_minister_to_ministry",
            "build_government_relations",
            "rebuild_profiles",
        ]
        enqueue_item(run_id, "discover_government_ministers", "Discover government ministers", {"query": query}, priority=10)
    elif run_type == "parliament_roster_enrichment":
        stages = [
            "discover_roster",
            "create_deputy_items",
            "process_deputy_profiles",
            "build_relations",
            "rebuild_profiles",
        ]
        enqueue_item(run_id, "discover_parliament_roster", "Discover parliament roster", {"query": query}, priority=10)
    else:
        stages = ["discover_sources", "bounded_research", "graph_update"]
        enqueue_item(
            run_id,
            "generic_topic_research",
            "Generic topic research",
            {
                "query": query,
                "budget_pages": budget.get("budget_pages"),
                "max_depth": budget.get("max_depth"),
                "question_id": budget.get("question_id", ""),
                "question_type": budget.get("question_type", ""),
                "target_entities": budget.get("target_entities", []),
                "expected_claim_types": budget.get("expected_claim_types", []),
                "suggested_source_types": budget.get("suggested_source_types", []),
                "seed_queries": budget.get("seed_queries", []),
            },
            priority=10,
        )
    return {"run_type": run_type, "stages": stages, "role_history_context": extract_role_history_context(query) if run_type == "role_history_enrichment" else {}}
