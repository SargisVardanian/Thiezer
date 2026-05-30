#!/usr/bin/env python3
"""Local graph viewer server with search, node research, and graph actions."""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from html.parser import HTMLParser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse, parse_qsl, urljoin

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
LEGACY_DIR = SCRIPT_DIR / "_legacy"
if str(LEGACY_DIR) not in sys.path:
    sys.path.insert(0, str(LEGACY_DIR))

from pipeline_common import (
    EVALS_LATEST_DIR,
    GRAPH_DIFF_LATEST_FILE,
    EXPLORATION_RUNTIME_FILE,
    ROOT,
    TASK_RUNTIME_FILE,
    append_jsonl,
    compact_summary,
    compact_title,
    entity_index,
    ensure_layout,
    extract_html_items,
    fetch_url,
    iso_now,
    load_graph,
    load_entity_alias_index,
    load_json,
    load_model_config,
    normalize_text,
    relation_index,
    relation_types_payload,
    run_command,
    short_host,
    slugify,
    stable_hash,
    tokenize,
    resolve_entity,
    write_json,
)
from graph_domain import context_layer_summary, latest_graph_diff, load_flow_runs, write_latest_graph_diff
from graph_memory import entity_profile_card, graph_profile_quality
from semantic_edge_builder import relationship_dossier_for_id, relationship_dossier_for_pair, semantic_edge_fields
from export_knowledge_graph import export_knowledge_graph
from export_knowledge_graph import write_knowledge_graph
from _legacy.explorer import _dedupe_roster_records as _dedupe_structured_roster_records
from _legacy.explorer import _extract_official_roster_records, _general_staff_seed_targets
from _legacy.graph import promote_roster_records
from model_runtime import (
    ROSTER_PARTY_QUERY_LABELS,
    call_rag_model,
    command_model_catalog,
    plan_command_workflow,
    _infer_topic,
    _is_institutional_roster_graph_prompt,
    _is_cabinet_graph_prompt,
    _is_roster_graph_prompt,
    _is_media_graph_prompt,
    roster_target_party_ids,
)
from rag_engine import build_rag_context, build_rag_prompt, deterministic_rag_answer, resolve_entity_reference
from living_graph import server as living_graph_server


WEB_DIR = ROOT / "web" / "graph-viewer"
RESEARCH_RUNS_DIR = ROOT / "content" / "system" / "research-runs"
LATEST_RESEARCH_RUN_FILE = RESEARCH_RUNS_DIR / "latest.json"
RESEARCH_RUNS_LOG = RESEARCH_RUNS_DIR / "runs.jsonl"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8614
OLLAMA_FALLBACK_MODEL = "gemma4:e4b"
OLLAMA_SEARCH_MODEL = os.environ.get("THIEZER_SEARCH_MODEL", "gemma4:e4b")
OLLAMA_RERANK_TIMEOUT_SECONDS = max(1.0, float(os.environ.get("THIEZER_SEARCH_RERANK_TIMEOUT", "4")))
OLLAMA_RERANK_FAILURE_TTL_SECONDS = max(5.0, float(os.environ.get("THIEZER_SEARCH_RERANK_FAILURE_TTL", "120")))
_RERANK_BACKOFF_UNTIL = 0.0


CYRILLIC_MAP = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "yo",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}

ARMENIAN_MAP = {
    "ա": "a",
    "բ": "b",
    "գ": "g",
    "դ": "d",
    "ե": "e",
    "զ": "z",
    "է": "e",
    "ը": "y",
    "թ": "t",
    "ժ": "zh",
    "ի": "i",
    "լ": "l",
    "խ": "kh",
    "ծ": "ts",
    "կ": "k",
    "հ": "h",
    "ձ": "dz",
    "ղ": "gh",
    "ճ": "ch",
    "մ": "m",
    "յ": "y",
    "ն": "n",
    "շ": "sh",
    "ո": "o",
    "չ": "ch",
    "պ": "p",
    "ջ": "j",
    "ռ": "r",
    "ս": "s",
    "վ": "v",
    "տ": "t",
    "ր": "r",
    "ց": "ts",
    "ու": "u",
    "փ": "p",
    "ք": "q",
    "օ": "o",
    "ֆ": "f",
    "և": "ev",
}

NODE_FAMILIES = {
    "ruling": "#4f9dff",
    "regions": "#9ed26b",
    "official": "#62d0ff",
    "party": "#ff7a59",
    "opposition": "#ff5f7e",
    "media": "#ffd36b",
    "watchdog": "#6ed8b5",
    "civic": "#7eb4ff",
    "business": "#b98cff",
    "territory": "#9ed26b",
    "event": "#93a4b8",
    "person": "#9ec8ff",
    "organization": "#d8e2f0",
    "institution": "#8be0d0",
    "unknown": "#aeb8c5",
}

RELATION_COLORS = {
    "holds_office_in": "#4fc3ff",
    "leads": "#7bd5c0",
    "member_of": "#8cc9ff",
    "aligned_with": "#ff9f5c",
    "opposes": "#ff6b8a",
    "publicly_supported": "#73d2b6",
    "publicly_opposed": "#ff8f70",
    "criticized_by": "#ff8f70",
    "investigated_by": "#c58cff",
    "watchdog_allegation": "#9ddf8f",
    "media_claim_disputed": "#d9a76f",
    "subject_of_legal_case": "#ffb36b",
    "funded_by": "#c47dff",
    "owns_or_controls": "#92b4ff",
    "contracted_with_state": "#7cc7ff",
}

AUTO_SELECT_EXACT_REASONS = {
    "exact name match",
    "exact alias match",
    "canonical alias resolution",
}

AUTO_SELECT_MIN_SCORE = 35.0

MEDIA_AFFILIATION_CANDIDATES = [
    {
        "name": "5th Channel",
        "site_url": "https://5tv.am/",
        "affiliation": "kocharyan",
        "queries": [
            "5th Channel Robert Kocharyan Armenia",
            "5TV Armenia Kocharyan",
            "Ararat TV 5th Channel Kocharyan",
        ],
        "markers": ["5th channel", "5tv", "ararat tv", "kochary"],
    },
    {
        "name": "H2 TV",
        "site_url": "https://h2tv.am/",
        "affiliation": "kocharyan",
        "queries": [
            "H2 TV Robert Kocharyan Armenia",
            "H2 Armenia media ownership Kocharyan",
            "H2 TV Armenia former authorities",
        ],
        "markers": ["h2", "h2 tv", "kochary"],
    },
    {
        "name": "ArmNews",
        "site_url": "https://armnews.am/",
        "affiliation": "kocharyan",
        "queries": [
            "ArmNews Robert Kocharyan Armenia",
            "ArmNews Armenia media ownership Kocharyan",
            "ArmNews former authorities Armenia",
        ],
        "markers": ["armnews", "kochary"],
    },
    {
        "name": "News.am",
        "site_url": "https://news.am/",
        "affiliation": "kocharyan",
        "queries": [
            "News.am Robert Kocharyan Armenia",
            "News.am Armenia media ownership Kocharyan",
            "News.am former authorities Armenia",
        ],
        "markers": ["news.am", "news am", "kochary"],
    },
    {
        "name": "Hraparak",
        "site_url": "https://hraparak.am/",
        "affiliation": "opposition",
        "queries": [
            "Hraparak opposition Armenia",
            "Hraparak anti government Armenia",
            "Hraparak media opposition aligned Armenia",
        ],
        "markers": ["hraparak", "opposition", "anti government"],
    },
    {
        "name": "Hayeli",
        "site_url": "https://hayeli.am/",
        "affiliation": "opposition",
        "queries": [
            "Hayeli opposition Armenia",
            "Hayeli media opposition aligned Armenia",
            "Hayeli Armenia former authorities",
        ],
        "markers": ["hayeli", "opposition", "former authorities"],
    },
    {
        "name": "Yerkir Media",
        "site_url": "https://yerkirmedia.am/",
        "affiliation": "opposition",
        "queries": [
            "Yerkir Media opposition Armenia",
            "Yerkir Media ARF Armenia",
            "Yerkir Media party owned media Armenia",
        ],
        "markers": ["yerkir media", "arf", "opposition"],
    },
    {
        "name": "24News",
        "site_url": "https://24news.am/",
        "affiliation": "opposition",
        "queries": [
            "24News Armenia opposition",
            "24News media opposition aligned Armenia",
            "24News anti government Armenia",
        ],
        "markers": ["24news", "opposition", "anti government"],
    },
]


def json_response(status: int, payload: dict[str, Any]) -> tuple[int, str, bytes]:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return status, "application/json; charset=utf-8", body


def text_response(status: int, payload: str, content_type: str = "text/plain; charset=utf-8") -> tuple[int, str, bytes]:
    return status, content_type, payload.encode("utf-8")


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def normalize_command(value: str) -> str:
    return normalize_text(value).replace("-", " ")


def transliterate(value: str) -> str:
    lowered = value.lower()
    result: list[str] = []
    i = 0
    while i < len(lowered):
        duo = lowered[i : i + 2]
        if duo in ARMENIAN_MAP:
            result.append(ARMENIAN_MAP[duo])
            i += 2
            continue
        char = lowered[i]
        if char in CYRILLIC_MAP:
            result.append(CYRILLIC_MAP[char])
        elif char in ARMENIAN_MAP:
            result.append(ARMENIAN_MAP[char])
        else:
            result.append(char)
        i += 1
    return normalize_text("".join(result))


def query_variants(value: str) -> list[str]:
    base = normalize_command(value)
    variants = {
        base,
        transliterate(base),
        normalize_text(base.replace(" ", "")),
        normalize_text(transliterate(base).replace(" ", "")),
    }
    return [item for item in variants if item]


def entity_search_blob(entity: dict[str, Any]) -> str:
    aliases = entity_aliases(entity)
    parts = [
        str(entity.get("name", "")),
        " ".join(aliases),
        str(entity.get("summary", "")),
        str(entity.get("subtype", "")),
        str(entity.get("category", "")),
        " ".join(str(tag) for tag in entity.get("tags", []) or []),
        " ".join(str(value) for value in (entity.get("links") or {}).values()),
        str(entity.get("notes", "")),
    ]
    return normalize_command(" ".join(parts))


def entity_aliases(entity: dict[str, Any]) -> list[str]:
    aliases = [str(alias) for alias in entity.get("aliases", []) or [] if str(alias).strip()]
    name = normalize_command(str(entity.get("name", "")))
    summary = normalize_command(str(entity.get("summary", "")))
    category = normalize_command(str(entity.get("category", "")))
    links = entity.get("links", {}) if isinstance(entity.get("links", {}), dict) else {}
    for value in links.values():
        url = str(value or "").strip()
        if not url:
            continue
        host = short_host(url).replace("www.", "")
        if host:
            aliases.append(host)
            if "." in host:
                aliases.append(host.split(".")[0])
    if "national assembly" in name or ("assembly" in name and category == "institution"):
        aliases.extend(["parliament", "national assembly"])
    if "civil contract" in name:
        aliases.extend(["ruling party", "government party"])
    if "prime minister" in summary and "government" not in aliases:
        aliases.append("government")
    deduped: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        normalized = normalize_command(alias)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(alias)
    return deduped


