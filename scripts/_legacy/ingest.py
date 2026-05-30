#!/usr/bin/env python3
"""Ingest Armenia-relevant sources into the canonical graph runtime."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from pipeline_common import (
    ARMENIA_KEYWORDS,
    CANONICAL_GRAPH,
    EVIDENCE_LOG,
    SOURCE_REGISTRY,
    append_jsonl,
    armenia_gate,
    classify_topic,
    compact_summary,
    compact_title,
    dedupe_items,
    discover_feed_links,
    ensure_layout,
    extract_html_items,
    fetch_url,
    iso_now,
    load_graph,
    load_json,
    load_source_registry,
    normalize_text,
    parse_feed_items,
    score_freshness,
    short_host,
    stable_hash,
    translate_to_russian,
    update_source_health,
    write_json,
)


def entity_alias_terms(graph: dict) -> dict[str, set[str]]:
    buckets = {"people": set(), "orgs": set(), "places": set()}
    for entity in graph.get("entities", []):
        category = str(entity.get("category") or "")
        bucket = "orgs"
        if category in {"person", "people"}:
            bucket = "people"
        elif category in {"country", "region", "place", "location", "administrative_unit"}:
            bucket = "places"
        names = [entity.get("name", "")] + list(entity.get("aliases", []) or [])
        for name in names:
            normalized = normalize_text(str(name))
            if normalized:
                buckets[bucket].add(normalized)
    return buckets


def source_fetch_plan(source: dict) -> list[str]:
    urls = [str(source.get("url") or "").strip()]
    telegram_url = str(source.get("telegram_url") or "").strip()
    if telegram_url and telegram_url not in urls:
        urls.append(telegram_url)
    return [url for url in urls if url]


def extract_source_items(source: dict, body: str, content_type: str, limit: int = 8) -> list[dict]:
    base_url = str(source.get("url") or "")
    feed_links = discover_feed_links(body, base_url) if body else []
    items = []
    if feed_links and content_type and "xml" not in content_type.lower():
        for feed_url in feed_links[:2]:
            feed_body, feed_type = fetch_url(feed_url)
            if feed_body and ("xml" in feed_type.lower() or feed_body.lstrip().startswith("<")):
                items.extend(parse_feed_items(feed_body, feed_url, limit))
    if not items and body:
        if "xml" in content_type.lower() or body.lstrip().startswith("<rss") or body.lstrip().startswith("<feed"):
            items.extend(parse_feed_items(body, base_url, limit))
        else:
            items.extend(extract_html_items(body, base_url, limit))
    return dedupe_items(items)[:limit]


def source_monitoring_score(source: dict) -> float:
    trust_weight = float(source.get("trust_weight", 0.0) or 0.0)
    freshness_weight = float(source.get("freshness_weight", 0.0) or 0.0)
    parse_quality = float(source.get("parse_quality_score", 0.0) or 0.0)
    coverage_contribution = float(source.get("coverage_contribution_last_7_runs", 0.0) or 0.0)
    items_window = source.get("items_last_7_runs", [])
    window_total = float(sum(int(value or 0) for value in items_window if isinstance(value, (int, float))))
    status = str(source.get("status") or "unknown")
    enabled_bonus = 0.1 if source.get("enabled", True) else -0.4
    status_bonus = {"active": 0.08, "degraded": -0.02, "broken": -0.18, "dormant": -0.1}.get(status, -0.05)
    last_success_at = str(source.get("last_success_at") or "").strip()
    recency_bonus = 0.0
    if last_success_at:
        try:
            dt = datetime.fromisoformat(last_success_at.replace("Z", "+00:00")).astimezone(timezone.utc)
            age_hours = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)
            recency_bonus = max(0.0, 1.0 - min(age_hours / 168.0, 1.0))
        except ValueError:
            recency_bonus = 0.0
    undercoverage_bonus = 1.0 / (1.0 + max(0.0, coverage_contribution + window_total))
    return round(
        (trust_weight * 0.22)
        + (freshness_weight * 0.14)
        + (parse_quality * 0.18)
        + (recency_bonus * 0.14)
        + (undercoverage_bonus * 0.22)
        + enabled_bonus
        + status_bonus,
        4,
    )


def select_diverse_sources(sources: list[dict], limit: int = 12) -> list[dict]:
    if not sources:
        return []
    skip_categories = {"analysis_civic", "telegram_only"}
    categorized: dict[str, list[dict]] = {}
    for source in sources:
        if not source.get("enabled", True):
            continue
        category = str(source.get("category") or "unknown")
        if category in skip_categories:
            continue
        categorized.setdefault(category, []).append(source)
    category_quotas = {
        "official_baseline": 3,
        "independent_watchdog": 4,
        "critical_opposition_adjacent": 2,
        "mainstream_baseline": 2,
        "external_analysis": 1,
    }
    selected: list[dict] = []
    seen_ids: set[str] = set()

    def add_source(source: dict) -> None:
        source_id = str(source.get("id") or source.get("source_id") or source.get("url") or "").strip()
        if not source_id or source_id in seen_ids:
            return
        seen_ids.add(source_id)
        selected.append(source)

    for category, quota in category_quotas.items():
        ranked = sorted(categorized.get(category, []), key=source_monitoring_score, reverse=True)
        for source in ranked[:quota]:
            add_source(source)

    ranked_all = sorted(
        [source for source in sources if source.get("enabled", True) and str(source.get("category") or "unknown") not in skip_categories],
        key=source_monitoring_score,
        reverse=True,
    )
    for source in ranked_all:
        if len(selected) >= limit:
            break
        add_source(source)

    return selected[:limit]


def build_candidate(source: dict, item: dict, graph: dict, alias_terms: dict[str, set[str]]) -> dict | None:
    gate = armenia_gate(item, alias_terms, graph)
    if not gate.get("passed"):
        return None
    topic = classify_topic(item.get("title", ""), item.get("summary", ""))
    freshness = score_freshness(str(item.get("published_at") or ""))
    trust_weight = float(source.get("trust_weight", 0.7) or 0.7)
    priority_score = round(float(gate.get("score", 0.0)) + freshness + trust_weight, 3)
    return {
        "id": stable_hash(str(source.get("id", "")), item.get("title", ""), item.get("url", "")),
        "source_id": source.get("id", ""),
        "source_name": source.get("source_name", ""),
        "source_type": source.get("source_type", ""),
        "category": source.get("category", ""),
        "url": item.get("url", ""),
        "title": compact_title(str(item.get("title", ""))),
        "summary": compact_summary(str(item.get("summary", ""))),
        "published_at": item.get("published_at", ""),
        "topic": topic,
        "gate_score": gate.get("score", 0.0),
        "gate_reasons": gate.get("reasons", []),
        "gate_matches": gate.get("matches", []),
        "freshness_score": freshness,
        "priority_score": priority_score,
        "host": short_host(str(item.get("url", ""))),
        "public_safe": True,
        "translation": translate_to_russian(compact_title(str(item.get("title", "")))),
    }


def main() -> int:
    ensure_layout()
    graph = load_graph()
    sources = select_diverse_sources(load_source_registry(), limit=12)
    alias_terms = entity_alias_terms(graph)

    candidates: list[dict] = []
    source_stats: list[dict] = []
    category_counts: Counter[str] = Counter()
    source_type_counts: Counter[str] = Counter()
    for source in sources:
        category_counts[str(source.get("category") or "unknown")] += 1
        source_type_counts[str(source.get("source_type") or "unknown")] += 1
        if not source.get("enabled", True):
            continue
        fetch_urls = source_fetch_plan(source)
        best_body = ""
        best_content_type = ""
        best_latency = 0.0
        best_items: list[dict] = []
        success = False
        last_error = ""
        for url in fetch_urls[:1]:
            body, content_type = fetch_url(url, timeout=5)
            if not body:
                last_error = content_type
                continue
            success = True
            best_body = body
            best_content_type = content_type
            best_items = extract_source_items(source, body, content_type)
            break
        if not success:
            updated = update_source_health(source, success=False, latency_ms=0.0, items_count=0, parse_quality_score=0.0, error_class=last_error or "fetch_failed", status_code=None)
            source_stats.append({"id": source.get("id"), "status": updated.get("status", "broken"), "items": 0})
            continue
        source_candidates = []
        for item in best_items:
            candidate = build_candidate(source, item, graph, alias_terms)
            if candidate:
                source_candidates.append(candidate)
        candidates.extend(source_candidates)
        parse_quality = min(1.0, len(source_candidates) / max(1, len(best_items))) if best_items else 0.0
        updated = update_source_health(
            source,
            success=True,
            latency_ms=best_latency,
            items_count=len(source_candidates),
            parse_quality_score=parse_quality,
            error_class="",
            status_code=200,
        )
        source_stats.append({"id": source.get("id"), "status": updated.get("status", "active"), "items": len(source_candidates)})
        source.update(updated)

    candidates = sorted(
        {candidate["url"]: candidate for candidate in candidates}.values(),
        key=lambda item: (float(item.get("priority_score", 0.0)), float(item.get("freshness_score", 0.0)), float(item.get("gate_score", 0.0))),
        reverse=True,
    )

    ingest_runtime = {
        "updated_at": iso_now(),
        "source_count": len(sources),
        "source_counts_by_type": dict(source_type_counts),
        "source_counts_by_category": dict(category_counts),
        "source_health_summary": {
            "active": sum(1 for row in source_stats if row["status"] == "active"),
            "degraded": sum(1 for row in source_stats if row["status"] == "degraded"),
            "broken": sum(1 for row in source_stats if row["status"] == "broken"),
        },
        "selected_sources": [
            {
                "id": source.get("id"),
                "source_name": source.get("source_name"),
                "category": source.get("category"),
                "source_type": source.get("source_type"),
                "score": source_monitoring_score(source),
            }
            for source in sources
        ],
        "candidates": candidates[:100],
    }
    graph.setdefault("runtime", {})["ingest"] = ingest_runtime
    graph["updated_at"] = iso_now()
    write_json(CANONICAL_GRAPH, graph)
    write_json(SOURCE_REGISTRY, sources)
    append_jsonl(
        EVIDENCE_LOG,
        [
            {
                "recorded_at": iso_now(),
                "action": "ingest",
                "source_count": len(sources),
                "candidate_count": len(candidates),
                "note": "canonical ingest snapshot",
            }
        ],
    )
    print(
        json.dumps(
            {
                "ok": True,
                "stage": "ingest",
                "sources": len(sources),
                "candidates": len(candidates),
                "source_health_summary": ingest_runtime["source_health_summary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
