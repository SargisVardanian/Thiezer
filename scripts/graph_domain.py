#!/usr/bin/env python3
"""Claim-first graph domain helpers for Thiezer."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 3
ADMISSION_POLICY_VERSION = 2

PERSPECTIVE_BUCKETS = (
    "neutral_analytic",
    "institutional",
    "government_or_ruling",
    "opposition",
    "independent_media",
    "watchdog_or_civic",
    "external_analytic",
)

CANONICAL_RELATION_CLASSES: dict[str, str] = {
    "holds_office_in": "institutional",
    "part_of": "institutional",
    "appointed_to": "institutional",
    "removed_from": "institutional",
    "appointed_by": "institutional",
    "licensed_by": "institutional",
    "implemented_by": "institutional",
    "member_of": "membership",
    "leads": "membership",
    "board_member_of": "membership",
    "funded_by": "membership",
    "contracted_with_state": "membership",
    "aligned_with": "political",
    "opposes": "political",
    "publicly_supported": "political",
    "publicly_opposed": "political",
    "owns_or_controls": "high_risk",
    "benefited_entity": "high_risk",
    "investigated_by": "high_risk",
    "subject_of_legal_case": "high_risk",
    "mentions": "observational",
    "reported_by": "observational",
    "announced_by": "event",
    "affects": "event",
    "criticized_by": "interpretive",
    "watchdog_allegation": "interpretive",
    "media_claim_disputed": "interpretive",
}

RUMORISH_RELATION_TYPES = {
    "mentions",
    "reported_by",
    "watchdog_allegation",
    "media_claim_disputed",
    "criticized_by",
}

STATUS_NORMALIZATION = {
    "verified": "confirmed",
    "official_active": "confirmed",
    "active": "confirmed",
    "former_official": "obsolete",
    "reported": "observed",
    "watchdog_attributed": "disputed",
    "sensitive": "disputed",
    "in_court": "disputed",
    "closed": "obsolete",
}

HUMAN_LABEL_RE = re.compile(r"^[\w][\w\s.,'’()/-]{1,160}$", flags=re.UNICODE)
HASHISH_LABEL_RE = re.compile(r"^(?:[a-fA-F0-9]{8,}|[A-Z]?[a-fA-F0-9]{8,}[A-Za-z0-9]*|E[0-9A-Fa-f]{12,}[A-Za-z0-9]*)$")


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_hash(*parts: Any) -> str:
    payload = "||".join(str(part or "").strip() for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _listify(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _dedupe_dicts(rows: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        row_id = str(row.get(key) or "").strip()
        if not row_id or row_id in seen:
            continue
        seen.add(row_id)
        result.append(row)
    return result


def _source_group_for_url(url: str, source_type: str = "") -> str:
    target = str(url or "").lower()
    source_type = str(source_type or "").lower()
    if any(marker in target for marker in ("gov", "parliament", "president", "prime", "court")) or source_type == "official":
        return "institutional"
    if source_type in {"watchdog", "independent"}:
        return "watchdog_or_civic" if source_type == "watchdog" else "independent_media"
    if source_type in {"opposition_adjacent"}:
        return "opposition"
    if source_type in {"external"}:
        return "external_analytic"
    return "independent_media"


def normalize_status(status: str) -> str:
    value = str(status or "").strip().lower()
    if not value:
        return "observed"
    return STATUS_NORMALIZATION.get(value, value if value in {"observed", "probable", "confirmed", "disputed", "obsolete", "retracted"} else "observed")


def relation_class(relation_type: str) -> str:
    return CANONICAL_RELATION_CLASSES.get(str(relation_type or "").strip(), "high_risk")


def vertex_admission_reason(entity: dict[str, Any]) -> tuple[bool, str]:
    entity_id = str(entity.get("id") or "").strip()
    label = str(entity.get("label") or entity.get("name") or "").strip()
    if not label:
        return False, "missing_label"
    if HASHISH_LABEL_RE.fullmatch(label) or HASHISH_LABEL_RE.fullmatch(entity_id):
        return False, "hash_like_label"
    return True, "accepted"


def is_renderable_vertex(entity: dict[str, Any]) -> bool:
    ok, _ = vertex_admission_reason(entity)
    return ok


def default_graph_bundle() -> dict[str, Any]:
    graph = {
        "schema_version": SCHEMA_VERSION,
        "version": SCHEMA_VERSION,
        "updated_at": iso_now(),
        "source_of_truth": "content/graph/country-graph.json",
        "vertices": [],
        "edges": [],
        "claims": [],
        "events": [],
        "sources": [],
        "evidence": [],
        "perspectives": [],
        "narratives": [],
        "story_mentions": [],
        "runtime": {},
        "indexes": {},
        "migration": {"status": "native_v3", "updated_at": iso_now()},
    }
    return sync_compatibility_views(graph)


def ensure_profile_shape(profile: dict[str, Any] | None) -> dict[str, Any]:
    profile = deepcopy(profile) if isinstance(profile, dict) else {}
    profile.setdefault("neutral_analytic_summary", str(profile.get("overview") or profile.get("neutral_analytic_summary") or "").strip())
    profile.setdefault("history_or_biography", _listify(profile.get("history_or_biography") or profile.get("biography") or profile.get("history")))
    profile.setdefault("current_roles_or_functions", _listify(profile.get("current_roles_or_functions") or profile.get("current_roles") or profile.get("mission_or_functions")))
    profile.setdefault("timeline", _listify(profile.get("timeline")))
    network = profile.get("network", {}) if isinstance(profile.get("network"), dict) else {}
    profile.setdefault("direct_network", _listify(profile.get("direct_network") or network.get("direct")))
    profile.setdefault("indirect_network", _listify(profile.get("indirect_network") or network.get("indirect")))
    profile.setdefault("evidence_summary", _listify(profile.get("evidence_summary") or profile.get("evidence") or profile.get("source_links")))
    profile.setdefault("dispute_flags", _listify(profile.get("dispute_flags")))
    return profile


def normalize_vertex(entity: dict[str, Any], *, kind: str = "entity") -> dict[str, Any]:
    entity_id = str(entity.get("id") or "").strip()
    label = str(entity.get("label") or entity.get("name") or entity_id).strip()
    profile = ensure_profile_shape(entity.get("profile"))
    return {
        "id": entity_id,
        "kind": str(entity.get("kind") or kind).strip() or kind,
        "label": label,
        "name": label,
        "category": str(entity.get("category") or entity.get("kind") or kind).strip() or kind,
        "subtype": str(entity.get("subtype") or "").strip(),
        "aliases": [str(item).strip() for item in _listify(entity.get("aliases")) if str(item).strip()],
        "summary": str(entity.get("summary") or "").strip(),
        "profile": profile,
        "tags": [str(item).strip() for item in _listify(entity.get("tags")) if str(item).strip()],
        "links": deepcopy(entity.get("links")) if isinstance(entity.get("links"), dict) else {},
        "notes": str(entity.get("notes") or "").strip(),
        "observed_at": str(entity.get("observed_at") or entity.get("updated_at") or iso_now()).strip(),
        "valid_from": str(entity.get("valid_from") or "").strip() or None,
        "valid_to": str(entity.get("valid_to") or "").strip() or None,
        "confidence": float(entity.get("confidence", 0.85) or 0.85),
        "public_safe": bool(entity.get("public_safe", True)),
        "last_changed_run_id": str(entity.get("last_changed_run_id") or "").strip() or None,
        "change_type": str(entity.get("change_type") or "unchanged").strip() or "unchanged",
        "updated_at": str(entity.get("updated_at") or iso_now()).strip(),
        "renderable": bool(entity.get("renderable", True)),
    }


def normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    event_id = str(event.get("id") or "").strip()
    label = str(event.get("label") or event.get("name") or event_id).strip()
    actor_ids = [str(item).strip() for item in _listify(event.get("actor_ids")) if str(item).strip()]
    return {
        "id": event_id,
        "vertex_id": event_id,
        "label": label,
        "name": label,
        "type": str(event.get("type") or event.get("subtype") or "story_event").strip(),
        "topic": str(event.get("topic") or event.get("subtype") or "").strip(),
        "summary": str(event.get("summary") or "").strip(),
        "actor_ids": actor_ids,
        "source_ids": [str(item).strip() for item in _listify(event.get("source_ids")) if str(item).strip()],
        "evidence_ids": [str(item).strip() for item in _listify(event.get("evidence_ids")) if str(item).strip()],
        "observed_at": str(event.get("observed_at") or event.get("updated_at") or iso_now()).strip(),
        "valid_from": str(event.get("valid_from") or "").strip() or None,
        "valid_to": str(event.get("valid_to") or "").strip() or None,
        "public_safe": bool(event.get("public_safe", True)),
        "updated_at": str(event.get("updated_at") or iso_now()).strip(),
    }


def _build_source(source_url: str, relation: dict[str, Any], *, suffix: str = "") -> dict[str, Any]:
    source_type = str(relation.get("source_type") or "").strip()
    if not source_type:
        inferred_group = _source_group_for_url(source_url)
        source_type = "official" if inferred_group == "institutional" else "media"
    source_id = f"source-{stable_hash(source_url, source_type, suffix)}"
    return {
        "id": source_id,
        "url": source_url,
        "title": str(relation.get("source_title") or "").strip(),
        "publisher": str(relation.get("source_name") or "").strip(),
        "source_class": source_type,
        "language": str(relation.get("language") or "").strip(),
        "reliability": float(relation.get("top_trust_score", relation.get("confidence", 0.55)) or 0.55),
        "updated_at": iso_now(),
    }


def _build_evidence(source: dict[str, Any], relation: dict[str, Any], *, suffix: str = "") -> dict[str, Any]:
    evidence_id = f"evidence-{stable_hash(source.get('id', ''), relation.get('id', ''), suffix)}"
    return {
        "id": evidence_id,
        "source_id": source["id"],
        "url": source.get("url", ""),
        "title": source.get("title") or source.get("publisher") or source.get("url", ""),
        "publisher": source.get("publisher", ""),
        "source_class": source.get("source_class", ""),
        "language": source.get("language", ""),
        "published_at": str(relation.get("valid_from") or "").strip(),
        "retrieved_at": str(relation.get("collected_at") or relation.get("last_checked_at") or iso_now()).strip(),
        "snippet": str(relation.get("evidence_quote") or relation.get("notes") or "").strip(),
        "quote": str(relation.get("evidence_quote") or "").strip(),
        "stance": "supporting",
        "supports_claim_ids": [],
        "contradicts_claim_ids": [],
    }


def build_claim_from_relation(relation: dict[str, Any], *, evidence_ids: list[str], source_ids: list[str]) -> dict[str, Any]:
    relation_type = str(relation.get("relation_type") or relation.get("type") or "mentions").strip()
    status = normalize_status(str(relation.get("status") or "observed"))
    top_trust = float(relation.get("top_trust_score", relation.get("confidence", 0.0)) or 0.0)
    corroboration = float(relation.get("corroboration_count", 1) or 1)
    interpretive_degree = 0.85 if relation_type in RUMORISH_RELATION_TYPES else (0.65 if relation_class(relation_type) in {"political", "interpretive"} else 0.2)
    source_reliability = max(0.0, min(1.0, top_trust if top_trust else float(relation.get("confidence", 0.55) or 0.55)))
    cross_source_confirmation = max(0.0, min(1.0, corroboration / 3.0))
    extraction_confidence = max(0.0, min(1.0, float(relation.get("confidence", 0.6) or 0.6)))
    publication_risk = min(1.0, 0.2 + interpretive_degree * 0.5 + (0.25 if status == "disputed" else 0.0) + (0.15 if relation_class(relation_type) == "high_risk" else 0.0))
    claim_id = f"claim-{stable_hash(relation.get('id', ''), relation_type, relation.get('from', ''), relation.get('to', ''))}"
    return {
        "id": claim_id,
        "subject_vertex_id": str(relation.get("from") or "").strip(),
        "object_vertex_id": str(relation.get("to") or "").strip() or None,
        "claim_type": relation_type,
        "statement": str(relation.get("evidence_quote") or relation.get("notes") or f"{relation.get('from')} {relation_type} {relation.get('to')}").strip(),
        "polarity": "positive" if status not in {"disputed", "retracted"} else "contested",
        "source_ids": source_ids,
        "evidence_ids": evidence_ids,
        "observed_at": str(relation.get("collected_at") or relation.get("last_checked_at") or relation.get("updated_at") or iso_now()).strip(),
        "valid_from": str(relation.get("valid_from") or "").strip() or None,
        "valid_to": str(relation.get("valid_to") or "").strip() or None,
        "status": status,
        "interpretive_degree": round(interpretive_degree, 3),
        "publication_risk": round(publication_risk, 3),
        "extraction_confidence": round(extraction_confidence, 3),
        "source_reliability": round(source_reliability, 3),
        "cross_source_confirmation": round(cross_source_confirmation, 3),
        "entity_linking_confidence": round(float(relation.get("entity_linking_confidence", 0.9) or 0.9), 3),
        "temporal_consistency_confidence": round(0.9 if relation.get("valid_to") or relation.get("valid_from") else 0.65, 3),
        "graph_consistency_confidence": round(0.4 if status == "disputed" else 0.78, 3),
        "source_independence_score": round(float(relation.get("source_independence_score", 0.0) or 0.0), 3),
        "claim_hash": str(relation.get("claim_hash") or stable_hash(claim_id, relation.get("evidence_quote", ""))),
        "raw_relation_id": str(relation.get("id") or ""),
        "updated_at": iso_now(),
    }


def canonical_admission(claim: dict[str, Any], sources_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    claim_type = str(claim.get("claim_type") or "").strip()
    claim_class = relation_class(claim_type)
    source_ids = [str(item).strip() for item in _listify(claim.get("source_ids")) if str(item).strip()]
    source_classes = {str((sources_by_id.get(source_id) or {}).get("source_class") or "").strip() for source_id in source_ids}
    has_official = "official" in source_classes
    source_count = len(source_ids)
    cross_source = float(claim.get("cross_source_confirmation", 0.0) or 0.0)
    source_reliability = float(claim.get("source_reliability", 0.0) or 0.0)
    interpretive = float(claim.get("interpretive_degree", 1.0) or 1.0)
    status = str(claim.get("status") or "observed").strip()

    if claim_class in {"observational", "interpretive"} or claim_type in RUMORISH_RELATION_TYPES:
        return {"admit": False, "reason": "claim_class_not_canonical", "layer": "claim"}
    if status in {"disputed", "retracted"}:
        return {"admit": False, "reason": "status_not_admissible", "layer": "claim"}

    thresholds = {
        "institutional": {"min_reliability": 0.7, "min_cross": 0.2, "max_interpretive": 0.35, "official_or_count": 1},
        "membership": {"min_reliability": 0.62, "min_cross": 0.2, "max_interpretive": 0.35, "official_or_count": 1},
        "political": {"min_reliability": 0.88, "min_cross": 0.6, "max_interpretive": 0.25, "official_or_count": 2},
        "high_risk": {"min_reliability": 0.92, "min_cross": 0.7, "max_interpretive": 0.2, "official_or_count": 2},
        "event": {"min_reliability": 0.75, "min_cross": 0.34, "max_interpretive": 0.45, "official_or_count": 1},
    }
    policy = thresholds.get(claim_class, thresholds["high_risk"])
    if source_reliability < policy["min_reliability"]:
        return {"admit": False, "reason": "source_reliability_too_low", "layer": "claim"}
    if cross_source < policy["min_cross"] and not has_official:
        return {"admit": False, "reason": "cross_source_confirmation_too_low", "layer": "claim"}
    if interpretive > policy["max_interpretive"]:
        return {"admit": False, "reason": "interpretive_degree_too_high", "layer": "claim"}
    if not has_official and source_count < policy["official_or_count"]:
        return {"admit": False, "reason": "insufficient_independent_sources", "layer": "claim"}
    return {"admit": True, "reason": "meets_class_policy", "layer": "canonical"}


def rebuild_edges_from_claims(graph: dict[str, Any]) -> dict[str, Any]:
    sources_by_id = {
        str(item.get("id") or "").strip(): item
        for item in graph.get("sources", [])
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    edges: list[dict[str, Any]] = []
    edge_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for claim in graph.get("claims", []):
        if not isinstance(claim, dict) or not claim.get("object_vertex_id"):
            continue
        admission = canonical_admission(claim, sources_by_id)
        if not admission["admit"]:
            continue
        key = (
            str(claim.get("subject_vertex_id") or "").strip(),
            str(claim.get("object_vertex_id") or "").strip(),
            str(claim.get("claim_type") or "").strip(),
        )
        candidate = build_edge_from_claim(
            claim,
            evidence_ids=list(claim.get("evidence_ids", []) or []),
            source_ids=list(claim.get("source_ids", []) or []),
        )
        existing = edge_by_key.get(key)
        if existing is None:
            edge_by_key[key] = candidate
            edges.append(candidate)
            continue
        existing["claim_ids"] = sorted(set(existing.get("claim_ids", [])) | set(candidate.get("claim_ids", [])))
        existing["evidence_ids"] = sorted(set(existing.get("evidence_ids", [])) | set(candidate.get("evidence_ids", [])))
        existing["source_ids"] = sorted(set(existing.get("source_ids", [])) | set(candidate.get("source_ids", [])))
        existing["confidence"] = round(max(float(existing.get("confidence", 0.0) or 0.0), float(candidate.get("confidence", 0.0) or 0.0)), 3)
        existing["status"] = "confirmed" if existing["confidence"] >= 0.82 else "probable"
        existing["updated_at"] = iso_now()
    graph["edges"] = edges
    return graph


def build_edge_from_claim(claim: dict[str, Any], *, evidence_ids: list[str], source_ids: list[str]) -> dict[str, Any]:
    edge_id = f"edge-{stable_hash(claim.get('subject_vertex_id', ''), claim.get('object_vertex_id', ''), claim.get('claim_type', ''))}"
    confidence = (
        float(claim.get("extraction_confidence", 0.0) or 0.0) * 0.3
        + float(claim.get("source_reliability", 0.0) or 0.0) * 0.35
        + float(claim.get("cross_source_confirmation", 0.0) or 0.0) * 0.35
    )
    return {
        "id": edge_id,
        "from": str(claim.get("subject_vertex_id") or "").strip(),
        "to": str(claim.get("object_vertex_id") or "").strip(),
        "type": str(claim.get("claim_type") or "").strip(),
        "relation_type": str(claim.get("claim_type") or "").strip(),
        "layer": "canonical",
        "status": "confirmed" if confidence >= 0.82 else "probable",
        "confidence": round(confidence, 3),
        "valid_from": claim.get("valid_from"),
        "valid_to": claim.get("valid_to"),
        "observed_at": claim.get("observed_at"),
        "claim_ids": [claim["id"]],
        "evidence_ids": evidence_ids,
        "source_ids": source_ids,
        "public_safe": True,
        "updated_at": iso_now(),
    }


def _perspective_item(vertex_id: str, bucket: str, summary: str, *, claim_ids: list[str] | None = None, evidence_ids: list[str] | None = None, actor_vertex_id: str | None = None) -> dict[str, Any]:
    return {
        "id": f"perspective-{stable_hash(vertex_id, bucket, summary[:160])}",
        "vertex_id": vertex_id,
        "actor_vertex_id": actor_vertex_id,
        "source_group": bucket,
        "perspective_type": bucket,
        "stance": "mixed" if bucket == "neutral_analytic" else bucket,
        "summary": summary.strip(),
        "claim_ids": list(claim_ids or []),
        "evidence_ids": list(evidence_ids or []),
        "updated_at": iso_now(),
    }


def build_default_perspectives(vertex: dict[str, Any]) -> list[dict[str, Any]]:
    profile = ensure_profile_shape(vertex.get("profile"))
    base_summary = str(profile.get("neutral_analytic_summary") or vertex.get("summary") or "").strip()
    if not base_summary:
        return []
    result = [_perspective_item(str(vertex.get("id") or ""), "neutral_analytic", base_summary)]
    if vertex.get("category") in {"institution", "organization", "party"}:
        result.append(_perspective_item(str(vertex.get("id") or ""), "institutional", base_summary))
    return result


def build_narrative_from_claim(claim: dict[str, Any], *, evidence_ids: list[str]) -> dict[str, Any] | None:
    if relation_class(str(claim.get("claim_type") or "")) not in {"interpretive"} and float(claim.get("interpretive_degree", 0.0) or 0.0) < 0.7:
        return None
    return {
        "id": f"narrative-{stable_hash(claim.get('id', ''), claim.get('statement', ''))}",
        "vertex_id": str(claim.get("subject_vertex_id") or "").strip(),
        "theme": str(claim.get("claim_type") or "narrative").strip(),
        "narrative_type": "reputation_or_interpretation",
        "summary": str(claim.get("statement") or "").strip(),
        "claim_ids": [str(claim.get("id") or "").strip()],
        "evidence_ids": list(evidence_ids),
        "time_window": {
            "observed_at": claim.get("observed_at"),
            "valid_from": claim.get("valid_from"),
            "valid_to": claim.get("valid_to"),
        },
        "status": str(claim.get("status") or "observed"),
    }


def sync_compatibility_views(graph: dict[str, Any]) -> dict[str, Any]:
    graph["schema_version"] = int(graph.get("schema_version") or SCHEMA_VERSION)
    graph["version"] = graph["schema_version"]
    vertices = _dedupe_dicts([normalize_vertex(item, kind=str(item.get("kind") or "entity")) for item in _listify(graph.get("vertices")) if isinstance(item, dict)], key="id")
    edges = _dedupe_dicts([deepcopy(item) for item in _listify(graph.get("edges")) if isinstance(item, dict)], key="id")
    claims = _dedupe_dicts([deepcopy(item) for item in _listify(graph.get("claims")) if isinstance(item, dict)], key="id")
    events = _dedupe_dicts([normalize_event(item) for item in _listify(graph.get("events")) if isinstance(item, dict)], key="id")
    graph["vertices"] = vertices
    graph["edges"] = edges
    graph["claims"] = claims
    graph["events"] = events
    graph["sources"] = _dedupe_dicts([deepcopy(item) for item in _listify(graph.get("sources")) if isinstance(item, dict)], key="id")
    graph["evidence"] = _dedupe_dicts([deepcopy(item) for item in _listify(graph.get("evidence")) if isinstance(item, dict)], key="id")
    graph["perspectives"] = _dedupe_dicts([deepcopy(item) for item in _listify(graph.get("perspectives")) if isinstance(item, dict)], key="id")
    graph["narratives"] = _dedupe_dicts([deepcopy(item) for item in _listify(graph.get("narratives")) if isinstance(item, dict)], key="id")
    graph.setdefault("story_mentions", [])
    graph.setdefault("runtime", {})
    graph.setdefault("indexes", {})
    graph.setdefault("migration", {"status": "native_v3", "updated_at": iso_now()})

    entities: list[dict[str, Any]] = []
    for vertex in vertices:
        if str(vertex.get("kind") or "") == "event":
            continue
        entity = {
            "id": vertex["id"],
            "name": vertex.get("label") or vertex["id"],
            "category": vertex.get("category", "entity"),
            "subtype": vertex.get("subtype", ""),
            "aliases": vertex.get("aliases", []),
            "tags": vertex.get("tags", []),
            "summary": vertex.get("summary", ""),
            "links": vertex.get("links", {}),
            "public_safe": vertex.get("public_safe", True),
            "notes": vertex.get("notes", ""),
            "profile": ensure_profile_shape(vertex.get("profile")),
            "updated_at": vertex.get("updated_at", iso_now()),
            "last_changed_run_id": vertex.get("last_changed_run_id"),
            "change_type": vertex.get("change_type", "unchanged"),
            "kind": vertex.get("kind", "entity"),
            "label": vertex.get("label") or vertex["id"],
            "observed_at": vertex.get("observed_at"),
            "valid_from": vertex.get("valid_from"),
            "valid_to": vertex.get("valid_to"),
            "confidence": vertex.get("confidence", 0.85),
        }
        entities.append(entity)
    graph["entities"] = entities

    events_view: list[dict[str, Any]] = []
    for event in events:
        events_view.append(
            {
                "id": event["id"],
                "name": event.get("label") or event["id"],
                "category": "event",
                "subtype": event.get("type", ""),
                "summary": event.get("summary", ""),
                "actor_ids": event.get("actor_ids", []),
                "source_ids": event.get("source_ids", []),
                "evidence_ids": event.get("evidence_ids", []),
                "public_safe": event.get("public_safe", True),
                "updated_at": event.get("updated_at", iso_now()),
            }
        )
    graph["event_nodes"] = events_view

    relations: list[dict[str, Any]] = []
    for edge in edges:
        relations.append(
            {
                "id": edge["id"],
                "from": edge.get("from", ""),
                "to": edge.get("to", ""),
                "relation_type": edge.get("type", ""),
                "type": edge.get("type", ""),
                "status": edge.get("status", "observed"),
                "confidence": edge.get("confidence", 0.0),
                "public_safe": edge.get("public_safe", True),
                "valid_from": edge.get("valid_from"),
                "valid_to": edge.get("valid_to"),
                "updated_at": edge.get("updated_at", iso_now()),
                "observed_at": edge.get("observed_at"),
                "claim_ids": edge.get("claim_ids", []),
                "evidence_ids": edge.get("evidence_ids", []),
                "source_ids": edge.get("source_ids", []),
                "layer": edge.get("layer", "canonical"),
            }
        )
    graph["relations"] = relations
    return graph


def _merge_scalar(existing: Any, incoming: Any) -> Any:
    if incoming in (None, "", [], {}):
        return deepcopy(existing)
    if isinstance(existing, dict) and isinstance(incoming, dict):
        return _merge_mapping(existing, incoming)
    if isinstance(existing, list) and isinstance(incoming, list):
        return _merge_sequence(existing, incoming)
    return deepcopy(incoming)


def _merge_mapping(existing: Any, incoming: Any) -> dict[str, Any]:
    base = deepcopy(existing) if isinstance(existing, dict) else {}
    if not isinstance(incoming, dict):
        return base
    for key, value in incoming.items():
        if value in (None, "", [], {}):
            continue
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            base[key] = _merge_mapping(base[key], value)
        elif key in base and isinstance(base[key], list) and isinstance(value, list):
            base[key] = _merge_sequence(base[key], value)
        else:
            base[key] = deepcopy(value)
    return base


def _merge_sequence(existing: Any, incoming: Any) -> list[Any]:
    base = [deepcopy(item) for item in existing] if isinstance(existing, list) else []
    if not isinstance(incoming, list):
        return base
    seen: set[str] = set()
    merged: list[Any] = []
    for item in [*base, *incoming]:
        try:
            marker = json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            marker = str(item)
        if marker in seen:
            continue
        seen.add(marker)
        merged.append(deepcopy(item))
    return merged


def _merge_by_id(existing: list[dict[str, Any]], incoming: list[dict[str, Any]], *, key: str = "id") -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def ingest(rows: list[dict[str, Any]]) -> None:
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_id = str(row.get(key) or "").strip()
            if not row_id:
                try:
                    row_id = json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)
                except Exception:
                    row_id = stable_hash(repr(row))
            if row_id not in merged:
                merged[row_id] = deepcopy(row)
                order.append(row_id)
            else:
                merged[row_id] = _merge_mapping(merged[row_id], row)

    ingest(existing or [])
    ingest(incoming or [])
    return [merged[row_id] for row_id in order]


def merge_graph_bundle(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    base = deepcopy(existing) if isinstance(existing, dict) else {}
    patch = deepcopy(incoming) if isinstance(incoming, dict) else {}
    merged = deepcopy(base)

    for key in ("vertices", "entities", "edges", "relations", "derived_relations", "claims", "events", "sources", "evidence", "perspectives", "narratives", "story_mentions"):
        merged[key] = _merge_by_id(
            [item for item in _listify(base.get(key)) if isinstance(item, dict)],
            [item for item in _listify(patch.get(key)) if isinstance(item, dict)],
        )

    for key in ("runtime", "indexes", "migration", "context_layer"):
        merged[key] = _merge_mapping(base.get(key), patch.get(key))

    for key, value in patch.items():
        if key in {"vertices", "entities", "edges", "relations", "derived_relations", "claims", "events", "sources", "evidence", "perspectives", "narratives", "story_mentions", "runtime", "indexes", "migration", "context_layer"}:
            continue
        if value in (None, "", [], {}):
            continue
        merged[key] = deepcopy(value)

    if not merged.get("source_of_truth"):
        merged["source_of_truth"] = str(base.get("source_of_truth") or patch.get("source_of_truth") or "content/graph/country-graph.json")
    merged["updated_at"] = str(patch.get("updated_at") or base.get("updated_at") or iso_now()).strip()
    return sync_compatibility_views(merged)


def migrate_graph_bundle(raw_graph: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(raw_graph, dict) or not raw_graph:
        graph = default_graph_bundle()
        report = {
            "migrated_at": iso_now(),
            "old_counts": {"entities": 0, "relations": 0, "event_nodes": 0},
            "new_counts": {"vertices": 0, "edges": 0, "claims": 0, "events": 0, "evidence": 0, "sources": 0},
            "claim_only_relations": 0,
            "canonical_edges_admitted": 0,
            "unmapped_fields": [],
            "lossy_transforms": [],
        }
        return graph, report

    if int(raw_graph.get("schema_version") or raw_graph.get("version") or 0) >= SCHEMA_VERSION and raw_graph.get("vertices") is not None:
        graph = sync_compatibility_views(deepcopy(raw_graph))
        migration = deepcopy(graph.get("migration", {})) if isinstance(graph.get("migration", {}), dict) else {}
        if int(migration.get("admission_policy_version", 0) or 0) != ADMISSION_POLICY_VERSION:
            graph = rebuild_edges_from_claims(graph)
            migration["admission_policy_version"] = ADMISSION_POLICY_VERSION
            migration["status"] = "migrated_to_v3"
            migration["canonical_edges_admitted"] = len(graph.get("edges", []))
            migration["new_counts"] = {
                "vertices": len(graph.get("vertices", [])),
                "edges": len(graph.get("edges", [])),
                "claims": len(graph.get("claims", [])),
                "events": len(graph.get("events", [])),
                "evidence": len(graph.get("evidence", [])),
                "sources": len(graph.get("sources", [])),
            }
            graph["migration"] = migration
        report = deepcopy(graph.get("migration", {}))
        return graph, report if isinstance(report, dict) else {}

    old_entities = [item for item in _listify(raw_graph.get("entities")) if isinstance(item, dict)]
    old_relations = [item for item in _listify(raw_graph.get("relations")) if isinstance(item, dict)]
    old_events = [item for item in _listify(raw_graph.get("event_nodes")) if isinstance(item, dict)]

    graph = default_graph_bundle()
    graph["updated_at"] = str(raw_graph.get("updated_at") or iso_now())
    graph["source_of_truth"] = str(raw_graph.get("source_of_truth") or "content/graph/country-graph.json")
    graph["runtime"] = deepcopy(raw_graph.get("runtime")) if isinstance(raw_graph.get("runtime"), dict) else {}
    graph["story_mentions"] = deepcopy(raw_graph.get("story_mentions")) if isinstance(raw_graph.get("story_mentions"), list) else []
    graph["context_layer"] = deepcopy(raw_graph.get("context_layer")) if isinstance(raw_graph.get("context_layer"), dict) else {}

    vertices = [normalize_vertex(entity) for entity in old_entities]
    events = [normalize_event(event) for event in old_events]
    event_vertex_ids = {event["id"] for event in events}
    for event in old_events:
        if str(event.get("id") or "").strip() in event_vertex_ids:
            vertices.append(normalize_vertex(event, kind="event"))

    sources: list[dict[str, Any]] = []
    evidence_items: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    narratives: list[dict[str, Any]] = []
    perspectives: list[dict[str, Any]] = []

    for vertex in vertices:
        perspectives.extend(build_default_perspectives(vertex))

    sources_by_id: dict[str, dict[str, Any]] = {}
    claim_only_relations = 0
    canonical_edges_admitted = 0

    for relation in old_relations:
        source_rows = []
        primary_url = str(relation.get("source_url") or "").strip()
        if primary_url:
            source_rows.append({"url": primary_url, "source_type": relation.get("source_type", "")})
        for index, source_link in enumerate(_listify(relation.get("source_links"))):
            if isinstance(source_link, dict) and str(source_link.get("url") or "").strip():
                source_rows.append({"url": str(source_link.get("url") or "").strip(), "source_type": source_link.get("source_type") or relation.get("source_type", ""), "suffix": str(index)})
        source_ids: list[str] = []
        evidence_ids: list[str] = []
        for source_row in source_rows or [{"url": "", "source_type": relation.get("source_type", "")}]:
            source = _build_source(str(source_row.get("url") or ""), relation, suffix=str(source_row.get("suffix") or ""))
            if source["id"] not in sources_by_id:
                sources_by_id[source["id"]] = source
                sources.append(source)
            source_ids.append(source["id"])
            evidence = _build_evidence(source, relation, suffix=str(source_row.get("suffix") or ""))
            evidence_items.append(evidence)
            evidence_ids.append(evidence["id"])

        claim = build_claim_from_relation(relation, evidence_ids=evidence_ids, source_ids=source_ids)
        claims.append(claim)
        for evidence in evidence_items[-len(evidence_ids):]:
            evidence["supports_claim_ids"].append(claim["id"])
        admission = canonical_admission(claim, sources_by_id)
        if admission["admit"] and claim.get("object_vertex_id"):
            edges.append(build_edge_from_claim(claim, evidence_ids=evidence_ids, source_ids=source_ids))
            canonical_edges_admitted += 1
        else:
            claim_only_relations += 1
            narrative = build_narrative_from_claim(claim, evidence_ids=evidence_ids)
            if narrative:
                narratives.append(narrative)
            bucket = _source_group_for_url(primary_url, str(relation.get("source_type") or ""))
            if str(claim.get("statement") or "").strip():
                perspectives.append(
                    _perspective_item(
                        str(claim.get("subject_vertex_id") or "").strip(),
                        bucket,
                        str(claim.get("statement") or "").strip(),
                        claim_ids=[claim["id"]],
                        evidence_ids=evidence_ids,
                    )
                )

    graph["vertices"] = _dedupe_dicts(vertices, key="id")
    graph["events"] = _dedupe_dicts(events, key="id")
    graph["sources"] = _dedupe_dicts(sources, key="id")
    graph["evidence"] = _dedupe_dicts(evidence_items, key="id")
    graph["claims"] = _dedupe_dicts(claims, key="id")
    graph["edges"] = _dedupe_dicts(edges, key="id")
    graph["narratives"] = _dedupe_dicts(narratives, key="id")
    graph["perspectives"] = _dedupe_dicts(perspectives, key="id")

    report = {
        "migrated_at": iso_now(),
        "old_counts": {"entities": len(old_entities), "relations": len(old_relations), "event_nodes": len(old_events)},
        "new_counts": {
            "vertices": len(graph["vertices"]),
            "edges": len(graph["edges"]),
            "claims": len(graph["claims"]),
            "events": len(graph["events"]),
            "evidence": len(graph["evidence"]),
            "sources": len(graph["sources"]),
        },
        "claim_only_relations": claim_only_relations,
        "canonical_edges_admitted": canonical_edges_admitted,
        "admission_policy_version": ADMISSION_POLICY_VERSION,
        "unmapped_fields": sorted(set(raw_graph.keys()) - {"version", "updated_at", "source_of_truth", "relation_types", "entities", "relations", "event_nodes", "story_mentions", "runtime", "context_layer"}),
        "lossy_transforms": ["legacy_relation_fields_collapsed_into_claim_and_evidence"] if old_relations else [],
        "status": "migrated_to_v3",
    }
    graph["migration"] = report
    return sync_compatibility_views(graph), report


SOURCE_TYPE_BASE = {
    "official": 0.96,
    "watchdog": 0.82,
    "independent": 0.74,
    "external": 0.68,
    "opposition_adjacent": 0.62,
    "unknown": 0.58,
    "media": 0.64,
}

CATEGORY_ADJUST = {
    "official_baseline": 0.05,
    "mainstream_baseline": 0.03,
    "independent_watchdog": 0.02,
    "external_analysis": 0.0,
    "critical_opposition_adjacent": -0.04,
    "analysis_civic": -0.01,
}

NON_DURABLE_RELATIONS = {"mentions", "reported_by"}
WRITE_POLICY_MATRIX: dict[str, dict[str, Any]] = {
    "mentions": {"min_trust_score": 0.0, "min_corroboration_count": 1, "allowed_claim_types": {"event_only", "attributed_claim", "durable_relation_candidate"}, "durable_allowed": False},
    "holds_office_in": {"min_trust_score": 0.62, "min_corroboration_count": 1, "allowed_claim_types": {"durable_relation_candidate"}, "durable_allowed": True},
    "part_of": {"min_trust_score": 0.62, "min_corroboration_count": 1, "allowed_claim_types": {"durable_relation_candidate"}, "durable_allowed": True},
    "appointed_to": {"min_trust_score": 0.72, "min_corroboration_count": 1, "allowed_claim_types": {"durable_relation_candidate"}, "durable_allowed": True},
    "removed_from": {"min_trust_score": 0.72, "min_corroboration_count": 1, "allowed_claim_types": {"durable_relation_candidate"}, "durable_allowed": True},
    "member_of": {"min_trust_score": 0.62, "min_corroboration_count": 1, "allowed_claim_types": {"durable_relation_candidate"}, "durable_allowed": True},
    "aligned_with": {"min_trust_score": 0.9, "min_corroboration_count": 2, "allowed_claim_types": {"durable_relation_candidate"}, "durable_allowed": True},
    "opposes": {"min_trust_score": 0.9, "min_corroboration_count": 2, "allowed_claim_types": {"durable_relation_candidate"}, "durable_allowed": True},
}

RELATION_EXPECTATIONS: dict[str, dict[str, set[str]]] = {
    "holds_office_in": {"left": {"person"}, "right": {"institution", "administrative_unit", "event", "office"}},
    "part_of": {"left": {"office", "institution", "organization"}, "right": {"institution", "organization", "government"}},
    "appointed_to": {"left": {"person"}, "right": {"event"}},
    "removed_from": {"left": {"person"}, "right": {"event"}},
    "member_of": {"left": {"person", "organization"}, "right": {"organization", "institution", "party", "media"}},
    "aligned_with": {"left": {"person", "organization", "party", "media", "community", "country", "institution"}, "right": {"person", "organization", "party", "media", "community", "country", "institution"}},
    "opposes": {"left": {"person", "organization", "party", "media", "community", "country", "institution"}, "right": {"person", "organization", "party", "media", "community", "country", "institution"}},
    "appointed_by": {"left": {"person"}, "right": {"person", "organization", "institution"}},
    "family_tie_public": {"left": {"person"}, "right": {"person"}},
    "owns_or_controls": {"left": {"person", "organization"}, "right": {"organization", "company"}},
    "board_member_of": {"left": {"person"}, "right": {"organization", "company", "institution"}},
    "subject_of_legal_case": {"left": {"person", "organization", "company", "institution"}, "right": {"case"}},
    "investigated_by": {"left": {"person", "organization", "company", "institution"}, "right": {"organization", "institution", "media"}},
    "licensed_by": {"left": {"organization", "company"}, "right": {"institution", "organization"}},
    "funded_by": {"left": {"organization", "project", "event", "company"}, "right": {"organization", "institution", "country", "person"}},
    "contracted_with_state": {"left": {"organization", "company"}, "right": {"institution", "government", "country"}},
    "publicly_supported": {"left": {"person", "organization", "party", "media"}, "right": {"person", "organization", "party", "institution", "country"}},
    "publicly_opposed": {"left": {"person", "organization", "party", "media"}, "right": {"person", "organization", "party", "institution", "country"}},
    "criticized_by": {"left": {"person", "organization", "party", "institution"}, "right": {"organization", "media", "person"}},
    "authored": {"left": {"person"}, "right": {"law", "draft_law", "media_investigation", "document"}},
    "coauthored": {"left": {"person"}, "right": {"law", "draft_law", "media_investigation", "document"}},
    "voted_for": {"left": {"person"}, "right": {"law", "draft_law", "government_decision", "proposal"}},
    "voted_against": {"left": {"person"}, "right": {"law", "draft_law", "government_decision", "proposal"}},
    "implemented_by": {"left": {"law", "project", "government_decision", "community_program", "municipal_project"}, "right": {"organization", "institution", "government"}},
    "announced_by": {"left": {"event", "law", "project", "government_decision"}, "right": {"person", "organization", "institution"}},
    "affects": {"left": {"event", "law", "project", "government_decision"}, "right": {"person", "organization", "institution", "community", "country", "administrative_unit"}},
}

NUMERIC_PATTERN = re.compile(r"\b\d+(?:[.,]\d+)?\b|[%$€₽֏]|միլիոն|մլրդ|million|billion|percent|տոկոս", re.I)
RELATIVE_CHANGE_MARKERS = ("вдвое", "удво", "doubl", "twice", "կրկնապատկ", "рост", "вырос", "увелич", "сниз", "упал", "increase", "decrease", "grew", "rose", "fell", "declin")
BASELINE_MARKERS = ("по сравнению", "compared to", "relative to", "as a share of gdp", "share of gdp", "к ввп", "по отношению к ввп", "относительно ввп", "as % of gdp", "since ", "с ", "against ", "year-on-year", "year over year", "к прошлому году", "к предыдущему году", "նախորդ տարվա", "համեմատ", "նկատմամբ")
SUBJECTIVE_FRAMING_MARKERS = ("завуалирован", "угроз", "схема", "many will take this as", "veiled threat", "likely means", "apparently", "обеспокоенность", "concern", "pressure campaign")


def _normalize_text(value: str) -> str:
    try:
        from pipeline_common import normalize_text

        return normalize_text(value)
    except Exception:
        return " ".join(str(value or "").lower().split())


def _compact_summary(value: str) -> str:
    try:
        from pipeline_common import compact_summary

        return compact_summary(value)
    except Exception:
        return " ".join(str(value or "").split())[:300]


def _relation_label_ru(value: str) -> str:
    try:
        from pipeline_common import relation_label_ru

        return relation_label_ru(value)
    except Exception:
        return str(value or "").replace("_", " ")


def _load_json(path: Path, default: Any) -> Any:
    try:
        from pipeline_common import load_json

        return load_json(path, default)
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    from pipeline_common import write_json

    write_json(path, payload)


def _entity_index(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    try:
        from pipeline_common import entity_index

        return entity_index(graph)
    except Exception:
        return {str(entity.get("id") or ""): entity for entity in graph.get("entities", []) if isinstance(entity, dict)}


def _tail_jsonl(path: Path, limit: int = 8) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in reversed(path.read_text(encoding="utf-8").splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except Exception:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
        if len(rows) >= limit:
            break
    rows.reverse()
    return rows


def score_source(source: dict[str, Any], *, claim_sensitivity: str = "normal") -> dict[str, Any]:
    source_type = str(source.get("source_type") or "unknown")
    category = str(source.get("category") or "unknown")
    source_id = str(source.get("id") or source.get("source_id") or "")
    source_name = str(source.get("source_name") or source.get("name") or source_id)
    trust_weight = float(source.get("trust_weight", 0.7) or 0.7)
    freshness_weight = float(source.get("freshness_weight", 0.7) or 0.7)
    enabled = bool(source.get("enabled", True))
    status = str(source.get("status") or ("active" if enabled else "dormant"))
    base = SOURCE_TYPE_BASE.get(source_type, SOURCE_TYPE_BASE["unknown"])
    category_adjust = CATEGORY_ADJUST.get(category, 0.0)
    status_adjust = 0.04 if status == "active" else -0.08 if status == "degraded" else -0.18 if status == "broken" else -0.04
    enabled_adjust = 0.02 if enabled else -0.08
    sensitivity_penalty = {"low": 0.0, "normal": 0.0, "high": 0.08, "sensitive": 0.14}.get(claim_sensitivity, 0.0)
    directness = str(source.get("directness") or ("primary" if source_type == "official" else "secondary" if source_type in {"watchdog", "independent"} else "commentary"))
    corroboration_count = int(source.get("corroboration_count", 1) or 1)
    ownership = str(source.get("ownership_or_alignment_if_known") or source.get("notes") or "")
    corroboration_bonus = min(0.08, max(0.0, (corroboration_count - 1) * 0.02))
    directness_adjust = 0.04 if directness == "primary" else 0.01 if directness == "secondary" else -0.03
    trust_score = max(
        0.0,
        min(
            1.0,
            base + category_adjust + status_adjust + enabled_adjust + directness_adjust + corroboration_bonus + 0.05 * (trust_weight - 0.5) + 0.04 * (freshness_weight - 0.5) - sensitivity_penalty,
        ),
    )
    bias_flags: list[str] = []
    caution_flags: list[str] = []
    if category in {"critical_opposition_adjacent", "analysis_civic"}:
        bias_flags.append("political_adjacent")
    if source_type == "opposition_adjacent":
        bias_flags.append("opposition_adjacent")
    if source_type == "external":
        bias_flags.append("external_context")
    if not enabled:
        caution_flags.append("disabled_source")
    if status in {"degraded", "broken", "dormant"}:
        caution_flags.append(f"status_{status}")
    if claim_sensitivity in {"high", "sensitive"} and source_type != "official":
        caution_flags.append("sensitive_claim_requires_corrobation")
    if directness == "commentary":
        caution_flags.append("indirect_or_commentary_source")
    if corroboration_count <= 1:
        caution_flags.append("single_source_claim")
    if ownership:
        bias_flags.append("ownership_or_alignment_known")
    explanation = (
        f"type={source_type} category={category} status={status} "
        f"base={base:.2f} category_adjust={category_adjust:.2f} "
        f"trust={trust_weight:.2f} freshness={freshness_weight:.2f} "
        f"directness={directness} corroboration={corroboration_count} "
        f"sensitivity={claim_sensitivity}"
    )
    return {
        "source_id": source_id,
        "source_name": source_name,
        "source_type": source_type,
        "category": category,
        "trust_score": round(trust_score, 3),
        "bias_flags": bias_flags,
        "caution_flags": caution_flags,
        "explanation": explanation,
        "ownership_or_alignment_if_known": ownership,
        "directness": directness,
        "corroboration_count": corroboration_count,
        "why_this_score": explanation,
    }


def rank_sources(sources: list[dict[str, Any]], *, claim_sensitivity: str = "normal") -> list[dict[str, Any]]:
    scored = [score_source(source, claim_sensitivity=claim_sensitivity) for source in sources]
    return sorted(scored, key=lambda item: (-item["trust_score"], item["source_id"], item["source_name"]))


def analyze_story_fact_check(story: dict[str, Any]) -> dict[str, Any]:
    title = str(story.get("title") or "").strip()
    summary = str(story.get("summary") or story.get("public_impact") or "").strip()
    public_impact = str(story.get("public_impact") or "").strip()
    combined = " ".join(part for part in (title, summary, public_impact) if part).strip()
    normalized = _normalize_text(combined)
    corroboration_count = int(story.get("source_trust", {}).get("corroboration_count", 0) or 0) if isinstance(story.get("source_trust", {}), dict) else 0
    has_numeric_signal = bool(NUMERIC_PATTERN.search(combined)) or any(marker in normalized for marker in RELATIVE_CHANGE_MARKERS)
    has_relative_change = any(marker in normalized for marker in RELATIVE_CHANGE_MARKERS)
    has_baseline = any(marker in normalized for marker in BASELINE_MARKERS)
    has_subjective_framing = any(marker in normalized for marker in SUBJECTIVE_FRAMING_MARKERS)
    issues: list[str] = []
    warnings: list[str] = []
    if has_numeric_signal and corroboration_count <= 1:
        issues.append("single_source_numeric_claim")
    if has_subjective_framing and corroboration_count <= 1:
        issues.append("single_source_subjective_framing")
    if has_relative_change and not has_baseline:
        warnings.append("relative_change_without_clear_baseline")
    if has_numeric_signal and "ввп" not in normalized and "gdp" not in normalized and any(marker in normalized for marker in ("долг", "debt", "պարտք")):
        warnings.append("macro_claim_without_gdp_context")
    verdict = "pass"
    if issues:
        verdict = "fail"
    elif warnings:
        verdict = "warn"
    top_source = story.get("source_trust", {}).get("top_source", {}) if isinstance(story.get("source_trust", {}), dict) else {}
    source_name = str(top_source.get("source_name") or top_source.get("label") or "").strip() or "источника"
    attributed_summary = _compact_summary(summary) or _compact_summary(public_impact) or _compact_summary(title)
    if attributed_summary and (has_numeric_signal or has_subjective_framing or corroboration_count <= 1):
        attributed_summary = f"По данным {source_name}: {attributed_summary}"
    return {
        "verdict": verdict,
        "issues": issues,
        "warnings": warnings,
        "has_numeric_signal": has_numeric_signal,
        "has_relative_change": has_relative_change,
        "has_subjective_framing": has_subjective_framing,
        "corroboration_count": corroboration_count,
        "publish_blocked": bool(issues),
        "attribution_required": bool(has_numeric_signal or has_subjective_framing or corroboration_count <= 1),
        "publication_summary": attributed_summary,
    }


def entity_categories(graph: dict[str, Any]) -> dict[str, str]:
    return {str(entity.get("id")): str(entity.get("category") or "unknown") for entity in graph.get("entities", [])}


def relation_type_ok(relation_type: str) -> bool:
    return relation_type in RELATION_EXPECTATIONS or relation_type in NON_DURABLE_RELATIONS or relation_type == "mentions"


def relation_safety(candidate: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    categories = entity_categories(graph)
    left_id = str(candidate.get("from") or "")
    right_id = str(candidate.get("to") or "")
    relation_type = str(candidate.get("relation_type") or "")
    issues: list[str] = []
    warnings: list[str] = []
    if not relation_type_ok(relation_type):
        issues.append("unknown_relation_type")
    left_category = categories.get(left_id, "unknown")
    right_category = categories.get(right_id, "unknown")
    expectations = RELATION_EXPECTATIONS.get(relation_type)
    if expectations:
        if left_category not in expectations["left"]:
            issues.append(f"left_category_mismatch:{left_category}")
        if right_category not in expectations["right"]:
            issues.append(f"right_category_mismatch:{right_category}")
    if relation_type in NON_DURABLE_RELATIONS and candidate.get("status") in {"official_active", "active"}:
        warnings.append("non_durable_relation_marked_active")
    claim_type = str(candidate.get("claim_type") or "")
    corroboration_count = int(candidate.get("corroboration_count", 1) or 1)
    top_trust_score = float(candidate.get("top_trust_score", 0.0) or 0.0)
    source_independence_score = float(candidate.get("source_independence_score", 0.0) or 0.0)
    layer = str(candidate.get("layer") or "").strip()
    policy = WRITE_POLICY_MATRIX.get(relation_type)
    if policy:
        allowed_claim_types = policy.get("allowed_claim_types", set())
        if claim_type and claim_type not in allowed_claim_types:
            issues.append(f"claim_type_not_allowed:{claim_type}")
        if corroboration_count < int(policy.get("min_corroboration_count", 1) or 1):
            issues.append("insufficient_corroboration_for_relation")
        if top_trust_score < float(policy.get("min_trust_score", 0.0) or 0.0):
            issues.append("insufficient_trust_for_relation")
        if not bool(policy.get("durable_allowed", True)) and claim_type == "durable_relation_candidate":
            warnings.append("relation_should_remain_non_durable")
    if layer and layer not in {"durable", "episodic", "inferred"}:
        warnings.append("unknown_relation_layer")
    if layer == "durable" and source_independence_score < 0.5:
        issues.append("insufficient_source_independence")
    if layer == "episodic" and relation_type not in NON_DURABLE_RELATIONS | {"mentions", "reported_by", "watchdog_allegation", "media_claim_disputed"}:
        warnings.append("episodic_claim_uses_durable_relation")
    if left_id.startswith("event-") and relation_type not in {"mentions", "announced_by", "affects"}:
        issues.append("event_node_used_as_durable_actor")
    if right_id.startswith("event-") and relation_type not in {"mentions", "announced_by", "affects", "appointed_to", "removed_from"}:
        issues.append("event_node_used_as_durable_target")
    verdict = "accept"
    if issues:
        verdict = "reject"
    elif warnings:
        verdict = "accept_with_warnings"
    return {"verdict": verdict, "issues": issues, "warnings": warnings, "left_category": left_category, "right_category": right_category, "source_independence_score": source_independence_score, "layer": layer}


def graph_safety_report(graph: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    relation_counts: Counter[str] = Counter()
    office_edges: dict[str, set[str]] = {}
    for relation in graph.get("relations", []):
        relation_type = str(relation.get("relation_type") or "")
        relation_counts[relation_type] += 1
        if relation_type == "holds_office_in":
            office_edges.setdefault(str(relation.get("from") or ""), set()).add(str(relation.get("to") or ""))
        if str(relation.get("from") or "").startswith("event-") and relation_type not in {"mentions", "announced_by", "affects"}:
            issues.append({"type": "event_leakage", "relation_id": relation.get("id"), "relation_type": relation_type})
        if relation.get("public_safe") is False:
            issues.append({"type": "sensitive_edge", "relation_id": relation.get("id"), "relation_type": relation_type})
    for entity_id, targets in office_edges.items():
        if len(targets) > 1:
            issues.append({"type": "multi_office_warning", "entity_id": entity_id, "targets": sorted(targets)})
    return {
        "issues": issues,
        "relation_counts": dict(relation_counts),
        "issue_count": len(issues),
        "multi_office_entities": [entity_id for entity_id, targets in office_edges.items() if len(targets) > 1],
    }


def verify_graph_proposal(graph: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    entity_ids = {str(entity.get("id")) for entity in graph.get("entities", [])}
    proposal_entities = proposal.get("entities", []) or []
    proposal_relations = proposal.get("relations", []) or []
    proposal_kind = str(proposal.get("proposal_kind") or "")
    proposal_claims = proposal.get("claims", []) or []
    provenance = proposal.get("provenance", {}) or {}
    for entity in proposal_entities:
        if isinstance(entity, str):
            entity_id = entity
            entity = {"id": entity}
        elif isinstance(entity, dict):
            entity_id = str(entity.get("id") or "")
        else:
            issues.append({"type": "invalid_entity_shape", "entity": entity})
            continue
        if not entity_id:
            issues.append({"type": "missing_entity_id", "entity": entity})
        elif entity_id in entity_ids:
            warnings.append({"type": "duplicate_entity", "entity_id": entity_id})
    for relation in proposal_relations:
        verdict = relation_safety(relation, graph)
        if verdict["verdict"] == "reject":
            issues.append({"type": "relation_rejected", "relation": relation, "reasons": verdict["issues"]})
        elif verdict["verdict"] == "accept_with_warnings":
            warnings.append({"type": "relation_warning", "relation": relation, "reasons": verdict["warnings"]})
    proposal_verdict = "accept"
    if issues:
        proposal_verdict = "reject"
    elif warnings:
        proposal_verdict = "accept_with_warnings"
    return {
        "verdict": proposal_verdict,
        "issues": issues,
        "warnings": warnings,
        "relation_count": len(proposal_relations),
        "entity_count": len(proposal_entities),
        "claim_count": len(proposal_claims),
        "proposal_kind": proposal_kind,
        "provenance": provenance,
    }


def local_graph_neighborhood(graph: dict[str, Any], entity_ids: list[str]) -> list[dict[str, Any]]:
    return [relation for relation in graph.get("relations", []) if relation.get("from") in entity_ids or relation.get("to") in entity_ids][:12]


def mutation_severity(proposal: dict[str, Any] | None) -> str:
    if not proposal:
        return "none"
    relations = proposal.get("relations", []) if isinstance(proposal, dict) else []
    if any(str(relation.get("relation_type") or "") != "mentions" for relation in relations if isinstance(relation, dict)):
        return "high"
    if relations:
        return "medium"
    return "low"


def critique_task(
    task: dict[str, Any],
    *,
    raw_output: str,
    parsed_output: dict[str, Any] | list[Any] | str | None,
    graph: dict[str, Any],
    sources: list[dict[str, Any]] | None = None,
    proposal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_type = str(task.get("task_type") or "")
    issues: list[str] = []
    cautions: list[str] = []
    failure_classes: list[str] = []
    proposal_entity_ids: list[str] = []
    if proposal and isinstance(proposal, dict):
        for relation in proposal.get("relations", []) or []:
            if isinstance(relation, dict):
                for key in ("from", "to"):
                    value = relation.get(key)
                    if isinstance(value, str) and not value.startswith("event-") and value not in proposal_entity_ids:
                        proposal_entity_ids.append(value)
    neighborhood = local_graph_neighborhood(graph, proposal_entity_ids)
    safety = verify_graph_proposal(graph, proposal) if proposal else {"verdict": "accept", "issues": [], "warnings": []}
    if safety["verdict"] == "reject":
        issues.append("graph_proposal_rejected")
        failure_classes.append("graph_safety")
        issues.extend(item.get("type", "proposal_error") for item in safety["issues"])
    elif safety["verdict"] == "accept_with_warnings":
        cautions.append("graph_proposal_warning")
        failure_classes.append("graph_warning")
    source_scores = [score_source(source) for source in sources or []]
    single_source = sum(1 for score in source_scores if score.get("source_id")) <= 1
    if source_scores and any(float(score["trust_score"]) < 0.65 for score in source_scores):
        cautions.append("low_trust_sources_present")
        failure_classes.append("source_trust")
    if single_source:
        cautions.append("single_source_input")
        failure_classes.append("source_trust")
    if proposal and isinstance(proposal, dict):
        proposal_kind = str(proposal.get("proposal_kind") or "")
        if proposal_kind == "claim_bundle" and proposal.get("durability_assessment") == "durable_relation_candidate" and single_source:
            issues.append("claim_to_fact_jump")
            failure_classes.append("claim_to_fact")
        if proposal.get("durability_assessment") == "event_only" and any(
            str(relation.get("relation_type") or "") != "mentions" for relation in proposal.get("relations", []) if isinstance(relation, dict)
        ):
            issues.append("event_only_contains_durable_relation")
            failure_classes.append("story_context_leakage")
    if task_type in {"refusal", "graph_safety"} and isinstance(parsed_output, dict):
        verdict = str(parsed_output.get("verdict") or parsed_output.get("decision") or "")
        if task_type == "refusal" and "insufficient" not in verdict.lower():
            issues.append("missing_insufficient_evidence_refusal")
            failure_classes.append("reasoning")
        if task_type == "graph_safety" and verdict not in {"accept", "accept_with_warnings", "reject"}:
            issues.append("invalid_graph_verdict")
            failure_classes.append("format")
    if task_type in {"entity_extraction", "relation_extraction"} and isinstance(parsed_output, dict):
        if not parsed_output.get("entities") and not parsed_output.get("relations"):
            issues.append("empty_structured_extraction")
            failure_classes.append("format")
    safety_report = graph_safety_report(graph)
    if safety_report["issue_count"] > 0:
        cautions.append("graph_has_existing_safety_issues")
    status = "pass"
    if issues:
        status = "fail"
    elif cautions:
        status = "warn"
    return {
        "status": status,
        "issues": issues,
        "cautions": cautions,
        "failure_classes": sorted(set(failure_classes)),
        "mutation_severity": mutation_severity(proposal),
        "neighborhood_size": len(neighborhood),
        "raw_output_excerpt": raw_output[:200],
    }


def summarize_flow_run(run: dict[str, Any]) -> dict[str, Any]:
    result = run.get("result", {}) if isinstance(run.get("result"), dict) else {}
    progress = run.get("progress", {}) if isinstance(run.get("progress", {}), dict) else {}
    if not progress and isinstance(result.get("progress", {}), dict):
        progress = result.get("progress", {})
    phases = run.get("phase_receipts", []) if isinstance(run.get("phase_receipts", []), list) else []
    if not phases and isinstance(result.get("phase_receipts", []), list):
        phases = result.get("phase_receipts", [])
    graph_summary = result.get("graph_summary", {}) if isinstance(result.get("graph_summary"), dict) else {}
    operator_trace = result.get("operator_trace_summary", "")
    return {
        "run_id": str(run.get("run_id", "")),
        "task_type": str(run.get("task_type", "")),
        "query": str(run.get("query", "")),
        "topic": str(run.get("topic", "")),
        "status": str(run.get("status") or result.get("status") or ""),
        "failure_class": str(run.get("failure_class") or result.get("failure_class") or ""),
        "updated_at": str(run.get("updated_at") or run.get("finished_at") or run.get("started_at") or ""),
        "finished_at": str(run.get("finished_at") or ""),
        "phase_count": len(phases),
        "partial": bool(run.get("partial") or result.get("partial")),
        "publish_status": str(progress.get("publish_status") or ""),
        "verified_stories": int(progress.get("verified_stories", 0) or 0),
        "rejected_stories": int(progress.get("rejected_stories", 0) or 0),
        "graph_updates_applied": int(progress.get("graph_updates_applied", 0) or 0),
        "graph_updates_rejected": int(progress.get("graph_updates_rejected", 0) or 0),
        "publication_count": int(progress.get("publication_count", 0) or 0),
        "transport_receipts": len(run.get("transport_receipts", []) or []),
        "graph_summary": graph_summary,
        "checkpoint_phase": str(run.get("checkpoint", {}).get("phase", "")) if isinstance(run.get("checkpoint"), dict) else "",
        "operator_trace_summary": operator_trace,
    }


def load_flow_runs(limit: int = 8) -> dict[str, Any]:
    from pipeline_common import TASK_RUNS_FILE

    runs = list(reversed(_tail_jsonl(TASK_RUNS_FILE, limit=limit * 2)))
    deduped: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for run in runs:
        run_id = str(run.get("run_id", ""))
        if run_id and run_id in seen_ids:
            continue
        if run_id:
            seen_ids.add(run_id)
        deduped.append(run)
        if len(deduped) >= limit:
            break
    return {"updated_at": iso_now(), "count": len(deduped), "runs": [summarize_flow_run(run) for run in deduped]}


def latest_graph_diff() -> dict[str, Any]:
    from pipeline_common import GRAPH_DIFF_LATEST_FILE

    if GRAPH_DIFF_LATEST_FILE.exists():
        return _load_json(GRAPH_DIFF_LATEST_FILE, {})
    return {}


def write_latest_graph_diff(payload: dict[str, Any]) -> None:
    from pipeline_common import GRAPH_DIFF_LATEST_FILE

    _write_json(GRAPH_DIFF_LATEST_FILE, payload)


def _top_entity_summary(graph: dict[str, Any], limit: int = 8) -> list[dict[str, Any]]:
    runtime = graph.get("runtime", {}) if isinstance(graph.get("runtime", {}), dict) else {}
    graph_runtime = runtime.get("graph", {}) if isinstance(runtime.get("graph", {}), dict) else {}
    memory = graph_runtime.get("memory", {}) if isinstance(graph_runtime.get("memory", {}), dict) else {}
    top_entities = memory.get("top_entities", [])
    entities = _entity_index(graph)
    if top_entities:
        return [{"id": str(item.get("id", "")), "name": str(item.get("name") or entities.get(str(item.get("id", "")), {}).get("name", item.get("id", ""))), "count": int(item.get("count", 0) or 0)} for item in top_entities[:limit] if str(item.get("id", ""))]
    counter = Counter()
    for relation in graph.get("relations", []):
        counter.update([str(relation.get("from", "")), str(relation.get("to", ""))])
    return [{"id": entity_id, "name": entities.get(entity_id, {}).get("name", entity_id), "count": count} for entity_id, count in counter.most_common(limit) if entity_id in entities]


def context_layer_summary(graph: dict[str, Any]) -> dict[str, Any]:
    runtime = graph.get("runtime", {}) if isinstance(graph.get("runtime", {}), dict) else {}
    graph_runtime = runtime.get("graph", {}) if isinstance(runtime.get("graph", {}), dict) else {}
    context_view = graph_runtime.get("graph_context_view", {}) if isinstance(graph_runtime.get("graph_context_view", {}), dict) else {}
    memory_cards = graph_runtime.get("graph_memory_cards", []) if isinstance(graph_runtime.get("graph_memory_cards", []), list) else []
    provenance_sources: list[str] = []
    provenance_story_ids: list[str] = []
    for story in graph_runtime.get("verified_story_pack", [])[:12]:
        story_id = str(story.get("story_id", ""))
        if story_id:
            provenance_story_ids.append(story_id)
        for source in story.get("sources", [])[:6]:
            url = str(source.get("url") or "").strip()
            if url and url not in provenance_sources:
                provenance_sources.append(url)
    for story in graph_runtime.get("rejected_story_pack", [])[:8]:
        story_id = str(story.get("story_id", ""))
        if story_id and story_id not in provenance_story_ids:
            provenance_story_ids.append(story_id)
        for source in story.get("sources", [])[:4]:
            url = str(source.get("url") or "").strip()
            if url and url not in provenance_sources:
                provenance_sources.append(url)
    return {
        "updated_at": iso_now(),
        "core": {"updated_at": iso_now(), "entity_count": len(graph.get("entities", [])), "relation_count": len(graph.get("relations", [])), "event_count": len(graph.get("event_nodes", [])), "top_entities": _top_entity_summary(graph, limit=8)},
        "provenance": {"updated_at": iso_now(), "story_count": len(graph_runtime.get("verified_story_pack", [])) + len(graph_runtime.get("rejected_story_pack", [])), "accepted_story_count": len(graph_runtime.get("verified_story_pack", [])), "rejected_story_count": len(graph_runtime.get("rejected_story_pack", [])), "proposal_receipts": len(graph_runtime.get("proposal_receipts", [])), "source_count": len(provenance_sources), "recent_story_ids": provenance_story_ids[:12], "recent_source_urls": provenance_sources[:12]},
        "retrieval": {"updated_at": iso_now(), "focus_story_ids": list(context_view.get("focus_story_ids", [])[:12]), "focus_entities_count": len(context_view.get("focus_entities", []) or []), "focus_relations_count": len(context_view.get("focus_relations", []) or []), "study_links_count": len(context_view.get("study_links", []) or []), "memory_cards_count": len(memory_cards)},
        "flows": {"updated_at": iso_now(), "latest_run_ids": [item.get("run_id", "") for item in load_flow_runs(limit=8).get("runs", []) if item.get("run_id")]},
    }