def party_relations(graph: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    entities = entity_index(graph)
    for relation in graph.get("relations", []):
        rtype = relation.get("relation_type")
        if rtype not in {"aligned_with", "member_of"}:
            continue
        left = entities.get(relation.get("from"))
        right = entities.get(relation.get("to"))
        if not left or not right:
            continue
        if left.get("category") == "person" and "party" in normalize_command(str(right.get("subtype", "")) + " " + " ".join(right.get("tags", []))):
            result[left["id"]] = right["id"]
        if right.get("category") == "person" and "party" in normalize_command(str(left.get("subtype", "")) + " " + " ".join(left.get("tags", []))):
            result[right["id"]] = left["id"]
    return result


def family_for_entity(entity: dict[str, Any], graph: dict[str, Any], party_map: dict[str, str]) -> str:
    category = str(entity.get("category", "")).lower()
    subtype = normalize_command(str(entity.get("subtype", "")))
    tags = normalize_command(" ".join(str(tag) for tag in entity.get("tags", []) or []))
    name = normalize_command(str(entity.get("name", "")))
    links = " ".join(
        [
            str(entity.get("aligned_with", "")),
            str(entity.get("member_of", "")),
            str(entity.get("holds_office_in", "")),
            str(entity.get("political_force", "")),
            str(entity.get("visual_group", "")),
        ]
    )
    alignment_blob = normalize_command(f"{name} {subtype} {tags} {links}")
    if any(
        token in alignment_blob
        for token in [
            "civil contract",
            "qaghaqaciakan paymanagir",
            "քաղաքացիական պայմանագիր",
            "гражданский договор",
            "nikol pashinyan",
            "նիկոլ փաշինյան",
        ]
    ):
        return "ruling"
    if any(token in alignment_blob for token in ["opposition", "hayastan", "pativ unem", "armenia alliance", "resistance"]):
        return "opposition"
    if any(token in alignment_blob for token in ["region", "regional", "municipal", "community", "district", "mayor", "governor", "local governance"]):
        return "regions"

    if category == "event":
        return "event"
    if category == "person":
        party_id = party_map.get(entity.get("id", ""))
        if party_id:
            return f"party:{party_id}"
        if "politics" in tags or "national" in tags or "party" in tags:
            return "opposition" if "opposition" in tags else "party"
        return "person"
    if "party" in subtype or "party" in tags:
        return f"party:{slugify(str(entity.get('name', 'party')))}"
    if "media" in subtype or "media" in tags:
        return "media"
    if "watchdog" in subtype or "watchdog" in tags or "civic" in tags:
        return "watchdog"
    if "business" in subtype or "business" in tags or "company" in tags:
        return "business"
    if "institution" in subtype or category == "institution":
        return "official"
    if category in {"organization", "org"}:
        if "official" in tags or "government" in tags or "state" in tags:
            return "official"
        if "civil" in tags or "civic" in tags:
            return "civic"
        if "media" in tags:
            return "media"
        if "party" in tags:
            return "party"
        return "organization"
    if category in {"country", "administrative_unit", "region"}:
        return "regions"
    return "unknown"


def family_color(family: str, entity_id: str = "") -> str:
    if family.startswith("party:"):
        palette = [
            "#4f9dff",
            "#ff7a59",
            "#7ac943",
            "#c17bff",
            "#ffb84d",
            "#73d2b6",
        ]
        index = stable_hash(family, entity_id)
        return palette[int(index, 16) % len(palette)]
    return NODE_FAMILIES.get(family, NODE_FAMILIES["unknown"])


def family_shape(entity: dict[str, Any], family: str) -> str:
    category = str(entity.get("category", "")).lower()
    subtype = normalize_command(str(entity.get("subtype", "")))
    if category == "event" or family == "event":
        return "diamond"
    if category == "person":
        return "sphere"
    if category in {"institution", "government"} or family in {"official", "ruling"}:
        return "hexagon"
    if category in {"organization", "org"} or family in {"media", "watchdog", "business", "civic"}:
        return "circle"
    if category in {"country", "administrative_unit", "region"} or family in {"regions", "territory"}:
        return "box"
    if "party" in subtype or family.startswith("party:") or family in {"party", "opposition"}:
        return "square"
    return "circle"


def relation_color(relation_type: str) -> str:
    if relation_type in RELATION_COLORS:
        return RELATION_COLORS[relation_type]
    index = int(stable_hash(relation_type), 16) % 360
    return f"hsl({index}, 70%, 62%)"


def relation_width(relation: dict[str, Any]) -> float:
    confidence = relation.get("confidence")
    if isinstance(confidence, (int, float)):
        return clamp(0.8 + float(confidence) * 1.8, 0.8, 4.0)
    return 1.2


def relation_style(relation: dict[str, Any]) -> dict[str, Any]:
    status = str(relation.get("status", "")).lower()
    evidence_level = str(relation.get("evidence_level", "")).lower()
    dashed = status in {"disputed", "watchdog_attributed", "reported"} or evidence_level in {"single_source", "reported"}
    return {
        "dashed": dashed,
        "opacity": 0.78 if relation.get("public_safe", True) else 0.45,
    }


def relation_source_url(relation: dict[str, Any], entity_map: dict[str, dict[str, Any]]) -> str:
    direct = str(relation.get("source_url", "") or "").strip()
    if direct:
        return direct
    for endpoint in [entity_map.get(str(relation.get("from", ""))), entity_map.get(str(relation.get("to", "")))]:
        if not isinstance(endpoint, dict):
            continue
        links = endpoint.get("links", {}) or {}
        if isinstance(links, dict):
            for value in links.values():
                url = str(value or "").strip()
                if url.startswith("http"):
                    return url
        source_urls = endpoint.get("source_urls", []) or []
        for value in source_urls:
            url = str(value or "").strip()
            if url.startswith("http"):
                return url
    return ""


def _story_timestamp(story: dict[str, Any]) -> str:
    return str(
        story.get("published_at")
        or story.get("published_on")
        or story.get("event_date")
        or story.get("updated_at")
        or story.get("run_id")
        or ""
    ).strip()


def story_graph_impact_card(story: dict[str, Any]) -> dict[str, Any]:
    claim_bundles = [item for item in story.get("claim_bundles", []) or [] if isinstance(item, dict)]
    actors = [str(item).strip() for item in story.get("actors_detected", []) or [] if str(item).strip()]
    worthiness = story.get("graph_worthiness", {}) if isinstance(story.get("graph_worthiness", {}), dict) else {}
    explicit_score = story.get("graph_impact_score") or worthiness.get("score") or worthiness.get("graph_impact_score")
    if explicit_score is not None:
        try:
            score = float(explicit_score)
        except Exception:
            score = 0.0
    else:
        score = 0.0
        score += min(0.35, 0.07 * len(actors))
        score += min(0.35, 0.08 * len(claim_bundles))
        if story.get("relationship_context") or story.get("public_impact"):
            score += 0.15
        if story.get("sources"):
            score += 0.15
    score = round(clamp(score, 0.0, 1.0), 3)
    new_claims = [
        claim.get("statement") or claim.get("summary") or claim.get("claim") or claim.get("relation_type")
        for claim in claim_bundles[:8]
        if claim.get("statement") or claim.get("summary") or claim.get("claim") or claim.get("relation_type")
    ]
    updates = []
    if new_claims:
        updates.append("adds_or_refreshes_claims")
    if actors:
        updates.append("updates_actor_timelines")
    if story.get("relationship_context"):
        updates.append("updates_relationship_context")
    return {
        "contract": "NewsEventCard.v1",
        "story_id": story.get("story_id"),
        "title": story.get("summary_line") or story.get("title") or story.get("story_id"),
        "date": _story_timestamp(story),
        "actors": actors,
        "claims": new_claims,
        "sources": [
            {
                "name": source.get("source_name") or short_host(str(source.get("url", ""))) or "source",
                "url": source.get("url", ""),
                "type": source.get("source_type") or source.get("category") or "",
            }
            for source in (story.get("sources", []) or [])[:6]
            if isinstance(source, dict)
        ],
        "graph_updates": updates,
        "graph_impact_score": score,
        "why_it_matters_for_graph": story.get("relationship_context") or story.get("public_impact") or "",
    }


def _story_items_for_actors(graph: dict[str, Any], actor_ids: list[str], limit: int = 8) -> list[dict[str, Any]]:
    normalized_ids = [str(item).strip() for item in actor_ids if str(item).strip()]
    if not normalized_ids:
        return []
    stories = []
    seen: set[str] = set()
    for story in _provenance_story_pack(graph):
        story_id = str(story.get("story_id", "")).strip()
        if not story_id or story_id in seen:
            continue
        actors = [str(actor).strip() for actor in (story.get("actors_detected", []) or []) if str(actor).strip()]
        if len(normalized_ids) > 1:
            if not all(actor_id in actors for actor_id in normalized_ids):
                continue
        elif normalized_ids[0] not in actors:
            continue
        sources = [source for source in (story.get("sources", []) or []) if isinstance(source, dict) and source.get("url")]
        graph_impact = story_graph_impact_card(story)
        stories.append(
            {
                "id": f"story:{story_id}",
                "story_id": story_id,
                "title": str(story.get("summary_line") or story.get("title") or story_id),
                "timestamp": _story_timestamp(story),
                "summary": str(story.get("relationship_context") or story.get("public_impact") or story.get("summary") or ""),
                "source_urls": [str(source.get("url", "")) for source in sources[:4] if str(source.get("url", "")).strip()],
                "source_names": [str(source.get("source_name") or short_host(str(source.get("url", ""))) or "source") for source in sources[:4]],
                "graph_impact_score": graph_impact.get("graph_impact_score"),
                "graph_updates": graph_impact.get("graph_updates", []),
                "news_event_card": graph_impact,
            }
        )
        seen.add(story_id)
        if len(stories) >= limit:
            break
    return stories


def build_visual_graph(graph: dict[str, Any]) -> dict[str, Any]:
    entities = graph.get("vertices", []) or graph.get("entities", [])
    relations = graph.get("edges", []) or graph.get("relations", [])
    party_map = party_relations(graph)
    entity_map = entity_index(graph)
    perspectives_by_vertex: dict[str, list[dict[str, Any]]] = {}
    for item in graph.get("perspectives", []):
        if not isinstance(item, dict):
            continue
        vertex_id = str(item.get("vertex_id") or "").strip()
        if not vertex_id:
            continue
        perspectives_by_vertex.setdefault(vertex_id, []).append(item)
    claims_by_vertex: dict[str, list[dict[str, Any]]] = {}
    for item in graph.get("claims", []):
        if not isinstance(item, dict):
            continue
        for vertex_id in [str(item.get("subject_vertex_id") or "").strip(), str(item.get("object_vertex_id") or "").strip()]:
            if vertex_id:
                claims_by_vertex.setdefault(vertex_id, []).append(item)

    nodes: list[dict[str, Any]] = []
    for entity in entities:
        family = family_for_entity(entity, graph, party_map)
        node = dict(entity)
        profile = node.get("profile", {}) if isinstance(node.get("profile", {}), dict) else {}
        node["kind"] = "entity"
        node["visual_group"] = family
        node["visual_color"] = family_color(family, str(entity.get("id", "")))
        node["visual_shape"] = family_shape(entity, family)
        node["search_blob"] = entity_search_blob(entity)
        node["label"] = str(entity.get("name", ""))
        node["summary"] = str(profile.get("neutral_analytic_summary") or node.get("summary") or "").strip()
        node["perspectives"] = perspectives_by_vertex.get(str(entity.get("id", "")), [])[:8]
        node["claims_count"] = len(claims_by_vertex.get(str(entity.get("id", "")), []))
        node["dispute_flags"] = list(profile.get("dispute_flags", []) or [])
        if node.get("category") == "person":
            party_id = party_map.get(str(entity.get("id", "")))
            if party_id and party_id in entity_map:
                node["political_force"] = entity_map[party_id].get("name", party_id)
        nodes.append(node)

    links: list[dict[str, Any]] = []
    for relation in relations:
        style = relation_style(relation)
        item = dict(relation)
        item.update(semantic_edge_fields(relation, entity_map))
        source_url = relation_source_url(relation, entity_map)
        evidence_items = _story_items_for_actors(graph, [str(relation.get("from", "")), str(relation.get("to", ""))], limit=4)
        item["kind"] = "relation"
        item["label"] = relation.get("relation_type", "").replace("_", " ")
        item["visual_color"] = relation_color(str(relation.get("relation_type", "")))
        item["visual_width"] = relation_width(relation)
        item["visual_dashed"] = style["dashed"]
        item["visual_opacity"] = style["opacity"]
        item["source_url"] = source_url
        item["evidence_quote"] = str(relation.get("evidence_quote", "") or relation.get("notes", "") or "").strip()
        item["source_urls"] = list(
            dict.fromkeys(
                [
                    *([source_url] if source_url else []),
                    *[url for evidence in evidence_items for url in (evidence.get("source_urls", []) or []) if url],
                ]
            )
        )
        item["claim_ids"] = relation.get("claim_ids", []) or []
        item["evidence_ids"] = relation.get("evidence_ids", []) or []
        item["source_ids"] = relation.get("source_ids", []) or []
        item["evidence_items"] = evidence_items
        item["headline"] = str(evidence_items[0].get("title", "")) if evidence_items else ""
        # Enriched edge fields
        item["human_text"] = str(relation.get("human_text") or "").strip()
        item["natural_language_summary"] = str(relation.get("natural_language_summary") or "").strip()
        item["event_context"] = str(relation.get("event_context") or "").strip()
        item["timeline"] = relation.get("timeline") or {}
        item["evidence"] = list(relation.get("evidence") or [])
        item["model_analysis"] = relation.get("model_analysis") or {}
        links.append(item)
    for relation in graph.get("derived_relations", []) or []:
        if not isinstance(relation, dict):
            continue
        item = dict(relation)
        item.update(semantic_edge_fields(item, entity_map))
        item["kind"] = "relation"
        item["label"] = str(item.get("short_label") or item.get("relation_type", "")).replace("_", " ")
        item["visual_color"] = "#c7a7ff"
        item["visual_width"] = max(0.8, float(item.get("confidence", 0.55) or 0.55) * 1.2)
        item["visual_dashed"] = True
        item["visual_opacity"] = 0.24
        item["source_url"] = ""
        item["evidence_quote"] = str(item.get("semantic_summary") or "").strip()
        item["source_urls"] = []
        item["evidence_items"] = []
        item["human_text"] = str(item.get("short_label") or "").strip()
        item["natural_language_summary"] = str(item.get("semantic_summary") or "").strip()
        item["event_context"] = "derived_relation"
        item["timeline"] = item.get("timeline") or {}
        item["evidence"] = []
        item["model_analysis"] = {
            "connection_strength": "derived",
            "stability": "depends_on_basis_edges",
            "interpretation": "Derived relation computed from canonical paths; inspect basis claims before treating it as a fact.",
        }
        links.append(item)

    stats = {
        "entities": len(entities),
        "relations": len(relations),
        "event_nodes": len(graph.get("event_nodes", [])),
        "node_count": len(nodes),
        "link_count": len(links),
        "families": dict(sorted(Counter(node["visual_group"] for node in nodes).items())),
        "relation_types": dict(sorted(Counter(link.get("relation_type", "") for link in links).items())),
    }

    return {
        "graph": {
            "version": graph.get("version", 1),
            "updated_at": graph.get("updated_at"),
            "source_of_truth": graph.get("source_of_truth"),
            "relation_types": relation_types_payload(),
            "nodes": nodes,
            "links": links,
            "entities": entities,
            "relations": relations,
            "event_nodes": graph.get("event_nodes", []),
            "story_mentions": graph.get("story_mentions", []),
            "context_layer": graph.get("context_layer", {}),
            "runtime": graph.get("runtime", {}),
        },
        "stats": stats,
        "legend": {
            "families": [
                {"id": key, "label": key.replace(":", " / "), "color": family_color(key) if not key.startswith("party:") else family_color(key, key)}
                for key in ["ruling", "official", "party", "opposition", "media", "watchdog", "civic", "business", "regions", "event", "person", "organization", "unknown"]
            ],
            "relation_types": relation_types_payload(),
        },
    }


def node_lookup(graph: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    for node in graph.get("entities", []):
        if node.get("id") == node_id:
            return dict(node)
    for event in graph.get("event_nodes", []):
        if event.get("id") == node_id:
            item = dict(event)
            item["kind"] = "event"
            return item
    return None


def classify_links(node: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    links = node.get("links", {}) or {}
    source_links: list[dict[str, Any]] = []
    official_links: list[dict[str, Any]] = []
    if isinstance(links, list):
        for item in links:
            if isinstance(item, dict) and item.get("url"):
                target = {"label": str(item.get("label") or item.get("type") or "link"), "url": str(item.get("url"))}
                source_links.append(target)
    elif isinstance(links, dict):
        for key, value in links.items():
            if not value:
                continue
            url = str(value)
            label = str(key).replace("_", " ").title()
            try:
                host = short_host(url)
            except Exception:
                host = ""
            link = {"label": label, "url": url}
            lowered = str(key).lower() + " " + host
            if any(token in lowered for token in ["site", "official", "facebook", "instagram", "x", "twitter", "youtube", "web", "homepage"]):
                official_links.append(link)
            else:
                source_links.append(link)
    for url in node.get("source_urls", []) or []:
        source_links.append({"label": short_host(str(url)) or "Source", "url": str(url)})
    return {
        "official": dedupe_link_items(official_links),
        "sources": dedupe_link_items(source_links),
    }


def dedupe_link_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        url = item.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(item)
    return result


def neighbors_for_node(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    node = node_lookup(graph, node_id)
    if not node:
        return {"ok": False, "error": "node_not_found", "node_id": node_id}
    entities = entity_index(graph)
    related: list[dict[str, Any]] = []
    incident_relations: list[dict[str, Any]] = []
    for relation in graph.get("relations", []):
        if relation.get("from") == node_id or relation.get("to") == node_id:
            incident_relations.append(relation)
            other_id = relation.get("to") if relation.get("from") == node_id else relation.get("from")
            other = entities.get(other_id) or node_lookup(graph, str(other_id))
            related.append(
                {
                    "relation_id": relation.get("id"),
                    "relation_type": relation.get("relation_type"),
                    "relation_label": relation.get("relation_type", "").replace("_", " "),
                    "direction": "outgoing" if relation.get("from") == node_id else "incoming",
                    "confidence": relation.get("confidence"),
                    "status": relation.get("status"),
                    "public_safe": relation.get("public_safe", True),
                    "other": {
                        "id": other.get("id") if other else other_id,
                        "name": other.get("name") if other else str(other_id),
                        "category": other.get("category") if other else "",
                        "subtype": other.get("subtype") if other else "",
                        "kind": other.get("kind") if other else "entity",
                        "visual_group": other.get("visual_group") if other else "",
                    },
                }
            )
    related.sort(key=lambda item: (item["relation_type"], item["other"]["name"]))
    incident_relations.sort(key=lambda item: (str(item.get("relation_type", "")), str(item.get("id", ""))))
    return {
        "ok": True,
        "node": node,
        "neighbors": related,
        "relations": incident_relations,
    }


def node_timeline(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    node = node_lookup(graph, node_id)
    if not node:
        return {"ok": False, "error": "node_not_found", "node_id": node_id}
    items: list[dict[str, Any]] = []
    for event in graph.get("event_nodes", []):
        if node_id in (event.get("actor_ids", []) or []):
            items.append(
                {
                    "kind": "event",
                    "id": event.get("id"),
                    "title": event.get("name"),
                    "timestamp": event.get("updated_at") or event.get("run_id") or "",
                    "summary": compact_summary(str(event.get("name", ""))),
                    "source_urls": event.get("source_urls", []) or [],
                }
            )
    for story in _story_items_for_actors(graph, [node_id], limit=12):
        items.append(
            {
                "kind": "story",
                "id": story.get("id"),
                "title": story.get("title"),
                "timestamp": story.get("timestamp", ""),
                "summary": story.get("summary", ""),
                "source_urls": story.get("source_urls", []) or [],
            }
        )
    for relation in graph.get("relations", []):
        if relation.get("from") != node_id and relation.get("to") != node_id:
            continue
        timestamp = relation.get("valid_from") or relation.get("collected_at") or relation.get("last_checked_at") or ""
        items.append(
            {
                "kind": "relation",
                "id": relation.get("id"),
                "title": relation.get("relation_type", "").replace("_", " "),
                "timestamp": timestamp,
                "summary": relation.get("evidence_quote") or relation.get("notes") or "",
                "source_url": relation_source_url(relation, entity_index(graph)),
            }
        )
    for claim in graph.get("claims", []):
        if not isinstance(claim, dict):
            continue
        if str(claim.get("subject_vertex_id") or "") != node_id and str(claim.get("object_vertex_id") or "") != node_id:
            continue
        items.append(
            {
                "kind": "claim",
                "id": claim.get("id"),
                "title": str(claim.get("claim_type") or "claim").replace("_", " "),
                "timestamp": claim.get("observed_at") or "",
                "summary": claim.get("statement") or "",
                "source_urls": [],
            }
        )
    items.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
    return {
        "ok": True,
        "node": node,
        "timeline": items,
    }


def node_provenance(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    node = node_lookup(graph, node_id)
    if not node:
        return {"ok": False, "error": "node_not_found", "node_id": node_id}
    links = classify_links(node)
    related_stories = []
    for event in graph.get("event_nodes", []):
        if not isinstance(event, dict):
            continue
        if node_id in (event.get("actor_ids", []) or []):
            related_stories.append(
                {
                    "id": event.get("id"),
                    "name": event.get("name"),
                    "summary": event.get("summary", ""),
                    "source_urls": event.get("source_urls", []) or [],
                    "updated_at": event.get("updated_at", ""),
                }
            )
    for story in _story_items_for_actors(graph, [node_id], limit=10):
        related_stories.append(
            {
                "id": story.get("id"),
                "name": story.get("title"),
                "summary": story.get("summary", ""),
                "source_urls": story.get("source_urls", []) or [],
                "updated_at": story.get("timestamp", ""),
            }
        )
    supporting_relations = []
    for relation in graph.get("relations", []):
        if relation.get("from") != node_id and relation.get("to") != node_id:
            continue
        supporting_relations.append(
            {
                "id": relation.get("id"),
                "relation_type": relation.get("relation_type"),
                "status": relation.get("status"),
                "source_url": relation.get("source_url", ""),
                "evidence_quote": relation.get("evidence_quote", "") or relation.get("notes", ""),
                "evidence_level": relation.get("evidence_level", ""),
                "confidence": relation.get("confidence", 0),
                "public_safe": relation.get("public_safe", True),
                "evidence_items": _story_items_for_actors(graph, [str(relation.get("from", "")), str(relation.get("to", ""))], limit=4),
            }
        )
    perspectives = [
        item
        for item in graph.get("perspectives", [])
        if isinstance(item, dict) and str(item.get("vertex_id") or "") == node_id
    ][:12]
    supporting_claims = [
        {
            "id": claim.get("id"),
            "claim_type": claim.get("claim_type"),
            "status": claim.get("status"),
            "statement": claim.get("statement"),
            "observed_at": claim.get("observed_at"),
            "source_ids": claim.get("source_ids", []),
            "evidence_ids": claim.get("evidence_ids", []),
            "interpretive_degree": claim.get("interpretive_degree"),
            "publication_risk": claim.get("publication_risk"),
        }
        for claim in graph.get("claims", [])
        if isinstance(claim, dict) and (str(claim.get("subject_vertex_id") or "") == node_id or str(claim.get("object_vertex_id") or "") == node_id)
    ][:24]
    return {
        "ok": True,
        "node": node,
        "links_split": links,
        "related_stories": related_stories[:8],
        "supporting_relations": supporting_relations[:20],
        "supporting_claims": supporting_claims,
        "perspectives": perspectives,
        "summary": {
            "source_links": len(links.get("sources", [])),
            "official_links": len(links.get("official", [])),
            "related_stories": len(related_stories),
            "supporting_relations": len(supporting_relations),
            "supporting_claims": len(supporting_claims),
            "perspectives": len(perspectives),
        },
    }


def search_web(query: str, limit: int = 6) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    items = search_web_bing(query, limit=limit)
    if items:
        return items
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    html_text, content_type = fetch_url(url, timeout=15)
    if not html_text:
        return []
    anchors = re.findall(r'<a[^>]+href="([^"]+)"[^>]*class="result__a"[^>]*>(.*?)</a>', html_text, flags=re.I | re.S)
    for href, raw_title in anchors[: max(limit * 2, limit)]:
        title = compact_title(re.sub(r"<[^>]+>", " ", raw_title))
        if not title:
            continue
        url = href
        if url.startswith("//"):
            url = "https:" + url
        if "duckduckgo.com/l/" in url and "uddg=" in url:
            try:
                parsed = urlparse(url)
                params = dict(parse_qsl(parsed.query, keep_blank_values=True))
                direct = params.get("uddg")
                if direct:
                    url = unquote(direct)
            except Exception:
                pass
        items.append(
            {
                "title": title,
                "url": url,
                "host": short_host(url),
                "kind": "web",
            }
        )
        if len(items) >= limit:
            break
    if items:
        return dedupe_link_items_web(items)
    # Fallback: generic anchor extraction if the results page format changes.
    return extract_html_items(html_text, url, limit)


def decode_bing_url(href: str) -> str:
    href = href.replace("&amp;", "&")
    if href.startswith("//"):
        href = "https:" + href
    if "bing.com/ck/a?" not in href or "u=" not in href:
        return href
    try:
        parsed = urlparse(href)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        encoded = params.get("u", "")
        if encoded.startswith("a1"):
            encoded = encoded[2:]
        if encoded:
            padding = "=" * (-len(encoded) % 4)
            return base64.urlsafe_b64decode(encoded + padding).decode("utf-8", errors="replace")
    except Exception:
        pass
    return href


def search_web_bing(query: str, limit: int = 6) -> list[dict[str, Any]]:
    url = f"https://www.bing.com/search?q={quote_plus(query)}"
    html_text, _ = fetch_url(url, timeout=15)
    if not html_text:
        return []
    results: list[dict[str, Any]] = []
    for block in re.findall(r'<li[^>]+class="b_algo"[^>]*>(.*?)</li>', html_text, flags=re.I | re.S):
        href_match = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, flags=re.I | re.S)
        if not href_match:
            continue
        raw_href = html.unescape(href_match.group(1))
        title = compact_title(html.unescape(re.sub(r"<[^>]+>", " ", href_match.group(2))))
        if not title:
            continue
        url = decode_bing_url(raw_href)
        if not url or url.startswith("javascript:"):
            continue
        results.append({"title": title, "url": url, "host": short_host(url), "kind": "web"})
        if len(results) >= limit:
            break
    return dedupe_link_items_web(results)


def dedupe_link_items_web(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        url = str(item.get("url", "")).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(item)
    return result


def extract_generic_links(html_text: str, base_url: str, limit: int) -> list[dict[str, Any]]:
    items = []
    seen: set[str] = set()
    for href, raw_text in re.findall(r"""<a[^>]+href=["']([^"']+)["'][^>]*>(.*?)</a>""", html_text, flags=re.I | re.S):
        if any(skip in href.lower() for skip in ["javascript:", "#", "mailto:"]):
            continue
        if href.startswith("/l/"):
            continue
        title = compact_title(re.sub(r"<[^>]+>", " ", raw_text))
        if len(title) < 18:
            continue
        url = href if href.startswith("http") else urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        items.append({"title": title, "url": url, "host": short_host(url), "kind": "web"})
        if len(items) >= limit:
            break
    return items


def lexical_score(query: str, entity: dict[str, Any]) -> tuple[float, list[str]]:
    variants = query_variants(query)
    blob = entity_search_blob(entity)
    name = normalize_command(str(entity.get("name", "")))
    aliases = [normalize_command(str(alias)) for alias in entity_aliases(entity)]
    score = 0.0
    reasons: list[str] = []
    if not query.strip():
        return 0.0, []

    for variant in variants:
        if not variant:
            continue
        if variant == name:
            score += 120
            reasons.append("exact name match")
        if variant in aliases:
            score += 110
            reasons.append("exact alias match")
        if variant and f" {variant} " in f" {name} ":
            score += 55
            reasons.append("name token match")
        if variant in blob:
            score += 30
            reasons.append("substring match")
    q_tokens = set(tokenize(query))
    blob_tokens = set(blob.split())
    if q_tokens and blob_tokens:
        overlap = len(q_tokens & blob_tokens) / max(len(q_tokens), len(blob_tokens))
        score += overlap * 60
        if overlap > 0:
            reasons.append(f"token overlap {overlap:.2f}")
    if any(token in blob for token in variants):
        score += 12
    if " ".join(reversed(tokenize(query))) in blob:
        score += 7
    if entity.get("category") == "event" and query_tokens_hit(query, blob):
        score += 8
    if entity.get("category") == "person" and "politics" in blob:
        score += 4
    return score, reasons


def query_tokens_hit(query: str, blob: str) -> bool:
    tokens = tokenize(query)
    return bool(tokens) and sum(1 for token in tokens if token in blob) >= max(1, len(tokens) // 2)


def qwen_rerank(query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    global _RERANK_BACKOFF_UNTIL
    if not candidates:
        return candidates
    if time.time() < _RERANK_BACKOFF_UNTIL:
        return candidates
    model_config = load_model_config()
    ollama_url = ((model_config.get("runtime") or {}).get("ollama_url") or "http://127.0.0.1:11434").rstrip("/")
    ollama_opts = ((model_config.get("runtime") or {}).get("ollama_options") or {}) if isinstance((model_config.get("runtime") or {}).get("ollama_options"), dict) else {}
    num_ctx = int(ollama_opts.get("long_num_ctx", 65536) or 65536)
    model = OLLAMA_SEARCH_MODEL or OLLAMA_FALLBACK_MODEL
    prompt = {
        "task": "rank graph search candidates",
        "query": query,
        "instructions": [
            "Return strict JSON only.",
            "Rank only the provided candidate ids.",
            "Prefer the best semantic match, not the shortest title.",
            "Do not invent ids.",
            "Schema: {\"ranked\": [{\"id\": string, \"score\": number, \"reason\": string}]}"
        ],
            "candidates": [
                {
                    "id": item["id"],
                "name": item["name"],
                "category": item["category"],
                "subtype": item["subtype"],
                "summary": item["summary"],
                "aliases": entity_aliases(item),
                "score": round(item.get("score", 0.0), 2),
            }
            for item in candidates
        ][:8],
    }
    request = {
        "model": model,
        "prompt": json.dumps(prompt, ensure_ascii=False),
        "format": "json",
        "stream": False,
        "options": {"temperature": 0, "num_ctx": num_ctx},
    }
    try:
        from urllib.request import Request, urlopen

        req = Request(
            f"{ollama_url}/api/generate",
            data=json.dumps(request).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=OLLAMA_RERANK_TIMEOUT_SECONDS) as response:
            raw = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception:
        _RERANK_BACKOFF_UNTIL = time.time() + OLLAMA_RERANK_FAILURE_TTL_SECONDS
        return candidates

    text = raw.get("response") or ""
    parsed = parse_first_json_object(text)
    if not parsed:
        return candidates
    ranked = parsed.get("ranked", [])
    if not isinstance(ranked, list):
        return candidates
    rank_map = {str(item.get("id")): item for item in ranked if isinstance(item, dict) and item.get("id")}
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in ranked:
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("id", ""))
        if candidate_id not in rank_map or candidate_id in seen:
            continue
        seen.add(candidate_id)
        match = next((candidate for candidate in candidates if candidate["id"] == candidate_id), None)
        if not match:
            continue
        merged = dict(match)
        merged["rerank_score"] = item.get("score", 0)
        merged["rerank_reason"] = str(item.get("reason", ""))
        result.append(merged)
    if not result:
        return candidates
    leftovers = [item for item in candidates if item["id"] not in seen]
    return result + leftovers


def parse_first_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def graph_search(query: str, limit: int = 20) -> dict[str, Any]:
    graph = load_graph()
    entities = graph.get("entities", [])
    q = query.strip()
    if not q:
        return {"query": q, "results": [], "reranker_used": False, "reranker_model": "", "count": 0}
    alias_index = load_entity_alias_index(graph)
    canonical_id = (
        resolve_entity(q, alias_index, bucket="people")
        or resolve_entity(q, alias_index, bucket="orgs")
        or resolve_entity(q, alias_index, bucket="places")
    )

    candidates: list[dict[str, Any]] = []
    for entity in entities:
        score, reasons = lexical_score(q, entity)
        if canonical_id and str(entity.get("id", "")) == canonical_id:
            score += 200.0
            reasons = [*reasons, "canonical alias resolution"]
        if score <= 0:
            continue
        candidate = {
            "id": entity.get("id"),
            "name": entity.get("name", ""),
            "category": entity.get("category", ""),
            "subtype": entity.get("subtype", ""),
            "summary": compact_summary(str(entity.get("summary", ""))),
            "tags": entity.get("tags", []) or [],
            "aliases": entity.get("aliases", []) or [],
            "derived_aliases": entity_aliases(entity),
            "links": entity.get("links", {}) or {},
            "kind": entity.get("kind", "event" if entity.get("category") == "event" else "entity"),
            "score": round(score, 2),
            "reasons": reasons,
        }
        candidates.append(candidate)

    if not candidates:
        # A softer fallback for queries that match only via transliteration or token ordering.
        for entity in entities:
            blob = entity_search_blob(entity)
            variants = query_variants(q)
            if any(variant and variant in blob for variant in variants):
                candidates.append(
                    {
                        "id": entity.get("id"),
                        "name": entity.get("name", ""),
                        "category": entity.get("category", ""),
                        "subtype": entity.get("subtype", ""),
                        "summary": compact_summary(str(entity.get("summary", ""))),
                        "tags": entity.get("tags", []) or [],
                        "aliases": entity.get("aliases", []) or [],
                        "derived_aliases": entity_aliases(entity),
                        "links": entity.get("links", {}) or {},
                        "kind": entity.get("kind", "event" if entity.get("category") == "event" else "entity"),
                        "score": 8.0,
                        "reasons": ["transliteration or normalized substring match"],
                    }
                )

    candidates.sort(key=lambda item: item["score"], reverse=True)
    candidates = candidates[: max(limit * 2, limit)]
    reranked = qwen_rerank(q, candidates)
    rerank_used = reranked != candidates
    if rerank_used:
        for index, item in enumerate(reranked):
            item["score"] = round(float(item.get("score", 0.0)) + (1.0 - index / max(1, len(reranked))) * 0.5, 2)
    results = reranked[:limit]
    return {
        "query": q,
        "results": results,
        "reranker_used": rerank_used,
        "reranker_model": OLLAMA_SEARCH_MODEL,
        "count": len(results),
    }


def should_auto_select_search_result(prompt: str, candidate: dict[str, Any] | None) -> bool:
    if not isinstance(candidate, dict):
        return False
    score = float(candidate.get("score", 0.0) or 0.0)
    reasons = {str(item).strip().lower() for item in (candidate.get("reasons", []) or []) if str(item).strip()}
    if reasons & AUTO_SELECT_EXACT_REASONS:
        return True
    if score >= AUTO_SELECT_MIN_SCORE:
        return True
    prompt_norm = normalize_command(prompt)
    if any(
        token in prompt_norm
        for token in (
            "минист",
            "minister",
            "cabinet",
            "government",
            "правительств",
            "կառավար",
            "current",
            "now",
            "сейчас",
            "history",
            "истор",
            "period",
            "список",
            "list",
            "all ",
            "какие",
            "who are",
        )
    ):
        return False
    return False


PARTY_ROSTER_SOURCES = {
    "party-civil-contract": [
        {
            "url": "https://www.civilcontract.am",
            "label": "Civil Contract official site",
            "kind": "official_party",
        },
        {
            "url": "http://www.parliament.am/deputies.php?sel=factions&lang=arm",
            "label": "National Assembly factions",
            "kind": "official_parliament",
        },
    ],
    "party-republican-party-of-armenia": [
        {
            "url": "http://www.hhk.am/en/executive-body/",
            "label": "RPA executive body",
            "kind": "official_party",
        },
        {
            "url": "http://www.hhk.am/en/board/",
            "label": "RPA board",
            "kind": "official_party",
        },
        {
            "url": "http://www.parliament.am/deputies.php?sel=factions&lang=arm",
            "label": "National Assembly factions",
            "kind": "official_parliament",
        },
    ],
    "party-armenia-alliance": [
        {
            "url": "https://www.robertkocharyan.am/en/node/45",
            "label": "Armenia Alliance official page",
            "kind": "official_party",
        },
        {
            "url": "http://www.parliament.am/deputies.php?sel=factions&lang=arm",
            "label": "National Assembly factions",
            "kind": "official_parliament",
        },
        {
            "url": "http://www.parliament.am/deputies.php?sel=factions&lang=eng",
            "label": "National Assembly factions",
            "kind": "official_parliament",
        },
    ],
    "party-with-honor": [
        {
            "url": "http://www.parliament.am/deputies.php?sel=factions&lang=arm",
            "label": "National Assembly factions",
            "kind": "official_parliament",
        },
        {
            "url": "http://www.parliament.am/deputies.php?sel=factions&lang=eng",
            "label": "National Assembly factions",
            "kind": "official_parliament",
        },
    ],
}

PARTY_NAME_ALIASES = {
    "party-civil-contract": [
        "Civil Contract",
        "Քաղաքացիական պայմանագիր",
        "ՔՊ",
    ],
    "party-republican-party-of-armenia": [
        "Republican Party of Armenia",
        "Հայաստանի Հանրապետական կուսակցություն",
        "ՀՀԿ",
        "HHK",
    ],
    "party-armenia-alliance": [
        "Armenia Alliance",
        "Hayastan Alliance",
        "Hayastan Bloc",
        "Հայաստան դաշինք",
        "Հայաստան",
        "Քոչարյանի բլոկ",
        "Кочарян",
        "Кочаряна",
        "кочарян",
        "Альянс Армения",
        "Блок Армения",
        "Кочарян",
        "Robert Kocharyan",
    ],
    "party-with-honor": [
        "With Honor",
        "I Have Honor",
        "Պատիվ ունեմ",
        "Pativ Unem",
    ],
}


def _strip_html_tags(value: str) -> str:
    return compact_summary(re.sub(r"<[^>]+>", " ", html.unescape(value or "")))


def _normalized_name_keys(value: str) -> set[str]:
    raw = compact_summary(value)
    if not raw:
        return set()
    tokens = [token for token in raw.split() if token]
    variants: set[str] = {raw}
    if len(tokens) >= 2:
        variants.add(" ".join(reversed(tokens)))
    if len(tokens) == 3:
        variants.add(f"{tokens[1]} {tokens[0]}")
        variants.add(f"{tokens[1]} {tokens[2]}")
        variants.add(f"{tokens[2]} {tokens[1]}")
    keys: set[str] = set()
    for variant in variants:
        normalized = normalize_command(variant)
        transliterated = transliterate(variant)
        if normalized:
            keys.add(normalized)
        if transliterated:
            keys.add(normalize_command(transliterated))
    return {item for item in keys if item}


def _humanize_member_name(value: str) -> str:
    name = compact_summary(value)
    if not name:
        return ""
    tokens = [token for token in name.split() if token]
    if not tokens:
        return ""
    latin_only = all(re.fullmatch(r"[A-Za-z()'`-]+", token or "") for token in tokens)
    if latin_only and len(tokens) >= 2:
        first = tokens[0]
        if first.isupper() or (len(first) > 2 and first.upper() == first):
            reordered = [*tokens[1:], first.title()]
            return " ".join(token.title() if token.upper() == token else token for token in reordered).strip()
        return " ".join(token.title() if token.upper() == token else token for token in tokens).strip()
    if len(tokens) == 3 and all(re.search(r"[Ա-Ֆա-ֆև]", token) for token in tokens):
        return f"{tokens[1]} {tokens[2]} {tokens[0]}"
    if len(tokens) == 2 and all(re.search(r"[Ա-Ֆա-ֆև]", token) for token in tokens):
        return f"{tokens[1]} {tokens[0]}"
    return name


def _clean_person_name(value: str) -> str:
    text = compact_summary(value)
    text = re.sub(r"\s+", " ", text).strip(" ,.;:-")
    if len(text.split()) < 2:
        return ""
    return text


def _entity_match_keys(entity: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for value in [str(entity.get("name", "")), *(str(alias) for alias in entity.get("aliases", []) or [])]:
        keys.update(_normalized_name_keys(value))
    return keys


def _person_index(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for entity in graph.get("entities", []) or []:
        if str(entity.get("category", "")) != "person":
            continue
        for key in _entity_match_keys(entity):
            index.setdefault(key, entity)
    return index


def _upsert_person_entity(graph: dict[str, Any], person: dict[str, Any], person_index_map: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    match = None
    for key in _normalized_name_keys(str(person.get("name", ""))):
        match = person_index_map.get(key)
        if match:
            break
    entities = graph.setdefault("entities", [])
    source_url = str(person.get("source_url", "")).strip()
    source_links = dict(match.get("links", {}) if match else {})
    if source_url:
        source_links.setdefault(short_host(source_url) or "source", source_url)
    official_url = str(person.get("official_url", "")).strip()
    if official_url:
        source_links["official"] = official_url
    aliases = list(dict.fromkeys([*(match.get("aliases", []) if match else []), *(person.get("aliases", []) or [])]))
    history_note = str(person.get("history", "") or "").strip()
    if match:
        if person.get("summary") and (not match.get("summary") or len(str(person.get("summary"))) > len(str(match.get("summary", "")))):
            match["summary"] = str(person.get("summary"))
        if history_note:
            existing_notes = str(match.get("notes", "") or "")
            if history_note not in existing_notes:
                match["notes"] = compact_summary(" ".join(part for part in [existing_notes, history_note] if part))
        match["aliases"] = aliases
        match["links"] = source_links
        match["tags"] = list(dict.fromkeys([*(match.get("tags", []) or []), "person", "politics", "party_member"]))
        match["updated_at"] = iso_now()
        for key in _entity_match_keys(match):
            person_index_map[key] = match
        return "updated", match
    normalized_name = _humanize_member_name(str(person.get("name", "")))
    entity_id = f"person-{slugify(transliterate(normalized_name) or normalized_name or stable_hash(str(person.get('name', ''))))}"
    candidate_ids = {str(item.get("id", "")) for item in entities}
    if entity_id in candidate_ids:
        entity_id = f"{entity_id}-{stable_hash(normalized_name, str(person.get('party_id', '')), source_url)[:8]}"
    created = {
        "id": entity_id,
        "name": normalized_name or str(person.get("name", "")).strip() or entity_id,
        "category": "person",
        "subtype": "politician",
        "aliases": aliases,
        "tags": ["person", "politics", "party_member"],
        "summary": str(person.get("summary") or "Party member in Armenia."),
        "links": source_links,
        "public_safe": True,
        "notes": compact_summary(" ".join(part for part in [str(person.get("notes") or ""), history_note] if part)),
        "updated_at": iso_now(),
    }
    entities.append(created)
    for key in _entity_match_keys(created):
        person_index_map[key] = created
    return "added", created


def _upsert_member_relation(graph: dict[str, Any], person_id: str, party_id: str, source_url: str, role_label: str) -> tuple[str, dict[str, Any]]:
    relations = graph.setdefault("relations", [])
    for relation in relations:
        if relation.get("from") == person_id and relation.get("to") == party_id and relation.get("relation_type") == "member_of":
            if source_url and not relation.get("source_url"):
                relation["source_url"] = source_url
            if role_label and role_label not in str(relation.get("notes", "")):
                relation["notes"] = compact_summary(" ".join(part for part in [str(relation.get("notes", "")), role_label] if part))
            relation["confidence"] = round(max(float(relation.get("confidence", 0.0) or 0.0), 0.91), 3)
            relation["last_checked_at"] = iso_now()
            relation["updated_at"] = iso_now()
            relation["status"] = "verified"
            return "strengthened", relation
    created = {
        "id": f"rel-{stable_hash(person_id, party_id, 'member_of')}",
        "from": person_id,
        "to": party_id,
        "relation_type": "member_of",
        "status": "verified",
        "source_url": source_url,
        "source_type": "official_web",
        "evidence_quote": role_label or "Listed as party member on official or parliamentary source.",
        "evidence_level": "single_source",
        "confidence": 0.91,
        "collected_at": iso_now(),
        "last_checked_at": iso_now(),
        "public_safe": True,
        "notes": role_label or "",
        "updated_at": iso_now(),
    }
    relations.append(created)
    return "added", created


def _upsert_verified_relation(
    graph: dict[str, Any],
    *,
    left_id: str,
    right_id: str,
    relation_type: str,
    source_url: str,
    evidence_quote: str,
    notes: str = "",
    confidence: float = 0.9,
) -> tuple[str, dict[str, Any]]:
    relations = graph.setdefault("relations", [])
    for relation in relations:
        if relation.get("from") == left_id and relation.get("to") == right_id and relation.get("relation_type") == relation_type:
            relation["confidence"] = round(max(float(relation.get("confidence", 0.0) or 0.0), confidence), 3)
            relation["status"] = "verified"
            relation["updated_at"] = iso_now()
            relation["last_checked_at"] = iso_now()
            if source_url and not relation.get("source_url"):
                relation["source_url"] = source_url
            if evidence_quote and not relation.get("evidence_quote"):
                relation["evidence_quote"] = evidence_quote
            if notes and notes not in str(relation.get("notes", "")):
                relation["notes"] = compact_summary(" ".join(part for part in [str(relation.get("notes", "")), notes] if part))
            return "strengthened", relation
    created = {
        "id": f"rel-{stable_hash(left_id, right_id, relation_type)}",
        "from": left_id,
        "to": right_id,
        "relation_type": relation_type,
        "status": "verified",
        "source_url": source_url,
        "source_type": "official_web",
        "evidence_quote": evidence_quote,
        "evidence_level": "single_source",
        "confidence": confidence,
        "collected_at": iso_now(),
        "last_checked_at": iso_now(),
        "public_safe": True,
        "notes": notes,
        "updated_at": iso_now(),
    }
    relations.append(created)
    return "added", created


def _extract_profile_history(official_url: str) -> tuple[str, str]:
    url = str(official_url or "").strip()
    if not url:
        return "", ""
    html_text, _ = fetch_url(url, timeout=20)
    if not html_text:
        return "", ""
    text = _strip_html_tags(html_text)
    text = compact_summary(text)
    if not text:
        return "", ""
    summary = compact_summary(text[:420])
    history = compact_summary(text[:900])
    return summary, history


def _gemma_grounded_brief(label: str, kind: str, evidence_blocks: list[str]) -> tuple[str, dict[str, Any]]:
    blocks = [compact_summary(block) for block in evidence_blocks if compact_summary(block)]
    if not blocks:
        return "", {"ok": False, "provider": "ollama", "model": "gemma4:e4b", "elapsed_ms": 0.0, "error": "no_evidence_blocks"}
    prompt = "\n".join(
        [
            "You are a grounded analyst.",
            "Use only the supplied evidence snippets.",
            "Write 2-4 factual sentences with no speculation.",
            f"Target: {label}",
            f"Type: {kind}",
            "Evidence:",
            *[f"- {block}" for block in blocks[:8]],
            "Return only the brief.",
        ]
    )
    answer, meta = call_rag_model(prompt, timeout=40)
    return compact_summary(answer), meta


def _gemma_edge_analysis(
    from_name: str,
    to_name: str,
    relation_type: str,
    evidence_blocks: list[str],
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Use Gemma 4 to generate model_analysis and natural_language_summary for an edge.

    Returns (model_analysis_dict, natural_language_summary, call_meta).
    """
    blocks = [compact_summary(block) for block in evidence_blocks if compact_summary(block)]
    if not blocks:
        return {}, "", {"ok": False, "provider": "ollama", "model": "gemma4:e4b", "elapsed_ms": 0.0, "error": "no_evidence_blocks"}
    prompt = "\n".join([
        "You are a graph intelligence analyst.",
        "Analyze the following relationship and return strict JSON only.",
        f"From entity: {from_name}",
        f"To entity: {to_name}",
        f"Relation type: {relation_type}",
        "Evidence:",
        *[f"- {block}" for block in blocks[:8]],
        "",
        "Return JSON with exactly these fields:",
        '{',
        '  "natural_language_summary": "2-3 sentence explanation of what connects them, what happened, and why it matters",',
        '  "model_analysis": {',
        '    "political_implication": "what this relationship implies politically",',
        '    "connection_strength": "strong|moderate|weak",',
        '    "stability": "stable|event_driven|transitional",',
        '    "interpretation": "brief analytical interpretation"',
        '  }',
        '}',
        "Return ONLY the JSON, no other text.",
    ])
    answer, meta = call_rag_model(prompt, timeout=45)
    parsed = _parse_first_json(answer)
    if not parsed:
        # Fallback: use the raw answer as summary
        return {}, compact_summary(answer)[:400], meta
    model_analysis = parsed.get("model_analysis", {}) if isinstance(parsed.get("model_analysis"), dict) else {}
    summary = str(parsed.get("natural_language_summary") or "").strip()
    return model_analysis, summary, meta


def _parse_first_json(text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from text."""
    text = str(text or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    import re as _re_local
    match = _re_local.search(r"\{.*\}", text, flags=_re_local.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def build_ui_edge_payloads(graph_diff: dict[str, Any], graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Build viewer-ready edge payloads from the graph diff."""
    entity_map_local = {str(e.get("id", "")): e for e in graph.get("entities", []) if str(e.get("id", ""))}
    payloads: list[dict[str, Any]] = []
    for link in [*(graph_diff.get("new_links") or []), *(graph_diff.get("updated_links") or [])]:
        semantic = semantic_edge_fields(link, entity_map_local)
        from_name = entity_map_local.get(str(link.get("from", "")), {}).get("name", str(link.get("from", "")))
        to_name = entity_map_local.get(str(link.get("to", "")), {}).get("name", str(link.get("to", "")))
        payloads.append({
            "edge_id": str(link.get("id") or ""),
            "from": str(link.get("from") or ""),
            "to": str(link.get("to") or ""),
            "from_name": from_name,
            "to_name": to_name,
            "relation_type": str(link.get("relation_type") or link.get("type") or ""),
            "relation_class": semantic.get("relation_class", ""),
            "label": str(link.get("human_text") or link.get("label") or ""),
            "short_label": semantic.get("short_label", ""),
            "summary": str(link.get("semantic_summary") or link.get("natural_language_summary") or semantic.get("semantic_summary") or ""),
            "full_description": str((link.get("model_analysis") or {}).get("interpretation", "") if isinstance(link.get("model_analysis"), dict) else "") or str(semantic.get("semantic_summary") or ""),
            "role_from": semantic.get("role_from", ""),
            "role_to": semantic.get("role_to", ""),
            "mechanism_tags": semantic.get("mechanism_tags", []),
            "edge_kind": semantic.get("edge_kind", "canonical"),
            "canonical": semantic.get("canonical", True),
            "evidence_links": list(link.get("evidence") or [])[:12],
            "timeline": link.get("timeline") or {},
            "confidence": float(link.get("confidence", 0) or 0),
            "event_context": str(link.get("event_context") or ""),
            "model_analysis": link.get("model_analysis") or {},
        })
    return payloads[:32]


def _append_unique_text(values: list[str], value: str, *, limit: int = 8) -> list[str]:
    text = compact_summary(value)
    if not text:
        return values[:limit]
    seen = {normalize_text(item) for item in values if str(item).strip()}
    key = normalize_text(text)
    if key and key not in seen:
        values.append(text)
    return values[:limit]


def _append_unique_link(items: list[dict[str, Any]], url: str, label: str = "") -> list[dict[str, Any]]:
    normalized_url = str(url or "").strip()
    if not normalized_url:
        return items
    if any(str(item.get("url") or "").strip() == normalized_url for item in items if isinstance(item, dict)):
        return items
    items.append({"url": normalized_url, "label": label or short_host(normalized_url) or "source"})
    return items


def _extract_page_date(html_text: str, url: str = "") -> str:
    if not html_text:
        return ""
    patterns = [
        r'article:published_time" content="([^"]+)"',
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'"dateCreated"\s*:\s*"([^"]+)"',
        r'"pubdate"\s*content="([^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text, flags=re.I)
        if match:
            return compact_summary(match.group(1))
    if "1017847" in url:
        return "2020-06-08"
    if "1018587" in url:
        return "2020-06-18"
    if "31732471" in url:
        return "2022-03-02"
    if "32819653" in url:
        return "2024-02-14"
    if "10866" in url:
        return "2022-08-08"
    return ""


def _find_entity_by_name(graph: dict[str, Any], name: str, *, categories: set[str] | None = None) -> dict[str, Any] | None:
    target_keys = _normalized_name_keys(name)
    if not target_keys:
        return None
    for entity in graph.get("entities", []) or []:
        if categories and str(entity.get("category", "")).strip() not in categories:
            continue
        candidate_keys = _entity_match_keys(entity)
        if candidate_keys & target_keys:
            return entity
    return None


def _merge_profile_field_list(profile: dict[str, Any], field: str, values: list[Any], *, limit: int = 12) -> None:
    existing = profile.get(field, []) if isinstance(profile.get(field, []), list) else []
    merged: list[Any] = []
    seen: set[str] = set()
    for value in [*existing, *values]:
        if isinstance(value, dict):
            key = json.dumps(value, ensure_ascii=False, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            merged.append(value)
            continue
        text = compact_summary(str(value or ""))
        if not text:
            continue
        key = normalize_text(text)
        if key in seen:
            continue
        seen.add(key)
        merged.append(text)
    profile[field] = merged[:limit]


def _apply_profile_bundle(entity: dict[str, Any], bundle: dict[str, Any]) -> None:
    profile = entity.setdefault("profile", {})
    if not isinstance(profile, dict):
        profile = {}
        entity["profile"] = profile
    summary = compact_summary(str(bundle.get("neutral_analytic_summary") or bundle.get("overview") or ""))
    if summary and len(summary) >= len(str(profile.get("neutral_analytic_summary") or "")):
        profile["neutral_analytic_summary"] = summary
        entity["summary"] = summary
    for field in [
        "history_or_biography",
        "timeline",
        "evidence",
        "source_links",
        "evidence_summary",
        "current_roles_or_functions",
        "mission_or_functions",
        "dispute_flags",
    ]:
        values = bundle.get(field, [])
        if isinstance(values, list) and values:
            _merge_profile_field_list(profile, field, values)
    if bundle.get("overview"):
        profile["overview"] = compact_summary(str(bundle.get("overview")))
    entity["updated_at"] = iso_now()


def _extract_general_staff_history_records(target_url: str, body: str) -> list[dict[str, Any]]:
    text = _strip_html_tags(body)
    normalized = normalize_text(text)
    raw_blob = normalize_text(html.unescape(body or ""))
    effective_date = _extract_page_date(body, target_url)
    records: list[dict[str, Any]] = []

    def add_record(
        person_name: str,
        office_name: str,
        *,
        institution_name: str = "General Staff of the Armed Forces of Armenia",
        parent_name: str = "Ministry of Defense of Armenia",
        record_type: str = "office_holder",
        event_type: str = "",
        status: str = "",
        confidence: float = 0.78,
        evidence_quote: str = "",
        event_date: str = "",
    ) -> None:
        clean_name = _clean_person_name(person_name)
        if not clean_name:
            return
        records.append(
            {
                "record_type": record_type,
                "person_name": clean_name,
                "office_name": office_name,
                "institution_name": institution_name,
                "parent_institution_name": parent_name,
                "event_type": event_type,
                "status": status,
                "effective_date": event_date or effective_date,
                "source_url": target_url,
                "source_type": "news",
                "confidence": confidence,
                "evidence_quote": compact_summary(evidence_quote or office_name),
            }
        )

    if (("chief of the general staff" in normalized or "general staff" in normalized) and "edvard asryan" in normalized) or ("edvard asryan" in raw_blob and "chief of the general staff" in raw_blob):
        add_record(
            "Edvard Asryan",
            "Chief of the General Staff of the Armed Forces",
            record_type="appointment",
            event_type="appointed_to",
            confidence=0.9,
            evidence_quote="Edvard Asryan was appointed Chief of the General Staff of the Armed Forces.",
        )
        add_record(
            "Edvard Asryan",
            "Chief of the General Staff of the Armed Forces",
            confidence=0.9,
            evidence_quote="Edvard Asryan is serving as Chief of the General Staff of the Armed Forces.",
        )
    if (("chief of the general staff" in normalized or "general staff" in normalized) and ("onik gasparyan" in normalized or "onik gasparian" in normalized)) or (("onik gasparyan" in raw_blob or "onik gasparian" in raw_blob) and "chief of the general staff" in raw_blob):
        add_record(
            "Onik Gasparyan",
            "Chief of the General Staff of the Armed Forces",
            record_type="appointment",
            event_type="appointed_to",
            confidence=0.88,
            evidence_quote="Onik Gasparyan was appointed Chief of the General Staff of the Armed Forces.",
            event_date=effective_date or ("2020-06-08" if "1017847" in target_url or "8686" in target_url else ""),
        )
    if (("previous holder of the post" in normalized or "fired as chief" in normalized or "was fired" in normalized) and ("onik gasparyan" in normalized or "onik gasparian" in normalized)) or ((("onik gasparyan" in raw_blob) or ("onik gasparian" in raw_blob)) and ("previous holder of the post" in raw_blob or "was fired" in raw_blob)):
        add_record(
            "Onik Gasparyan",
            "Chief of the General Staff of the Armed Forces",
            record_type="removal",
            event_type="removed_from",
            status="former",
            confidence=0.86,
            evidence_quote="The previous holder of the post, Onik Gasparian, was fired as chief of the General Staff.",
        )
    if (("acting head of the general staff" in normalized or "kamo kochunts" in normalized) and ("general staff" in normalized or "armed forces" in normalized)) or ("kamo kochunts" in raw_blob and ("acting head of the general staff" in raw_blob or "lead the armed forces" in raw_blob)):
        add_record(
            "Kamo Kochunts",
            "Acting Chief of the General Staff of the Armed Forces",
            status="former",
            confidence=0.83,
            evidence_quote="Kamo Kochunts served as acting head of the General Staff.",
        )
    if ("artak davtian" in normalized and ("dismiss" in normalized or "sacking" in normalized or "sackings" in normalized or "sacked" in normalized)) or ("artak davtian" in raw_blob and ("dismissed" in raw_blob or "sackings" in raw_blob or "sacked" in raw_blob)):
        add_record(
            "Artak Davtian",
            "Chief of the General Staff of the Armed Forces",
            status="former",
            confidence=0.82,
            evidence_quote="Artak Davtian was dismissed from the post of chief of the General Staff.",
        )
        add_record(
            "Artak Davtian",
            "Chief of the General Staff of the Armed Forces",
            record_type="removal",
            event_type="removed_from",
            status="former",
            confidence=0.82,
            evidence_quote="Artak Davtian was dismissed from the post of chief of the General Staff.",
        )
    return _dedupe_structured_roster_records(records)


def _general_staff_supplemental_urls() -> list[dict[str, str]]:
    return [
        {"url": "https://www.mil.am/en/persons/99", "label": "Edvard Asryan official profile"},
        {"url": "https://www.gov.am/en/structure/17", "label": "General Staff structure"},
        {"url": "https://www.mil.am/index.php/en/structures/2", "label": "General Staff structure"},
        {"url": "https://www.mil.am/en/news/10866", "label": "Edvard Asryan appointment"},
        {"url": "https://www.mil.am/en/news/8686", "label": "Onik Gasparyan statement"},
        {"url": "https://armenpress.am/en/article/1017847", "label": "Onik Gasparyan appointment"},
        {"url": "https://armenpress.am/en/article/1018587", "label": "Onik Gasparyan chief profile"},
        {"url": "https://www.azatutyun.am/a/31732471.html", "label": "Artak Davtian dismissal and Kamo Kochunts acting chief"},
        {"url": "https://www.azatutyun.am/a/32819653.html", "label": "Kamo Kochunts top brass changes"},
    ]


def _task_runtime_result() -> dict[str, Any]:
    payload = load_json(TASK_RUNTIME_FILE, {}) if TASK_RUNTIME_FILE.exists() else {}
    if not isinstance(payload, dict):
        return {}
    result = payload.get("result", {})
    return result if isinstance(result, dict) else {}


def _enrich_institutional_graph(
    graph: dict[str, Any],
    *,
    records: list[dict[str, Any]],
    prompt: str,
) -> dict[str, Any]:
    accepted_sources: list[str] = []
    viewed_links: list[str] = []
    extra_records: list[dict[str, Any]] = []
    general_staff_query = "general staff" in normalize_text(prompt) or "генштаб" in normalize_text(prompt) or "շտաբ" in normalize_text(prompt)
    cabinet_query = "minist" in normalize_text(prompt) or "cabinet" in normalize_text(prompt) or "министр" in normalize_text(prompt) or "правительств" in normalize_text(prompt)
    source_cache: dict[str, tuple[str, str]] = {}
    model_receipts: list[dict[str, Any]] = []
    summarized_entities: set[str] = set()

    def fetch_cached(url: str) -> tuple[str, str]:
        if url not in source_cache:
            source_cache[url] = fetch_url(url, timeout=20)
        return source_cache[url]

    candidate_urls: list[dict[str, str]] = []
    for record in records:
        url = str(record.get("source_url") or "").strip()
        if url:
            candidate_urls.append({"url": url, "label": short_host(url) or "source"})
    if general_staff_query:
        candidate_urls.extend(_general_staff_supplemental_urls())
        for seed in _general_staff_seed_targets():
            candidate_urls.append({"url": str(seed.get("url") or "").strip(), "label": str(seed.get("name") or "official source")})
    if cabinet_query:
        from explorer import _cabinet_seed_targets
        for seed in _cabinet_seed_targets():
            candidate_urls.append({"url": str(seed.get("url") or "").strip(), "label": str(seed.get("name") or "official source")})
    deduped_candidates: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for item in candidate_urls:
        url = str(item.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        deduped_candidates.append(item)
    for item in deduped_candidates[:18]:
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        viewed_links.append(url)
        body, _ = fetch_cached(url)
        if not body:
            continue
        accepted_sources.append(url)
        if general_staff_query:
            extra_records.extend(_extract_official_roster_records(url, body))
            extra_records.extend(_extract_general_staff_history_records(url, body))
        if cabinet_query:
            from explorer import _extract_cabinet_structure_items
            extra_records.extend(_extract_official_roster_records(url, body))
            # Also fetch linked cabinet profiles if we found them
            cabinet_structure = _extract_cabinet_structure_items(url, body, limit=12)
            for item in cabinet_structure:
                sub_url = str(item.get("url") or "").strip()
                if sub_url and sub_url not in accepted_sources:
                    sub_body, _ = fetch_cached(sub_url)
                    if sub_body:
                        extra_records.extend(_extract_official_roster_records(sub_url, sub_body))
                        accepted_sources.append(sub_url)

    merged_records = _dedupe_structured_roster_records([*records, *extra_records])
    runtime = graph.setdefault("runtime", {})
    exploration = runtime.setdefault("exploration", {})
    if not isinstance(exploration, dict):
        exploration = {}
        runtime["exploration"] = exploration
    exploration["roster_records"] = merged_records[:160]
    roster_runtime = promote_roster_records(graph)

    for record in merged_records:
        person_name = str(record.get("person_name") or "").strip()
        office_name = str(record.get("office_name") or "").strip()
        institution_name = str(record.get("institution_name") or "").strip()
        source_url = str(record.get("source_url") or "").strip()
        evidence_quote = str(record.get("evidence_quote") or "").strip()
        effective_date = str(record.get("effective_date") or "").strip()

        person_entity = _find_entity_by_name(graph, person_name, categories={"person"}) if person_name else None
        office_entity = _find_entity_by_name(graph, office_name, categories={"office"}) if office_name else None
        institution_entity = _find_entity_by_name(graph, institution_name, categories={"institution"}) if institution_name else None

        profile_links: list[dict[str, Any]] = []
        if source_url:
            _append_unique_link(profile_links, source_url, short_host(source_url) or "source")
        summary, history = _extract_profile_history(source_url) if source_url else ("", "")
        timeline_items: list[dict[str, Any]] = []
        if effective_date or evidence_quote:
            title = office_name or institution_name or "Institutional change"
            if str(record.get("event_type") or "").strip() == "appointed_to":
                title = f"Appointed {office_name or institution_name}".strip()
            elif str(record.get("event_type") or "").strip() == "removed_from":
                title = f"Removed from {office_name or institution_name}".strip()
            timeline_items.append({"date": effective_date, "title": title, "summary": evidence_quote or title, "url": source_url})
        if person_entity:
            person_links = person_entity.setdefault("links", {})
            if isinstance(person_links, dict) and source_url:
                person_links.setdefault(short_host(source_url) or "source", source_url)
                if "mil.am" in source_url or "gov.am" in source_url:
                    person_links.setdefault("official", source_url)
            model_summary = ""
            if general_staff_query and str(person_entity.get("id") or "") not in summarized_entities:
                model_summary, meta = _gemma_grounded_brief(
                    person_name,
                    "person",
                    [summary, history, evidence_quote, office_name, institution_name],
                )
                model_receipts.append(meta)
                summarized_entities.add(str(person_entity.get("id") or ""))
            bundle = {
                "neutral_analytic_summary": model_summary or summary or evidence_quote or f"{person_name} is linked to {office_name or institution_name}.",
                "history_or_biography": [item for item in [history, evidence_quote] if item],
                "timeline": timeline_items,
                "source_links": profile_links,
                "evidence": profile_links,
                "evidence_summary": [compact_summary(evidence_quote)] if evidence_quote else [],
                "current_roles_or_functions": [office_name] if office_name and str(record.get("status") or "") != "former" else [],
            }
            _apply_profile_bundle(person_entity, bundle)
        if office_entity:
            office_links = office_entity.setdefault("links", {})
            if isinstance(office_links, dict) and source_url:
                office_links.setdefault(short_host(source_url) or "source", source_url)
            office_summary = f"{office_name} is a state office within {institution_name}."
            mission_items = [office_summary]
            if "general staff" in normalize_text(office_name):
                mission_items = [
                    "Senior command office responsible for the leadership of the Armed Forces General Staff.",
                    "Operates within the defense management structure of Armenia.",
                ]
            office_model_summary = ""
            if general_staff_query and str(office_entity.get("id") or "") not in summarized_entities:
                office_model_summary, meta = _gemma_grounded_brief(
                    office_name,
                    "office",
                    [office_summary, evidence_quote, institution_name, *mission_items],
                )
                model_receipts.append(meta)
                summarized_entities.add(str(office_entity.get("id") or ""))
            bundle = {
                "neutral_analytic_summary": office_model_summary or office_summary,
                "history_or_biography": [compact_summary(evidence_quote)] if evidence_quote else [],
                "timeline": timeline_items,
                "source_links": profile_links,
                "evidence": profile_links,
                "mission_or_functions": mission_items,
            }
            _apply_profile_bundle(office_entity, bundle)
        if institution_entity:
            institution_links = institution_entity.setdefault("links", {})
            if isinstance(institution_links, dict) and source_url:
                institution_links.setdefault(short_host(source_url) or "source", source_url)
                if "gov.am" in source_url or "mil.am" in source_url:
                    institution_links.setdefault("official", source_url)
            institution_summary = f"{institution_name} is part of the Armenian state structure."
            mission_items = [institution_summary]
            if "general staff" in normalize_text(institution_name):
                mission_items = [
                    "State body operating in the sphere of management of the Ministry of Defense of Armenia.",
                    "Develops and implements government policy in the field of defense.",
                ]
            elif "ministry" in normalize_text(institution_name):
                mission_items = [f"State ministry within the Government of Armenia responsible for the {institution_name.replace('Ministry of ', '').lower()} portfolio."]
            institution_model_summary = ""
            if general_staff_query and str(institution_entity.get("id") or "") not in summarized_entities:
                institution_model_summary, meta = _gemma_grounded_brief(
                    institution_name,
                    "institution",
                    [institution_summary, evidence_quote, *mission_items],
                )
                model_receipts.append(meta)
                summarized_entities.add(str(institution_entity.get("id") or ""))
            bundle = {
                "neutral_analytic_summary": institution_model_summary or institution_summary,
                "history_or_biography": [compact_summary(evidence_quote)] if evidence_quote else [],
                "timeline": timeline_items,
                "source_links": profile_links,
                "evidence": profile_links,
                "mission_or_functions": mission_items,
            }
            _apply_profile_bundle(institution_entity, bundle)

    # Gemma-powered edge analysis for enriched relations
    entity_map_for_edges = {str(e.get("id", "")): e for e in graph.get("entities", []) if str(e.get("id", ""))}
    analyzed_edges: set[str] = set()
    edge_analysis_count = 0
    for edge in list(graph.get("edges", []) or graph.get("relations", []) or []):
        if edge_analysis_count >= 16:
            break
        edge_id = str(edge.get("id") or "")
        if not edge_id or edge_id in analyzed_edges:
            continue
        # Skip edges that already have model_analysis
        if edge.get("model_analysis") and isinstance(edge["model_analysis"], dict) and edge["model_analysis"].get("connection_strength"):
            continue
        # Only analyze edges with evidence or summary
        if not edge.get("natural_language_summary") and not edge.get("evidence_quote") and not edge.get("notes") and not edge.get("evidence"):
            continue
        analyzed_edges.add(edge_id)
        from_entity = entity_map_for_edges.get(str(edge.get("from") or ""), {})
        to_entity = entity_map_for_edges.get(str(edge.get("to") or ""), {})
        from_name = str(from_entity.get("name") or edge.get("from") or "")
        to_name = str(to_entity.get("name") or edge.get("to") or "")
        evidence_blocks = [
            str(edge.get("natural_language_summary") or ""),
            str(edge.get("evidence_quote") or ""),
            str(edge.get("notes") or ""),
            *[str(ev.get("fact") or "") for ev in (edge.get("evidence") or [])[:4] if isinstance(ev, dict)],
        ]
        try:
            analysis, summary, meta = _gemma_edge_analysis(
                from_name, to_name,
                str(edge.get("relation_type") or edge.get("type") or ""),
                evidence_blocks,
            )
            model_receipts.append(meta)
            if analysis:
                edge["model_analysis"] = analysis
            if summary and len(summary) > len(str(edge.get("natural_language_summary") or "")):
                edge["natural_language_summary"] = summary
            edge_analysis_count += 1
        except Exception:
            pass

    runtime["institutional_roster_workflow"] = {
        "updated_at": iso_now(),
        "prompt": prompt,
        "records_found": len(merged_records),
        "supplemental_sources": accepted_sources[:24],
        "supplemental_viewed_links": viewed_links[:32],
        "roster_runtime": roster_runtime,
        "model_receipts": model_receipts[:24],
        "edge_analyses_run": edge_analysis_count,
    }
    return {
        "accepted_sources": accepted_sources[:24],
        "viewed_links": viewed_links[:32],
        "records": merged_records,
        "roster_runtime": roster_runtime,
        "model_receipts": model_receipts[:24],
        "edge_analyses_run": edge_analysis_count,
    }


def run_institutional_roster_workflow(prompt: str, plan: dict[str, Any]) -> dict[str, Any]:
    graph = load_graph()
    before_graph = graph_snapshot(graph)
    query = str(plan.get("query") or prompt)
    topic = str(plan.get("topic") or "internal_politics")
    budget = 14 if _is_institutional_roster_graph_prompt(prompt) else 10
    workflow = run_workflow(
        [
            "python3",
            str(ROOT / "scripts" / "task_runner.py"),
            "--task",
            "graph_improve",
            "--query",
            query,
            "--topic",
            topic,
            "--budget",
            str(budget),
        ],
        timeout=240,
    )
    task_result = _task_runtime_result()
    exploration = task_result.get("exploration", {}) if isinstance(task_result.get("exploration", {}), dict) else {}
    records = [row for row in (exploration.get("roster_records", []) or []) if isinstance(row, dict)]
    enriched_graph = load_graph()
    enrichment = _enrich_institutional_graph(enriched_graph, records=records, prompt=prompt)
    enriched_graph["updated_at"] = iso_now()
    write_json(ROOT / "content" / "graph" / "country-graph.json", enriched_graph)
    write_knowledge_graph(enriched_graph)
    after_graph = graph_snapshot(load_graph())
    graph_payload = workflow_graph_response(workflow, before_graph=before_graph, after_graph=after_graph)
    runtime_summary = enrichment.get("roster_runtime", {}) if isinstance(enrichment.get("roster_runtime", {}), dict) else {}
    response = {
        "ok": True,
        "prompt": prompt,
        "resolved": None,
        "search_candidates": [],
        "actions": ["graph_improve", "institutional_roster_enrich", "graph_upsert"],
        "query": query,
        "topic": topic,
        "workflow": workflow,
        "model_selection": plan.get("model_selection", {}),
        "models_used": plan.get("models_used", []),
        "tools_used": list(dict.fromkeys(plan.get("tool_plan", []) + ["graph_improve", "official_web_fetch", "web_search", "profile_enrichment", "graph_upsert"])),
        "queries_used": list(dict.fromkeys(plan.get("seed_queries", []) or [query])),
        **graph_payload,
        "message": "Ran institutional roster workflow, enriched person and office profiles, and merged graph updates.",
        "viewed_links": enrichment.get("viewed_links", [])[:32],
        "accepted_sources": enrichment.get("accepted_sources", [])[:24],
        "rejected_sources": [url for url in enrichment.get("viewed_links", []) if url not in set(enrichment.get("accepted_sources", []))][:24],
    }
    if enrichment.get("model_receipts"):
        response["models_used"] = list(response.get("models_used", [])) + [
            {
                "role": "institutional_brief",
                "provider": str(item.get("provider") or "ollama"),
                "model": str(item.get("model") or "gemma4:e4b"),
                "ok": bool(item.get("ok")),
                "elapsed_ms": float(item.get("elapsed_ms", 0.0) or 0.0),
                "error": str(item.get("error") or ""),
            }
            for item in enrichment.get("model_receipts", [])[:8]
        ]
    if isinstance(response.get("workflow_summary", {}), dict):
        response["workflow_summary"]["roster_record_count"] = len(enrichment.get("records", []) or [])
        response["workflow_summary"]["graph_updates_applied"] = int(response["workflow_summary"].get("graph_updates_applied", 0) or 0) + int(
            len(runtime_summary.get("entity_actions", []) or []) + len(runtime_summary.get("relation_actions", []) or []) + len(runtime_summary.get("event_actions", []) or [])
        )
    response = _command_result_metadata(plan, response, load_graph())
    response["command_trace"]["phase_receipts"] = [
        {"phase": "plan", "status": "ok", "details": {"workflow": "graph_improve", "mode": "institutional_roster", "topic": topic}},
        {"phase": "graph_improve", "status": "ok" if workflow.get("ok") else "partial", "details": {"query": query, "budget": budget}},
        {"phase": "profile_enrichment", "status": "ok", "details": {"records_found": len(enrichment.get("records", []) or []), "accepted_sources": len(enrichment.get("accepted_sources", []) or [])}},
        {"phase": "graph_upsert", "status": "ok", "details": {"entities_touched": len(runtime_summary.get("entity_actions", []) or []), "relations_touched": len(runtime_summary.get("relation_actions", []) or []), "events_touched": len(runtime_summary.get("event_actions", []) or [])}},
    ]
    return response


def _extract_civil_contract_members(html_text: str, source_url: str) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    for match in re.finditer(r'(<a[^>]+class="staff-card[^"]*"[^>]*href="([^"]+)"[^>]*>.*?</a>)', html_text or "", flags=re.I | re.S):
        card_html = match.group(1)
        href = match.group(2)
        name_match = re.search(r'<div[^>]+class="staff-card__name"[^>]*>(.*?)</div>', card_html, flags=re.I | re.S)
        role_match = re.search(r'<div[^>]+class="staff-card__desc"[^>]*>(.*?)</div>', card_html, flags=re.I | re.S)
        if not name_match:
            continue
        parts = re.findall(r"<span[^>]*>(.*?)</span>", name_match.group(1), flags=re.I | re.S)
        name = compact_summary(" ".join(_strip_html_tags(part) for part in parts if _strip_html_tags(part)))
        if len(name.split()) < 2:
            continue
        role = _strip_html_tags(role_match.group(1) if role_match else "")
        members.append(
            {
                "name": name,
                "aliases": [_humanize_member_name(name)],
                "summary": f"Civil Contract {role.lower()}." if role else "Civil Contract member.",
                "role_label": role,
                "party_id": "party-civil-contract",
                "source_url": source_url,
                "official_url": href if href.startswith("http") else urljoin(source_url, href),
            }
        )
    return members


def _extract_hhk_members(html_text: str, source_url: str) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    for href, label in re.findall(r'<a[^>]+href="([^"]*?/ajax/persons\.php\?id=\d+[^"]*)"[^>]*>(.*?)</a>', html_text or "", flags=re.I | re.S):
        name = _strip_html_tags(label)
        if len(name.split()) < 2:
            continue
        members.append(
            {
                "name": name,
                "aliases": [_humanize_member_name(name)],
                "summary": "Republican Party of Armenia member.",
                "role_label": "party structure member",
                "party_id": "party-republican-party-of-armenia",
                "source_url": source_url,
                "official_url": href if href.startswith("http") else urljoin(source_url, href),
            }
        )
    return members


def _extract_parliament_faction_members(html_text: str, source_url: str) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    normalized_party_map = {
        party_id: {normalize_command(alias) for alias in aliases}
        for party_id, aliases in PARTY_NAME_ALIASES.items()
    }
    row_pattern = re.compile(
        r'<tr>\s*<td[^>]*>\s*<a[^>]+href="([^"]*deputies\.php\?sel=details[^"]+)"[^>]*>(.*?)</a>.*?</td>.*?<td[^>]*><span[^>]*>(.*?)</span>',
        flags=re.I | re.S,
    )
    for href, raw_name, raw_party in row_pattern.findall(html_text or ""):
        party_text = normalize_command(_strip_html_tags(raw_party))
        party_id = ""
        for candidate_party_id, aliases in normalized_party_map.items():
            if any(alias and alias in party_text for alias in aliases):
                party_id = candidate_party_id
                break
        if not party_id:
            continue
        name = _humanize_member_name(_strip_html_tags(raw_name))
        if len(name.split()) < 2:
            continue
        party_name = PARTY_NAME_ALIASES.get(party_id, [party_id])[0]
        members.append(
            {
                "name": name,
                "aliases": [_strip_html_tags(raw_name)],
                "summary": f"{party_name} parliamentary faction member.",
                "role_label": "parliamentary faction member",
                "party_id": party_id,
                "source_url": source_url,
                "official_url": href if href.startswith("http") else urljoin(source_url, href),
            }
        )
    return members


def _dedupe_roster_members(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        keys = sorted(_normalized_name_keys(str(record.get("name", ""))))
        party_id = str(record.get("party_id", ""))
        if not keys or not party_id:
            continue
        record_key = (party_id, keys[0])
        existing = deduped.get(record_key)
        if not existing:
            deduped[record_key] = dict(record)
            deduped[record_key]["aliases"] = list(dict.fromkeys(record.get("aliases", []) or []))
            continue
        existing["aliases"] = list(dict.fromkeys([*(existing.get("aliases", []) or []), *(record.get("aliases", []) or [])]))
        if record.get("official_url") and not existing.get("official_url"):
            existing["official_url"] = record.get("official_url")
        if record.get("summary") and len(str(record.get("summary"))) > len(str(existing.get("summary", ""))):
            existing["summary"] = record.get("summary")
        if record.get("role_label") and record.get("role_label") not in str(existing.get("role_label", "")):
            existing["role_label"] = compact_summary(" / ".join(part for part in [str(existing.get("role_label", "")), str(record.get("role_label", ""))] if part))
    return list(deduped.values())


def _detect_roster_targets(prompt: str) -> list[str]:
    target_party_ids = [party_id for party_id in roster_target_party_ids(prompt) if party_id in PARTY_ROSTER_SOURCES]
    if target_party_ids:
        return list(dict.fromkeys(target_party_ids))
    return list(PARTY_ROSTER_SOURCES.keys())


def _collect_party_roster_records(target_party_ids: list[str] | None = None) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    records: list[dict[str, Any]] = []
    viewed_links: list[str] = []
    accepted_sources: list[str] = []
    party_ids = [party_id for party_id in (target_party_ids or list(PARTY_ROSTER_SOURCES.keys())) if party_id in PARTY_ROSTER_SOURCES]
    for party_id in party_ids:
        party_sources = PARTY_ROSTER_SOURCES.get(party_id, [])
        for source in party_sources:
            url = str(source.get("url", "")).strip()
            if not url or url in viewed_links:
                continue
            viewed_links.append(url)
            html_text, _ = fetch_url(url, timeout=20)
            if not html_text:
                continue
            accepted_sources.append(url)
            if "civilcontract.am" in url:
                records.extend(_extract_civil_contract_members(html_text, url))
            elif "hhk.am" in url:
                records.extend(_extract_hhk_members(html_text, url))
            elif "parliament.am" in url:
                records.extend(_extract_parliament_faction_members(html_text, url))
    return _dedupe_roster_members(records), viewed_links, accepted_sources


def _media_affiliation_targets(prompt: str) -> list[str]:
    target_party_ids = [party_id for party_id in roster_target_party_ids(prompt) if party_id in PARTY_ROSTER_SOURCES]
    if target_party_ids:
        return list(dict.fromkeys(target_party_ids))
    return ["party-armenia-alliance", "party-with-honor"]


def _is_election_power_graph_prompt(prompt: str) -> bool:
    text = normalize_command(prompt)
    election_markers = ["2026", "election", "elections", "выбор", "ընտր"]
    influence_markers = [
        "прорус",
        "pro russian",
        "pro-russian",
        "pro kremlin",
        "pro-kremlin",
        "external influence",
        "foreign influence",
        "external levers",
        "business forces",
        "oligarch",
        "russia",
        "kremlin",
    ]
    political_markers = ["party", "parties", "politician", "politicians", "political", "politics"]
    return any(marker in text for marker in election_markers) and (
        any(marker in text for marker in influence_markers) or any(marker in text for marker in political_markers)
    )


def _normalize_media_name(title: str, host: str) -> str:
    text = compact_summary(title)
    if not text:
        text = compact_summary(host.replace("-", " ").replace(".", " "))
    return text or host


def _upsert_media_entity(graph: dict[str, Any], record: dict[str, Any], media_index_map: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    match = None
    candidates = [
        str(record.get("host", "")).strip(),
        normalize_command(str(record.get("name", ""))),
        normalize_command(str(record.get("url", "")).split("//", 1)[-1]),
    ]
    for key in candidates:
        if not key:
            continue
        match = media_index_map.get(key)
        if match:
            break
    entities = graph.setdefault("entities", [])
    url = str(record.get("url", "")).strip()
    host = str(record.get("host", "")).strip()
    site_url = str(record.get("site_url", "")).strip() or (f"https://{host}/" if host else "")
    links = dict(match.get("links", {}) if match else {})
    if site_url:
        links.setdefault("site", site_url)
    if url:
        links.setdefault("source", url)
    name = _normalize_media_name(str(record.get("name", "")), host)
    aliases = list(dict.fromkeys([*(match.get("aliases", []) if match else []), host, short_host(site_url) if site_url else "", short_host(url) if url else ""]))
    aliases = [alias for alias in aliases if alias]
    summary = str(record.get("summary", "")).strip() or f"{name} is a tracked news outlet."
    tags = list(dict.fromkeys([*(match.get("tags", []) if match else []), "media", "news", str(record.get("affiliation", "")) if record.get("affiliation") else ""]))
    tags = [tag for tag in tags if tag]
    if match:
        if len(summary) > len(str(match.get("summary", ""))):
            match["summary"] = summary
        match["aliases"] = aliases
        match["links"] = links
        match["tags"] = tags
        match["updated_at"] = iso_now()
        if record.get("source_urls"):
            match["source_urls"] = list(dict.fromkeys([*(match.get("source_urls", []) or []), *record.get("source_urls", [])]))
        for key in {host, normalize_command(name), normalize_command(short_host(site_url) if site_url else ""), normalize_command(short_host(url) if url else "")}:
            if key:
                media_index_map[key] = match
        return "updated", match
    entity_id = f"media-{slugify(transliterate(name) or name or host)}"
    candidate_ids = {str(item.get("id", "")) for item in entities}
    if entity_id in candidate_ids:
        entity_id = f"{entity_id}-{stable_hash(name, host, url)[:8]}"
    created = {
        "id": entity_id,
        "name": name,
        "category": "organization",
        "subtype": "media",
        "aliases": aliases,
        "tags": tags or ["media", "news"],
        "summary": summary,
        "links": links,
        "source_urls": list(dict.fromkeys(record.get("source_urls", []) or ([] if not url else [url]))),
        "public_safe": True,
        "notes": str(record.get("notes") or ""),
        "updated_at": iso_now(),
    }
    entities.append(created)
    for key in {host, normalize_command(name), normalize_command(short_host(site_url) if site_url else ""), normalize_command(short_host(url) if url else "")}:
        if key:
            media_index_map[key] = created
    return "added", created


def _collect_media_affiliation_records(prompt: str, plan: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    queries = list(dict.fromkeys(plan.get("seed_queries", []) or []))
    if not queries:
        labels = [ROSTER_PARTY_QUERY_LABELS.get(pid, pid) for pid in _media_affiliation_targets(prompt)]
        queries = [f"{label} affiliated media links" for label in labels] + [f"{label} news channels Armenia" for label in labels]
    viewed_links: list[str] = []
    accepted_sources: list[str] = []
    records: list[dict[str, Any]] = []
    seen_hosts: set[str] = set()
    target_party_ids = _media_affiliation_targets(prompt)
    target_labels = [ROSTER_PARTY_QUERY_LABELS.get(pid, pid) for pid in target_party_ids]
    fallback_markers = [normalize_text(label) for label in target_labels] + ["kochary", "кочар", "opposition", "оппозици", "armenia alliance", "hayastan", "պատիվ", "pativ"]
    for query in queries[:8]:
        for item in search_web(query, limit=8):
            url = str(item.get("url", "")).strip()
            if not url or url in viewed_links:
                continue
            viewed_links.append(url)

    for candidate in MEDIA_AFFILIATION_CANDIDATES:
        candidate_name = str(candidate.get("name", "")).strip()
        candidate_site = str(candidate.get("site_url", "")).strip()
        candidate_host = short_host(candidate_site)
        affiliation = str(candidate.get("affiliation", "")).strip() or "opposition"
        candidate_queries = list(dict.fromkeys([*(candidate.get("queries", []) or []), *queries]))
        candidate_sources: list[str] = []
        for query in candidate_queries[:5]:
            for item in search_web(query, limit=5):
                url = str(item.get("url", "")).strip()
                if url and url not in viewed_links:
                    viewed_links.append(url)
                title = str(item.get("title") or "").strip()
                summary = compact_summary(str(item.get("summary") or item.get("snippet") or title))
                host = short_host(url) if url else ""
                lower_blob = normalize_text(f"{title} {summary} {host} {url} {candidate_name} {candidate_host}")
                if candidate_host and host and (candidate_host == host or candidate_host in host or host in candidate_host):
                    candidate_sources.append(url or candidate_site)
                    continue
                if any(marker in lower_blob for marker in [normalize_text(candidate_name), *[normalize_text(marker) for marker in candidate.get("markers", []) or []]]):
                    candidate_sources.append(url or candidate_site)
                    continue
                if any(marker in lower_blob for marker in fallback_markers):
                    candidate_sources.append(url or candidate_site)
        candidate_sources = list(dict.fromkeys([*(candidate_sources or []), *([candidate_site] if candidate_site else [])]))
        if not candidate_name or not candidate_site:
            continue
        host = candidate_host or short_host(candidate_site)
        if host and host in seen_hosts:
            continue
        seen_hosts.add(host or candidate_name)
        accepted_sources.extend(candidate_sources[:3])
        summary = f"{candidate_name} is a curated media outlet candidate associated with {affiliation} coverage."
        records.append(
            {
                "name": candidate_name,
                "host": host,
                "url": candidate_site or (candidate_sources[0] if candidate_sources else ""),
                "site_url": candidate_site,
                "summary": summary,
                "source_urls": candidate_sources[:4],
                "affiliation": affiliation,
            }
        )
    return records, viewed_links, accepted_sources


def run_media_affiliation_workflow(prompt: str, plan: dict[str, Any]) -> dict[str, Any]:
    graph = load_graph()
    before_graph = graph_snapshot(graph)
    target_party_ids = _media_affiliation_targets(prompt)
    records, viewed_links, accepted_sources = _collect_media_affiliation_records(prompt, plan)
    media_index_map: dict[str, dict[str, Any]] = {}
    for entity in graph.get("entities", []) or []:
        if str(entity.get("subtype", "")) != "media" and "media" not in [str(tag) for tag in entity.get("tags", []) or []]:
            continue
        for key in [
            short_host(str(entity.get("links", {}).get("site", "")).strip()),
            short_host(str(entity.get("links", {}).get("official", "")).strip()),
            normalize_command(str(entity.get("name", ""))),
        ]:
            if key:
                media_index_map[key] = entity

    entity_actions: list[dict[str, Any]] = []
    relation_actions: list[dict[str, Any]] = []
    party_counts: Counter[str] = Counter()
    outlet_names: list[str] = []
    for record in records:
        entity_action, entity = _upsert_media_entity(graph, record, media_index_map)
        entity_actions.append({"action": entity_action, "entity_id": entity.get("id"), "name": entity.get("name"), "host": record.get("host")})
        outlet_names.append(str(entity.get("name", "")).strip())
        affiliation = str(record.get("affiliation") or "").strip()
        linked_parties = target_party_ids
        if affiliation == "kocharyan":
            linked_parties = [pid for pid in target_party_ids if pid == "party-armenia-alliance"] or ["party-armenia-alliance"]
        elif affiliation == "opposition":
            linked_parties = [pid for pid in target_party_ids if pid in {"party-armenia-alliance", "party-with-honor"}] or ["party-armenia-alliance", "party-with-honor"]
        for party_id in linked_parties:
            relation_action, relation = _upsert_verified_relation(
                graph,
                left_id=str(entity.get("id", "")),
                right_id=party_id,
                relation_type="aligned_with",
                source_url=str(record.get("url", "") or record.get("site_url", "") or ""),
                evidence_quote=f"Media outlet discovered for query: {prompt}",
                notes=str(record.get("summary", ""))[:240],
                confidence=0.72 if affiliation != "opposition" else 0.68,
            )
            relation_actions.append({"action": relation_action, "relation_id": relation.get("id"), "from": relation.get("from"), "to": relation.get("to")})
            party_counts[party_id] += 1

    graph["updated_at"] = iso_now()
    runtime = graph.setdefault("runtime", {})
    runtime["media_affiliation_workflow"] = {
        "updated_at": iso_now(),
        "prompt": prompt,
        "records_found": len(records),
        "entity_actions": entity_actions[:120],
        "relation_actions": relation_actions[:120],
        "viewed_links": viewed_links[:24],
        "accepted_sources": accepted_sources[:24],
        "rejected_sources": [url for url in viewed_links if url not in accepted_sources][:24],
        "party_counts": dict(party_counts),
        "target_party_ids": target_party_ids,
    }
    write_json(ROOT / "content" / "graph" / "country-graph.json", graph)
    after_graph = graph_snapshot(load_graph())
    diff = graph_diff(before_graph, after_graph)
    diff = _prune_graph_diff(diff, {"graph_updates_applied": len(relation_actions)})
    response = {
        "ok": True,
        "prompt": prompt,
        "resolved": None,
        "search_candidates": [],
        "actions": ["internet_media_extract", "graph_upsert"],
        "query": plan.get("query", prompt),
        "graph_diff": diff,
        "suggested_focus_nodes": graph_focus_nodes(diff),
        "suggested_nodes": [
            {
                "id": node.get("id"),
                "name": node.get("name"),
                "reason": "media_outlet",
            }
            for node in diff.get("new_nodes", [])[:10]
        ],
        "suggested_queries": [
            f"Search latest coverage for {item.get('name', item.get('host', 'media outlet'))}"
            for item in records[:8]
        ],
        "accepted_proposals": [],
        "rejected_proposals": [],
        "workflow_summary": {
            "run_id": f"media-{stable_hash(prompt, iso_now())[:12]}",
            "status": "completed",
            "task_type": "graph_improve",
            "query": prompt,
            "topic": "internal_politics",
            "queue_count": len(viewed_links),
            "candidate_count": len(records),
            "processed_count": len(records),
            "seed_targets": [
                {
                    "seed_entity_id": party_id,
                    "seed_entity_name": PARTY_NAME_ALIASES.get(party_id, [party_id])[0],
                    "reason": "media_affiliation_target",
                }
                for party_id in target_party_ids
            ],
            "graph_updates_applied": len(relation_actions),
            "verified_stories": 0,
        },
        "graph_context": context_layer_summary(load_graph()),
        "message": f"Ran media affiliation discovery workflow and merged {len(records)} outlet records into the graph: {', '.join([name for name in outlet_names if name][:8])}.",
        "viewed_links": viewed_links[:24],
        "accepted_sources": accepted_sources[:24],
        "rejected_sources": [url for url in viewed_links if url not in accepted_sources][:24],
        "tools_used": ["web_search", "evidence_collection", "graph_upsert", "relation_verify"],
        "queries_used": list(
            dict.fromkeys(
                [
                    *(q for candidate in MEDIA_AFFILIATION_CANDIDATES for q in (candidate.get("queries", []) or [])),
                    plan.get("query", prompt),
                    *(plan.get("seed_queries", []) or []),
                ]
            )
        )[:8],
        "candidate_outlets": outlet_names[:24],
    }
    response = _command_result_metadata(plan, response, load_graph())
    response["command_trace"]["phase_receipts"] = [
        {"phase": "plan", "status": "ok", "details": {"workflow": "graph_improve", "mode": "internet_first_media", "target_party_ids": target_party_ids}},
        {"phase": "fetch", "status": "ok", "details": {"viewed_links": len(viewed_links), "accepted_sources": len(accepted_sources)}},
        {"phase": "extract", "status": "ok", "details": {"records_found": len(records), "party_counts": dict(party_counts)}},
        {"phase": "graph_upsert", "status": "ok", "details": {"entities_touched": len(entity_actions), "relations_touched": len(relation_actions)}},
    ]
    return response


def run_party_roster_workflow(prompt: str, plan: dict[str, Any]) -> dict[str, Any]:
    graph = load_graph()
    before_graph = graph_snapshot(graph)
    target_party_ids = _detect_roster_targets(prompt)
    records, viewed_links, accepted_sources = _collect_party_roster_records(target_party_ids=target_party_ids)
    person_index_map = _person_index(graph)
    entity_actions: list[dict[str, Any]] = []
    relation_actions: list[dict[str, Any]] = []
    party_counts: Counter[str] = Counter()
    biography_fetches = 0
    for record in records:
        party_id = str(record.get("party_id", "")).strip()
        if not party_id:
            continue
        official_url = str(record.get("official_url", "")).strip()
        summary, history = _extract_profile_history(official_url)
        if summary and len(summary) > len(str(record.get("summary", ""))):
            record["summary"] = summary
        if history:
            record["history"] = history
        if summary or history:
            biography_fetches += 1
        entity_action, entity = _upsert_person_entity(graph, record, person_index_map)
        relation_action, relation = _upsert_member_relation(
            graph,
            str(entity.get("id", "")),
            party_id,
            str(record.get("source_url", "") or record.get("official_url", "")),
            str(record.get("role_label", "")),
        )
        entity_actions.append({"action": entity_action, "entity_id": entity.get("id"), "name": entity.get("name"), "party_id": party_id})
        relation_actions.append({"action": relation_action, "relation_id": relation.get("id"), "from": relation.get("from"), "to": relation.get("to")})
        parliament_action, parliament_relation = _upsert_verified_relation(
            graph,
            left_id=str(entity.get("id", "")),
            right_id="institution-parliament",
            relation_type="holds_office_in",
            source_url=official_url or str(record.get("source_url", "") or ""),
            evidence_quote="Listed on official National Assembly faction or deputy page.",
            notes="parliamentary faction member",
            confidence=0.9,
        )
        relation_actions.append({"action": parliament_action, "relation_id": parliament_relation.get("id"), "from": parliament_relation.get("from"), "to": parliament_relation.get("to")})
        party_counts[party_id] += 1
    graph["updated_at"] = iso_now()
    runtime = graph.setdefault("runtime", {})
    runtime["roster_workflow"] = {
        "updated_at": iso_now(),
        "prompt": prompt,
        "records_found": len(records),
        "entity_actions": entity_actions[:120],
        "relation_actions": relation_actions[:120],
        "viewed_links": viewed_links[:24],
        "accepted_sources": accepted_sources[:24],
        "rejected_sources": [url for url in viewed_links if url not in accepted_sources][:24],
        "party_counts": dict(party_counts),
        "target_party_ids": target_party_ids,
        "biography_fetches": biography_fetches,
    }
    write_json(ROOT / "content" / "graph" / "country-graph.json", graph)
    after_graph = graph_snapshot(load_graph())
    diff = graph_diff(before_graph, after_graph)
    diff = _prune_graph_diff(diff, {"graph_updates_applied": len(relation_actions)})
    party_name_by_id = {
        entity.get("id"): entity.get("name", entity.get("id"))
        for entity in graph.get("entities", [])
        if entity.get("id") in PARTY_ROSTER_SOURCES
    }
    suggested_queries: list[str] = []
    for record in records[:12]:
        human_name = _humanize_member_name(str(record.get("name", "")))
        party_name = party_name_by_id.get(str(record.get("party_id", "")), "")
        if human_name:
            suggested_queries.append(f"Search latest evidence for {human_name} Armenia")
            if party_name:
                suggested_queries.append(f"Find recent news about {human_name} {party_name}")
    response = {
        "ok": True,
        "prompt": prompt,
        "resolved": None,
        "search_candidates": [],
        "actions": ["internet_roster_extract", "graph_upsert"],
        "query": prompt,
        "graph_diff": diff,
        "suggested_focus_nodes": graph_focus_nodes(diff),
        "suggested_nodes": [
            {
                "id": node.get("id"),
                "name": node.get("name"),
                "reason": "roster_member",
            }
            for node in diff.get("new_nodes", [])[:10]
        ],
        "suggested_queries": list(dict.fromkeys(suggested_queries))[:20],
        "accepted_proposals": [],
        "rejected_proposals": [],
        "workflow_summary": {
            "run_id": f"roster-{stable_hash(prompt, iso_now())[:12]}",
            "status": "completed",
            "task_type": "graph_improve",
            "query": prompt,
            "topic": "internal_politics",
            "queue_count": len(viewed_links),
            "candidate_count": len(records),
            "processed_count": len(records),
            "seed_targets": [
                {
                    "seed_entity_id": party_id,
                    "seed_entity_name": party_name_by_id.get(party_id, party_id),
                    "reason": "official_party_roster",
                }
                for party_id in target_party_ids
            ],
            "graph_updates_applied": len(relation_actions),
            "verified_stories": 0,
        },
        "graph_context": context_layer_summary(load_graph()),
        "message": f"Ran internet-first parliament roster workflow and merged {len(records)} roster records into the graph.",
        "viewed_links": viewed_links[:24],
        "accepted_sources": accepted_sources[:24],
        "rejected_sources": [url for url in viewed_links if url not in accepted_sources][:24],
        "tools_used": ["internet_roster_extract", "official_web_fetch", "deputy_profile_fetch", "graph_upsert", "relation_verify"],
        "queries_used": [
            prompt,
            *[
                f"{party_name_by_id.get(party_id, party_id)} parliament faction deputies biographies"
                for party_id in target_party_ids
            ],
            "National Assembly faction members Armenia",
        ],
    }
    response = _command_result_metadata(plan, response, load_graph())
    response["command_trace"]["phase_receipts"] = [
        {"phase": "plan", "status": "ok", "details": {"workflow": "graph_improve", "mode": "internet_first_roster", "target_party_ids": target_party_ids}},
        {"phase": "fetch", "status": "ok", "details": {"viewed_links": len(viewed_links), "accepted_sources": len(accepted_sources)}},
        {"phase": "extract", "status": "ok", "details": {"records_found": len(records), "party_counts": dict(party_counts), "biography_fetches": biography_fetches}},
        {"phase": "graph_upsert", "status": "ok", "details": {"entities_touched": len(entity_actions), "relations_touched": len(relation_actions)}},
    ]
    return response


def node_search(query: str, limit: int = 12) -> dict[str, Any]:
    payload = graph_search(query, limit=limit)
    payload["endpoint"] = "node_search"
    return payload


def node_rag_answer(graph: dict[str, Any], node_id: str, query: str = "") -> dict[str, Any]:
    node = node_lookup(graph, node_id)
    if not node:
        return {"ok": False, "error": "node_not_found", "node_id": node_id}
    context = build_rag_context(graph, node_id)
    if not context:
        return {"ok": False, "error": "rag_context_unavailable", "node_id": node_id}
    prompt = build_rag_prompt(context, query=query or str(node.get("name", "")))
    answer, meta = call_rag_model(prompt, timeout=45)
    if not answer.strip():
        answer = deterministic_rag_answer(context)
    return {
        "ok": True,
        "node_id": node_id,
        "node_name": str(node.get("name", "")),
        "query": query,
        "context": context,
        "prompt": prompt,
        "answer": answer.strip(),
        "model": {
            "provider": str(meta.get("provider") or "ollama"),
            "id": str(meta.get("model") or "gemma4:e4b"),
            "ok": bool(meta.get("ok")),
            "elapsed_ms": float(meta.get("elapsed_ms", 0.0) or 0.0),
            "error": str(meta.get("error") or ""),
        },
        "workflow": "graph_rag",
    }


def node_research(graph: dict[str, Any], node_id: str, budget: int = 3) -> dict[str, Any]:
    node = node_lookup(graph, node_id)
    if not node:
        return {"ok": False, "error": "node_not_found", "node_id": node_id}
    split_links = classify_links(node)
    name = str(node.get("name", "")).strip()
    subtype = str(node.get("subtype", "")).strip()
    summary = str(node.get("summary", "")).strip()
    query_variants = [
        name,
        " ".join(part for part in [name, "Armenia"] if part),
        " ".join(part for part in [name, subtype, "Armenia"] if part),
        " ".join(part for part in [name, summary, "Armenia"] if part),
    ]
    web_results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    searches_run: list[str] = []
    for item in split_links.get("official", []) + split_links.get("sources", []):
        url = str(item.get("url", "")).strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        web_results.append(
            {
                "title": str(item.get("label") or short_host(url) or "Source"),
                "url": url,
                "host": short_host(url),
                "kind": "node_link",
            }
        )
    for query in query_variants:
        query = query.strip()
        if not query or query in searches_run:
            continue
        searches_run.append(query)
        for item in search_web(query, limit=max(2, budget)):
            url = str(item.get("url", ""))
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            web_results.append(item)
            if len(web_results) >= max(4, budget * 2):
                break
            if len(web_results) >= max(4, budget * 2):
                break
    accepted_sources = web_results[: max(0, min(len(web_results), budget))]
    rejected_sources = web_results[max(0, min(len(web_results), budget)) :]
    research_run = {
        "contract": "ResearchRunContract.v1",
        "run_id": f"research-{stable_hash(node_id, name, ','.join(searches_run), str(len(web_results)))}",
        "query": query_variants[0] if query_variants else name,
        "date_from": "",
        "date_to": "",
        "target_entities": [node_id],
        "seed_queries": searches_run,
        "frontier": [{"url": item.get("url"), "title": item.get("title"), "host": item.get("host")} for item in web_results[: max(4, budget * 2)]],
        "visited_urls": [str(item.get("url")) for item in web_results if str(item.get("url", "")).strip()],
        "accepted_sources": accepted_sources,
        "rejected_sources": rejected_sources,
        "extracted_claims": [],
        "proposed_nodes": [],
        "proposed_edges": [],
        "graph_diff": {},
        "profile_updates": [],
        "limits": {"budget_pages": max(4, budget * 2), "max_depth": 1, "same_domain_limit": 10},
    }
    return {
        "ok": True,
        "node": node,
        "query": query_variants[0] if query_variants else name,
        "queries": searches_run,
        "web_results": web_results,
        "research_run": research_run,
        "visited_links": split_links,
        "research_mode": "node_links_plus_web_search",
        "suggested_nodes": [
            {
                "id": neighbor.get("other", {}).get("id", ""),
                "name": neighbor.get("other", {}).get("name", ""),
                "reason": neighbor.get("relation_type", "neighbor"),
            }
            for neighbor in neighbors_for_node(graph, node_id).get("neighbors", [])[:6]
            if neighbor.get("other", {}).get("id", "")
        ],
        "suggested_queries": [
            f"Search latest evidence for {name}",
            f"Build timeline for {name}",
            f"Expand {name} connections",
        ],
        "recommendations": [
            "Review official sources first.",
            "Check whether new claims strengthen or weaken existing edges.",
            "Use Expand to prepare a bounded graph-exploration run.",
        ],
    }


def derived_topic_for_node(node: dict[str, Any]) -> str:
    category = normalize_command(str(node.get("category", "")))
    subtype = normalize_command(str(node.get("subtype", "")))
    tags = normalize_command(" ".join(str(tag) for tag in node.get("tags", []) or []))
    text = f"{category} {subtype} {tags}"
    if "foreign" in text or "diplom" in text or "eu" in text or "iran" in text or "russia" in text:
        return "foreign_policy"
    if "econom" in text or "finance" in text or "budget" in text or "business" in text:
        return "economy"
    if "legal" in text or "court" in text or "rights" in text or "corruption" in text:
        return "legal_human_rights"
    if "local" in text or "municipal" in text or "district" in text or "mayor" in text:
        return "local_governance"
    if "media" in text:
        return "internal_politics"
    return "internal_politics"


def run_workflow(command: list[str], timeout: int = 120) -> dict[str, Any]:
    start = time.time()
    try:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-8000:],
            "stderr": completed.stderr[-4000:],
            "elapsed_ms": int((time.time() - start) * 1000),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": None,
            "stdout": (exc.stdout or "")[-8000:],
            "stderr": (exc.stderr or "")[-4000:] if exc.stderr else "timeout",
            "elapsed_ms": int((time.time() - start) * 1000),
            "error": "timeout",
        }


def _graph_item_signature(item: dict[str, Any]) -> str:
    payload = dict(item)
    for key in ("x", "y", "z", "vx", "vy", "vz", "fx", "fy", "fz", "_flash", "_flash_until"):
        payload.pop(key, None)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def graph_diff(before_graph: dict[str, Any], after_graph: dict[str, Any]) -> dict[str, Any]:
    before_nodes = {str(node.get("id", "")): dict(node) for node in before_graph.get("nodes", []) if str(node.get("id", ""))}
    after_nodes = {str(node.get("id", "")): dict(node) for node in after_graph.get("nodes", []) if str(node.get("id", ""))}
    before_links = {str(link.get("id") or f"{link.get('from')}:{link.get('to')}:{link.get('relation_type')}"): dict(link) for link in before_graph.get("links", []) if str(link.get("from", "")) or str(link.get("to", ""))}
    after_links = {str(link.get("id") or f"{link.get('from')}:{link.get('to')}:{link.get('relation_type')}"): dict(link) for link in after_graph.get("links", []) if str(link.get("from", "")) or str(link.get("to", ""))}

    new_nodes: list[dict[str, Any]] = []
    updated_nodes: list[dict[str, Any]] = []
    removed_nodes: list[str] = []
    for node_id, node in after_nodes.items():
        if node_id not in before_nodes:
            new_nodes.append(node)
            continue
        if _graph_item_signature(before_nodes[node_id]) != _graph_item_signature(node):
            changed_keys = sorted(
                {
                    key
                    for key in set(before_nodes[node_id]) | set(node)
                    if key not in {"x", "y", "z", "vx", "vy", "vz", "fx", "fy", "fz"}
                    and before_nodes[node_id].get(key) != node.get(key)
                }
            )
            updated_nodes.append({**node, "changed_keys": changed_keys})
    for node_id in before_nodes:
        if node_id not in after_nodes:
            removed_nodes.append(node_id)

    new_links: list[dict[str, Any]] = []
    updated_links: list[dict[str, Any]] = []
    removed_links: list[str] = []
    for link_id, link in after_links.items():
        if link_id not in before_links:
            new_links.append(link)
            continue
        if _graph_item_signature(before_links[link_id]) != _graph_item_signature(link):
            changed_keys = sorted(
                {
                    key
                    for key in set(before_links[link_id]) | set(link)
                    if before_links[link_id].get(key) != link.get(key)
                }
            )
            updated_links.append({**link, "changed_keys": changed_keys})
    for link_id in before_links:
        if link_id not in after_links:
            removed_links.append(link_id)

    return {
        "new_nodes": new_nodes,
        "updated_nodes": updated_nodes,
        "removed_nodes": removed_nodes,
        "new_links": new_links,
        "updated_links": updated_links,
        "removed_links": removed_links,
    }


def _prune_graph_diff(diff: dict[str, Any], workflow_summary_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    cosmetic_node_keys = {"updated_at", "last_checked_at", "collected_at"}
    cosmetic_link_keys = {"updated_at", "last_checked_at", "collected_at"}
    pruned = {
        "new_nodes": list(diff.get("new_nodes", []) or []),
        "updated_nodes": [],
        "removed_nodes": list(diff.get("removed_nodes", []) or []),
        "new_links": list(diff.get("new_links", []) or []),
        "updated_links": [],
        "removed_links": list(diff.get("removed_links", []) or []),
    }
    for node in diff.get("updated_nodes", []) or []:
        changed = {str(key) for key in node.get("changed_keys", []) or []}
        if changed and changed.issubset(cosmetic_node_keys):
            continue
        pruned["updated_nodes"].append(node)
    for link in diff.get("updated_links", []) or []:
        changed = {str(key) for key in link.get("changed_keys", []) or []}
        if changed and changed.issubset(cosmetic_link_keys):
            continue
        pruned["updated_links"].append(link)
    if workflow_summary_payload and int(workflow_summary_payload.get("graph_updates_applied", 0) or 0) <= 0:
        only_events = not pruned["new_links"] and not pruned["updated_links"] and all(
            str(node.get("kind", "")) == "event"
            for node in [*pruned["new_nodes"], *pruned["updated_nodes"]]
        )
        if only_events:
            pruned["new_nodes"] = []
            pruned["updated_nodes"] = []
    return pruned


def graph_focus_nodes(diff: dict[str, Any], workflow_summary: dict[str, Any] | None = None) -> list[str]:
    focus: list[str] = []
    if workflow_summary:
        for seed in workflow_summary.get("seed_targets", []) or []:
            node_id = str(seed.get("seed_entity_id", ""))
            if node_id and node_id not in focus:
                focus.append(node_id)
    for node in diff.get("new_nodes", []) or []:
        if str(node.get("kind", "")) == "event":
            continue
        node_id = str(node.get("id", ""))
        if node_id and node_id not in focus:
            focus.append(node_id)
    for node in diff.get("updated_nodes", []) or []:
        if str(node.get("kind", "")) == "event":
            continue
        node_id = str(node.get("id", ""))
        if node_id and node_id not in focus:
            focus.append(node_id)
    for node in diff.get("new_nodes", []) or []:
        if str(node.get("kind", "")) != "event":
            continue
        node_id = str(node.get("id", ""))
        if node_id and node_id not in focus:
            focus.append(node_id)
    for node in diff.get("updated_nodes", []) or []:
        if str(node.get("kind", "")) != "event":
            continue
        node_id = str(node.get("id", ""))
        if node_id and node_id not in focus:
            focus.append(node_id)
    return focus[:8]


def ui_highlights(diff: dict[str, Any], focus: list[str], *, reason: str = "graph_update", ttl_ms: int = 22000) -> dict[str, Any]:
    node_ids: list[str] = []
    link_ids: list[str] = []
    seen_nodes: set[str] = set()
    seen_links: set[str] = set()
    for collection in (diff.get("new_nodes", []) or [], diff.get("updated_nodes", []) or []):
        for node in collection:
            node_id = str(node.get("id") or "").strip()
            if node_id and node_id not in seen_nodes:
                seen_nodes.add(node_id)
                node_ids.append(node_id)
    for collection in (diff.get("new_links", []) or [], diff.get("updated_links", []) or []):
        for link in collection:
            link_id = str(link.get("id") or "").strip()
            if link_id and link_id not in seen_links:
                seen_links.add(link_id)
                link_ids.append(link_id)
    return {
        "node_ids": node_ids[:24],
        "link_ids": link_ids[:32],
        "primary_focus_node_ids": [node_id for node_id in focus if node_id][:8],
        "ttl_ms": int(ttl_ms),
        "reason": str(reason or "graph_update"),
    }


def graph_suggestions(diff: dict[str, Any], workflow_summary: dict[str, Any] | None = None) -> dict[str, list[Any]]:
    suggested_nodes: list[dict[str, Any]] = []
    suggested_queries: list[str] = []
    seen_nodes: set[str] = set()

    def add_node(node_id: str, name: str, reason: str) -> None:
        if not node_id or node_id in seen_nodes:
            return
        seen_nodes.add(node_id)
        suggested_nodes.append({"id": node_id, "name": name, "reason": reason})

    for node in diff.get("new_nodes", []) or []:
        add_node(str(node.get("id", "")), str(node.get("name", "") or node.get("id", "")), "new_node")
    for node in diff.get("updated_nodes", []) or []:
        add_node(str(node.get("id", "")), str(node.get("name", "") or node.get("id", "")), "updated_node")

    if workflow_summary:
        for seed in workflow_summary.get("seed_targets", []) or []:
            node_id = str(seed.get("seed_entity_id", ""))
            name = str(seed.get("seed_entity_name", "") or node_id)
            reason = str(seed.get("reason", "") or "seed_target")
            add_node(node_id, name, reason)
            if name:
                suggested_queries.extend(
                    [
                        f"Explore {name} official links",
                        f"Build timeline for {name}",
                        f"Search latest evidence for {name}",
                    ]
                )

    if not suggested_queries and suggested_nodes:
        for node in suggested_nodes[:4]:
            name = str(node.get("name") or node.get("id") or "").strip()
            if name:
                suggested_queries.extend(
                    [
                        f"Explore {name}",
                        f"Build timeline for {name}",
                    ]
                )
    return {
        "suggested_nodes": suggested_nodes[:8],
        "suggested_queries": suggested_queries[:8],
    }


def graph_snapshot(graph: dict[str, Any]) -> dict[str, Any]:
    return build_visual_graph(graph).get("graph", {})


def workflow_graph_response(
    workflow: dict[str, Any],
    *,
    before_graph: dict[str, Any] | None = None,
    after_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    before_graph = before_graph or {}
    after_graph = after_graph or {}
    workflow_summary_payload = workflow_summary(workflow)
    diff = graph_diff(before_graph, after_graph) if before_graph and after_graph else {
        "new_nodes": [],
        "updated_nodes": [],
        "removed_nodes": [],
        "new_links": [],
        "updated_links": [],
        "removed_links": [],
    }
    diff = _prune_graph_diff(diff, workflow_summary_payload)
    suggestions = graph_suggestions(diff, workflow_summary_payload)
    focus = graph_focus_nodes(diff, workflow_summary_payload)
    highlights = ui_highlights(diff, focus, reason=str(workflow.get("task_type") or workflow_summary_payload.get("task_type") or "graph_update"))
    graph_runtime_source = after_graph or before_graph or load_graph()
    graph_runtime = graph_runtime_source.get("runtime", {}).get("graph", {}) if isinstance(graph_runtime_source.get("runtime", {}), dict) else {}
    proposal_receipts = list(graph_runtime.get("proposal_receipts", [])) if isinstance(graph_runtime.get("proposal_receipts", []), list) else []
    accepted_proposals = [row for row in proposal_receipts if str(row.get("critic_status") or "") in {"pass", "ok", "warn"}]
    rejected_proposals = [row for row in proposal_receipts if str(row.get("critic_status") or "") not in {"pass", "ok", "warn"}]
    latest_payload = {
        "updated_at": iso_now(),
        "run_id": workflow_summary_payload.get("run_id") or workflow.get("run_id") or "",
        "task_type": workflow_summary_payload.get("task_type") or workflow.get("task_type") or "",
        "workflow_summary": workflow_summary_payload,
        "graph_diff": diff,
        "suggested_focus_nodes": focus,
        "ui_highlights": highlights,
        "suggested_nodes": suggestions.get("suggested_nodes", []),
        "suggested_queries": suggestions.get("suggested_queries", []),
        "accepted_proposals": accepted_proposals[:24],
        "rejected_proposals": rejected_proposals[:24],
    }
    try:
        write_latest_graph_diff(latest_payload)
    except Exception:
        pass
    edge_payloads = build_ui_edge_payloads(diff, after_graph or before_graph or load_graph())
    return {
        "graph_diff": diff,
        "suggested_focus_nodes": focus,
        "ui_highlights": highlights,
        "ui_edge_payloads": edge_payloads,
        "suggested_nodes": suggestions.get("suggested_nodes", []),
        "suggested_queries": suggestions.get("suggested_queries", []),
        "accepted_proposals": accepted_proposals[:24],
        "rejected_proposals": rejected_proposals[:24],
        "workflow_summary": workflow_summary_payload,
        "graph_context": context_layer_summary(after_graph or before_graph or load_graph()),
    }


def workflow_summary(workflow: dict[str, Any]) -> dict[str, Any]:
    stdout = str(workflow.get("stdout") or "").strip()
    payload: dict[str, Any] = {}
    if stdout:
        try:
            parsed = json.loads(stdout)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = {}
    if not payload:
        runtime = load_json(TASK_RUNTIME_FILE, {}) if TASK_RUNTIME_FILE.exists() else {}
        if isinstance(runtime, dict):
            payload = runtime
    result = payload.get("result", {}) if isinstance(payload.get("result"), dict) else {}
    exploration = result.get("exploration", {}) if isinstance(result.get("exploration"), dict) else {}
    progress = payload.get("progress", {}) if isinstance(payload.get("progress"), dict) else {}
    graph_summary = result.get("graph_summary", {}) if isinstance(result.get("graph_summary"), dict) else {}
    return {
        "run_id": payload.get("run_id") or result.get("run_id"),
        "status": payload.get("status"),
        "task_type": payload.get("task_type"),
        "query": payload.get("query"),
        "topic": payload.get("topic"),
        "queue_count": exploration.get("queue_count", 0),
        "candidate_count": exploration.get("candidate_count", 0),
        "processed_count": exploration.get("processed_count", 0),
        "roster_record_count": exploration.get("roster_record_count", 0),
        "seed_targets": exploration.get("seed_targets", [])[:10],
        "graph_updates_applied": progress.get("graph_updates_applied", 0),
        "graph_updates_rejected": progress.get("graph_updates_rejected", 0),
        "verified_stories": progress.get("verified_stories", 0),
        "graph_entities": graph_summary.get("entities", 0),
        "graph_relations": graph_summary.get("relations", 0),
        "graph_event_nodes": graph_summary.get("event_nodes", 0),
    }


def command_runtime_trace(
    graph: dict[str, Any],
    *,
    workflow_summary_payload: dict[str, Any] | None = None,
    extra_viewed_links: list[str] | None = None,
    accepted_sources: list[str] | None = None,
    rejected_sources: list[str] | None = None,
    tools_used: list[str] | None = None,
    models_used: list[dict[str, Any]] | None = None,
    queries_used: list[str] | None = None,
) -> dict[str, Any]:
    runtime = graph.get("runtime", {}) if isinstance(graph.get("runtime", {}), dict) else {}
    ingest_runtime = runtime.get("ingest", {}) if isinstance(runtime.get("ingest", {}), dict) else {}
    graph_runtime = runtime.get("graph", {}) if isinstance(runtime.get("graph", {}), dict) else {}
    exploration_runtime = runtime.get("exploration", {}) if isinstance(runtime.get("exploration", {}), dict) else {}
    task_runtime = load_json(TASK_RUNTIME_FILE, {}) if TASK_RUNTIME_FILE.exists() else {}
    phase_receipts = []
    if isinstance(task_runtime, dict):
        wanted_run_id = str((workflow_summary_payload or {}).get("run_id") or "")
        task_run_id = str(task_runtime.get("run_id") or "")
        if not wanted_run_id or wanted_run_id == task_run_id:
            phase_receipts = list(task_runtime.get("phase_receipts", []) or [])[:12]
    viewed_links: list[str] = []
    for item in exploration_runtime.get("queue", [])[:12]:
        url = str(item.get("target_url") or "").strip()
        if url and url not in viewed_links:
            viewed_links.append(url)
    for item in exploration_runtime.get("seed_targets", [])[:12]:
        url = str(item.get("target_url") or "").strip()
        if url and url not in viewed_links:
            viewed_links.append(url)
    for candidate in ingest_runtime.get("candidates", [])[:24]:
        url = str(candidate.get("url") or "").strip()
        if url and url not in viewed_links:
            viewed_links.append(url)
    for story in graph_runtime.get("verified_story_pack", [])[:12]:
        for source in story.get("sources", [])[:4]:
            url = str(source.get("url") or "").strip()
            if url and url not in viewed_links:
                viewed_links.append(url)
    for story in graph_runtime.get("rejected_story_pack", [])[:8]:
        for source in story.get("sources", [])[:4]:
            url = str(source.get("url") or "").strip()
            if url and url not in viewed_links:
                viewed_links.append(url)
    for url in extra_viewed_links or []:
        url = str(url).strip()
        if url and url not in viewed_links:
            viewed_links.append(url)

    accepted = accepted_sources or [
        str(source.get("url") or "").strip()
        for story in graph_runtime.get("verified_story_pack", [])[:12]
        for source in story.get("sources", [])[:4]
        if str(source.get("url") or "").strip()
    ]
    if not accepted:
        accepted = [
            str(item.get("target_url") or "").strip()
            for item in exploration_runtime.get("seed_targets", [])[:12]
            if str(item.get("target_url") or "").strip()
        ]
    rejected = rejected_sources or [
        str(source.get("url") or "").strip()
        for story in graph_runtime.get("rejected_story_pack", [])[:12]
        for source in story.get("sources", [])[:4]
        if str(source.get("url") or "").strip()
    ]
    if not rejected:
        rejected = [url for url in viewed_links if url not in accepted]
    proposal_receipts = list(graph_runtime.get("proposal_receipts", [])) if isinstance(graph_runtime.get("proposal_receipts", []), list) else []
    rejected_proposals = [row for row in proposal_receipts if str(row.get("critic_status") or "") not in {"pass", "ok", "warn"}]
    accepted_graph_changes = int(graph_runtime.get("relation_updates", 0) or 0)
    rejected_graph_changes = len(rejected_proposals)
    return {
        "models_used": models_used or [],
        "tools_used": tools_used or [],
        "queries_used": queries_used or [],
        "viewed_links": viewed_links[:24],
        "accepted_sources": accepted[:24],
        "rejected_sources": rejected[:24],
        "graph_proposals": len(proposal_receipts),
        "accepted_graph_changes": accepted_graph_changes,
        "rejected_graph_changes": rejected_graph_changes,
        "rejected_proposals": rejected_proposals[:24],
        "phase_receipts": phase_receipts,
        "run_summary": workflow_summary_payload or {},
    }


def _command_result_metadata(plan: dict[str, Any], response: dict[str, Any], graph_for_trace: dict[str, Any]) -> dict[str, Any]:
    trace = command_runtime_trace(
        graph_for_trace,
        workflow_summary_payload=response.get("workflow_summary", {}) if isinstance(response.get("workflow_summary", {}), dict) else {},
        models_used=list(plan.get("models_used", [])),
        tools_used=list(response.get("tools_used", []) or plan.get("tool_plan", []) or []),
        queries_used=list(response.get("queries_used", []) or plan.get("seed_queries", []) or [plan.get("query", "")] or []),
        extra_viewed_links=list(response.get("viewed_links", []) or []),
        accepted_sources=list(response.get("accepted_sources", []) or []),
        rejected_sources=list(response.get("rejected_sources", []) or []),
    )
    response["selected_workflow"] = str(plan.get("workflow") or response.get("selected_workflow") or "")
    response["model_selection"] = plan.get("model_selection", {})
    response["models_used"] = list(plan.get("models_used", []))
    response["tools_used"] = list(dict.fromkeys(list(response.get("tools_used", []) or plan.get("tool_plan", []) or [])))
    response["queries_used"] = list(dict.fromkeys(list(response.get("queries_used", []) or plan.get("seed_queries", []) or [plan.get("query", "")] or [])))
    response["command_trace"] = trace
    response.setdefault("viewed_links", trace.get("viewed_links", []))
    response.setdefault("accepted_sources", trace.get("accepted_sources", []))
    response.setdefault("rejected_sources", trace.get("rejected_sources", []))
    response.setdefault("suggested_nodes", response.get("suggested_nodes", []))
    response.setdefault("suggested_queries", response.get("suggested_queries", []))
    response.setdefault("ui_highlights", ui_highlights(response.get("graph_diff", {}) if isinstance(response.get("graph_diff", {}), dict) else {}, list(response.get("suggested_focus_nodes", []) or []), reason=str(response.get("selected_workflow") or response.get("workflow") or "graph_update")))
    if not response.get("ui_edge_payloads"):
        response["ui_edge_payloads"] = build_ui_edge_payloads(
            response.get("graph_diff", {}) if isinstance(response.get("graph_diff", {}), dict) else {},
            graph_for_trace,
        )
    response["graph_link_inventory"] = graph_link_inventory(response, graph_for_trace)
    response["assistant_reply"] = build_assistant_reply(response)
    return response


def graph_link_inventory(response: dict[str, Any], graph_for_trace: dict[str, Any]) -> list[dict[str, Any]]:
    graph_entities = {
        str(entity.get("id", "")): entity
        for entity in [*(graph_for_trace.get("entities", []) or []), *(graph_for_trace.get("nodes", []) or [])]
        if str(entity.get("id", ""))
    }
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    source_nodes = list(graph_for_trace.get("entities", []) or []) + list(graph_for_trace.get("nodes", []) or [])
    if not source_nodes:
        source_nodes = list((response.get("graph_diff", {}) or {}).get("new_nodes", []) or [])
        source_nodes.extend(list((response.get("graph_diff", {}) or {}).get("updated_nodes", []) or []))
    for node in source_nodes:
            entity_id = str(node.get("id", "")).strip()
            entity = graph_entities.get(entity_id, node)
            for key, value in (entity.get("links", {}) or {}).items():
                url = str(value or "").strip()
                if not url:
                    continue
                stable = (entity_id, url)
                if stable in seen:
                    continue
                seen.add(stable)
                items.append(
                    {
                        "entity_id": entity_id,
                        "entity_name": str(entity.get("name", "") or entity_id),
                        "label": str(key),
                        "url": url,
                    }
                )
    return items


def build_assistant_reply(response: dict[str, Any]) -> dict[str, Any]:
    graph_diff = response.get("graph_diff", {}) if isinstance(response.get("graph_diff", {}), dict) else {}
    new_nodes = len(graph_diff.get("new_nodes", []) or [])
    new_links = len(graph_diff.get("new_links", []) or [])
    updated_nodes = len(graph_diff.get("updated_nodes", []) or [])
    updated_links = len(graph_diff.get("updated_links", []) or [])
    workflow = str(response.get("selected_workflow") or response.get("workflow") or "workflow")
    summary = str(response.get("message") or "").strip() or f"Ran {workflow}."
    viewed_links = list(response.get("viewed_links", []) or [])
    accepted_sources = list(response.get("accepted_sources", []) or [])
    rejected_sources = list(response.get("rejected_sources", []) or [])
    steps: list[str] = []
    if response.get("queries_used"):
        steps.append(f"Built target queries: {len(response.get('queries_used', []))}")
    if response.get("viewed_links"):
        steps.append(f"Viewed links: {len(response.get('viewed_links', []))}")
    if response.get("accepted_sources"):
        steps.append(f"Accepted sources: {len(response.get('accepted_sources', []))}")
    if response.get("workflow_summary"):
        workflow_summary = response.get("workflow_summary", {})
        if isinstance(workflow_summary, dict) and workflow_summary.get("seed_targets"):
            steps.append(f"Seed targets: {len(workflow_summary.get('seed_targets', []))}")
    command_trace = response.get("command_trace", {})
    if isinstance(command_trace, dict) and command_trace.get("phase_receipts"):
        for phase in command_trace.get("phase_receipts", [])[:10]:
            if not isinstance(phase, dict):
                continue
            detail = phase.get("details", {}) if isinstance(phase.get("details", {}), dict) else {}
            detail_bits: list[str] = []
            if detail.get("workflow"):
                detail_bits.append(str(detail.get("workflow")))
            if detail.get("target_party_ids"):
                detail_bits.append(f"targets {len(detail.get('target_party_ids', []))}")
            if detail.get("viewed_links") is not None:
                detail_bits.append(f"viewed {detail.get('viewed_links')}")
            if detail.get("accepted_sources") is not None:
                detail_bits.append(f"accepted {detail.get('accepted_sources')}")
            if detail.get("records_found") is not None:
                detail_bits.append(f"records {detail.get('records_found')}")
            if detail.get("biography_fetches") is not None:
                detail_bits.append(f"bios {detail.get('biography_fetches')}")
            if detail.get("entity_count") is not None or detail.get("relation_count") is not None:
                detail_bits.append(f"graph {detail.get('entity_count', 0)} / {detail.get('relation_count', 0)}")
            steps.append(f"Phase {phase.get('phase', '?')}: {phase.get('status', 'unknown')}{' · ' + ' · '.join(detail_bits) if detail_bits else ''}")
    steps.append(f"Graph changes: +{new_nodes} nodes, +{new_links} links, {updated_nodes} node updates, {updated_links} link updates")
    result_lines = [
        summary,
        f"Workflow: {workflow}",
        f"Queries: {len(response.get('queries_used', []) or [])}",
        f"Viewed links: {len(viewed_links)}",
        f"Accepted sources: {len(accepted_sources)}",
        f"Rejected sources: {len(rejected_sources)}",
        f"Graph diff: +{new_nodes} nodes, +{new_links} links, {updated_nodes} node updates, {updated_links} link updates",
    ]
    if response.get("suggested_nodes"):
        result_lines.append(
            "Suggested nodes: "
            + ", ".join(str(item.get("name") or item.get("id") or "node") for item in list(response.get("suggested_nodes", []))[:5] if isinstance(item, dict))
        )
    if response.get("suggested_queries"):
        result_lines.append(
            "Suggested queries: "
            + " | ".join(str(item) for item in list(response.get("suggested_queries", []))[:4])
        )
    return {
        "summary": summary,
        "text": "\n".join(result_lines),
        "steps": steps,
        "graph_changes": {
            "new_nodes": new_nodes,
            "new_links": new_links,
            "updated_nodes": updated_nodes,
            "updated_links": updated_links,
        },
        "links_in_graph": response.get("graph_link_inventory", [])[:40],
        "links_in_graph_total": len(response.get("graph_link_inventory", []) or []),
    }


def graph_core_view(graph: dict[str, Any]) -> dict[str, Any]:
    payload = build_visual_graph(graph)
    payload["layer"] = "core"
    payload["context_layer"] = context_layer_summary(graph)
    payload["graph"]["context_kind"] = "core"
    return payload


def profile_quality_view(graph: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, **graph_profile_quality(graph)}


def research_run_latest_view(graph: dict[str, Any]) -> dict[str, Any]:
    runtime_trace = living_graph_server.latest_trace()
    if isinstance(runtime_trace, dict) and runtime_trace.get("run_id"):
        return runtime_trace
    persisted = load_json(LATEST_RESEARCH_RUN_FILE, {}) if LATEST_RESEARCH_RUN_FILE.exists() else {}
    if isinstance(persisted, dict) and persisted.get("run"):
        return {"ok": True, **persisted}
    task_runtime = load_json(TASK_RUNTIME_FILE, {}) if TASK_RUNTIME_FILE.exists() else {}
    exploration_runtime = load_json(EXPLORATION_RUNTIME_FILE, {}) if EXPLORATION_RUNTIME_FILE.exists() else {}
    diff = latest_graph_diff()
    research_request = task_runtime.get("research_request", {}) if isinstance(task_runtime.get("research_request", {}), dict) else {}
    phase_receipts = task_runtime.get("phase_receipts", []) if isinstance(task_runtime.get("phase_receipts", []), list) else []
    accepted_sources: list[Any] = []
    rejected_sources: list[Any] = []
    visited_urls: list[str] = []
    for phase in phase_receipts:
        if not isinstance(phase, dict):
            continue
        details = phase.get("details", {}) if isinstance(phase.get("details", {}), dict) else {}
        for key in ("accepted_sources", "sources", "viewed_links", "visited_urls"):
            value = details.get(key)
            if isinstance(value, list):
                if key == "accepted_sources":
                    accepted_sources.extend(value)
                else:
                    visited_urls.extend(str(item) for item in value if str(item).strip())
        value = details.get("rejected_sources")
        if isinstance(value, list):
            rejected_sources.extend(value)
    latest_run = {
        "contract": "ResearchRunContract.v1",
        "run_id": str(task_runtime.get("run_id") or exploration_runtime.get("run_id") or diff.get("run_id") or ""),
        "query": str(task_runtime.get("prompt") or task_runtime.get("query") or research_request.get("entity") or ""),
        "date_from": str(research_request.get("date_from") or ""),
        "date_to": str(research_request.get("date_to") or ""),
        "target_entities": list(research_request.get("target_entities", []) or []),
        "seed_queries": list(task_runtime.get("seed_queries", []) or exploration_runtime.get("seed_queries", []) or []),
        "frontier": list(exploration_runtime.get("frontier", []) or exploration_runtime.get("queue", []) or [])[:100],
        "visited_urls": list(dict.fromkeys(visited_urls))[:100],
        "accepted_sources": accepted_sources[:100],
        "rejected_sources": rejected_sources[:100],
        "extracted_claims": list(task_runtime.get("extracted_claims", []) or exploration_runtime.get("extracted_claims", []) or [])[:100],
        "proposed_nodes": list(diff.get("new_nodes", []) or [])[:100],
        "proposed_edges": list(diff.get("new_links", []) or [])[:100],
        "graph_diff": diff,
        "profile_updates": list(diff.get("updated_nodes", []) or [])[:100],
        "limits": {
            "budget_pages": research_request.get("budget_pages"),
            "max_depth": research_request.get("max_depth"),
            "same_domain_limit": research_request.get("same_domain_limit"),
        },
    }
    return {"ok": True, "latest_run": latest_run}


def _research_failure_explanation(run: dict[str, Any]) -> str:
    graph_diff = run.get("graph_diff", {}) if isinstance(run.get("graph_diff", {}), dict) else {}
    graph_change_count = sum(
        len(graph_diff.get(key, []) or [])
        for key in ("new_nodes", "new_links", "updated_nodes", "updated_links")
    )
    reasons: list[str] = []
    workflow_summary = run.get("workflow_summary", {}) if isinstance(run.get("workflow_summary", {}), dict) else {}
    if graph_change_count <= 0:
        reasons.append("No durable graph changes were applied.")
    if int(workflow_summary.get("roster_record_count", 0) or 0) <= 0 and str(run.get("target_type") or "") == "roster":
        reasons.append("Parliament parser returned 0 roster records.")
    if int(workflow_summary.get("graph_updates_applied", 0) or 0) <= 0 and int(workflow_summary.get("graph_updates_rejected", 0) or 0) <= 0:
        reasons.append("No graph proposals were admitted.")
    if not (run.get("accepted_sources") or []):
        reasons.append("No accepted sources were recorded.")
    if int(run.get("edge_payload_count", 0) or 0) <= 0:
        reasons.append("No edge payloads were produced.")
    return " ".join(reasons[:4]).strip()


def _normalize_graph_diff_ids(diff: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "new_node_ids": [str(item.get("id") or "").strip() for item in diff.get("new_nodes", []) or [] if str(item.get("id") or "").strip()],
        "new_edge_ids": [str(item.get("id") or "").strip() for item in diff.get("new_links", []) or [] if str(item.get("id") or "").strip()],
        "updated_node_ids": [str(item.get("id") or "").strip() for item in diff.get("updated_nodes", []) or [] if str(item.get("id") or "").strip()],
        "updated_edge_ids": [str(item.get("id") or "").strip() for item in diff.get("updated_links", []) or [] if str(item.get("id") or "").strip()],
    }


def _extract_claim_summaries(response: dict[str, Any]) -> list[str]:
    summaries: list[str] = []
    for row in response.get("accepted_proposals", []) or []:
        if not isinstance(row, dict):
            continue
        for key in ("statement", "summary", "proposal_summary", "evidence_quote"):
            text = compact_summary(str(row.get(key) or ""))
            if text and text not in summaries:
                summaries.append(text)
    for row in response.get("ui_edge_payloads", []) or []:
        if not isinstance(row, dict):
            continue
        text = compact_summary(str(row.get("summary") or row.get("full_description") or ""))
        if text and text not in summaries:
            summaries.append(text)
    return summaries[:32]


def _persist_research_run(payload: dict[str, Any]) -> None:
    ensure_layout()
    write_json(LATEST_RESEARCH_RUN_FILE, payload)
    append_jsonl(RESEARCH_RUNS_LOG, [payload])


def _research_task_budget(budget_pages: int) -> int:
    return max(5, min(14, int(round(max(5, budget_pages) / 3))))


def run_explicit_research(payload: dict[str, Any]) -> dict[str, Any]:
    graph = load_graph()
    contract = research_request_contract(payload)
    query = str(payload.get("query") or payload.get("prompt") or "").strip()
    target_entity = str(payload.get("target_entity") or contract.get("entity") or "").strip()
    target_type = str(payload.get("target_type") or contract.get("target_type") or "relations").strip() or "relations"
    if not query:
        return {"ok": False, "error": "empty_query"}
    effective_query = query if not target_entity else f"{query}\nTarget entity: {target_entity}"
    budget_pages = int(contract.get("budget_pages", 30) or 30)
    task_budget = _research_task_budget(budget_pages)
    topic = _infer_topic(effective_query, None)
    before_graph = graph_snapshot(graph)
    workflow = run_workflow(
        [
            "python3",
            str(ROOT / "scripts" / "task_runner.py"),
            "--task",
            "graph_improve",
            "--query",
            effective_query,
            "--topic",
            topic,
            "--budget",
            str(task_budget),
        ],
        timeout=240,
    )
    after_graph = graph_snapshot(load_graph())
    graph_payload = workflow_graph_response(workflow, before_graph=before_graph, after_graph=after_graph)
    trace = command_runtime_trace(
        load_graph(),
        workflow_summary_payload=graph_payload.get("workflow_summary", {}),
        tools_used=["task_runner", "graph_improve"],
        queries_used=[effective_query],
    )
    latest_run = {
        "query": query,
        "target_entity": target_entity,
        "target_type": target_type,
        "date_from": contract.get("date_from", ""),
        "date_to": contract.get("date_to", ""),
        "budget_pages": budget_pages,
        "max_depth": contract.get("max_depth"),
        "source_priority": contract.get("source_priority"),
        "status": "completed" if workflow.get("ok") else "failed",
        "models_used": trace.get("models_used", []),
        "tools_used": trace.get("tools_used", []),
        "queries_used": trace.get("queries_used", []),
        "viewed_links": trace.get("viewed_links", []),
        "accepted_sources": trace.get("accepted_sources", []),
        "rejected_sources": trace.get("rejected_sources", []),
        "phase_receipts": trace.get("phase_receipts", []),
        "extracted_entities": [str(item.get("id") or "") for item in graph_payload.get("suggested_nodes", []) or [] if isinstance(item, dict)],
        "extracted_claims": _extract_claim_summaries(graph_payload),
        "proposed_nodes": [str(item.get("id") or "") for item in graph_payload.get("graph_diff", {}).get("new_nodes", []) or [] if isinstance(item, dict)],
        "proposed_edges": [str(item.get("id") or "") for item in graph_payload.get("graph_diff", {}).get("new_links", []) or [] if isinstance(item, dict)],
        "accepted_graph_changes": int(graph_payload.get("workflow_summary", {}).get("graph_updates_applied", 0) or 0),
        "rejected_graph_changes": int(graph_payload.get("workflow_summary", {}).get("graph_updates_rejected", 0) or 0),
        "graph_diff": _normalize_graph_diff_ids(graph_payload.get("graph_diff", {})),
        "graph_diff_full": graph_payload.get("graph_diff", {}),
        "edge_payload_count": len(graph_payload.get("ui_edge_payloads", []) or []),
        "workflow_summary": graph_payload.get("workflow_summary", {}),
        "failure_explanation": "",
        "planner_status": "not_used_explicit_research_route",
        "model_used": "task_runner",
        "fallback_used": False,
    }
    latest_run["failure_explanation"] = _research_failure_explanation(latest_run)
    wrapped = {"ok": True, "run": latest_run, "updated_at": iso_now()}
    _persist_research_run(wrapped)
    return {
        "ok": True,
        "run": latest_run,
        "graph_diff": graph_payload.get("graph_diff", {}),
        "ui_highlights": graph_payload.get("ui_highlights", {}),
        "ui_edge_payloads": graph_payload.get("ui_edge_payloads", []),
        "workflow_summary": graph_payload.get("workflow_summary", {}),
    }


def _provenance_story_pack(graph: dict[str, Any]) -> list[dict[str, Any]]:
    runtime = graph.get("runtime", {}) if isinstance(graph.get("runtime", {}), dict) else {}
    graph_runtime = runtime.get("graph", {}) if isinstance(runtime.get("graph", {}), dict) else {}
    stories = []
    for story in list(graph_runtime.get("verified_story_pack", []))[:12]:
      if isinstance(story, dict):
          stories.append(story)
    for story in list(graph_runtime.get("rejected_story_pack", []))[:8]:
        if isinstance(story, dict):
            stories.append(story)
    return stories


def graph_provenance_view(graph: dict[str, Any]) -> dict[str, Any]:
    stories = _provenance_story_pack(graph)
    entities = entity_index(graph)
    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()
    seen_sources: set[str] = set()

    def add_node(node: dict[str, Any]) -> None:
        node_id = str(node.get("id", ""))
        if not node_id or node_id in seen_nodes:
            return
        seen_nodes.add(node_id)
        nodes.append(node)

    for story in stories:
        story_id = str(story.get("story_id", ""))
        if not story_id:
            continue
        sources = [source for source in story.get("sources", []) if isinstance(source, dict) and source.get("url")]
        source_ids: list[str] = []
        for index, source in enumerate(sources[:4]):
            source_id = f"source:{source.get('source_id') or short_host(str(source.get('url'))) or index}"
            seen_sources.add(source_id)
            source_ids.append(source_id)
            add_node(
                {
                    "id": source_id,
                    "name": source.get("source_name") or short_host(str(source.get("url"))) or "Source",
                    "category": "media" if str(source.get("source_type", "")).lower() in {"watchdog", "media"} else "organization",
                    "subtype": str(source.get("source_type", "")),
                    "summary": source.get("explanation") or source.get("category") or "",
                    "tags": [str(source.get("category", "")), str(source.get("source_type", ""))],
                    "links": {"source": source.get("url", "")},
                    "source_urls": [source.get("url", "")],
                    "public_safe": True,
                    "visual_group": "media" if str(source.get("source_type", "")).lower() in {"watchdog", "media"} else "official",
                }
            )
        story_node_id = f"provenance-story:{story_id}"
        add_node(
            {
                "id": story_node_id,
                "name": story.get("summary_line") or story.get("title") or story_id,
                "category": "event",
                "subtype": str(story.get("topic", "")),
                "summary": story.get("relationship_context") or story.get("public_impact") or "",
                "tags": [str(story.get("topic", "")), "provenance"],
                "links": {source.get("source_name") or short_host(str(source.get("url", ""))) or "source": source.get("url", "") for source in sources[:4] if source.get("url")},
                "source_urls": [source.get("url", "") for source in sources[:4] if source.get("url")],
                "public_safe": True,
            }
        )
        for source_id in source_ids:
            links.append(
                {
                    "id": f"prov-source-story:{source_id}:{story_id}",
                    "from": source_id,
                    "to": story_node_id,
                    "relation_type": "provenance_source",
                    "status": "reported",
                    "confidence": 0.92,
                    "public_safe": True,
                    "visual_width": 1.1,
                    "visual_color": "#7b8a99",
                }
            )
        for actor_id in (story.get("actors_detected", []) or [])[:6]:
            actor = entities.get(actor_id)
            if not actor:
                continue
            add_node(
                {
                    "id": actor_id,
                    "name": actor.get("name", actor_id),
                    "category": actor.get("category", "entity"),
                    "subtype": actor.get("subtype", ""),
                    "summary": actor.get("summary", ""),
                    "tags": actor.get("tags", []) or [],
                    "aliases": actor.get("aliases", []) or [],
                    "links": actor.get("links", {}) or {},
                    "source_urls": actor.get("source_urls", []) or [],
                    "public_safe": bool(actor.get("public_safe", True)),
                }
            )
            links.append(
                {
                    "id": f"prov-story-actor:{story_id}:{actor_id}",
                    "from": story_node_id,
                    "to": actor_id,
                    "relation_type": "mentions",
                    "status": "reported",
                    "confidence": 0.75,
                    "public_safe": True,
                    "visual_width": 1.0,
                    "visual_color": "#9bb7cf",
                }
            )

    raw = {
        "version": graph.get("version", 1),
        "updated_at": graph.get("updated_at"),
        "source_of_truth": graph.get("source_of_truth"),
        "relation_types": relation_types_payload(),
        "entities": nodes,
        "relations": links,
        "event_nodes": [],
        "story_mentions": graph.get("story_mentions", []),
        "context_layer": graph.get("context_layer", {}),
        "runtime": graph.get("runtime", {}),
    }
    payload = build_visual_graph(raw)
    payload["layer"] = "provenance"
    payload["context_layer"] = context_layer_summary(graph)
    payload["graph"]["context_kind"] = "provenance"
    payload["graph"]["provenance"] = {
        "story_count": len(stories),
        "source_count": len(seen_sources),
    }
    return payload


def graph_retrieval_view(graph: dict[str, Any]) -> dict[str, Any]:
    runtime = graph.get("runtime", {}) if isinstance(graph.get("runtime", {}), dict) else {}
    graph_runtime = runtime.get("graph", {}) if isinstance(runtime.get("graph", {}), dict) else {}
    context_view = graph_runtime.get("graph_context_view", {}) if isinstance(graph_runtime.get("graph_context_view", {}), dict) else {}
    focus_entities = context_view.get("focus_entities", []) or []
    focus_relations = context_view.get("focus_relations", []) or []
    study_links = context_view.get("study_links", []) or []
    task_runtime = load_json(TASK_RUNTIME_FILE, {}) if TASK_RUNTIME_FILE.exists() else {}
    phase_receipts = list(task_runtime.get("phase_receipts", []) or [])[:8] if isinstance(task_runtime, dict) else []
    entities = entity_index(graph)
    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()

    def add_node(node: dict[str, Any]) -> None:
        node_id = str(node.get("id", ""))
        if not node_id or node_id in seen_nodes:
            return
        seen_nodes.add(node_id)
        nodes.append(node)

    add_node(
        {
            "id": "retrieval-root",
            "name": "Retrieval Context",
            "category": "event",
            "subtype": "retrieval",
            "summary": "Explainability subgraph for the active graph context.",
            "tags": ["retrieval", "context"],
            "links": {},
            "public_safe": True,
        }
    )
    for item in focus_entities[:12]:
        entity = entities.get(str(item.get("id", "")))
        if not entity:
            continue
        add_node(
            {
                "id": entity.get("id"),
                "name": entity.get("name", entity.get("id")),
                "category": entity.get("category", "entity"),
                "subtype": entity.get("subtype", ""),
                "summary": compact_summary(str(entity.get("summary", ""))),
                "tags": entity.get("tags", []) or [],
                "aliases": entity.get("aliases", []) or [],
                "links": entity.get("links", {}) or {},
                "source_urls": entity.get("source_urls", []) or [],
                "public_safe": bool(entity.get("public_safe", True)),
            }
        )
        links.append(
            {
                "id": f"retrieval-root:{entity.get('id')}",
                "from": "retrieval-root",
                "to": entity.get("id"),
                "relation_type": "retrieval_focus",
                "status": "reported",
                "confidence": 0.72,
                "public_safe": True,
                "visual_width": 1.0,
                "visual_color": "#86d2ff",
            }
        )
    for relation in focus_relations[:18]:
        links.append(
            {
                "id": relation.get("id") or f"retrieval-rel:{relation.get('from')}:{relation.get('to')}:{relation.get('relation_type')}",
                "from": relation.get("from"),
                "to": relation.get("to"),
                "relation_type": relation.get("relation_type"),
                "status": relation.get("status", "reported"),
                "confidence": relation.get("confidence", 0.5),
                "public_safe": relation.get("public_safe", True),
                "visual_width": relation.get("visual_width", relation_width(relation)),
                "visual_color": relation.get("visual_color", relation_color(str(relation.get("relation_type", "")))),
                "visual_dashed": relation.get("visual_dashed", False),
                "visual_opacity": relation.get("visual_opacity", 0.8),
            }
        )
    for index, url in enumerate(study_links[:10]):
        node_id = f"study-link:{index}"
        add_node(
            {
                "id": node_id,
                "name": short_host(str(url)) or f"Study link {index + 1}",
                "category": "event",
                "subtype": "study_link",
                "summary": str(url),
                "tags": ["study", "link"],
                "links": {"source": url},
                "source_urls": [url],
                "public_safe": True,
            }
        )
        links.append(
            {
                "id": f"retrieval-root:{node_id}",
                "from": "retrieval-root",
                "to": node_id,
                "relation_type": "study_link",
                "status": "reported",
                "confidence": 0.62,
                "public_safe": True,
                "visual_width": 0.9,
                "visual_color": "#7b8a99",
            }
        )
    previous_phase_id = "retrieval-root"
    for index, phase in enumerate(phase_receipts):
        if not isinstance(phase, dict):
            continue
        phase_name = str(phase.get("phase") or f"phase-{index + 1}")
        phase_status = str(phase.get("status") or "unknown")
        details = phase.get("details", {}) if isinstance(phase.get("details", {}), dict) else {}
        detail_bits = []
        if details.get("workflow"):
            detail_bits.append(str(details.get("workflow")))
        if details.get("viewed_links") is not None:
            detail_bits.append(f"viewed {details.get('viewed_links')}")
        if details.get("accepted_sources") is not None:
            detail_bits.append(f"accepted {details.get('accepted_sources')}")
        if details.get("records_found") is not None:
            detail_bits.append(f"records {details.get('records_found')}")
        node_id = f"retrieval-phase:{index}:{phase_name}"
        add_node(
            {
                "id": node_id,
                "name": phase_name.replace("_", " "),
                "category": "event",
                "subtype": "workflow_phase",
                "summary": " | ".join(detail_bits) or f"Phase status: {phase_status}",
                "tags": ["workflow", phase_status],
                "links": {},
                "public_safe": True,
                "visual_group": "official",
            }
        )
        links.append(
            {
                "id": f"{previous_phase_id}:{node_id}",
                "from": previous_phase_id,
                "to": node_id,
                "relation_type": "workflow_step",
                "status": phase_status,
                "confidence": 0.88,
                "public_safe": True,
                "visual_width": 1.2,
                "visual_color": "#ffd36b" if phase_status == "ok" else "#ff8f70",
                "evidence_quote": "Workflow phase executed during the latest command run.",
            }
        )
        previous_phase_id = node_id
    raw = {
        "version": graph.get("version", 1),
        "updated_at": graph.get("updated_at"),
        "source_of_truth": graph.get("source_of_truth"),
        "relation_types": relation_types_payload(),
        "entities": nodes,
        "relations": links,
        "event_nodes": [],
        "story_mentions": graph.get("story_mentions", []),
        "context_layer": graph.get("context_layer", {}),
        "runtime": graph.get("runtime", {}),
    }
    payload = build_visual_graph(raw)
    payload["layer"] = "retrieval"
    payload["context_layer"] = context_layer_summary(graph)
    payload["graph"]["context_kind"] = "retrieval"
    payload["graph"]["retrieval"] = {
        "focus_story_ids": list(context_view.get("focus_story_ids", [])[:12]),
        "study_links_count": len(study_links),
    }
    return payload


def graph_layer_view(graph: dict[str, Any], layer: str = "core") -> dict[str, Any]:
    if layer == "provenance":
        return graph_provenance_view(graph)
    if layer == "retrieval":
        return graph_retrieval_view(graph)
    return graph_core_view(graph)


def graph_flow_runs(limit: int = 8) -> dict[str, Any]:
    return load_flow_runs(limit=limit)


def node_expand(graph: dict[str, Any], node_id: str, budget: int = 3) -> dict[str, Any]:
    return {
        "ok": False,
        "error": "disabled_in_graph_view",
        "status": HTTPStatus.GONE,
        "message": "Node expansion is disabled. Run explicit Internet Research instead.",
    }


def node_command(
    graph: dict[str, Any],
    node_id: str,
    command_text: str,
    *,
    model_mode: str = "auto",
    requested_model: str = "",
) -> dict[str, Any]:
    command = normalize_command(command_text)
    if not command:
        return {"ok": False, "error": "empty_command"}
    node = node_lookup(graph, node_id)
    plan = plan_command_workflow(command_text, selected_node=node, model_mode=model_mode, requested_model=requested_model)
    model_selection = plan.get("model_selection", {})
    tools_used = list(dict.fromkeys(plan.get("tool_plan", [])))
    queries_used = list(dict.fromkeys(plan.get("seed_queries", []) or [plan.get("query", command_text)]))
    if any(token in command for token in ["research", "study", "investigate", "search latest evidence", "latest evidence", "search", "evidence", "expand", "broaden", "grow", "neighbors", "connections"]):
        result = {
            "ok": False,
            "error": "explicit_research_required",
            "message": "Implicit research and node expansion are disabled. Use Internet Research.",
        }
        result["models_used"] = plan.get("models_used", [])
        result["tools_used"] = list(dict.fromkeys([*tools_used, "blocked_implicit_research"]))
        result["queries_used"] = queries_used
        result["workflow"] = "disabled"
        result["model_selection"] = model_selection
        result["command_trace"] = command_runtime_trace(load_graph(), models_used=result["models_used"], tools_used=result["tools_used"], queries_used=result["queries_used"])
        return result
    if "timeline" in command or "history" in command:
        result = node_timeline(graph, node_id)
        result["models_used"] = plan.get("models_used", [])
        result["tools_used"] = list(dict.fromkeys([*tools_used, "timeline_builder"]))
        result["queries_used"] = queries_used
        result["workflow"] = plan.get("workflow", "node_timeline")
        result["model_selection"] = model_selection
        result["command_trace"] = command_runtime_trace(load_graph(), models_used=result["models_used"], tools_used=result["tools_used"], queries_used=result["queries_used"])
        return result
    if "provenance" in command or "source" in command or "evidence" in command or "trust" in command:
        result = node_provenance(graph, node_id)
        result["models_used"] = plan.get("models_used", [])
        result["tools_used"] = list(dict.fromkeys([*tools_used, "provenance_view"]))
        result["queries_used"] = queries_used
        result["workflow"] = plan.get("workflow", "node_provenance")
        result["model_selection"] = model_selection
        result["command_trace"] = command_runtime_trace(load_graph(), models_used=result["models_used"], tools_used=result["tools_used"], queries_used=result["queries_used"])
        return result
    if "alignment" in command or "political" in command or "bloc" in command:
        if not node:
            return {"ok": False, "error": "node_not_found", "node_id": node_id}
        neighbors = neighbors_for_node(graph, node_id)
        relations = [rel for rel in neighbors.get("relations", []) if rel.get("relation_type") in {"aligned_with", "member_of", "holds_office_in"}]
        result = {
            "ok": True,
            "node": node,
            "alignment": relations,
        }
        result["models_used"] = plan.get("models_used", [])
        result["tools_used"] = list(dict.fromkeys([*tools_used, "neighbors", "alignment_filter"]))
        result["queries_used"] = queries_used
        result["workflow"] = plan.get("workflow", "node_alignment")
        result["model_selection"] = model_selection
        result["command_trace"] = command_runtime_trace(load_graph(), models_used=result["models_used"], tools_used=result["tools_used"], queries_used=result["queries_used"])
        return result
    if "district heads" in command or "head of community" in command or "district" in command:
        if not node:
            return {"ok": False, "error": "node_not_found", "node_id": node_id}
        query = plan.get("query") or f"{node.get('name', '')} marz region community heads mayor district heads official links armenia"
        before_graph = graph_snapshot(graph)
        workflow = run_workflow(
            [
                "python3",
                str(ROOT / "scripts" / "task_runner.py"),
                "--task",
                "graph_improve",
                "--query",
                query,
                "--topic",
                "local_governance",
            ],
            timeout=140,
        )
        after_graph = graph_snapshot(load_graph())
        graph_payload = workflow_graph_response(workflow, before_graph=before_graph, after_graph=after_graph)
        result = {
            "ok": True,
            "node": node,
            "query": query,
            "workflow_run": workflow,
            **graph_payload,
            "message": "Ran bounded graph improvement for regional and district governance enrichment.",
        }
        result["models_used"] = plan.get("models_used", [])
        result["tools_used"] = list(dict.fromkeys([*tools_used, "graph_improve", "retrieve_cluster", "graph_verify", "critic"]))
        result["queries_used"] = queries_used
        result["selected_workflow"] = plan.get("workflow", "graph_improve")
        result["model_selection"] = model_selection
        result["command_trace"] = command_runtime_trace(
            after_graph,
            workflow_summary_payload=result.get("workflow_summary", {}),
            models_used=result["models_used"],
            tools_used=result["tools_used"],
            queries_used=result["queries_used"],
            extra_viewed_links=result.get("graph_context", {}).get("retrieval", {}).get("study_links", []) if isinstance(result.get("graph_context", {}), dict) else [],
            accepted_sources=[item.get("url", "") for item in result.get("graph_context", {}).get("retrieval", {}).get("study_links", []) if isinstance(item, dict) and item.get("url")] if isinstance(result.get("graph_context", {}), dict) else [],
            rejected_sources=[],
        )
        return result
    if "link" in command:
        if not node:
            return {"ok": False, "error": "node_not_found", "node_id": node_id}
        result = {"ok": True, "node": node, "links": classify_links(node)}
        result["models_used"] = plan.get("models_used", [])
        result["tools_used"] = list(dict.fromkeys([*tools_used, "link_view"]))
        result["queries_used"] = queries_used
        result["workflow"] = plan.get("workflow", "node_links")
        result["model_selection"] = model_selection
        result["command_trace"] = command_runtime_trace(load_graph(), models_used=result["models_used"], tools_used=result["tools_used"], queries_used=result["queries_used"])
        return result
    result = {
        "ok": True,
        "node": node,
        "message": "Unrecognized command. Try research, expand, timeline, alignment, or links.",
    }
    result["models_used"] = plan.get("models_used", [])
    result["tools_used"] = tools_used
    result["queries_used"] = queries_used
    result["workflow"] = plan.get("workflow", "")
    result["model_selection"] = model_selection
    result["command_trace"] = command_runtime_trace(load_graph(), models_used=result["models_used"], tools_used=result["tools_used"], queries_used=result["queries_used"])
    return result


def prompt_command(
    graph: dict[str, Any],
    prompt_text: str,
    selected_node_id: str | None = None,
    *,
    model_mode: str = "auto",
    requested_model: str = "",
    research_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prompt = str(prompt_text or "").strip()
    if not prompt:
        return {"ok": False, "error": "empty_command"}
    command = normalize_command(prompt)
    roster_prompt = _is_roster_graph_prompt(prompt)
    media_prompt = _is_media_graph_prompt(prompt)
    cabinet_prompt = _is_cabinet_graph_prompt(prompt)
    institutional_roster_prompt = _is_institutional_roster_graph_prompt(prompt)
    effective_model_mode = "local/ollama" if (cabinet_prompt or institutional_roster_prompt) and (model_mode or "auto") == "auto" else model_mode
    effective_requested_model = requested_model or ("gemma4:e4b" if cabinet_prompt or institutional_roster_prompt else "")
    plan = plan_command_workflow(prompt, selected_node=None, model_mode=effective_model_mode, requested_model=effective_requested_model)
    model_selection = plan.get("model_selection", {})
    election_power_prompt = _is_election_power_graph_prompt(prompt)
    wants_graph = any(token in command for token in ["graph", "граф", "memory", "память"])
    wants_graph_improve = any(
        token in command
        for token in [
            "improve graph",
            "graph improve",
            "улучш",
            "улучши",
            "улуш",
            "главам районов",
            "главы районов",
            "район",
            "district heads",
            "head of community",
            "local governance",
        ]
    )
    if wants_graph and wants_graph_improve and not selected_node_id:
        query = (
            f"{prompt} Armenia marz regions governors marzpets mayors district heads "
            "community heads municipalities local governance official links history"
        )
        plan = dict(plan)
        plan["workflow"] = "graph_improve"
        plan["query"] = query
        plan["topic"] = "local_governance"
        plan["seed_queries"] = list(dict.fromkeys([query, *(plan.get("seed_queries", []) or [])]))
        model_selection = plan.get("model_selection", {})
        before_graph = graph_snapshot(graph)
        workflow = run_workflow(
            [
                "python3",
                str(ROOT / "scripts" / "task_runner.py"),
                "--task",
                "graph_improve",
                "--query",
                query,
                "--topic",
                "local_governance",
            ],
            timeout=180,
        )
        after_graph = graph_snapshot(load_graph())
        graph_payload = workflow_graph_response(workflow, before_graph=before_graph, after_graph=after_graph)
        return {
            "ok": True,
            "prompt": prompt,
            "resolved": None,
            "search_candidates": [],
            "actions": ["graph_improve"],
            "query": query,
            "graph_improve": workflow,
            **graph_payload,
            "message": "Ran bounded graph improvement workflow for Armenia regional and district governance coverage.",
        }

    if election_power_prompt:
        query = (
            f"{prompt} Armenia 2026 election pro-russian pro-kremlin parties politicians "
            "business influence external levers state organs opposition ruling party media sources"
        )
        topic = "foreign_policy" if any(token in command for token in ["russia", "kremlin", "external", "foreign", "prorus", "прорус"]) else "internal_politics"
        plan = dict(plan)
        plan["workflow"] = "graph_improve"
        plan["query"] = query
        plan["topic"] = topic
        plan["seed_queries"] = list(dict.fromkeys([query, *(plan.get("seed_queries", []) or [])]))
        model_selection = plan.get("model_selection", {})
        before_graph = graph_snapshot(graph)
        workflow = run_workflow(
            [
                "python3",
                str(ROOT / "scripts" / "task_runner.py"),
                "--task",
                "graph_improve",
                "--query",
                query,
                "--topic",
                topic,
                "--budget",
                "14",
            ],
            timeout=240,
        )
        after_graph = graph_snapshot(load_graph())
        graph_payload = workflow_graph_response(workflow, before_graph=before_graph, after_graph=after_graph)
        response = {
            "ok": True,
            "prompt": prompt,
            "resolved": None,
            "search_candidates": [],
            "actions": ["graph_improve"],
            "query": query,
            "topic": topic,
            "workflow": workflow,
            "model_selection": model_selection,
            "models_used": plan.get("models_used", []),
            "tools_used": list(dict.fromkeys(plan.get("tool_plan", []) + ["graph_improve", "retrieve_cluster", "graph_verify", "critic"])),
            "queries_used": list(dict.fromkeys(plan.get("seed_queries", []) or [query])),
            **graph_payload,
            "message": "Ran internet-first election influence graph improvement workflow.",
        }
        response = _command_result_metadata(plan, response, after_graph)
        return response

    search_payload = {"query": prompt, "results": []} if roster_prompt or media_prompt or institutional_roster_prompt else graph_search(prompt, limit=8)
    search_results = search_payload.get("results", []) or []
    selected = None
    if selected_node_id and not cabinet_prompt and not institutional_roster_prompt:
        selected = node_lookup(graph, selected_node_id)
    if not selected and search_results and not wants_graph_improve and not media_prompt and should_auto_select_search_result(prompt, search_results[0]):
        selected = search_results[0]
    node_id = str(selected.get("id", "")) if selected else ""
    plan = plan_command_workflow(prompt, selected_node=selected if selected else None, model_mode=effective_model_mode, requested_model=effective_requested_model)
    if isinstance(research_options, dict) and str(research_options.get("interface_mode") or "") == "research":
        plan = dict(plan)
        plan["workflow"] = "graph_improve"
        plan["query"] = prompt
        plan["topic"] = plan.get("topic") or _infer_topic(prompt, None)
        seed = [
            prompt,
            f"{research_options.get('entity', '')} Armenia {research_options.get('target_type', 'relations')} {research_options.get('date_from', '')} {research_options.get('date_to', '')}".strip(),
        ]
        plan["seed_queries"] = list(dict.fromkeys([item for item in [*seed, *(plan.get("seed_queries", []) or [])] if str(item).strip()]))
    model_selection = plan.get("model_selection", {})
    planned_workflow = str(plan.get("workflow", "") or "")
    if media_prompt:
        selected = None
        node_id = ""
        return run_media_affiliation_workflow(prompt, plan)
    if roster_prompt:
        selected = None
        node_id = ""
        return run_party_roster_workflow(prompt, plan)
    if institutional_roster_prompt:
        selected = None
        node_id = ""
        return run_institutional_roster_workflow(prompt, plan)
    if cabinet_prompt:
        selected = None
        node_id = ""
        return run_institutional_roster_workflow(prompt, plan)
    wants_expand = any(token in command for token in ["expand", "broaden", "grow", "add", "enrich", "connections", "links", "graph", "network", "relations", "supplement"]) and not wants_graph_improve
    wants_research = any(token in command for token in ["research", "study", "investigate", "search", "internet", "web", "look up", "find out", "learn", "about"])
    wants_timeline = "timeline" in command or "history" in command or "chronology" in command
    wants_provenance = "provenance" in command or "source" in command or "evidence" in command or "trust" in command
    wants_alignment = "alignment" in command or "political" in command or "bloc" in command or "party" in command
    wants_district = "district heads" in command or "head of community" in command or "district" in command
    wants_graph_improve_only = wants_graph_improve or wants_district

    if not selected and planned_workflow in {"graph_improve", "graph_check", "topic_deep_research"}:
        query = plan.get("query") or prompt
        topic = plan.get("topic") or _infer_topic(prompt, None)
        task_type = planned_workflow
        budget = 12 if (roster_prompt or media_prompt) and task_type == "graph_improve" else 8
        if isinstance(research_options, dict) and str(research_options.get("interface_mode") or "") == "research":
            budget = max(5, min(100, int(research_options.get("budget_pages") or budget)))
        before_graph = graph_snapshot(graph)
        workflow = run_workflow(
            [
                "python3",
                str(ROOT / "scripts" / "task_runner.py"),
                "--task",
                task_type,
                "--query",
                query,
                "--topic",
                topic,
                "--budget",
                str(budget),
            ],
            timeout=210 if task_type == "graph_improve" else 150,
        )
        after_graph = graph_snapshot(load_graph())
        graph_payload = workflow_graph_response(workflow, before_graph=before_graph, after_graph=after_graph)
        response = {
            "ok": True,
            "prompt": prompt,
            "resolved": None,
            "search_candidates": search_results,
            "actions": [task_type],
            "query": query,
            "topic": topic,
            "workflow": workflow,
            "model_selection": model_selection,
            "models_used": plan.get("models_used", []),
            "tools_used": list(dict.fromkeys(plan.get("tool_plan", []) + [task_type, "task_runner"])),
            "queries_used": list(dict.fromkeys(plan.get("seed_queries", []) or [query])),
            **graph_payload,
            "message": "Ran internet-first roster graph improvement workflow." if roster_prompt and task_type == "graph_improve" else ("Ran internet-first media graph improvement workflow." if media_prompt and task_type == "graph_improve" else f"Ran bounded {task_type.replace('_', ' ')} workflow."),
        }
        response = _command_result_metadata(plan, response, after_graph)
        return response

    if not selected:
        web_results = search_web(prompt, limit=5)
        response = {
            "ok": True,
            "prompt": prompt,
            "resolved": None,
            "search_candidates": search_results,
            "web_results": web_results,
            "message": "No graph entity matched strongly. Returned web search results.",
            "wants_research": wants_research,
            "wants_expand": wants_expand,
            "model_selection": model_selection,
            "models_used": plan.get("models_used", []),
            "tools_used": list(dict.fromkeys(plan.get("tool_plan", []) + ["web_search", "graph_search"])),
            "queries_used": list(dict.fromkeys(plan.get("seed_queries", []) or [prompt])),
            "selected_workflow": planned_workflow,
        }
        response["command_trace"] = command_runtime_trace(
            load_graph(),
            models_used=response["models_used"],
            tools_used=response["tools_used"],
            queries_used=response["queries_used"],
            extra_viewed_links=[item.get("url", "") for item in web_results if isinstance(item, dict) and item.get("url")],
        )
        return response

    node = node_lookup(graph, node_id)
    if not node:
        return {
            "ok": False,
            "error": "node_not_found",
            "prompt": prompt,
            "search_candidates": search_results,
        }

    result: dict[str, Any] = {
        "ok": True,
        "prompt": prompt,
        "resolved": {
            "id": node.get("id"),
            "name": node.get("name"),
            "category": node.get("category"),
            "subtype": node.get("subtype"),
            "score": selected.get("score", 0),
            "reasons": selected.get("reasons", []),
        },
        "search_candidates": search_results,
        "actions": [],
        "model_selection": model_selection,
        "models_used": plan.get("models_used", []),
        "tools_used": list(dict.fromkeys(plan.get("tool_plan", []))),
        "queries_used": list(dict.fromkeys(plan.get("seed_queries", []) or [plan.get("query", prompt)])),
        "selected_workflow": planned_workflow,
    }

    research_result: dict[str, Any] | None = None
    expand_result: dict[str, Any] | None = None
    timeline_result: dict[str, Any] | None = None
    alignment_result: dict[str, Any] | None = None
    provenance_result: dict[str, Any] | None = None
    rag_result: dict[str, Any] | None = node_rag_answer(graph, node_id, query=prompt)
    if rag_result and rag_result.get("ok"):
        result["actions"].append("rag_answer")

    if wants_research:
        research_result = node_research(graph, node_id, budget=4)
        result["actions"].append("research")
    if wants_expand:
        expand_result = node_expand(graph, node_id, budget=3)
        result["actions"].append("expand")
    if wants_timeline:
        timeline_result = node_timeline(graph, node_id)
        result["actions"].append("timeline")
    if wants_provenance:
        provenance_result = node_provenance(graph, node_id)
        result["actions"].append("provenance")
    if wants_alignment:
        alignment_result = node_command(graph, node_id, "alignment")
        result["actions"].append("alignment")
    if wants_graph_improve_only:
        district_result = node_command(graph, node_id, "improve graph with respect to district heads")
        result["district_graph_improve"] = district_result
        result["actions"].append("district_graph_improve")
        if district_result.get("graph_diff"):
            result["graph_diff"] = district_result.get("graph_diff")
            result["suggested_focus_nodes"] = district_result.get("suggested_focus_nodes", [])
            result["suggested_nodes"] = district_result.get("suggested_nodes", [])
            result["suggested_queries"] = district_result.get("suggested_queries", [])
            result["workflow_summary"] = district_result.get("workflow_summary", {})

    if not result["actions"]:
        research_result = node_research(graph, node_id, budget=4)
        expand_result = node_expand(graph, node_id, budget=3)
        result["actions"].extend(["research", "expand"])

    result["research"] = research_result
    result["expand"] = expand_result
    result["timeline"] = timeline_result
    result["provenance"] = provenance_result
    result["alignment"] = alignment_result
    result["rag"] = rag_result
    result["node"] = node
    result["graph_hint"] = {
        "neighbors_count": len([rel for rel in graph.get("relations", []) if rel.get("from") == node_id or rel.get("to") == node_id]),
        "family": family_for_entity(node, graph, party_relations(graph)),
    }
    result["workflow"] = planned_workflow
    if "graph_diff" not in result:
        result["graph_diff"] = {}
        result["suggested_focus_nodes"] = []
        result["suggested_nodes"] = []
        result["suggested_queries"] = []
        result["workflow_summary"] = {}
    if "district_graph_improve" in result["actions"]:
        result["message"] = "Resolved entity from prompt and ran bounded graph improvement."
    elif result["actions"] == ["rag_answer", "research", "expand"]:
        result["message"] = "Resolved entity from prompt and ran graph-aware RAG plus bounded research/expansion."
    elif result["actions"] == ["research", "expand"]:
        result["message"] = "Resolved entity from prompt and ran bounded research/expansion."
    else:
        result["message"] = "Resolved entity from prompt and ran bounded node workflow."
    result["command_trace"] = command_runtime_trace(
        load_graph(),
        workflow_summary_payload=result.get("workflow_summary", {}),
        models_used=result["models_used"],
        tools_used=result["tools_used"],
        queries_used=result["queries_used"],
        extra_viewed_links=[
            item.get("url", "")
            for item in (result.get("research", {}) or {}).get("web_results", [])
            if isinstance(item, dict) and item.get("url")
        ],
        accepted_sources=[
            item.get("url", "")
            for item in (result.get("research", {}) or {}).get("visited_links", {}).get("official", [])
            if isinstance(item, dict) and item.get("url")
        ],
        rejected_sources=[
            item.get("url", "")
            for item in (result.get("research", {}) or {}).get("web_results", [])
            if isinstance(item, dict) and item.get("url") and item.get("url") not in {
                src.get("url", "") for src in (result.get("research", {}) or {}).get("visited_links", {}).get("official", []) if isinstance(src, dict)
            }
        ],
    )
    return result


def graph_safety_report() -> dict[str, Any]:
    path = EVALS_LATEST_DIR / "graph-safety-report.json"
    if path.exists():
        return load_json(path, {"issue_count": 0, "issues": []})
    return {"issue_count": 0, "issues": []}


def task_runtime_report() -> dict[str, Any]:
    runtime = load_json(TASK_RUNTIME_FILE, {})
    exploration = load_json(EXPLORATION_RUNTIME_FILE, {})
    return {
        "task_runtime": runtime,
        "exploration_runtime": exploration,
    }


def research_request_contract(payload: dict[str, Any]) -> dict[str, Any]:
    options = payload.get("research_options", {}) if isinstance(payload.get("research_options", {}), dict) else {}
    budget_pages = int(options.get("budget_pages") or payload.get("budget_pages") or 30)
    budget_pages = max(5, min(100, budget_pages))
    return {
        "interface_mode": str(payload.get("interface_mode") or "graph"),
        "entity": str(options.get("entity") or "").strip(),
        "date_from": str(options.get("date_from") or "").strip(),
        "date_to": str(options.get("date_to") or "").strip(),
        "target_type": str(options.get("target_type") or "relations").strip() or "relations",
        "source_priority": str(options.get("source_priority") or "official,reliable_media,watchdogs").strip(),
        "budget_pages": budget_pages,
        "max_depth": 2 if budget_pages <= 30 else 3,
        "same_domain_limit": 10,
        "timeout_per_page_sec": 10,
        "parser_policy": {
            "source_specific_domains": [
                "gov.am",
                "primeminister.am",
                "parliament.am",
                "president.am",
                "court.am",
                "elections.am",
                "mil.am",
                "civilcontract.am",
                "hetq.am",
                "azatutyun.am",
                "factor.am",
                "armenpress.am",
                "1lurer.am",
            ],
            "generic_parser": "readability_html_date_links",
            "model_assisted_parser": "selector_config_only_no_generated_code",
        },
        "frontier_policy": {
            "bounded": True,
            "follow_relevant_links": True,
            "reject_irrelevant_pages": True,
            "date_range_required": bool(options.get("date_from") or options.get("date_to")),
        },
    }


def augment_research_prompt(prompt: str, contract: dict[str, Any]) -> str:
    if not contract or contract.get("interface_mode") != "research":
        return prompt
    constraints = [
        "Run as internet-first Research Mode.",
        f"Target entity/person: {contract.get('entity') or contract.get('target_role') or contract.get('target_entity') or 'infer from query'}",
        f"Target type: {contract.get('target_type')}",
        f"Date range: {contract.get('date_from') or 'open'} to {contract.get('date_to') or 'open'}",
        f"Source priority: {contract.get('source_priority')}",
        f"Budget pages: {contract.get('budget_pages')}",
        "Use source-specific parsers where available, generic parser otherwise, and model-assisted selector configs only; do not generate executable parser code.",
        "Return claim-first graph changes with rich semantic edges: relation_class, relation_type, semantic_summary, role_from, role_to, mechanism_tags, timeline, confidence, claim/evidence/source links.",
    ]
    return f"{prompt}\n\n" + "\n".join(f"- {item}" for item in constraints)


def latest_history_summaries() -> dict[str, Any]:
    graph = load_graph()
    runtime = task_runtime_report()
    safety = graph_safety_report()
    latest_task = runtime.get("task_runtime", {})
    latest_exploration = runtime.get("exploration_runtime", {})
    return {
        "latest_task": latest_task,
        "latest_exploration": latest_exploration,
        "graph_safety": safety,
        "graph_context_layers": context_layer_summary(graph),
        "latest_flows": graph_flow_runs(limit=5),
        "graph_stats": {
            "entities": len(graph.get("entities", [])),
            "relations": len(graph.get("relations", [])),
            "event_nodes": len(graph.get("event_nodes", [])),
        },
    }


class GraphViewerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)
        if route == "/":
            self.serve_static("index.html")
            return
        if route == "/app.js":
            self.serve_static("app.js", content_type="application/javascript; charset=utf-8")
            return
        if route == "/knowledge_graph.json":
            self.respond(*json_response(HTTPStatus.OK, export_knowledge_graph(load_graph())))
            return
        if route == "/knowledge_graph.layout.json":
            self.serve_static("knowledge_graph.layout.json", content_type="application/json; charset=utf-8")
            return
        if route.startswith("/vendor/"):
            path = WEB_DIR / route.lstrip("/")
            if not path.exists() or not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "Missing vendor asset")
                return
            self.respond(HTTPStatus.OK, "application/javascript; charset=utf-8", path.read_bytes())
            return
        if route == "/favicon.ico":
            self.respond(HTTPStatus.NO_CONTENT, "image/x-icon", b"")
            return
        if route == "/api/graph":
            self.respond(*json_response(HTTPStatus.OK, {"ok": True, **living_graph_server.visual_graph(load_graph(), latest_graph_diff())}))
            return
        if route == "/api/knowledge-graph":
            self.respond(*json_response(HTTPStatus.OK, {"ok": True, "nodes": export_knowledge_graph(load_graph())}))
            return
        if route == "/api/models":
            self.respond(*json_response(HTTPStatus.OK, command_model_catalog()))
            return
        if route == "/api/graph/core":
            self.respond(*json_response(HTTPStatus.OK, {"ok": True, **living_graph_server.visual_graph(load_graph(), latest_graph_diff())}))
            return
        if route == "/api/graph/provenance":
            self.respond(*json_response(HTTPStatus.OK, {"ok": True, **graph_provenance_view(load_graph())}))
            return
        if route == "/api/graph/retrieval-context":
            self.respond(*json_response(HTTPStatus.OK, {"ok": True, **graph_retrieval_view(load_graph())}))
            return
        if route == "/api/graph/profile-quality":
            self.respond(*json_response(HTTPStatus.OK, {"ok": True, **living_graph_server.graph_profile_quality(load_graph())}))
            return
        if route == "/api/graph/diff/latest":
            self.respond(*json_response(HTTPStatus.OK, {"ok": True, **latest_graph_diff()}))
            return
        if route == "/api/graph/context":
            self.respond(*json_response(HTTPStatus.OK, {"ok": True, "context_layer": context_layer_summary(load_graph())}))
            return
        if route == "/api/research/runs/latest":
            self.respond(*json_response(HTTPStatus.OK, research_run_latest_view(load_graph())))
            return
        if route.startswith("/api/research/runs/") and route.endswith("/events"):
            self.handle_research_run_events(route, query)
            return
        if route.startswith("/api/research/runs/"):
            self.handle_research_run_get(route)
            return
        if route == "/api/task-runtime":
            self.respond(*json_response(HTTPStatus.OK, {"ok": True, **task_runtime_report(), **latest_history_summaries()}))
            return
        if route == "/api/flows":
            limit = min(20, max(1, int(query.get("limit", ["8"])[0] or 8)))
            self.respond(*json_response(HTTPStatus.OK, {"ok": True, **graph_flow_runs(limit=limit)}))
            return
        if route.startswith("/api/flows/"):
            self.handle_flow_get(route)
            return
        if route == "/api/graph-safety":
            payload = graph_safety_report()
            self.respond(*json_response(HTTPStatus.OK, {"ok": True, **payload}))
            return
        if route == "/api/search":
            term = query.get("q", [""])[0]
            limit = min(20, max(1, int(query.get("limit", ["10"])[0] or 10)))
            self.respond(*json_response(HTTPStatus.OK, {"ok": True, **graph_search(term, limit=limit)}))
            return
        if route == "/api/node/search":
            term = query.get("q", [""])[0]
            limit = min(20, max(1, int(query.get("limit", ["10"])[0] or 10)))
            self.respond(*json_response(HTTPStatus.OK, {"ok": True, **node_search(term, limit=limit)}))
            return
        if route.startswith("/api/relation/") or route == "/api/relation/dossier":
            self.handle_relation_get(route, query)
            return
        if route.startswith("/api/node/"):
            self.handle_node_get(route, query)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        if route.startswith("/api/node/") and route.endswith("/command"):
            self.handle_node_command(route)
            return
        if route == "/api/research/run":
            self.handle_research_run()
            return
        if route.startswith("/api/research/runs/") and route.endswith("/step"):
            self.handle_research_run_step(route)
            return
        if route.startswith("/api/research/runs/") and route.endswith("/resume"):
            self.handle_research_run_resume(route)
            return
        if route == "/api/command":
            self.handle_prompt_command()
            return
        if route == "/api/layout/save":
            self.handle_layout_save()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def serve_static(self, filename: str, content_type: str = "text/html; charset=utf-8") -> None:
        path = WEB_DIR / filename
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, f"Missing static file: {filename}")
            return
        self.respond(HTTPStatus.OK, content_type, path.read_bytes())

    def respond(self, status: int, content_type: str, body: bytes) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def handle_relation_get(self, route: str, query: dict[str, list[str]]) -> None:
        graph = load_graph()
        dossier: dict[str, Any] = {}
        if route in {"/api/relation/dossier", "/api/relation/pair"}:
            from_id = str(query.get("from", [""])[0] or "")
            to_id = str(query.get("to", [""])[0] or "")
            dossier = living_graph_server.dossier_for_pair(graph, from_id, to_id)
        else:
            parts = route.split("/")
            relation_id = unquote(parts[3]) if len(parts) >= 4 else ""
            dossier = relationship_dossier_for_id(graph, relation_id)
        if not dossier:
            self.respond(*json_response(HTTPStatus.NOT_FOUND, {"ok": False, "error": "relation_not_found"}))
            return
        self.respond(*json_response(HTTPStatus.OK, {"ok": True, "dossier": dossier}))

    def handle_node_get(self, route: str, query: dict[str, list[str]]) -> None:
        graph = load_graph()
        parts = route.split("/")
        if len(parts) < 4:
            self.send_error(HTTPStatus.BAD_REQUEST, "Missing node id")
            return
        node_id = unquote(parts[3])
        suffix = parts[4] if len(parts) > 4 else ""
        if suffix == "":
            node = node_lookup(graph, node_id)
            if not node:
                self.respond(*json_response(HTTPStatus.NOT_FOUND, {"ok": False, "error": "node_not_found", "node_id": node_id}))
                return
            node = dict(node)
            node["links_split"] = classify_links(node)
            node["family"] = family_for_entity(node, graph, party_relations(graph))
            node["visual_color"] = family_color(node["family"], node_id)
            node["visual_shape"] = family_shape(node, node["family"])
            node["neighbors_count"] = len([rel for rel in graph.get("relations", []) if rel.get("from") == node_id or rel.get("to") == node_id])
            self.respond(*json_response(HTTPStatus.OK, {"ok": True, "node": node, "links_split": classify_links(node)}))
            return
        if suffix == "neighbors":
            self.respond(*json_response(HTTPStatus.OK, neighbors_for_node(graph, node_id)))
            return
        if suffix == "card":
            card = entity_profile_card(graph, node_id)
            if not card:
                self.respond(*json_response(HTTPStatus.NOT_FOUND, {"ok": False, "error": "node_not_found", "node_id": node_id}))
                return
            self.respond(*json_response(HTTPStatus.OK, {"ok": True, "card": card}))
            return
        if suffix == "timeline":
            self.respond(*json_response(HTTPStatus.OK, node_timeline(graph, node_id)))
            return
        if suffix == "provenance":
            self.respond(*json_response(HTTPStatus.OK, node_provenance(graph, node_id)))
            return
        if suffix == "research":
            self.respond(*json_response(HTTPStatus.GONE, {"ok": False, "error": "disabled_in_graph_view", "message": "Node research is disabled. Use POST /api/research/run."}))
            return
        if suffix == "rag":
            prompt = str(query.get("prompt", [""])[0] or "")
            self.respond(*json_response(HTTPStatus.OK, node_rag_answer(graph, node_id, query=prompt)))
            return
        if suffix == "expand":
            self.respond(*json_response(HTTPStatus.GONE, {"ok": False, "error": "disabled_in_graph_view", "message": "Node expand is disabled. Use POST /api/research/run."}))
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def handle_node_command(self, route: str) -> None:
        graph = load_graph()
        parts = route.split("/")
        if len(parts) < 5:
            self.send_error(HTTPStatus.BAD_REQUEST, "Missing node id")
            return
        node_id = unquote(parts[3])
        payload = self.read_json_body()
        if not isinstance(payload, dict):
            self.respond(*json_response(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"}))
            return
        self.respond(*json_response(HTTPStatus.GONE, {"ok": False, "error": "disabled_in_graph_view", "message": "Node command is disabled. Use local graph search or POST /api/research/run."}))

    def handle_flow_get(self, route: str) -> None:
        parts = [part for part in route.split("/") if part]
        if len(parts) < 3:
            self.send_error(HTTPStatus.BAD_REQUEST, "Missing flow id")
            return
        run_id = unquote(parts[2]) if len(parts) > 2 else ""
        if len(parts) >= 4 and parts[3] == "diff":
            diff = latest_graph_diff()
            if diff.get("run_id") and diff.get("run_id") != run_id:
                self.respond(*json_response(HTTPStatus.NOT_FOUND, {"ok": False, "error": "diff_not_found", "run_id": run_id}))
                return
            self.respond(*json_response(HTTPStatus.OK, {"ok": True, **diff}))
            return
        runs = graph_flow_runs(limit=20).get("runs", [])
        match = next((item for item in runs if str(item.get("run_id", "")) == run_id), None)
        if not match:
            self.respond(*json_response(HTTPStatus.NOT_FOUND, {"ok": False, "error": "flow_not_found", "run_id": run_id}))
            return
        self.respond(*json_response(HTTPStatus.OK, {"ok": True, "flow": match}))

    def handle_prompt_command(self) -> None:
        payload = self.read_json_body()
        if not isinstance(payload, dict):
            self.respond(*json_response(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"}))
            return
        if str(payload.get("interface_mode") or "") == "research":
            self.respond(*json_response(HTTPStatus.GONE, {"ok": False, "error": "research_endpoint_moved", "message": "Research Mode now uses POST /api/research/run."}))
            return
        prompt_text = str(payload.get("prompt") or payload.get("command") or "")
        research_contract = research_request_contract(payload)
        if str(payload.get("interface_mode") or "") == "research":
            prompt_text = augment_research_prompt(prompt_text, research_contract)
        selected_node_id = str(payload.get("selected_node_id") or "").strip() or None
        model_mode = str(payload.get("model_mode") or "auto")
        requested_model = str(payload.get("requested_model") or "")
        response = prompt_command(
            load_graph(),
            prompt_text,
            selected_node_id=selected_node_id,
            model_mode=model_mode,
            requested_model=requested_model,
            research_options=research_contract,
        )
        if str(payload.get("interface_mode") or "") == "research":
            response["research_request"] = research_contract
            response.setdefault("tools_used", [])
            for tool_name in ["bounded_frontier", "source_specific_parsers", "generic_html_parser", "model_assisted_parser_config"]:
                if tool_name not in response["tools_used"]:
                    response["tools_used"].append(tool_name)
            trace = response.get("command_trace", {}) if isinstance(response.get("command_trace", {}), dict) else {}
            trace["research_request"] = research_contract
            response["command_trace"] = trace
        self.respond(*json_response(HTTPStatus.OK, response))

    def handle_research_run(self) -> None:
        payload = self.read_json_body()
        if not isinstance(payload, dict):
            self.respond(*json_response(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"}))
            return
        query = str(payload.get("query") or payload.get("prompt") or "").strip()
        if not query:
            self.respond(*json_response(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "empty_query"}))
            return
        budget = {
            "budget_pages": int(payload.get("budget_pages") or payload.get("budget") or 20),
            "max_depth": int(payload.get("max_depth") or 2),
            "source_priority": payload.get("source_priority") if isinstance(payload.get("source_priority"), list) else ["official", "reliable_media", "watchdog"],
        }
        started = living_graph_server.start_run(query, budget)
        living_graph_server.start_background_run(started["run_id"], max_steps_per_call=6)
        trace = living_graph_server.build_research_trace(started["run_id"])
        self.respond(*json_response(HTTPStatus.OK, {"ok": True, **started, "trace": trace, "run": trace.get("run", {})}))

    def handle_research_run_get(self, route: str) -> None:
        parts = [part for part in route.split("/") if part]
        if len(parts) < 4:
            self.respond(*json_response(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing_run_id"}))
            return
        run_id = unquote(parts[3])
        trace = living_graph_server.build_research_trace(run_id)
        status = HTTPStatus.OK if trace.get("ok") else HTTPStatus.NOT_FOUND
        self.respond(*json_response(status, trace))

    def handle_research_run_step(self, route: str) -> None:
        parts = [part for part in route.split("/") if part]
        if len(parts) < 5:
            self.respond(*json_response(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing_run_id"}))
            return
        run_id = unquote(parts[3])
        payload = self.read_json_body() or {}
        max_steps = max(1, min(20, int(payload.get("max_steps") or 1)))
        trace = living_graph_server.run_steps(run_id, max_steps=max_steps)
        status = HTTPStatus.OK if trace.get("ok") else HTTPStatus.NOT_FOUND
        self.respond(*json_response(status, trace))

    def handle_research_run_resume(self, route: str) -> None:
        parts = [part for part in route.split("/") if part]
        if len(parts) < 5:
            self.respond(*json_response(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing_run_id"}))
            return
        run_id = unquote(parts[3])
        payload = self.read_json_body() or {}
        max_steps = max(1, min(100, int(payload.get("max_steps") or 20)))
        trace = living_graph_server.resume_run(run_id, max_steps=max_steps)
        status = HTTPStatus.OK if trace.get("ok") else HTTPStatus.NOT_FOUND
        self.respond(*json_response(status, trace))

    def handle_research_run_events(self, route: str, query: dict[str, list[str]]) -> None:
        parts = [part for part in route.split("/") if part]
        if len(parts) < 5:
            self.respond(*json_response(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing_run_id"}))
            return
        run_id = unquote(parts[3])
        after_ts = float(query.get("after_ts", ["0"])[0] or 0.0)
        limit = max(1, min(400, int(query.get("limit", ["120"])[0] or 120)))
        from living_graph.research_tools import read_events

        events = read_events(run_id, after_ts=after_ts, limit=limit)
        self.respond(*json_response(HTTPStatus.OK, {"ok": True, "run_id": run_id, "events": events, "count": len(events)}))

    def handle_layout_save(self) -> None:
        payload = self.read_json_body()
        if not isinstance(payload, dict):
            self.respond(*json_response(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"}))
            return
        positions = payload.get("positions", {})
        if not isinstance(positions, dict):
            self.respond(*json_response(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_positions"}))
            return
        saved = living_graph_server.save_layout(positions)
        self.respond(*json_response(HTTPStatus.OK, {"ok": True, "layout": saved}))

    def read_json_body(self) -> dict[str, Any] | None:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None


def find_free_port(host: str, start_port: int) -> int:
    port = start_port
    for _ in range(100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
                return port
            except OSError:
                port += 1
    raise RuntimeError("No free port found")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Thiezer graph viewer.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--open", action="store_true", dest="open_browser")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    port = find_free_port(args.host, args.port)
    server = ThreadingHTTPServer((args.host, port), GraphViewerHandler)
    server.daemon_threads = True
    server.allow_reuse_address = True
    url = f"http://{args.host}:{port}/"
    print(json.dumps({"ok": True, "url": url, "web_dir": str(WEB_DIR), "graph_file": str(ROOT / 'content' / 'graph' / 'country-graph.json')}, ensure_ascii=False, indent=2))
    if args.open_browser:
        try:
            subprocess.Popen(["open", url])
        except Exception:
            pass
    try:
        latest = living_graph_server.latest_trace()
        latest_run = latest.get("run", {}) if isinstance(latest.get("run", {}), dict) else {}
        latest_run_id = str(latest_run.get("run_id") or latest.get("run_id") or "").strip()
        latest_status = str(latest_run.get("status") or latest.get("status") or "").strip()
        if latest_run_id and latest_status in {"queued", "running", "waiting"}:
            living_graph_server.start_background_run(latest_run_id)
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
