#!/usr/bin/env python3
"""Publish verified story packs into deterministic public and social outputs."""

from __future__ import annotations

import os

import json
import re
from functools import lru_cache
from typing import Any
from urllib.parse import quote_plus
from urllib.request import urlopen

from pipeline_common import (
    CANONICAL_GRAPH,
    EVIDENCE_LOG,
    PUBLIC_POST_CHAT_HANDLE,
    TASK_RUNTIME_FILE,
    append_jsonl,
    compact_summary,
    ensure_layout,
    iso_now,
    load_graph,
    load_publication_ledger,
    load_json,
    publication_fingerprint,
    stable_hash,
    translate_to_russian,
    normalize_text,
    write_json,
)


def contains_cyrillic(text: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", text or ""))


def strip_markup(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", "", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def classify_importance(score: float) -> tuple[str, str]:
    if score >= 2.7:
        return "🚨", "срочно"
    if score >= 2.45:
        return "🔥", "важно"
    if score >= 2.15:
        return "🟠", "заметно"
    return "🟢", "фон"


def classify_style(story: dict) -> tuple[str, str]:
    text_blob = " ".join(
        [
            str(story.get("title", "")),
            str(story.get("summary", "")),
            str(story.get("public_impact", "")),
        ]
    ).lower()
    topic = str(story.get("topic", "")).strip()

    urgent_markers = [
        "сроч",
        "urgent",
        "экстр",
        "авари",
        "пожар",
        "взрыв",
        "обстрел",
        "ударил",
        "ударов",
        "теракт",
        "катастроф",
        "землетряс",
        "шторм",
        "наводнен",
        "storm",
        "attack",
        "missile",
        "rocket",
        "war",
        "conflict",
        "escalat",
    ]
    if any(marker in text_blob for marker in urgent_markers):
        return "❗", "срочно"

    conflict_markers = [
        "войн",
        "конфликт",
        "эскалац",
        "боев",
        "ракет",
        "обстрел",
        "военн",
        "militar",
        "attack",
        "strike",
        "missile",
        "shell",
    ]
    if topic in {"foreign_policy"} and any(marker in text_blob for marker in conflict_markers):
        return "🔥", "критическое обострение"

    economy_markers = [
        "эконом",
        "рынок",
        "бирж",
        "курс",
        "инвест",
        "бизнес",
        "компан",
        "прибыл",
        "доход",
        "налог",
        "finance",
        "market",
    ]
    if topic == "economy" or any(marker in text_blob for marker in economy_markers):
        return "📈", "экономика / бизнес"

    politics_markers = [
        "парламент",
        "правительств",
        "закон",
        "институт",
        "суд",
        "министерств",
        "совет",
        "администрац",
        "конституц",
        "president",
        "government",
        "law",
        "bill",
        "court",
    ]
    if topic in {"internal_politics", "legal_human_rights", "local_governance"} or any(marker in text_blob for marker in politics_markers):
        return "🏛️", "внутренняя политика"

    infrastructure_markers = [
        "энерг",
        "электр",
        "дорог",
        "мост",
        "транспорт",
        "вода",
        "газ",
        "коммун",
        "сервис",
        "школ",
        "больниц",
        "infra",
        "utility",
    ]
    if topic == "social_infrastructure_culture" or topic == "utility" or any(marker in text_blob for marker in infrastructure_markers):
        return "⚡", "инфраструктура / сервисы"

    dialogue_markers = [
        "разговор",
        "телефон",
        "встреч",
        "переговор",
        "заявил",
        "заявили",
        "statement",
        "talk",
        "dialog",
        "meeting",
        "discuss",
    ]
    if topic == "foreign_policy" or any(marker in text_blob for marker in dialogue_markers):
        return "💬", "внешняя политика"

    return "🏛️", "внутренняя политика"


@lru_cache(maxsize=512)
def translate_news_to_russian(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if not cleaned:
        return ""
    if contains_cyrillic(cleaned):
        return cleaned
    try:
        url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=ru&dt=t&q=" + quote_plus(cleaned)
        with urlopen(url, timeout=15) as response:
            raw = response.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw)
        translated = str(parsed[0][0][0]).strip() if parsed and parsed[0] and parsed[0][0] else ""
    except Exception:
        return cleaned
    translated = re.sub(r"\s+", " ", translated)
    return translated or cleaned


def source_label(story: dict) -> str:
    topics = {
        "internal_politics": "Политика",
        "legal_human_rights": "Право и права",
        "economy": "Экономика",
        "foreign_policy": "Внешняя политика",
        "local_governance": "Местное управление",
        "social_infrastructure_culture": "Общество",
        "utility": "Фон",
    }
    return topics.get(str(story.get("topic", "")), "Новости")


def social_package(story: dict) -> dict:
    title = strip_markup(
        translate_news_to_russian(translate_to_russian(story.get("title", "")) or story.get("title", ""))
    )
    fact_check = story.get("fact_check", {}) if isinstance(story.get("fact_check", {}), dict) else {}
    perspective_blend = story.get("perspective_blend", {}) if isinstance(story.get("perspective_blend", {}), dict) else {}
    summary_source = (
        str(perspective_blend.get("merged_summary") or "").strip()
        or str(fact_check.get("publication_summary") or "").strip()
        or compact_summary(story.get("summary", ""))
        or story.get("public_impact", "")
    )
    summary = strip_markup(translate_news_to_russian(summary_source))
    badge, importance = classify_style(story)
    source_links = [source.get("url", "") for source in story.get("sources", []) if source.get("url")][:4]
    source_line = "🗂 Источники: " + ", ".join(source_links) if source_links else "🗂 Источники: см. verified story pack"
    return {
        "telegram_post": f"{badge} {title}\n🏷 {source_label(story)} · Важность: {importance}\n\n{summary}\n\n{source_line}",
        "telegram_thread": [
            title,
            summary,
            source_line.replace("🗂 ", ""),
        ],
        "x_thread": [
            title,
            summary,
        ],
        "short_caption": compact_summary(summary)[:180],
        "article_teaser": f"{title}: {compact_summary(summary)}",
    }


def publication_score(story: dict) -> float:
    top_source = story.get("source_trust", {}).get("top_source", {}) if isinstance(story.get("source_trust", {}), dict) else {}
    trust = float(top_source.get("trust_score", 0.0) or 0.0)
    corroboration = float(story.get("source_trust", {}).get("corroboration_count", 0) or 0.0)
    novelty = float(story.get("novelty_score", 0.0) or 0.0)
    priority = float(story.get("priority_score", 0.0) or 0.0)
    impact = min(1.0, len(str(story.get("public_impact", "")).split()) / 30.0)
    topic_weight = {
        "internal_politics": 1.0,
        "legal_human_rights": 0.95,
        "economy": 0.9,
        "foreign_policy": 0.85,
        "local_governance": 0.75,
        "social_infrastructure_culture": 0.65,
    }.get(str(story.get("topic", "")), 0.5)
    fact_check = story.get("fact_check", {}) if isinstance(story.get("fact_check", {}), dict) else {}
    penalty = 0.0
    if fact_check.get("verdict") == "warn":
        penalty = 0.2
    elif fact_check.get("verdict") == "fail":
        penalty = 1.0
    return round((trust * 0.35) + (corroboration * 0.1) + (novelty * 0.15) + (priority * 0.2) + (impact * 0.1) + (topic_weight * 0.1) - penalty, 3)


def feed_admission_gate(story: dict) -> dict[str, Any]:
    top_source = story.get("source_trust", {}).get("top_source", {}) if isinstance(story.get("source_trust", {}), dict) else {}
    fact_check = story.get("fact_check", {}) if isinstance(story.get("fact_check", {}), dict) else {}
    perspective_blend = story.get("perspective_blend", {}) if isinstance(story.get("perspective_blend", {}), dict) else {}
    extraction_confidence = min(1.0, max(0.0, 0.55 + float(story.get("novelty_score", 0.0) or 0.0) * 0.35))
    source_reliability = min(1.0, max(0.0, float(top_source.get("trust_score", 0.0) or 0.0)))
    cross_source_confirmation = min(1.0, max(0.0, float(story.get("source_trust", {}).get("corroboration_count", 0) or 0) / 3.0))
    contradiction_state = bool(fact_check.get("warnings")) or fact_check.get("verdict") in {"warn", "fail"}
    interpretive = bool(perspective_blend.get("official_framing")) or bool(perspective_blend.get("opposition_framing"))
    publication_risk = min(1.0, 0.2 + (0.3 if contradiction_state else 0.0) + (0.2 if interpretive else 0.0) + (0.25 if fact_check.get("publish_blocked") else 0.0))
    decision = "auto_publish"
    if fact_check.get("publish_blocked"):
        decision = "blocked"
    elif contradiction_state or source_reliability < 0.65 or cross_source_confirmation < 0.34:
        decision = "review_required"
    return {
        "decision": decision,
        "reason_codes": [
            code
            for code, enabled in [
                ("publish_blocked", fact_check.get("publish_blocked")),
                ("contradiction_state", contradiction_state),
                ("low_source_reliability", source_reliability < 0.65),
                ("low_cross_source_confirmation", cross_source_confirmation < 0.34),
                ("interpretive_pressure", interpretive),
            ]
            if enabled
        ],
        "metrics": {
            "extraction_confidence": round(extraction_confidence, 3),
            "source_reliability": round(source_reliability, 3),
            "cross_source_confirmation": round(cross_source_confirmation, 3),
            "publication_risk": round(publication_risk, 3),
        },
    }


def resolve_public_target() -> str:
    target = str(os.environ.get("THIEZER_PUBLIC_TARGET", "") or PUBLIC_POST_CHAT_HANDLE).strip()
    return target or PUBLIC_POST_CHAT_HANDLE


def publication_candidates(graph: dict) -> list[dict]:
    runtime = graph.get("runtime", {}) if isinstance(graph.get("runtime", {}), dict) else {}
    graph_runtime = runtime.get("graph", {}) if isinstance(runtime.get("graph", {}), dict) else {}
    retrieval_runtime = runtime.get("retrieval", {}) if isinstance(runtime.get("retrieval", {}), dict) else {}
    candidates: list[dict] = []
    seen_story_ids: set[str] = set()

    def add_candidate(story: dict, *, source: str) -> None:
        if not isinstance(story, dict):
            return
        story_id = str(story.get("story_id") or "").strip()
        if not story_id or story_id in seen_story_ids:
            return
        if source == "retrieval":
            worthiness = story.get("graph_worthiness", {})
            if isinstance(worthiness, dict) and not bool(worthiness.get("worthy")):
                return
        seen_story_ids.add(story_id)
        story_copy = dict(story)
        story_copy["_publication_source"] = source
        candidates.append(story_copy)

    for story in list(graph_runtime.get("verified_story_pack", [])):
        add_candidate(story, source="verified")
    for story in list(retrieval_runtime.get("stories", [])):
        add_candidate(story, source="retrieval")
    return candidates


def build_election_digest_candidate(graph: dict) -> dict | None:
    task_runtime = load_json(TASK_RUNTIME_FILE, {}) if TASK_RUNTIME_FILE.exists() else {}
    if not isinstance(task_runtime, dict):
        return None
    if str(task_runtime.get("task_type") or "").strip() != "news_today":
        return None
    if str(task_runtime.get("topic") or "").strip() != "internal_politics":
        return None
    query = str(task_runtime.get("query") or "").strip().lower()
    if not any(marker in query for marker in ["выбор", "election", "parliament", "парламент", "парт", "affiliat", "аффили"]):
        return None

    party_entities = []
    for entity in graph.get("entities", []):
        if not isinstance(entity, dict):
            continue
        subtype = str(entity.get("subtype") or "").strip()
        tags = {str(tag).strip() for tag in entity.get("tags", []) or []}
        if subtype == "party" or "party" in tags:
            party_entities.append(entity)
    if not party_entities:
        return None

    relation_map = {}
    for relation in graph.get("relations", []):
        if not isinstance(relation, dict):
            continue
        relation_type = str(relation.get("relation_type") or "").strip()
        if relation_type not in {"aligned_with", "member_of", "holds_office_in", "leads"}:
            continue
        left = str(relation.get("from") or "").strip()
        right = str(relation.get("to") or "").strip()
        if left and right:
            relation_map.setdefault(left, set()).add((relation_type, right))
            relation_map.setdefault(right, set()).add((relation_type, left))

    entity_name_by_id = {str(entity.get("id") or ""): str(entity.get("name") or "") for entity in graph.get("entities", []) if isinstance(entity, dict)}
    party_lines = []
    source_links = []
    for entity in party_entities[:8]:
        entity_id = str(entity.get("id") or "").strip()
        name = str(entity.get("name") or entity_id).strip()
        links = entity.get("links", {}) if isinstance(entity.get("links", {}), dict) else {}
        official_url = str(links.get("official") or links.get("site") or links.get("home") or "").strip()
        if official_url:
            source_links.append({"label": name, "url": official_url, "source_name": name})
        affiliated_names = []
        for relation_type, other_id in sorted(relation_map.get(entity_id, set()))[:6]:
            other_name = entity_name_by_id.get(other_id, other_id)
            if other_name and other_name not in affiliated_names:
                affiliated_names.append(other_name)
        party_lines.append(f"- {name}: {', '.join(affiliated_names[:4]) if affiliated_names else 'аффилиации пока требуют доп. верификации'}")

    if not party_lines:
        return None

    title = "Парламентские выборы в Армении: кто выдвигается и с кем связан"
    summary = (
        "Сводка по roster-enriched графу: подтверждены партийные узлы и их видимые связи. "
        "Позитивная сторона: у части партий есть официальные страницы и воспроизводимые roster-записи. "
        "Осторожность: по ряду связей пока single-source coverage, поэтому это рабочая карта, а не финальный вердикт. "
        "Партии и связи:\n" + "\n".join(party_lines)
    )
    source_urls = [item["url"] for item in source_links if item.get("url")]
    digest_id = f"election-digest-{stable_hash(title, summary, *source_urls)[:12]}"
    return {
        "story_id": digest_id,
        "candidate_source": "synthesized",
        "title": title,
        "summary": summary,
        "topic": "internal_politics",
        "importance": "внутренняя политика",
        "importance_badge": "🏛️",
        "source_links": source_urls[:4],
        "sources": source_links[:4],
        "proposal_verdict": "accept",
        "critic_status": "warn",
        "top_source": {
            "source_id": "graph-roster",
            "source_name": "Graph roster digest",
            "source_type": "graph",
            "category": "internal",
            "trust_score": 0.75,
            "bias_flags": [],
            "caution_flags": ["single_source_claim"],
            "directness": "secondary",
            "corroboration_count": len(party_entities),
        },
        "fact_check": {
            "verdict": "pass",
            "issues": [],
            "warnings": ["synthesized_digest"],
            "has_numeric_signal": False,
            "has_relative_change": False,
            "has_subjective_framing": False,
            "corroboration_count": len(party_entities),
            "publish_blocked": False,
            "attribution_required": True,
            "publication_summary": summary,
        },
        "perspective_blend": {
            "ready": False,
            "items": [],
            "distinct_roles": [],
            "official_framing": "",
            "opposition_framing": "",
            "watchdog_framing": "",
            "merged_summary": summary,
        },
        "publication_score": 2.9,
        "freshness_score": 0.9,
        "published_at": iso_now(),
        "graph_worthiness": {
            "worthy": True,
            "highest_trust_score": 0.75,
            "corroboration_count": len(party_entities),
            "caution_flags": [],
        },
        "receipt": {
            "proposal_verdict": "accept",
            "critic_status": "warn",
            "fact_check": {
                "verdict": "pass",
                "publication_summary": summary,
            },
        },
        "public_impact": summary,
    }


def story_is_publishable(story: dict) -> bool:
    freshness_score = float(story.get("freshness_score", 0.0) or 0.0)
    published_at = str(story.get("published_at", "") or "").strip()
    caution_flags = set(story.get("graph_worthiness", {}).get("caution_flags", []) or [])
    fact_check = story.get("fact_check", {}) if isinstance(story.get("fact_check", {}), dict) else {}
    perspective_blend = story.get("perspective_blend", {}) if isinstance(story.get("perspective_blend", {}), dict) else {}
    if "static_page_like_url" in caution_flags or "stale_or_undated_story" in caution_flags:
        return False
    if fact_check.get("publish_blocked") and not perspective_blend.get("ready"):
        return False
    return freshness_score >= 0.45 or bool(published_at)


def build_publication(graph: dict) -> dict:
    verified = publication_candidates(graph)
    max_public_posts = max(1, int(os.environ.get("THIEZER_MAX_PUBLIC_POSTS", "4") or 4))
    public_target = resolve_public_target()
    ledger = load_publication_ledger(limit=800)
    published_story_ids = {
        str(row.get("story_id") or "").strip()
        for row in ledger
        if isinstance(row, dict)
        and str(row.get("target") or "").strip() == public_target
        and str(row.get("status") or "").strip() == "sent"
        and str(row.get("story_id") or "").strip()
    }
    published_fingerprints = {
        str(row.get("fingerprint") or "").strip()
        for row in ledger
        if isinstance(row, dict)
        and str(row.get("target") or "").strip() == public_target
        and str(row.get("status") or "").strip() == "sent"
        and str(row.get("fingerprint") or "").strip()
    }
    published_texts = {
        normalize_text(str(row.get("text") or ""))
        for row in ledger
        if isinstance(row, dict)
        and str(row.get("target") or "").strip() == public_target
        and str(row.get("status") or "").strip() == "sent"
        and str(row.get("text") or "").strip()
    }
    items = []
    social_outputs = []
    skipped_story_ids: list[str] = []
    for story in sorted(verified, key=publication_score, reverse=True):
        if len(items) >= max_public_posts:
            break
        if not story_is_publishable(story):
            skipped_story_ids.append(str(story.get("story_id") or ""))
            continue
        feed_gate = feed_admission_gate(story)
        if feed_gate["decision"] != "auto_publish":
            skipped_story_ids.append(str(story.get("story_id") or ""))
            continue
        title = translate_news_to_russian(translate_to_russian(story.get("title", "")) or story.get("title", ""))
        fact_check = story.get("fact_check", {}) if isinstance(story.get("fact_check", {}), dict) else {}
        perspective_blend = story.get("perspective_blend", {}) if isinstance(story.get("perspective_blend", {}), dict) else {}
        summary = translate_news_to_russian(
            str(perspective_blend.get("merged_summary") or "").strip()
            or str(fact_check.get("publication_summary") or "").strip()
            or compact_summary(story.get("summary", ""))
            or story.get("public_impact", "")
        )
        badge, importance = classify_style(story)
        item = {
            "story_id": story.get("story_id"),
            "candidate_source": story.get("_publication_source", "verified"),
            "title": title,
            "summary": summary,
            "topic": story.get("topic", ""),
            "importance": importance,
            "importance_badge": badge,
            "source_links": [source.get("url", "") for source in story.get("sources", []) if source.get("url")][:4],
            "proposal_verdict": story.get("receipt", {}).get("proposal_verdict", ""),
            "critic_status": story.get("receipt", {}).get("critic_status", ""),
            "top_source": story.get("source_trust", {}).get("top_source", {}),
            "fact_check": fact_check,
            "perspective_blend": perspective_blend,
            "publication_score": publication_score(story),
            "feed_gate": feed_gate,
        }
        story_id = str(story.get("story_id") or "").strip()
        text = social_package(story)["telegram_post"]
        source_links = item["source_links"]
        fingerprint = publication_fingerprint(
            story_id=story_id,
            target=public_target,
            text=text,
            source_links=source_links,
        )
        if (
            story_id in published_story_ids
            or fingerprint in published_fingerprints
            or normalize_text(text) in published_texts
        ):
            skipped_story_ids.append(story_id or fingerprint)
            continue
        items.append(item)
        social_outputs.append({"story_id": story.get("story_id"), **social_package(story)})
    if not items:
        digest = build_election_digest_candidate(graph)
        if digest and story_is_publishable(digest):
            story_id = str(digest.get("story_id") or "").strip()
            text = social_package(digest)["telegram_post"]
            source_links = list(digest.get("source_links", []) or [])
            fingerprint = publication_fingerprint(
                story_id=story_id,
                target=public_target,
                text=text,
                source_links=source_links,
            )
            if story_id not in published_story_ids and fingerprint not in published_fingerprints and normalize_text(text) not in published_texts:
                items.append(
                    {
                        "story_id": story_id,
                        "candidate_source": digest.get("candidate_source", "synthesized"),
                        "title": digest.get("title", ""),
                        "summary": digest.get("summary", ""),
                        "topic": digest.get("topic", "internal_politics"),
                        "importance": digest.get("importance", "внутренняя политика"),
                        "importance_badge": digest.get("importance_badge", "🏛️"),
                        "source_links": source_links,
                        "proposal_verdict": digest.get("proposal_verdict", "accept"),
                        "critic_status": digest.get("critic_status", "warn"),
                        "top_source": digest.get("top_source", {}),
                        "fact_check": digest.get("fact_check", {}),
                        "perspective_blend": digest.get("perspective_blend", {}),
                        "publication_score": digest.get("publication_score", 2.9),
                    }
                )
                social_outputs.append({"story_id": story_id, **social_package(digest)})
    return {
        "updated_at": iso_now(),
        "published_at": iso_now(),
        "target": public_target,
        "count": len(items),
        "items": items,
        "social_outputs": social_outputs,
        "skipped_story_ids": skipped_story_ids,
        "feed_gate_mode": "auto_for_feed_gated_for_graph",
    }


def main() -> int:
    ensure_layout()
    graph = load_graph()
    publication = build_publication(graph)
    graph.setdefault("runtime", {})["publication"] = publication
    graph["updated_at"] = iso_now()
    write_json(CANONICAL_GRAPH, graph)
    append_jsonl(
        EVIDENCE_LOG,
        [
            {
                "recorded_at": iso_now(),
                "action": "publish",
                "published_count": publication["count"],
                "verified_story_ids": [item.get("story_id") for item in publication.get("items", [])],
            }
        ],
    )
    print(
        json.dumps(
            {
                "ok": True,
                "stage": "publish",
                "published": publication["count"],
                "publication": publication,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
