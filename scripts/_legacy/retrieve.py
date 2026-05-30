#!/usr/bin/env python3
"""Retrieval stage for the minimal deterministic Thiezer pipeline."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from itertools import combinations

from pipeline_common import (
    CANONICAL_GRAPH,
    EVIDENCE_LOG,
    EVALS_LATEST_DIR,
    TASK_RUNTIME_FILE,
    append_jsonl,
    bucket_sources,
    build_event_fingerprint,
    build_story_cluster_key,
    choose_story_summary,
    clean_editorial_line,
    compact_summary,
    compact_title,
    ensure_layout,
    iso_now,
    load_graph,
    load_entity_alias_index,
    load_source_registry,
    load_json,
    normalize_text,
    relation_label_ru,
    resolve_entity,
    stable_hash,
    translate_to_russian,
    write_json,
)
from graph_domain import analyze_story_fact_check, score_source
from graph_memory import append_proposal_ledger, claim_hash, graph_rag_context as build_story_graph_rag_context, source_independence_score


RELATION_PRIORITY = {
    "holds_office_in": 5.0,
    "leads": 4.8,
    "member_of": 4.5,
    "aligned_with": 4.0,
    "owns_or_controls": 4.0,
    "opposes": 3.5,
    "publicly_opposed": 3.5,
    "mentions": 2.0,
}


def entity_lookup(graph: dict) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    alias_index = load_entity_alias_index(graph)
    for entity in graph.get("entities", []):
        lookup[normalize_text(str(entity.get("name", "")))] = entity
        for alias in entity.get("aliases", []) or []:
            lookup[normalize_text(str(alias))] = entity
    for entity_id in alias_index.get("people", {}).values():
        entity = next((item for item in graph.get("entities", []) if str(item.get("id", "")) == str(entity_id)), None)
        if not entity:
            continue
        for alias, mapped_id in alias_index.get("people", {}).items():
            if str(mapped_id) == str(entity_id):
                lookup[alias] = entity
    return lookup


def detect_entities(text: str, graph: dict) -> list[str]:
    normalized = normalize_text(text)
    matched: list[str] = []
    seen: set[str] = set()
    alias_index = load_entity_alias_index(graph)
    direct = resolve_entity(normalized, alias_index, bucket="people")
    if direct and direct not in seen:
        matched.append(direct)
        seen.add(direct)
    for key, entity in entity_lookup(graph).items():
        if key and len(key) >= 3 and key in normalized and entity.get("id") not in seen:
            matched.append(str(entity.get("id")))
            seen.add(str(entity.get("id")))
    return matched


def resolve_entities_scored(query: str, graph: dict, limit: int = 5) -> list[str]:
    q = normalize_text(query)
    if not q:
        return []
    alias_index = load_entity_alias_index(graph)
    direct = resolve_entity(q, alias_index, bucket="people")
    scored: list[tuple[float, str, str]] = []
    seen: set[str] = set()
    if direct:
        entity = next((row for row in graph.get("entities", []) if str(row.get("id", "")) == str(direct)), None)
        scored.append((100.0, str(direct), str(entity.get("name", "")) if entity else str(direct)))
        seen.add(str(direct))
    tokens = set(q.split())
    for entity in graph.get("entities", []):
        entity_id = str(entity.get("id", "")).strip()
        if not entity_id or entity_id in seen:
            continue
        name = normalize_text(entity.get("name", ""))
        aliases = [normalize_text(alias) for alias in entity.get("aliases", []) or []]
        name_tokens = set(name.split())
        score = 0.0
        if q == name:
            score += 10.0
        if q in aliases:
            score += 9.0
        if q and q in name:
            score += 6.0
        score += 1.5 * len(tokens & name_tokens)
        if score > 0:
            scored.append((score, entity_id, str(entity.get("name", ""))))
    scored.sort(key=lambda row: (-row[0], row[2]))
    return [entity_id for _, entity_id, _ in scored[:limit]]


def person_dossier_bundle(graph: dict, person_id: str) -> dict:
    entity_map = {
        str(entity.get("id", "")).strip(): entity
        for entity in graph.get("entities", [])
        if str(entity.get("id", "")).strip()
    }
    person = entity_map.get(str(person_id or "").strip(), {})
    profile = person.get("profile", {}) if isinstance(person.get("profile", {}), dict) else {}
    network = profile.get("network", {}) if isinstance(profile.get("network", {}), dict) else {}

    direct = sorted(
        [item for item in (network.get("direct", []) or []) if isinstance(item, dict)],
        key=lambda item: (
            -RELATION_PRIORITY.get(str(item.get("type") or ""), 0.0),
            -float(item.get("confidence", 0.0) or 0.0),
            str(item.get("name") or ""),
        ),
    )[:10]
    indirect = sorted(
        [item for item in (network.get("indirect", []) or []) if isinstance(item, dict)],
        key=lambda item: (-float(item.get("confidence", 0.0) or 0.0), str(item.get("person_name") or "")),
    )[:8]
    timeline = [item for item in (profile.get("timeline", []) or []) if isinstance(item, dict)][:8]

    return {
        "entity_id": str(person_id or ""),
        "name": str(person.get("name", "")),
        "overview": str(profile.get("overview", "") or person.get("summary", "")).strip(),
        "biography": [str(item).strip() for item in (profile.get("biography", []) or []) if str(item).strip()][:8],
        "current_roles": [str(item).strip() for item in (profile.get("current_roles", []) or []) if str(item).strip()][:8],
        "timeline": timeline,
        "direct_links": direct,
        "indirect_links": indirect,
        "sources": [str(item).strip() for item in (profile.get("evidence", []) or profile.get("links", []) or []) if str(item).strip()][:8],
    }


def retrieve_graph_rag_context(query: str, graph: dict) -> dict:
    entity_ids = resolve_entities_scored(query, graph)
    dossiers = [person_dossier_bundle(graph, entity_id) for entity_id in entity_ids]
    return {
        "query": query,
        "matched_entities": entity_ids,
        "dossiers": dossiers,
    }


def relation_context(graph: dict, entity_ids: list[str]) -> str:
    entities = {entity.get("id"): entity for entity in graph.get("entities", [])}
    lines: list[str] = []
    for relation in graph.get("relations", []):
        left = relation.get("from")
        right = relation.get("to")
        if left not in entity_ids and right not in entity_ids:
            continue
        relation_type = str(relation.get("relation_type") or "")
        if relation_type == "mentions":
            continue
        left_name = entities.get(left, {}).get("name", left)
        right_name = entities.get(right, {}).get("name", right)
        lines.append(f"{left_name} {relation_label_ru(relation_type)} {right_name}")
    return clean_editorial_line("; ".join(lines[:4]))


def network_neighbors(graph: dict, entity_ids: list[str]) -> list[str]:
    neighbors: list[str] = []
    seen: set[str] = set()
    for relation in graph.get("relations", []):
        left = relation.get("from")
        right = relation.get("to")
        if left in entity_ids and right not in seen:
            neighbors.append(str(right))
            seen.add(str(right))
        if right in entity_ids and left not in seen:
            neighbors.append(str(left))
            seen.add(str(left))
    return neighbors[:12]


def story_summary_text(story: dict) -> str:
    return clean_editorial_line(translate_to_russian(story.get("title", ""))) or compact_title(str(story.get("title", "")))


def story_source_profiles(items: list[dict], registry_by_id: dict[str, dict]) -> list[dict]:
    profiles: list[dict] = []
    corroboration_count = len({str(item.get("source_id") or "") for item in items if item.get("source_id")})
    for item in items:
        source_id = str(item.get("source_id") or "")
        source = dict(registry_by_id.get(source_id, {}))
        if not source:
            source = {
                "id": source_id,
                "source_name": item.get("source_name", source_id),
                "source_type": item.get("source_type", "unknown"),
                "category": item.get("category", "unknown"),
            }
        source["corroboration_count"] = corroboration_count
        source["directness"] = "primary" if source.get("source_type") == "official" else "secondary"
        profiles.append(score_source(source, claim_sensitivity="normal"))
    return profiles


def story_graph_worthiness(story: dict) -> dict:
    profiles = story.get("source_trust", {}).get("sources", [])
    fact_check = story.get("fact_check", {}) if isinstance(story.get("fact_check", {}), dict) else {}
    perspective_blend = story.get("perspective_blend", {}) if isinstance(story.get("perspective_blend", {}), dict) else {}
    highest_trust = max((float(profile.get("trust_score", 0.0) or 0.0) for profile in profiles), default=0.0)
    corroboration_count = int(story.get("source_trust", {}).get("corroboration_count", 0) or 0)
    source_urls = [str(source.get("url", "")) for source in story.get("sources", [])]
    freshness_score = float(story.get("freshness_score", 0.0) or 0.0)
    published_at = str(story.get("published_at", "") or "").strip()
    homepage_like = any(url.rstrip("/").count("/") <= 2 for url in source_urls)
    static_page_like = any(
        marker in url.lower()
        for url in source_urls
        for marker in (
            "/mayor/",
            "/leadership",
            "/board",
            "/deputies.php",
            "sel=details",
            "/team/",
            "/about/",
        )
    )
    title = normalize_text(str(story.get("title", "")))
    summary = normalize_text(str(story.get("summary", "")))
    same_title_summary = bool(title and summary and title == summary)
    has_actor_signal = bool(story.get("actors_detected")) or bool(story.get("neighbor_entities"))
    concise_but_trusted = len(summary.split()) >= 5 or len(title.split()) >= 4
    worthy = (
        highest_trust >= 0.7
        and corroboration_count >= 1
        and story.get("topic") != "utility"
        and not homepage_like
        and not static_page_like
        and (freshness_score >= 0.45 or bool(published_at) or corroboration_count >= 2)
        and (not same_title_summary or highest_trust >= 0.75 or story.get("topic") in {"internal_politics", "foreign_policy", "social_infrastructure_culture", "local_governance"})
        and (has_actor_signal or concise_but_trusted or story.get("topic") in {"internal_politics", "foreign_policy", "social_infrastructure_culture", "local_governance"})
    )
    caution_flags: list[str] = []
    if corroboration_count <= 1:
        caution_flags.append("single_source_story")
    if highest_trust < 0.7:
        caution_flags.append("low_trust_lead_source")
    if story.get("topic") == "utility":
        caution_flags.append("utility_topic")
    if homepage_like:
        caution_flags.append("homepage_like_url")
    if static_page_like:
        caution_flags.append("static_page_like_url")
    if freshness_score < 0.45 and not published_at and corroboration_count < 2:
        caution_flags.append("stale_or_undated_story")
    if same_title_summary:
        caution_flags.append("thin_story_signal")
    if not has_actor_signal:
        caution_flags.append("no_actor_signal")
    if worthy and not has_actor_signal:
        caution_flags.append("trusted_concise_story")
    if fact_check.get("verdict") == "fail":
        caution_flags.append("fact_check_fail")
    elif fact_check.get("verdict") == "warn":
        caution_flags.append("fact_check_warn")
    if fact_check.get("verdict") == "fail" and not perspective_blend.get("ready"):
        caution_flags.append("needs_perspective_enrichment")
    return {
        "worthy": worthy,
        "highest_trust_score": round(highest_trust, 3),
        "corroboration_count": corroboration_count,
        "caution_flags": caution_flags,
    }


def retrieval_mode(actor_ids: list[str], topic: str) -> str:
    return "actor_centric" if actor_ids else f"topic_centric:{topic}"


def build_claim_bundles(story: dict, items: list[dict]) -> list[dict]:
    source_trust = story.get("source_trust", {})
    top_source = source_trust.get("top_source", {}) if isinstance(source_trust, dict) else {}
    corroboration_count = int(source_trust.get("corroboration_count", 0) or 0) if isinstance(source_trust, dict) else 0
    trust_score = float(top_source.get("trust_score", 0.0) or 0.0) if isinstance(top_source, dict) else 0.0
    bundles: list[dict] = []
    for actor_id in story.get("actors_detected", [])[:8]:
        claim_type = "event_only"
        if corroboration_count >= 2 and trust_score >= 0.85:
            claim_type = "durable_relation_candidate"
        elif trust_score >= 0.7:
            claim_type = "attributed_claim"
        source_urls = [item.get("url", "") for item in items[:4] if item.get("url")]
        claim = {
            "claim_id": stable_hash(story.get("story_id", ""), actor_id, "claim"),
            "claim_type": claim_type,
            "relation_type": "mentions",
            "from": f"event-{story['story_id']}",
            "to": actor_id,
            "evidence_quote": story.get("summary_line", ""),
            "source_urls": source_urls,
            "corroboration_count": corroboration_count,
            "top_trust_score": round(trust_score, 3),
            "layer": "episodic",
            "source_independence_score": source_independence_score([{ "url": url } for url in source_urls]),
        }
        claim["claim_hash"] = claim_hash(claim)
        bundles.append(claim)
    return bundles


def build_story_context_pack(story: dict) -> dict:
    return {
        "retrieval_mode": retrieval_mode(story.get("actors_detected", []), str(story.get("topic", ""))),
        "actor_ids": story.get("actors_detected", [])[:8],
        "neighbor_ids": story.get("neighbor_entities", [])[:12],
        "relationship_context": story.get("relationship_context", ""),
        "study_links": story.get("study_links", [])[:12],
        "graph_rag_context": build_story_graph_rag_context(load_graph(), query=str(story.get("title") or story.get("summary_line") or ""), entity_ids=story.get("actors_detected", [])[:8], story=story),
    }


def current_task_topic() -> str:
    runtime = load_json(TASK_RUNTIME_FILE, {}) if TASK_RUNTIME_FILE.exists() else {}
    if not isinstance(runtime, dict):
        return ""
    return str(runtime.get("topic") or "").strip()


def _summary_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"\b[\w-]{4,}\b", normalize_text(text))
        if len(token) >= 4
    }


SIGNATURE_STOPWORDS = {
    "armenia",
    "armenian",
    "pashinyan",
    "prime",
    "minister",
    "parliament",
    "parliamentary",
    "government",
    "region",
    "regional",
    "development",
    "developments",
    "discuss",
    "discussion",
    "speaker",
    "deputy",
    "ambassador",
    "former",
    "leader",
    "news",
    "today",
    "politics",
    "political",
    "election",
    "elections",
    "campaign",
    "claim",
    "claims",
    "statement",
    "report",
    "reports",
    "meeting",
    "talks",
    "talk",
    "said",
    "says",
    "will",
    "with",
    "from",
    "about",
    "against",
    "during",
    "after",
    "before",
    "inside",
    "around",
}


def _signature_tokens(text: str) -> set[str]:
    return {token for token in _summary_tokens(text) if token not in SIGNATURE_STOPWORDS}


def _perspective_role(source_type: str) -> str:
    mapping = {
        "official": "official",
        "opposition_adjacent": "opposition",
        "watchdog": "watchdog",
        "independent": "independent",
        "external": "external",
    }
    return mapping.get(source_type, "independent")


def build_perspective_blend(story: dict, items: list[dict], candidates: list[dict], graph: dict) -> dict:
    story_urls = {str(source.get("url") or "").strip() for source in story.get("sources", []) if source.get("url")}
    story_source_ids = {str(source.get("source_id") or "").strip() for source in story.get("sources", []) if source.get("source_id")}
    story_actor_ids = set(story.get("actors_detected", []) or [])
    story_topic = str(story.get("topic") or "")
    story_tokens = _summary_tokens(" ".join([str(story.get("title") or ""), str(story.get("summary") or ""), str(story.get("public_impact") or "")]))
    story_signature = _signature_tokens(" ".join([str(story.get("title") or ""), str(story.get("summary") or ""), str(story.get("public_impact") or "")]))
    alternatives: list[dict] = []
    best_by_source: dict[str, dict] = {}

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        url = str(candidate.get("url") or "").strip()
        if not url or url in story_urls:
            continue
        source_id = str(candidate.get("source_id") or "").strip()
        if source_id and source_id in story_source_ids:
            continue
        candidate_text = " ".join([str(candidate.get("title") or ""), str(candidate.get("summary") or "")]).strip()
        if not candidate_text:
            continue
        candidate_topic = str(candidate.get("topic") or "")
        candidate_actors = set(detect_entities(candidate_text, graph))
        actor_overlap = len(story_actor_ids & candidate_actors)
        token_overlap = len(story_tokens & _summary_tokens(candidate_text))
        signature_overlap = len(story_signature & _signature_tokens(candidate_text))
        score = actor_overlap * 3 + min(token_overlap, 4)
        if candidate_topic == story_topic:
            score += 1
        if candidate_topic != story_topic:
            continue
        if actor_overlap > 0 and signature_overlap == 0:
            continue
        if signature_overlap == 0 and token_overlap < 4:
            continue
        if actor_overlap == 0 and token_overlap < 4:
            continue
        if score < 4:
            continue
        entry = {
            "source_id": source_id,
            "source_name": candidate.get("source_name") or candidate.get("host") or source_id or url,
            "source_type": candidate.get("source_type", "independent"),
            "role": _perspective_role(str(candidate.get("source_type", "independent"))),
            "url": url,
            "summary": compact_summary(candidate.get("summary", "")) or compact_summary(candidate.get("title", "")),
            "title": candidate.get("title", ""),
            "score": score,
        }
        previous = best_by_source.get(source_id or url)
        if previous is None or float(entry["score"]) > float(previous["score"]):
            best_by_source[source_id or url] = entry

    alternatives = sorted(best_by_source.values(), key=lambda item: (-float(item["score"]), item["source_name"]))[:4]
    role_summaries: dict[str, str] = {}
    for item in alternatives:
        role = str(item.get("role") or "independent")
        if role not in role_summaries and item.get("summary"):
            role_summaries[role] = str(item.get("summary"))

    lead_summary = compact_summary(story.get("summary", "")) or compact_summary(story.get("public_impact", "")) or compact_summary(story.get("title", ""))
    perspective_lines: list[str] = []
    for item in alternatives[:2]:
        alt_summary = str(item.get("summary") or "").strip()
        if alt_summary and normalize_text(alt_summary) != normalize_text(lead_summary):
            perspective_lines.append(f"{item.get('source_name')}: {alt_summary}")
    merged_summary = lead_summary
    if perspective_lines:
        merged_summary = f"{lead_summary} Другие ракурсы: " + "; ".join(perspective_lines)

    distinct_roles = sorted({str(item.get("role") or "independent") for item in alternatives})
    return {
        "ready": len(alternatives) >= 1,
        "items": alternatives,
        "distinct_roles": distinct_roles,
        "official_framing": role_summaries.get("official", ""),
        "opposition_framing": role_summaries.get("opposition", ""),
        "watchdog_framing": role_summaries.get("watchdog", ""),
        "merged_summary": merged_summary,
    }


def main() -> int:
    ensure_layout()
    graph = load_graph()
    source_registry = load_source_registry()
    registry_by_id = {str(source.get("id") or ""): source for source in source_registry}
    focus_topic = current_task_topic()
    ingest_runtime = graph.get("runtime", {}).get("ingest", {})
    exploration_runtime = graph.get("runtime", {}).get("exploration", {})
    ingest_candidates = list(ingest_runtime.get("candidates", [])) if isinstance(ingest_runtime, dict) else []
    exploration_candidates = list(exploration_runtime.get("candidates", [])) if isinstance(exploration_runtime, dict) else []
    merged_candidates: dict[str, dict] = {}
    for candidate in [*ingest_candidates, *exploration_candidates]:
        if not isinstance(candidate, dict):
            continue
        url = str(candidate.get("url") or "").strip()
        if not url:
            continue
        current = merged_candidates.get(url)
        if current is None:
            merged_candidates[url] = candidate
            continue
        current_score = (
            float(current.get("freshness_score", 0.0) or 0.0),
            float(current.get("priority_score", 0.0) or 0.0),
            float(current.get("gate_score", 0.0) or 0.0),
        )
        candidate_score = (
            float(candidate.get("freshness_score", 0.0) or 0.0),
            float(candidate.get("priority_score", 0.0) or 0.0),
            float(candidate.get("gate_score", 0.0) or 0.0),
        )
        if candidate_score > current_score:
            merged_candidates[url] = candidate
    candidates = sorted(
        merged_candidates.values(),
        key=lambda item: (
            float(item.get("freshness_score", 0.0) or 0.0),
            float(item.get("priority_score", 0.0) or 0.0),
            float(item.get("gate_score", 0.0) or 0.0),
        ),
        reverse=True,
    )
    grouped: dict[str, list[dict]] = defaultdict(list)
    for candidate in candidates:
        grouped[build_story_cluster_key([candidate])].append(candidate)

    stories: list[dict] = []
    pair_candidates: list[dict] = []
    source_trust_report_items: list[dict] = []
    for cluster_key, items in grouped.items():
        bucketed = bucket_sources(items)
        title, summary = choose_story_summary(items)
        lead = sorted(
            items,
            key=lambda item: (
                float(item.get("priority_score", 0.0)),
                float(item.get("freshness_score", 0.0)),
                float(item.get("gate_score", 0.0)),
            ),
            reverse=True,
        )[0]
        story_text = f"{title} {summary} {' '.join(item.get('summary', '') for item in items)}"
        actor_ids = detect_entities(story_text, graph)
        if lead.get("source_name") and not actor_ids:
            actor_ids = detect_entities(lead.get("source_name", ""), graph)
        study_links = []
        seen_urls: set[str] = set()
        for item in items[:6]:
            url = str(item.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            study_links.append({"label": item.get("source_name") or item.get("host") or url, "url": url, "kind": "source"})
        for actor_id in actor_ids[:6]:
            entity = next((entity for entity in graph.get("entities", []) if entity.get("id") == actor_id), {})
            for label, url in (entity.get("links") or {}).items():
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    study_links.append({"label": str(label), "url": str(url), "kind": "entity_link"})
        relationship_context = relation_context(graph, actor_ids)
        neighbors = network_neighbors(graph, actor_ids)
        topic = lead.get("topic") or "internal_politics"
        if focus_topic and topic != focus_topic:
            continue
        story_id = f"story-{stable_hash(cluster_key, title, summary)}"
        source_profiles = story_source_profiles(items, registry_by_id)
        ranked_profiles = sorted(source_profiles, key=lambda item: (-float(item.get("trust_score", 0.0)), item.get("source_id", "")))
        source_trust = {
            "sources": ranked_profiles,
            "corroboration_count": len({str(item.get("source_id") or "") for item in items if item.get("source_id")}),
            "source_types": dict(Counter(str(item.get("source_type") or "unknown") for item in items)),
            "top_source": ranked_profiles[0] if ranked_profiles else {},
        }
        draft_story = {
            "story_id": story_id,
            "cluster_key": cluster_key,
            "event_fingerprint": build_event_fingerprint(items),
            "topic": topic,
            "summary_line": story_summary_text({"title": title or summary}),
            "title": title,
            "summary": compact_summary(summary),
            "published_at": str(lead.get("published_at", "") or ""),
            "freshness_score": round(float(lead.get("freshness_score", 0.0) or 0.0), 3),
            "sources": [
                {
                    "label": item.get("source_name") or item.get("host") or item.get("url", ""),
                    "url": item.get("url", ""),
                    "source_name": item.get("source_name", ""),
                    "source_id": item.get("source_id", ""),
                    "type": item.get("source_type", ""),
                }
                for item in items[:8]
            ],
            "study_links": study_links,
            "actors_detected": actor_ids,
            "neighbor_entities": neighbors,
            "relationship_context": relationship_context,
            "public_impact": compact_summary(summary) or compact_summary(title),
            "sources_by_type": {key: len(value) for key, value in bucketed.items()},
            "analysis": {
                "official_framing": compact_summary(title),
                "opposition_framing": "",
                "watchdog_framing": "",
                "relationship_context": relationship_context,
                "public_context": compact_summary(summary),
                "public_impact": compact_summary(summary) or compact_summary(title),
            },
            "source_trust": source_trust,
            "novelty_score": round(float(lead.get("freshness_score", 0.0) or 0.0), 3),
            "priority_score": round(float(lead.get("priority_score", 0.0) or 0.0), 3),
        }
        draft_story["perspective_blend"] = build_perspective_blend(draft_story, items, candidates, graph)
        draft_story["fact_check"] = analyze_story_fact_check(draft_story)
        merged_summary = str(draft_story.get("perspective_blend", {}).get("merged_summary") or "").strip()
        if merged_summary:
            draft_story["analysis"]["public_context"] = merged_summary
            draft_story["analysis"]["public_impact"] = merged_summary
            draft_story["analysis"]["official_framing"] = draft_story["perspective_blend"].get("official_framing", "")
            draft_story["analysis"]["opposition_framing"] = draft_story["perspective_blend"].get("opposition_framing", "")
            draft_story["analysis"]["watchdog_framing"] = draft_story["perspective_blend"].get("watchdog_framing", "")
            draft_story["public_impact"] = merged_summary
        draft_story["graph_worthiness"] = story_graph_worthiness(draft_story)
        draft_story["claim_bundles"] = build_claim_bundles(draft_story, items)
        draft_story["story_context_pack"] = build_story_context_pack(draft_story)
        draft_story["graph_rag_context"] = draft_story["story_context_pack"]["graph_rag_context"]
        stories.append(draft_story)
        source_trust_report_items.append(
            {
                "story_id": story_id,
                "title": title,
                "topic": topic,
                "source_trust": source_trust,
                "fact_check": draft_story["fact_check"],
                "perspective_blend": draft_story["perspective_blend"],
                "graph_worthiness": draft_story["graph_worthiness"],
                "claim_bundle_count": len(draft_story["claim_bundles"]),
                "retrieval_mode": draft_story["story_context_pack"]["retrieval_mode"],
            }
        )
        for left, right in combinations(actor_ids[:4], 2):
            pair_candidates.append(
                {
                    "from": left,
                    "to": right,
                    "relation_type": "mentions",
                    "confidence": 0.5,
                    "story_id": story_id,
                    "evidence_quote": compact_summary(summary) or compact_title(title),
                }
            )

    retrieval_runtime = {
        "updated_at": iso_now(),
        "cluster_count": len(grouped),
        "story_count": len(stories),
        "stories": stories,
        "pair_candidates": pair_candidates,
        "source_trust_report": {
            "updated_at": iso_now(),
            "items": source_trust_report_items,
        },
        "summary": {
            "topic_counts": dict(Counter(story["topic"] for story in stories)),
            "source_count": len(candidates),
        },
    }
    graph.setdefault("runtime", {})["retrieval"] = retrieval_runtime
    graph["updated_at"] = iso_now()
    write_json(CANONICAL_GRAPH, graph)
    append_jsonl(
        EVIDENCE_LOG,
        [
            {
                "recorded_at": iso_now(),
                "action": "retrieve",
                "cluster_count": len(grouped),
                "story_count": len(stories),
                "pair_candidate_count": len(pair_candidates),
            }
        ],
    )
    write_json(
        EVALS_LATEST_DIR / "source-trust-report.json",
        {
            "generated_at": iso_now(),
            "story_count": len(source_trust_report_items),
            "items": source_trust_report_items,
        },
    )
    print(
        json.dumps(
            {
                "ok": True,
                "stage": "retrieve",
                "clusters": len(grouped),
                "stories": len(stories),
                "pair_candidates": len(pair_candidates),
                "graph_worthy_stories": sum(1 for story in stories if story.get("graph_worthiness", {}).get("worthy")),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
