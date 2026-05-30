#!/usr/bin/env python3
"""Graph proposal, verification, and durable-write stage for Thiezer."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from graph_domain import (
    build_claim_from_relation,
    build_edge_from_claim,
    build_narrative_from_claim,
    canonical_admission,
    context_layer_summary,
    critique_task,
    default_graph_bundle,
    graph_safety_report,
    iso_now as domain_iso_now,
    normalize_event,
    normalize_vertex,
    relation_class,
    verify_graph_proposal,
    sync_compatibility_views,
)
from graph_memory import (
    append_proposal_ledger,
    claim_hash,
    duplicate_claim_exists,
    novelty_gate,
    proposal_hash,
    promote_or_reject_proposal,
)
from pipeline_common import (
    CANONICAL_GRAPH,
    EVALS_LATEST_DIR,
    EVIDENCE_LOG,
    append_jsonl,
    ensure_layout,
    iso_now,
    load_graph,
    relation_types_payload,
    stable_hash,
    write_json,
)
from semantic_edge_builder import semantic_edge_fields


def entity_by_id(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(entity.get("id")): entity for entity in graph.get("entities", [])}


def _merge_evidence_list(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge evidence lists, deduplicating by URL."""
    seen_urls: set[str] = set()
    merged: list[dict[str, Any]] = []
    for item in [*existing, *incoming]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        key = url or str(item.get("title") or "").strip()
        if not key or key in seen_urls:
            continue
        seen_urls.add(key)
        merged.append(item)
    return merged[:24]


