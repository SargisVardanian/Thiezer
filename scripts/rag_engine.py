#!/usr/bin/env python3
"""Graph-RAG helpers for entity-centric answering."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pipeline_common import compact_summary, load_entity_alias_index, normalize_text, relation_label_ru, resolve_entity
from graph_memory import dossier_bundle, entity_profile_card, graph_rag_context as build_structured_graph_rag_context


ROLE_RELATIONS = {"holds_office_in", "member_of", "leads", "aligned_with"}


def _clean_bio_text(value: str) -> str:
    text = compact_summary(str(value or ""))
    text = re.sub(r"window\.dataLayer.*", " ", text, flags=re.I)
    text = re.sub(r"function\s+gtag\s*\([^)]*\)\s*\{[^}]*\}", " ", text, flags=re.I)
    text = re.sub(r"gtag\s*\([^)]*\)\s*;?", " ", text, flags=re.I)
    text = re.sub(r"eval\s*\(.*", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" -|,;")
    return compact_summary(text)


def _is_noisy_text(value: str) -> bool:
    lowered = normalize_text(_clean_bio_text(value))
    return any(marker in lowered for marker in ("window datalayer", "function gtag", "tracked in the graph", "appears in the armenia graph"))


def _entity_map(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(entity.get("id", "")).strip(): entity
        for entity in graph.get("entities", [])
        if isinstance(entity, dict) and str(entity.get("id", "")).strip()
    }


def resolve_entity_reference(graph: dict[str, Any], value: str, *, bucket: str = "people") -> str | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    entities = _entity_map(graph)
    if candidate in entities:
        return candidate
    alias_index = load_entity_alias_index(graph)
    resolved = resolve_entity(candidate, alias_index, bucket=bucket)
    if resolved:
        return resolved
    normalized = normalize_text(candidate)
    for entity_id, entity in entities.items():
        names = [str(entity.get("name", "")), *(str(alias) for alias in entity.get("aliases", []) or [])]
        if any(normalize_text(name) == normalized for name in names if str(name).strip()):
            return entity_id
    return None


def _relation_view(graph: dict[str, Any], relation: dict[str, Any], focus_id: str) -> dict[str, Any]:
    entities = _entity_map(graph)
    left_id = str(relation.get("from", "")).strip()
    right_id = str(relation.get("to", "")).strip()
    other_id = right_id if left_id == focus_id else left_id
    other = entities.get(other_id, {})
    relation_type = str(relation.get("relation_type", "")).strip()
    return {
        "relation_type": relation_type,
        "other_id": other_id,
        "other_name": str(other.get("name") or other_id).strip(),
        "label": f"{str(entities.get(left_id, {}).get('name') or left_id).strip()} {relation_label_ru(relation_type)} {str(entities.get(right_id, {}).get('name') or right_id).strip()}",
        "confidence": float(relation.get("confidence", 0.0) or 0.0),
        "evidence_quote": compact_summary(str(relation.get("evidence_quote") or relation.get("notes") or "")),
        "source_url": str(relation.get("source_url") or ""),
    }


def _event_items(graph: dict[str, Any], entity_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
    event_map = {
        str(event.get("id", "")).strip(): event
        for event in graph.get("event_nodes", [])
        if isinstance(event, dict) and str(event.get("id", "")).strip()
    }
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for relation in graph.get("relations", []):
        left_id = str(relation.get("from", "")).strip()
        right_id = str(relation.get("to", "")).strip()
        event_id = ""
        if left_id.startswith("event-") and right_id == entity_id:
            event_id = left_id
        elif right_id.startswith("event-") and left_id == entity_id:
            event_id = right_id
        if not event_id or event_id in seen:
            continue
        event = event_map.get(event_id, {})
        title = compact_summary(str(event.get("name") or relation.get("evidence_quote") or event_id))
        item = {
            "id": event_id,
            "title": title,
            "summary": compact_summary(str(event.get("summary") or event.get("notes") or relation.get("evidence_quote") or "")),
            "topic": str(event.get("subtype") or ""),
            "relation_type": str(relation.get("relation_type") or ""),
            "source_urls": [
                str(url)
                for url in [
                    str(relation.get("source_url") or ""),
                    *[
                        str(url)
                        for url in ((event.get("links", {}) or {}).values() if isinstance(event.get("links", {}), dict) else [])
                    ],
                ]
                if url
            ][:4],
        }
        items.append(item)
        seen.add(event_id)
        if len(items) >= limit:
            break
    return items


def build_rag_context(graph: dict[str, Any], entity_id: str) -> dict[str, Any]:
    bundle = dossier_bundle(graph, entity_id)
    if not bundle:
        return {}
    entity_card = entity_profile_card(graph, entity_id)
    entity = _entity_map(graph).get(str(entity_id or "").strip(), {})
    direct_network = bundle.get("network", {}).get("direct", []) if isinstance(bundle.get("network", {}), dict) else []
    indirect_network = bundle.get("network", {}).get("indirect", []) if isinstance(bundle.get("network", {}), dict) else []
    roles = [item.get("human_text") or item.get("name") for item in direct_network if item.get("relation_type") in ROLE_RELATIONS]
    events = bundle.get("timeline", []) or _event_items(graph, str(entity.get("id", "")), limit=10)
    biography_lines = [
        str(item).strip()
        for item in (entity_card.get("biography_or_history", []) or bundle.get("biography", []) or [])
        if str(item).strip()
    ]
    history = [str(item).strip() for item in (bundle.get("history", []) or []) if str(item).strip()]
    bio = biography_lines[0] if biography_lines else (bundle.get("overview", "") or "")
    return {
        "retrieval_contract": "GraphRAGCardContext.v1",
        "entity_card": entity_card,
        "entity_id": str(entity.get("id", "")),
        "name": str(entity.get("name", "")),
        "category": str(entity.get("category", "")),
        "subtype": str(entity.get("subtype", "")),
        "aliases": [str(alias) for alias in (entity_card.get("aliases", []) or bundle.get("canonical_aliases", []))[:12] if str(alias).strip()],
        "overview": str(entity_card.get("overview") or bundle.get("overview") or "").strip(),
        "bio": bio,
        "history": "\n".join(history) if history else bio,
        "biography": biography_lines[:8],
        "roles": [item for item in direct_network if item.get("relation_type") in ROLE_RELATIONS][:8],
        "connections": direct_network[:10],
        "events": events,
        "direct_network": direct_network,
        "indirect_network": indirect_network,
        "timeline": events[:8],
        "links": {link.get("title") or link.get("domain") or link.get("url"): link.get("url") for link in entity_card.get("source_links", []) if isinstance(link, dict) and link.get("url")},
        "evidence": [str(item) for item in (entity_card.get("evidence_summary", []) or bundle.get("evidence", []) or []) if str(item).strip()][:8],
        "profile_actions": [str(item.get("human_text") or item.get("name") or "") for item in direct_network if str(item.get("human_text") or item.get("name") or "").strip()][:10],
        "current_roles": [str(item) for item in entity_card.get("current_roles_or_functions", [])[:8] if str(item).strip()]
        or [str(item.get("human_text") or item.get("name") or "") for item in direct_network if item.get("relation_type") in ROLE_RELATIONS][:8],
        "graph_rag_context": build_structured_graph_rag_context(graph, query=str(entity.get("name", "")), entity_ids=[str(entity.get("id", ""))], story=None),
    }


def build_rag_prompt(context: dict[str, Any], query: str = "") -> str:
    roles = "\n".join(f"- {item}" for item in context.get("current_roles", [])[:8]) or "\n".join(f"- {item.get('label')}" for item in context.get("roles", [])[:8]) or "- none"
    biography = "\n".join(f"- {item}" for item in context.get("biography", [])[:8]) or f"- {context.get('bio', '') or context.get('history', '') or 'No biography available.'}"
    direct_connections = "\n".join(
        f"- {item.get('type')}: {item.get('name')} (confidence {float(item.get('confidence', 0.0) or 0.0):.2f})"
        for item in context.get("direct_network", [])[:10]
    ) or "\n".join(f"- {item.get('label')}" for item in context.get("connections", [])[:10]) or "- none"
    indirect_connections = "\n".join(
        f"- via {item.get('via_name')}: {item.get('person_name')} ({item.get('relation_type')})"
        for item in context.get("indirect_network", [])[:8]
    ) or "- none"
    events = "\n".join(
        f"- {item.get('date') or item.get('title')}: {item.get('summary') or item.get('topic') or 'event'}"
        for item in context.get("timeline", [])[:10]
    ) or "- none"
    actions = "\n".join(f"- {item}" for item in context.get("profile_actions", [])[:10]) or "- none"
    evidence = "\n".join(f"- {item}" for item in context.get("evidence", [])[:8]) or "- none"
    return (
        "You are a political analyst.\n\n"
        "Given structured graph cards, write a grounded entity brief.\n"
        "Use only the supplied graph context. Do not invent facts. If event coverage is thin, say so briefly.\n\n"
        f"User query:\n{query.strip() or context.get('name', '')}\n\n"
        f"Name: {context.get('name', '')}\n"
        f"Entity ID: {context.get('entity_id', '')}\n"
        f"Type: {context.get('category', '')} / {context.get('subtype', '')}\n"
        f"Aliases: {', '.join(context.get('aliases', [])[:8]) or 'none'}\n\n"
        f"Overview:\n{context.get('overview', '') or context.get('bio', '') or context.get('history', '') or 'No overview available.'}\n\n"
        f"Biography:\n{biography}\n\n"
        f"Current roles:\n{roles}\n\n"
        f"Direct network:\n{direct_connections}\n\n"
        f"Indirect network:\n{indirect_connections}\n\n"
        f"Timeline:\n{events}\n\n"
        f"Evidence:\n{evidence}\n\n"
        f"Profile quality:\n{context.get('entity_card', {}).get('profile_quality', {})}\n\n"
        f"Known activity items:\n{actions}\n\n"
        "Write:\n"
        "- Short biography (3-5 sentences)\n"
        "- Key political actions/events\n"
        "- Current position and influence\n"
    )


def deterministic_rag_answer(context: dict[str, Any]) -> str:
    lines = []
    name = context.get("name") or context.get("entity_id") or "Entity"
    bio = context.get("overview") or context.get("bio") or context.get("history") or f"{name} is represented in the political graph."
    lines.append(compact_summary(str(bio)))
    roles = [item for item in context.get("current_roles", [])[:3] if item] or [item.get("label") for item in context.get("roles", [])[:3] if item.get("label")]
    if roles:
        lines.append("Current role context: " + "; ".join(roles) + ".")
    events = [item.get("title") or item.get("summary") for item in context.get("timeline", [])[:3] if item.get("title") or item.get("summary")]
    if events:
        lines.append("Key graph-linked events: " + "; ".join(events) + ".")
    elif context.get("profile_actions"):
        lines.append("Key graph-linked activity: " + "; ".join(context.get("profile_actions", [])[:3]) + ".")
    connections = [item.get("name") for item in context.get("direct_network", [])[:3] if item.get("name")] or [item.get("label") for item in context.get("connections", [])[:3] if item.get("label")]
    if connections:
        lines.append("Important connections: " + "; ".join(connections) + ".")
    return " ".join(line for line in lines if line).strip()