def _merge_timeline(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge timeline dicts, widening the date range."""
    start = str(existing.get("start_date") or incoming.get("start_date") or "").strip() or None
    end = str(incoming.get("end_date") or existing.get("end_date") or "").strip() or None
    if start and existing.get("start_date") and str(existing["start_date"]) < start:
        start = str(existing["start_date"])
    return {"start_date": start, "end_date": end}


def validate_edge_quality(edge: dict[str, Any]) -> tuple[bool, str]:
    """Reject edges that are shallow/empty. Returns (is_valid, reason)."""
    relation_type = str(edge.get("relation_type") or edge.get("type") or "").strip()
    if relation_type in {"connected", "related", "unknown", ""}:
        return False, "shallow_relation_type"
    has_evidence = bool(
        edge.get("evidence_quote")
        or edge.get("natural_language_summary")
        or edge.get("evidence")
        or edge.get("notes")
        or edge.get("evidence_ids")
    )
    if not has_evidence:
        return False, "no_evidence_or_summary"
    return True, "ok"


def upsert_relation(graph: dict[str, Any], relation: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    relations = graph.setdefault("edges", [])
    for existing in relations:
        if (
            existing.get("from") == relation.get("from")
            and existing.get("to") == relation.get("to")
            and existing.get("type") == relation.get("type")
        ):
            existing["confidence"] = round(
                max(float(existing.get("confidence", 0.0) or 0.0), float(relation.get("confidence", 0.0) or 0.0)),
                3,
            )
            existing["updated_at"] = iso_now()
            existing["status"] = relation.get("status", existing.get("status", "reported"))
            existing["claim_ids"] = sorted(set(existing.get("claim_ids", [])) | set(relation.get("claim_ids", [])))
            existing["evidence_ids"] = sorted(set(existing.get("evidence_ids", [])) | set(relation.get("evidence_ids", [])))
            existing["source_ids"] = sorted(set(existing.get("source_ids", [])) | set(relation.get("source_ids", [])))
            # Merge enriched edge fields
            new_summary = str(relation.get("natural_language_summary") or "").strip()
            if new_summary and len(new_summary) > len(str(existing.get("natural_language_summary") or "")):
                existing["natural_language_summary"] = new_summary
            new_human = str(relation.get("human_text") or "").strip()
            if new_human and not existing.get("human_text"):
                existing["human_text"] = new_human
            if relation.get("event_context") and not existing.get("event_context"):
                existing["event_context"] = relation["event_context"]
            existing["evidence"] = _merge_evidence_list(
                list(existing.get("evidence") or []),
                list(relation.get("evidence") or []),
            )
            existing["timeline"] = _merge_timeline(
                existing.get("timeline") or {},
                relation.get("timeline") or {},
            )
            if relation.get("model_analysis") and isinstance(relation["model_analysis"], dict):
                existing["model_analysis"] = relation["model_analysis"]
            for field in ["relation_class", "short_label", "semantic_summary", "role_from", "role_to", "mechanism_tags", "edge_kind", "canonical"]:
                if relation.get(field) and not existing.get(field):
                    existing[field] = relation[field]
            return "strengthened", existing
    relation["updated_at"] = iso_now()
    relations.append(relation)
    return "added", relation


def upsert_vertex(graph: dict[str, Any], vertex: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    vertices = graph.setdefault("vertices", [])
    existing = next((item for item in vertices if str(item.get("id") or "") == str(vertex.get("id") or "")), None)
    normalized = normalize_vertex(vertex, kind=str(vertex.get("kind") or "entity"))
    if existing is not None:
        existing.update(normalized)
        existing["updated_at"] = iso_now()
        return "updated", existing
    vertices.append(normalized)
    return "added", normalized


def _slug_bits(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or ""))
    return "-".join(bit for bit in cleaned.split("-") if bit)[:80]


def _vertex_id(kind: str, label: str) -> str:
    slug = _slug_bits(label)
    return f"{kind}-{slug}" if slug else f"{kind}-{stable_hash(kind, label)}"


def _upsert_structured_relation(
    graph: dict[str, Any],
    *,
    left_id: str,
    right_id: str,
    relation_type: str,
    source_ids: list[str] | None = None,
    evidence_ids: list[str] | None = None,
    confidence: float = 0.88,
    status: str = "confirmed",
    valid_from: str | None = None,
    valid_to: str | None = None,
    notes: str = "",
    natural_language_summary: str = "",
    event_context: str = "",
    evidence_list: list[dict[str, Any]] | None = None,
    model_analysis: dict[str, Any] | None = None,
    human_text: str = "",
) -> tuple[str, dict[str, Any]]:
    edge = {
        "id": f"edge-{stable_hash(left_id, right_id, relation_type)}",
        "from": left_id,
        "to": right_id,
        "type": relation_type,
        "relation_type": relation_type,
        "layer": "canonical",
        "status": status,
        "confidence": round(float(confidence or 0.0), 3),
        "valid_from": valid_from or None,
        "valid_to": valid_to or None,
        "claim_ids": [],
        "evidence_ids": list(evidence_ids or []),
        "source_ids": list(source_ids or []),
        "public_safe": True,
        "notes": notes[:280].strip(),
        "natural_language_summary": natural_language_summary[:600].strip(),
        "event_context": event_context[:120].strip(),
        "evidence": list(evidence_list or [])[:24],
        "model_analysis": dict(model_analysis) if model_analysis else {},
        "human_text": human_text[:200].strip(),
        "timeline": {"start_date": valid_from or None, "end_date": valid_to or None},
        "updated_at": iso_now(),
    }
    edge.update(semantic_edge_fields(edge))
    return upsert_relation(graph, edge)


def _source_and_evidence_ids(graph: dict[str, Any], *, source_url: str, source_type: str, evidence_quote: str, effective_date: str = "") -> tuple[list[str], list[str]]:
    source_id = f"source-{stable_hash(source_url, source_type)}"
    evidence_id = f"evidence-{stable_hash(source_url, evidence_quote[:200], effective_date)}"
    upsert_support_rows(
        graph,
        sources=[
            {
                "id": source_id,
                "url": source_url,
                "title": source_url,
                "publisher": source_url,
                "source_class": source_type or "official",
                "language": "",
                "reliability": 0.92 if source_type == "official" else 0.78,
                "updated_at": iso_now(),
            }
        ],
        evidence=[
            {
                "id": evidence_id,
                "source_id": source_id,
                "url": source_url,
                "title": source_url,
                "publisher": source_url,
                "source_class": source_type or "official",
                "language": "",
                "published_at": effective_date,
                "retrieved_at": iso_now(),
                "snippet": evidence_quote,
                "quote": evidence_quote,
                "stance": "supporting",
                "supports_claim_ids": [],
                "contradicts_claim_ids": [],
            }
        ],
        perspectives=[],
        narratives=[],
    )
    return [source_id], [evidence_id]


def promote_roster_records(graph: dict[str, Any]) -> dict[str, Any]:
    exploration = graph.get("runtime", {}).get("exploration", {}) if isinstance(graph.get("runtime", {}).get("exploration", {}), dict) else {}
    records = [row for row in (exploration.get("roster_records", []) or []) if isinstance(row, dict)]
    entity_actions: list[dict[str, Any]] = []
    relation_actions: list[dict[str, Any]] = []
    event_actions: list[dict[str, Any]] = []

    government_id = _vertex_id("institution", "Government of Armenia")
    mod_id = _vertex_id("institution", "Ministry of Defense of Armenia")
    gs_id = _vertex_id("institution", "General Staff of the Armed Forces of Armenia")
    for vertex in [
        {"id": government_id, "label": "Government of Armenia", "category": "government", "kind": "entity", "subtype": "government", "summary": "Supreme body of the executive power of Armenia."},
        {"id": mod_id, "label": "Ministry of Defense of Armenia", "category": "institution", "kind": "entity", "subtype": "ministry", "summary": "State body responsible for defense policy."},
        {"id": gs_id, "label": "General Staff of the Armed Forces of Armenia", "category": "institution", "kind": "entity", "subtype": "general_staff", "summary": "State body operating in the sphere of management of the Ministry of Defense of Armenia."},
    ]:
        action, inserted = upsert_vertex(graph, vertex)
        entity_actions.append({"action": action, "entity_id": inserted.get("id"), "name": inserted.get("name")})
    _upsert_structured_relation(
        graph, left_id=gs_id, right_id=mod_id, relation_type="part_of", confidence=0.93, status="confirmed",
        natural_language_summary="The General Staff of the Armed Forces operates within the Ministry of Defense of Armenia.",
        human_text="General Staff → part of Ministry of Defense",
        event_context="institutional_hierarchy",
    )
    _upsert_structured_relation(
        graph, left_id=mod_id, right_id=government_id, relation_type="part_of", confidence=0.93, status="confirmed",
        natural_language_summary="The Ministry of Defense is a state body within the Government of Armenia.",
        human_text="Ministry of Defense → part of Government",
        event_context="institutional_hierarchy",
    )

    for record in records:
        person_name = str(record.get("person_name") or "").strip()
        office_name = str(record.get("office_name") or "").strip()
        institution_name = str(record.get("institution_name") or "").strip()
        if not person_name or not office_name or not institution_name:
            continue
        parent_name = str(record.get("parent_institution_name") or "").strip()
        person_id = _vertex_id("person", person_name)
        office_id = _vertex_id("office", office_name)
        institution_id = _vertex_id("institution", institution_name)
        source_url = str(record.get("source_url") or "").strip()
        source_type = str(record.get("source_type") or "official").strip()
        evidence_quote = str(record.get("evidence_quote") or office_name).strip()
        effective_date = str(record.get("effective_date") or "").strip()
        event_type = str(record.get("event_type") or "").strip()
        source_ids, evidence_ids = _source_and_evidence_ids(
            graph,
            source_url=source_url,
            source_type=source_type,
            evidence_quote=evidence_quote,
            effective_date=effective_date,
        )
        # Build evidence list for this record
        record_evidence: list[dict[str, Any]] = []
        if source_url:
            record_evidence.append({
                "title": source_url.split("//")[-1].split("/")[0] if "//" in source_url else source_url,
                "url": source_url,
                "fact": evidence_quote[:280],
            })
        for vertex in [
            {"id": person_id, "label": person_name, "category": "person", "kind": "entity", "subtype": "official", "summary": str(record.get("evidence_quote") or "")[:260]},
            {"id": office_id, "label": office_name, "category": "office", "kind": "entity", "subtype": "state_office", "summary": office_name},
            {"id": institution_id, "label": institution_name, "category": "institution", "kind": "entity", "subtype": "institution", "summary": institution_name},
        ]:
            action, inserted = upsert_vertex(graph, vertex)
            entity_actions.append({"action": action, "entity_id": inserted.get("id"), "name": inserted.get("name")})
        if parent_name:
            parent_id = _vertex_id("institution", parent_name)
            action, inserted = upsert_vertex(graph, {"id": parent_id, "label": parent_name, "category": "institution", "kind": "entity", "subtype": "institution", "summary": parent_name})
            entity_actions.append({"action": action, "entity_id": inserted.get("id"), "name": inserted.get("name")})
            rel_action, relation = _upsert_structured_relation(
                graph,
                left_id=institution_id,
                right_id=parent_id,
                relation_type="part_of",
                source_ids=source_ids,
                evidence_ids=evidence_ids,
                confidence=float(record.get("confidence", 0.9) or 0.9),
                status="confirmed",
                natural_language_summary=f"{institution_name} is a subordinate body of {parent_name}.",
                human_text=f"{institution_name} → part of {parent_name}",
                event_context="institutional_hierarchy",
                evidence_list=record_evidence,
            )
            relation_actions.append({"action": rel_action, "relation_id": relation.get("id"), "from": relation.get("from"), "to": relation.get("to")})
        rel_action, relation = _upsert_structured_relation(
            graph,
            left_id=office_id,
            right_id=institution_id,
            relation_type="part_of",
            source_ids=source_ids,
            evidence_ids=evidence_ids,
            confidence=float(record.get("confidence", 0.9) or 0.9),
            status="confirmed",
            natural_language_summary=f"The office of {office_name} is a position within {institution_name}.",
            human_text=f"{office_name} → within {institution_name}",
            event_context="institutional_hierarchy",
            evidence_list=record_evidence,
        )
        relation_actions.append({"action": rel_action, "relation_id": relation.get("id"), "from": relation.get("from"), "to": relation.get("to")})
        # Build human_text for the holds_office_in edge
        date_suffix = f" ({effective_date})" if effective_date else ""
        holds_human_text = f"{person_name} → {office_name}{date_suffix}"
        holds_summary = evidence_quote or f"{person_name} holds the office of {office_name} in {institution_name}."
        holds_event_ctx = "appointment" if event_type == "appointed_to" else ("dismissal" if event_type == "removed_from" else "office_tenure")
        rel_action, relation = _upsert_structured_relation(
            graph,
            left_id=person_id,
            right_id=office_id,
            relation_type="holds_office_in",
            source_ids=source_ids,
            evidence_ids=evidence_ids,
            confidence=float(record.get("confidence", 0.9) or 0.9),
            status="confirmed",
            valid_from=effective_date or None,
            notes=str(record.get("seed_reason") or ""),
            natural_language_summary=holds_summary,
            human_text=holds_human_text,
            event_context=holds_event_ctx,
            evidence_list=record_evidence,
        )
        relation_actions.append({"action": rel_action, "relation_id": relation.get("id"), "from": relation.get("from"), "to": relation.get("to")})

        event_type = str(record.get("event_type") or "").strip()
        if event_type in {"appointed_to", "removed_from"}:
            effective_date = str(record.get("effective_date") or "").strip()
            event_label = f"{person_name} {event_type.replace('_', ' ')} {office_name}"
            event_id = f"event-{stable_hash(person_id, office_id, event_type, effective_date)}"
            event_node = normalize_event(
                {
                    "id": event_id,
                    "label": event_label,
                    "type": event_type,
                    "topic": "internal_politics",
                    "summary": str(record.get("evidence_quote") or event_label),
                    "actor_ids": [person_id, office_id, institution_id],
                    "source_ids": source_ids,
                    "evidence_ids": evidence_ids,
                    "valid_from": effective_date or None,
                    "observed_at": effective_date or iso_now(),
                    "updated_at": iso_now(),
                }
            )
            event_action = upsert_event_node(graph.setdefault("events", []), event_node)
            event_actions.append({"action": event_action, "event_id": event_id, "label": event_label})
            event_human = f"{person_name} {'appointed to' if event_type == 'appointed_to' else 'removed from'} {office_name}"
            event_summary = evidence_quote or event_human
            event_ctx = "appointment" if event_type == "appointed_to" else "dismissal"
            for rel_type_iter, left_id_iter, right_id_iter, iter_human, iter_summary in [
                (event_type, person_id, event_id, f"{person_name} → {event_human}", event_summary),
                ("affects", event_id, office_id, f"{event_label} → affects {office_name}", f"This event affected the office of {office_name}."),
            ]:
                rel_action, relation = _upsert_structured_relation(
                    graph,
                    left_id=left_id_iter,
                    right_id=right_id_iter,
                    relation_type=rel_type_iter,
                    source_ids=source_ids,
                    evidence_ids=evidence_ids,
                    confidence=float(record.get("confidence", 0.88) or 0.88),
                    status="confirmed",
                    valid_from=effective_date or None,
                    natural_language_summary=iter_summary,
                    human_text=iter_human,
                    event_context=event_ctx,
                    evidence_list=record_evidence,
                )
                relation_actions.append({"action": rel_action, "relation_id": relation.get("id"), "from": relation.get("from"), "to": relation.get("to")})

    return {
        "record_count": len(records),
        "entity_actions": entity_actions,
        "relation_actions": relation_actions,
        "event_actions": event_actions,
    }


def upsert_event_node(event_nodes: list[dict[str, Any]], event_node: dict[str, Any]) -> str:
    existing = next((node for node in event_nodes if node.get("id") == event_node["id"]), None)
    if existing:
        existing.update(event_node)
        return "updated"
    event_nodes.append(event_node)
    return "added"


def upsert_claim(graph: dict[str, Any], claim: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    claims = graph.setdefault("claims", [])
    existing = next((item for item in claims if str(item.get("claim_hash") or "") == str(claim.get("claim_hash") or "")), None)
    if existing:
        existing["status"] = claim.get("status", existing.get("status", "observed"))
        existing["updated_at"] = iso_now()
        existing["source_ids"] = sorted(set(existing.get("source_ids", [])) | set(claim.get("source_ids", [])))
        existing["evidence_ids"] = sorted(set(existing.get("evidence_ids", [])) | set(claim.get("evidence_ids", [])))
        return "updated", existing
    claims.append(claim)
    return "added", claim


def upsert_support_rows(graph: dict[str, Any], *, sources: list[dict[str, Any]], evidence: list[dict[str, Any]], perspectives: list[dict[str, Any]], narratives: list[dict[str, Any]]) -> None:
    for key, rows in {"sources": sources, "evidence": evidence, "perspectives": perspectives, "narratives": narratives}.items():
        bucket = graph.setdefault(key, [])
        existing_ids = {str(item.get("id") or "") for item in bucket if isinstance(item, dict)}
        for row in rows:
            row_id = str(row.get("id") or "").strip()
            if not row_id:
                continue
            if row_id in existing_ids:
                existing = next((item for item in bucket if str(item.get("id") or "") == row_id), None)
                if existing is not None:
                    existing.update(row)
                continue
            bucket.append(row)
            existing_ids.add(row_id)


def upsert_story_mentions(story_mentions: list[dict[str, Any]], item: dict[str, Any]) -> str:
    existing = next((row for row in story_mentions if row.get("story_id") == item.get("story_id")), None)
    if existing:
        existing.update(item)
        return "updated"
    story_mentions.append(item)
    return "added"


def build_event_node(story: dict[str, Any]) -> dict[str, Any]:
    return normalize_event(
        {
        "id": f"event-{story['story_id']}",
        "label": story.get("summary_line", story.get("title", story["story_id"])),
        "type": story.get("topic", ""),
        "summary": story.get("public_impact", ""),
        "actor_ids": [str(item).strip() for item in story.get("actors_detected", []) if str(item).strip()],
        "source_ids": [str(item.get("source_id") or "").strip() for item in story.get("sources", []) if str(item.get("source_id") or "").strip()],
        "public_safe": True,
        "updated_at": iso_now(),
    }
    )


def relation_candidates_for_story(story: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for claim in story.get("claim_bundles", [])[:12]:
        if not isinstance(claim, dict):
            continue
        actor_id = str(claim.get("to") or "")
        event_id = str(claim.get("from") or f"event-{story['story_id']}")
        source_links = [
            {
                "title": str(source.get("label") or source.get("url") or "").strip(),
                "url": str(source.get("url") or "").strip(),
                "domain": str(source.get("url") or "").strip(),
                "source_type": str(source.get("type") or "media").strip(),
                "language": "",
                "date_if_known": str(story.get("published_at") or ""),
            }
            for source in story.get("sources", [])[:4]
            if str(source.get("url") or "").strip()
        ]
        candidates.append(
            {
                "id": stable_hash(event_id, actor_id, str(claim.get("relation_type") or "mentions")),
                "from": event_id,
                "to": actor_id,
                "relation_type": str(claim.get("relation_type") or "mentions"),
                "status": "reported",
                "source_url": source_links[0]["url"] if source_links else "",
                "source_type": source_links[0]["source_type"] if source_links else "",
                "evidence_quote": str(claim.get("evidence_quote") or story.get("summary_line", "")),
                "evidence_level": "story_summary",
                "confidence": 0.72,
                "collected_at": iso_now(),
                "last_checked_at": iso_now(),
                "public_safe": True,
                "notes": story.get("relationship_context", ""),
                "claim_type": claim.get("claim_type", "event_only"),
                "corroboration_count": claim.get("corroboration_count", 1),
                "top_trust_score": claim.get("top_trust_score", 0.0),
                "layer": "episodic",
                "claim_hash": str(claim.get("claim_hash") or claim_hash(claim)),
                "source_links": source_links,
                "source_independence_score": claim.get("source_independence_score", 0.0),
            }
        )
    return candidates


def claim_records_for_story(story: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    relation_candidates = relation_candidates_for_story(story)
    sources: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    perspectives: list[dict[str, Any]] = []
    narratives: list[dict[str, Any]] = []
    sources_by_id: dict[str, dict[str, Any]] = {}
    for candidate in relation_candidates:
        source_ids: list[str] = []
        evidence_ids: list[str] = []
        for source_link in candidate.get("source_links", []) or []:
            source_id = f"source-{stable_hash(source_link.get('url', ''), source_link.get('source_type', 'media'))}"
            source = {
                "id": source_id,
                "url": str(source_link.get("url") or "").strip(),
                "title": str(source_link.get("title") or "").strip(),
                "publisher": str(source_link.get("title") or "").strip(),
                "source_class": str(source_link.get("source_type") or "media").strip(),
                "language": str(source_link.get("language") or "").strip(),
                "reliability": round(float(candidate.get("top_trust_score", candidate.get("confidence", 0.55)) or 0.55), 3),
                "updated_at": iso_now(),
            }
            if source_id not in sources_by_id:
                sources_by_id[source_id] = source
                sources.append(source)
            source_ids.append(source_id)
            evidence_id = f"evidence-{stable_hash(candidate.get('id', ''), source_id, source_link.get('url', ''))}"
            evidence_rows.append(
                {
                    "id": evidence_id,
                    "source_id": source_id,
                    "url": source["url"],
                    "title": source["title"] or source["url"],
                    "publisher": source["publisher"],
                    "source_class": source["source_class"],
                    "language": source["language"],
                    "published_at": str(story.get("published_at") or "").strip(),
                    "retrieved_at": str(candidate.get("collected_at") or iso_now()).strip(),
                    "snippet": str(candidate.get("evidence_quote") or candidate.get("notes") or "").strip(),
                    "quote": str(candidate.get("evidence_quote") or "").strip(),
                    "stance": "supporting",
                    "supports_claim_ids": [],
                    "contradicts_claim_ids": [],
                }
            )
            evidence_ids.append(evidence_id)
        claim = build_claim_from_relation(candidate, evidence_ids=evidence_ids, source_ids=source_ids)
        for evidence in evidence_rows[-len(evidence_ids):]:
            evidence["supports_claim_ids"].append(claim["id"])
        claims.append(claim)
        if relation_class(str(claim.get("claim_type") or "")) in {"interpretive", "political", "observational"} or float(claim.get("interpretive_degree", 0.0) or 0.0) >= 0.6:
            perspectives.append(
                {
                    "id": f"perspective-{stable_hash(claim['subject_vertex_id'], claim['claim_type'], claim['statement'][:96])}",
                    "vertex_id": claim["subject_vertex_id"],
                    "actor_vertex_id": None,
                    "source_group": "independent_media",
                    "perspective_type": "independent_media",
                    "stance": "reported",
                    "summary": claim["statement"],
                    "claim_ids": [claim["id"]],
                    "evidence_ids": evidence_ids,
                    "updated_at": iso_now(),
                }
            )
        narrative = build_narrative_from_claim(claim, evidence_ids=evidence_ids)
        if narrative:
            narratives.append(narrative)
    return {
        "sources": sources,
        "evidence": evidence_rows,
        "claims": claims,
        "perspectives": perspectives,
        "narratives": narratives,
    }


def build_proposal(story: dict[str, Any]) -> dict[str, Any]:
    claim_bundles = [
        {
            **claim,
            "claim_hash": str(claim.get("claim_hash") or claim_hash(claim)),
            "layer": str(claim.get("layer") or "episodic"),
        }
        for claim in story.get("claim_bundles", [])
        if isinstance(claim, dict)
    ]
    proposal = {
        "proposal_kind": "claim_bundle",
        "entities": [normalize_vertex({"id": f"event-{story['story_id']}", "label": story.get("summary_line", story.get("title", story["story_id"])), "category": "event", "subtype": story.get("topic", ""), "summary": story.get("public_impact", ""), "public_safe": True}, kind="event")],
        "relations": relation_candidates_for_story(story),
        "event_nodes": [build_event_node(story)],
        "claims": claim_bundles,
        "story_id": story.get("story_id"),
        "durability_assessment": "event_only",
        "why_not_durable": "story mention and event participation should not become durable actor alignment automatically",
        "evidence_refs": [source.get("url", "") for source in story.get("sources", []) if source.get("url")][:6],
        "provenance": {
            "source_ids": [source.get("source_id", "") for source in story.get("sources", []) if source.get("source_id")],
            "top_source": story.get("source_trust", {}).get("top_source", {}),
            "retrieval_mode": story.get("story_context_pack", {}).get("retrieval_mode", ""),
            "source_independence_score": min((float(claim.get("source_independence_score", 0.0) or 0.0) for claim in claim_bundles), default=0.0),
        },
    }
    proposal["proposal_hash"] = proposal_hash(proposal)
    return proposal


def graph_context_view(graph: dict[str, Any], verified_story_pack: list[dict[str, Any]]) -> dict[str, Any]:
    entities = entity_by_id(graph)
    focus_entity_ids: list[str] = []
    for story in verified_story_pack[:6]:
        for entity_id in story.get("actors_detected", [])[:4]:
            if entity_id not in focus_entity_ids:
                focus_entity_ids.append(entity_id)
    focus_relations = [
        relation
        for relation in graph.get("relations", [])
        if relation.get("from") in focus_entity_ids or relation.get("to") in focus_entity_ids
    ][:24]
    focus_entities = [
        {
            "id": entity_id,
            "name": entities.get(entity_id, {}).get("name", entity_id),
            "category": entities.get(entity_id, {}).get("category", "unknown"),
            "summary": entities.get(entity_id, {}).get("summary", ""),
            "profile": entities.get(entity_id, {}).get("profile", {}),
            "links": entities.get(entity_id, {}).get("links", {}),
        }
        for entity_id in focus_entity_ids[:12]
    ]
    return {
        "updated_at": iso_now(),
        "focus_story_ids": [story.get("story_id") for story in verified_story_pack[:6]],
        "focus_entities": focus_entities,
        "focus_relations": focus_relations,
        "study_links": [
            link
            for story in verified_story_pack[:6]
            for link in story.get("study_links", [])[:6]
        ][:24],
    }


def graph_memory_cards(graph: dict[str, Any], verified_story_pack: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entities = entity_by_id(graph)
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for story in verified_story_pack:
        for entity_id in story.get("actors_detected", [])[:4]:
            if entity_id in seen or entity_id not in entities:
                continue
            seen.add(entity_id)
            entity = entities[entity_id]
            local_relations = [
                relation
                for relation in graph.get("relations", [])
                if relation.get("from") == entity_id or relation.get("to") == entity_id
            ][:10]
            cards.append(
                {
                    "entity_id": entity_id,
                    "name": entity.get("name", entity_id),
                    "category": entity.get("category", "unknown"),
                    "summary": entity.get("summary", ""),
                    "profile": entity.get("profile", {}),
                    "links": entity.get("links", {}),
                    "local_relations": local_relations,
                    "recent_events": [story.get("story_id") for story in verified_story_pack if entity_id in story.get("actors_detected", [])][:4],
                    "recent_event_titles": [
                        story.get("summary_line", story.get("title", story.get("story_id", "")))
                        for story in verified_story_pack
                        if entity_id in story.get("actors_detected", [])
                    ][:4],
                }
            )
    return cards[:12]


def graph_memory_snapshot(graph: dict[str, Any]) -> dict[str, Any]:
    entity_counts = Counter(entity.get("category", "unknown") for entity in graph.get("entities", []))
    relation_counts = Counter(relation.get("relation_type", "unknown") for relation in graph.get("relations", []))
    top_entities = Counter()
    for relation in graph.get("relations", []):
        top_entities.update([relation.get("from", ""), relation.get("to", "")])
    entities = entity_by_id(graph)
    return {
        "updated_at": iso_now(),
        "entity_counts": dict(entity_counts),
        "relation_counts": dict(relation_counts.most_common(8)),
        "top_entities": [
            {
                "id": entity_id,
                "name": entities.get(entity_id, {}).get("name", entity_id),
                "count": count,
            }
            for entity_id, count in top_entities.most_common(8)
            if entity_id in entities
        ],
    }


def main() -> int:
    ensure_layout()
    graph = sync_compatibility_views(load_graph() or default_graph_bundle())
    retrieval = graph.get("runtime", {}).get("retrieval", {})
    stories = list(retrieval.get("stories", []))
    event_nodes = graph.setdefault("events", [])
    story_mentions = graph.setdefault("story_mentions", [])
    graph.setdefault("relation_types", relation_types_payload())
    roster_runtime = promote_roster_records(graph)

    relation_updates = 0
    claim_updates = 0
    event_node_updates = 0
    story_mention_updates = 0
    accepted_stories: list[dict[str, Any]] = []
    rejected_stories: list[dict[str, Any]] = []
    proposal_receipts: list[dict[str, Any]] = []

    relation_updates += sum(1 for row in roster_runtime.get("relation_actions", []) if row.get("action") == "added")
    event_node_updates += sum(1 for row in roster_runtime.get("event_actions", []) if row.get("action") == "added")

    for story in stories:
        proposal = build_proposal(story)
        safety = verify_graph_proposal(graph, proposal)
        critique = critique_task(
            {
                "id": story.get("story_id"),
                "task_type": "graph_proposal",
                "input": {"proposal": proposal},
                "expected": {"verdict": "accept_with_warnings"},
            },
            raw_output=json.dumps(proposal, ensure_ascii=False),
            parsed_output=proposal,
            graph=graph,
            sources=story.get("source_trust", {}).get("sources", []),
            proposal=proposal,
        )
        proposal_status = promote_or_reject_proposal(proposal, graph)
        append_proposal_ledger(
            {
                "recorded_at": iso_now(),
                "story_id": story.get("story_id"),
                "proposal_hash": proposal.get("proposal_hash"),
                "claim_hashes": [claim.get("claim_hash") for claim in proposal.get("claims", []) if isinstance(claim, dict)],
                "status": proposal_status,
                "why": proposal.get("why_not_durable") if proposal_status != "accepted" else "",
                "sources": proposal.get("evidence_refs", []),
                "source_independence_score": proposal.get("provenance", {}).get("source_independence_score", 0.0),
                "retrieval_mode": proposal.get("provenance", {}).get("retrieval_mode", ""),
                "layer": "episodic",
            }
        )
        receipt = {
            "story_id": story.get("story_id"),
            "proposal_verdict": safety.get("verdict"),
            "proposal_issues": safety.get("issues", []),
            "proposal_warnings": safety.get("warnings", []),
            "proposal_kind": proposal.get("proposal_kind"),
            "claim_count": len(proposal.get("claims", [])),
            "critic_status": critique.get("status"),
            "critic_issues": critique.get("issues", []),
            "critic_cautions": critique.get("cautions", []),
            "critic_failure_classes": critique.get("failure_classes", []),
            "mutation_severity": critique.get("mutation_severity", "none"),
            "graph_worthiness": story.get("graph_worthiness", {}),
            "fact_check": story.get("fact_check", {}),
            "source_trust": story.get("source_trust", {}),
            "provenance": proposal.get("provenance", {}),
        }
        proposal_receipts.append(receipt)

        if safety.get("verdict") == "reject" or critique.get("status") == "fail" or not story.get("graph_worthiness", {}).get("worthy"):
            rejected_stories.append(story | {"receipt": receipt})
            continue

        event_node = proposal["event_nodes"][0]
        if upsert_event_node(event_nodes, event_node) == "added":
            event_node_updates += 1
        if upsert_story_mentions(
            story_mentions,
            {
                "story_id": story["story_id"],
                "cluster_key": story.get("cluster_key", ""),
                "event_id": event_node["id"],
                "title": story.get("summary_line", ""),
                "topic": story.get("topic", ""),
                "updated_at": iso_now(),
            },
        ) == "added":
            story_mention_updates += 1
        claim_records = claim_records_for_story(story)
        upsert_support_rows(
            graph,
            sources=claim_records["sources"],
            evidence=claim_records["evidence"],
            perspectives=claim_records["perspectives"],
            narratives=claim_records["narratives"],
        )
        accepted_relation_count = 0
        admitted_claim_count = 0
        sources_by_id = {str(item.get("id") or ""): item for item in graph.get("sources", []) if isinstance(item, dict)}
        for claim in claim_records["claims"]:
            relation_proxy = {
                "from": claim.get("subject_vertex_id"),
                "to": claim.get("object_vertex_id"),
                "relation_type": claim.get("claim_type"),
                "claim_hash": claim.get("claim_hash"),
            }
            if not novelty_gate(relation_proxy, graph) or duplicate_claim_exists(graph, relation_proxy):
                continue
            claim_action, inserted_claim = upsert_claim(graph, claim)
            if claim_action == "added":
                claim_updates += 1
            admission = canonical_admission(inserted_claim, sources_by_id)
            if admission["admit"] and inserted_claim.get("object_vertex_id"):
                edge = build_edge_from_claim(
                    inserted_claim,
                    evidence_ids=list(inserted_claim.get("evidence_ids", []) or []),
                    source_ids=list(inserted_claim.get("source_ids", []) or []),
                )
                action, inserted = upsert_relation(graph, edge)
                if action == "added":
                    relation_updates += 1
                    accepted_relation_count += 1
                admitted_claim_count += 1
            else:
                inserted = inserted_claim
            append_jsonl(
                EVIDENCE_LOG,
                [
                    {
                        "recorded_at": iso_now(),
                        "action": "graph_claim_update",
                        "story_id": story["story_id"],
                        "entity_from": inserted_claim.get("subject_vertex_id"),
                        "entity_to": inserted_claim.get("object_vertex_id"),
                        "relation_type": inserted_claim.get("claim_type"),
                        "claim_id": inserted_claim.get("id"),
                        "source_ids": inserted_claim.get("source_ids", []),
                        "evidence_ids": inserted_claim.get("evidence_ids", []),
                        "confidence": {
                            "extraction_confidence": inserted_claim.get("extraction_confidence"),
                            "source_reliability": inserted_claim.get("source_reliability"),
                            "cross_source_confirmation": inserted_claim.get("cross_source_confirmation"),
                            "interpretive_degree": inserted_claim.get("interpretive_degree"),
                            "publication_risk": inserted_claim.get("publication_risk"),
                        },
                        "canonical_admission": admission,
                        "proposal_verdict": safety.get("verdict"),
                        "critic_status": critique.get("status"),
                    }
                ],
            )
        accepted_stories.append(story | {"receipt": receipt, "accepted_relation_count": accepted_relation_count, "admitted_claim_count": admitted_claim_count})

    safety_report = graph_safety_report(graph)
    context_view = graph_context_view(graph, accepted_stories)
    memory_cards = graph_memory_cards(graph, accepted_stories)

    graph.setdefault("runtime", {})["graph"] = {
        "updated_at": iso_now(),
        "story_count": len(stories),
        "accepted_story_count": len(accepted_stories),
        "rejected_story_count": len(rejected_stories),
        "claim_updates": claim_updates,
        "relation_updates": relation_updates,
        "event_node_updates": event_node_updates,
        "story_mention_updates": story_mention_updates,
        "event_nodes": len(event_nodes),
        "claims": len(graph.get("claims", [])),
        "verified_story_pack": accepted_stories[:12],
        "rejected_story_pack": rejected_stories[:12],
        "proposal_receipts": proposal_receipts[:24],
        "roster_runtime": roster_runtime,
        "graph_context_view": context_view,
        "graph_memory_cards": memory_cards,
        "graph_safety_report": safety_report,
        "memory": graph_memory_snapshot(graph),
    }
    graph["context_layer"] = context_layer_summary(graph)
    graph["updated_at"] = iso_now()
    write_json(CANONICAL_GRAPH, sync_compatibility_views(graph))
    append_jsonl(
        EVIDENCE_LOG,
        [
            {
                "recorded_at": iso_now(),
                "action": "graph",
                "story_count": len(stories),
                "accepted_story_count": len(accepted_stories),
                "rejected_story_count": len(rejected_stories),
                "claim_updates": claim_updates,
                "relation_updates": relation_updates,
                "event_nodes": len(event_nodes),
            }
        ],
    )
    write_json(
        EVALS_LATEST_DIR / "graph-safety-report.json",
        {
            "generated_at": iso_now(),
            "graph_safety": safety_report,
            "proposal_receipts": proposal_receipts,
            "accepted_story_count": len(accepted_stories),
            "rejected_story_count": len(rejected_stories),
        },
    )
    print(
        json.dumps(
            {
                "ok": True,
                "stage": "graph",
                "story_count": len(stories),
                "accepted_story_count": len(accepted_stories),
                "rejected_story_count": len(rejected_stories),
                "claim_updates": claim_updates,
                "relation_updates": relation_updates,
                "event_nodes": len(event_nodes),
                "memory": graph["runtime"]["graph"]["memory"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
