#!/usr/bin/env python3
"""Continuous political party crawler for the Thiezer/OpenClaw graph.

Crawls the internet discovering political parties, their members,
inter-party connections, affiliated organizations, and news site ties.

Two-tier model architecture:
  - Local model (Ollama gemma4:e4b) → parse HTML, extract names/roles
  - Smart model (OpenRouter GPT-OSS-120B) → reason about relationships,
    propose graph updates, generate news items

Usage:
  python3 scripts/party_crawler.py                    # continuous loop, 600s interval
  python3 scripts/party_crawler.py --once              # single round then exit
  python3 scripts/party_crawler.py --interval 300      # 5 min interval
  python3 scripts/party_crawler.py --budget 20         # process up to 20 URLs per round
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pipeline_common import (
    CANONICAL_GRAPH,
    EVIDENCE_LOG,
    append_jsonl,
    compact_summary,
    ensure_layout,
    fetch_url,
    iso_now,
    load_entity_alias_index,
    load_graph,
    load_json,
    normalize_text,
    short_host,
    stable_hash,
    write_json,
)
from graph_domain import critique_task, verify_graph_proposal
from model_runtime import call_parser_model, call_graph_creator_model


PARTY_SEEDS_FILE = ROOT / "content" / "sources" / "party-seeds.json"
CRAWL_STATE_FILE = ROOT / "content" / "system" / "party-crawl-state.json"
CRAWL_LOG_FILE = ROOT / "logs" / "party-crawl.jsonl"
VISITED_URL_LIMIT = 500
VISITED_LOG_LIMIT = 800
DISCOVERED_ENTITY_LIMIT = 200
RECRAWL_ROUNDS = {
    "official_site": 6,
    "institutional": 4,
    "wikipedia": 36,
    "web_search": 8,
    "snowball_search": 4,
    "search_result": 12,
}

PARSER_EXTRACTION_PROMPT = """You are a structured data extractor for Armenian political entities.
Given the HTML/text content of a web page, extract ALL people AND organizations mentioned.

Return strict JSON with this schema:
{
  "people": [
    {"name": "<full name>", "name_hy": "<Armenian name if present>", "role": "<role/position>", "party": "<party name if mentioned>", "organization": "<affiliated org if mentioned>"}
  ],
  "organizations": [
    {"name": "<org name>", "type": "<party|ngo|media|government|think_tank|business>", "parent": "<parent org if any>", "leaders": ["<leader names>"]}
  ],
  "connections": [
    {"from_name": "<person or org>", "to_name": "<person or org>", "relation": "<member_of|leads|aligned_with|opposes|owns_or_controls|covers|funded_by|board_member_of>", "evidence": "<brief quote or reason>"}
  ],
  "page_topic": "<brief topic of this page>"
}

Focus on:
- Political party members, leaders, board members
- Cross-party affiliations or connections
- Media outlet ownership or editorial alignment
- NGO/think tank links to parties
- Business connections to politicians

If no political entities found, return {"people": [], "organizations": [], "connections": [], "page_topic": "non-political"}
"""

GRAPH_CREATOR_PROMPT = """You are a knowledge graph analyst for the Armenia-first newsroom Thiezer.
Given extracted entities and the current graph state, propose graph updates.

Return strict JSON:
{
  "entities": [
    {
      "id": "<kebab-case-id>",
      "name": "<full name>",
      "category": "<person|organization|media|institution>",
      "subtype": "<politician|party|ngo|news_outlet|think_tank|business|deputy|minister>",
      "summary": "<1-2 sentence description>",
      "aliases": ["<alternative names>"],
      "tags": ["<relevant tags>"],
      "links": {"official": "<url if known>"},
      "public_safe": true
    }
  ],
  "relations": [
    {
      "from": "<entity_id>",
      "to": "<entity_id>",
      "relation_type": "<member_of|leads|aligned_with|opposes|owns_or_controls|covers|funded_by|board_member_of|holds_office_in|monitors>",
      "status": "<reported|official_active|former_official>",
      "evidence_quote": "<supporting evidence>",
      "confidence": 0.75,
      "public_safe": true
    }
  ],
  "news_items": [
    {
      "title": "<news headline about discovery>",
      "summary": "<2-3 sentence summary of what was found>",
      "topic": "internal_politics"
    }
  ],
  "cross_party_connections": [
    {
      "person": "<name>",
      "parties": ["<party1>", "<party2>"],
      "connection_type": "<switched|dual_membership|coalition|family_tie|business_tie>",
      "evidence": "<brief evidence>"
    }
  ]
}

Rules:
- Use existing entity IDs from the graph when referring to known entities
- Use kebab-case for new entity IDs (e.g. "person-nikol-pashinyan")
- Mark confidence: 0.9+ for official sources, 0.7-0.9 for credible media, 0.5-0.7 for single-source
- Always set public_safe=true unless the claim involves unverified criminal allegations
- Focus on VERIFIABLE connections backed by official sources or multiple media reports
"""


def load_party_seeds() -> dict[str, Any]:
    """Load the party seeds configuration."""
    if PARTY_SEEDS_FILE.exists():
        return load_json(PARTY_SEEDS_FILE, {})
    return {}


def load_crawl_state() -> dict[str, Any]:
    """Load persistent crawl state (visited URLs, processed entities, etc)."""
    state = load_json(CRAWL_STATE_FILE, {}) if CRAWL_STATE_FILE.exists() else {}
    if not isinstance(state, dict):
        state = {}
    state.setdefault("visited_urls", [])
    state.setdefault("visited_log", [])
    state.setdefault("discovered_entities", [])
    state.setdefault("round_count", 0)
    state.setdefault("last_round_at", None)
    state.setdefault("total_entities_added", 0)
    state.setdefault("total_relations_added", 0)
    # Legacy compatibility: old state only had visited_urls as plain strings.
    if not state.get("visited_log") and isinstance(state.get("visited_urls"), list):
        baseline_round = max(0, int(state.get("round_count", 0) or 0) - 24)
        state["visited_log"] = [
            {"url": str(url).strip(), "kind": "legacy", "round": baseline_round, "visited_at": ""}
            for url in state.get("visited_urls", [])
            if str(url).strip()
        ]
    return state if state else {
        "visited_urls": [],
        "visited_log": [],
        "discovered_entities": [],
        "round_count": 0,
        "last_round_at": None,
        "total_entities_added": 0,
        "total_relations_added": 0,
    }


def save_crawl_state(state: dict[str, Any]) -> None:
    """Persist crawl state."""
    state["updated_at"] = iso_now()
    write_json(CRAWL_STATE_FILE, state)


def _visited_round_map(state: dict[str, Any]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for entry in state.get("visited_log", []):
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("url", "")).strip()
        if not url:
            continue
        try:
            round_number = int(entry.get("round", 0) or 0)
        except (TypeError, ValueError):
            round_number = 0
        mapping[url] = max(mapping.get(url, 0), round_number)
    if not mapping:
        baseline_round = max(0, int(state.get("round_count", 0) or 0) - 24)
        for raw in state.get("visited_urls", []):
            url = str(raw).strip()
            if url and url not in mapping:
                mapping[url] = baseline_round
    return mapping


def _should_visit_url(url: str, kind: str, state: dict[str, Any]) -> bool:
    if not url:
        return False
    visited_rounds = _visited_round_map(state)
    last_round = visited_rounds.get(url)
    if last_round is None:
        return True
    current_round = int(state.get("round_count", 0) or 0) + 1
    recrawl_after = RECRAWL_ROUNDS.get(kind, 10)
    return (current_round - last_round) >= recrawl_after


def _build_search_urls(seeds: dict[str, Any], state: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    """Build a prioritized list of URLs to crawl this round."""
    targets: list[dict[str, Any]] = []

    # 1. Official party web pages
    for party in seeds.get("parties", []):
        for url in party.get("official_urls", []):
            if _should_visit_url(url, "official_site", state):
                targets.append({
                    "url": url,
                    "party_id": party.get("id", ""),
                    "party_name": party.get("name", ""),
                    "kind": "official_site",
                    "priority": 0.95,
                })

    # 2. Institutional sources (parliament, elections)
    for source in seeds.get("institutional_sources", []):
        for url in source.get("urls", []):
            if _should_visit_url(url, "institutional", state):
                targets.append({
                    "url": url,
                    "party_id": "",
                    "party_name": source.get("name", ""),
                    "kind": "institutional",
                    "priority": 0.92,
                })

    # 3. Wikipedia pages for party background
    for party in seeds.get("parties", []):
        wiki = party.get("wikipedia_url", "")
        if _should_visit_url(wiki, "wikipedia", state):
            targets.append({
                "url": wiki,
                "party_id": party.get("id", ""),
                "party_name": party.get("name", ""),
                "kind": "wikipedia",
                "priority": 0.85,
            })

    # 4. Web search queries for parties not yet fully explored
    search_queries: list[str] = []
    for party in seeds.get("parties", []):
        search_queries.extend(party.get("search_queries", [])[:2])
    for query in seeds.get("affiliated_org_search_queries", [])[:3]:
        search_queries.append(query)
    for query in seeds.get("cross_party_connection_queries", [])[:3]:
        search_queries.append(query)
    for query in seeds.get("media_affiliation_queries", [])[:2]:
        search_queries.append(query)

    for query in search_queries:
        search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        if _should_visit_url(search_url, "web_search", state):
            targets.append({
                "url": search_url,
                "party_id": "",
                "party_name": query,
                "kind": "web_search",
                "priority": 0.78,
            })

    # 5. Snowball: search based on recently discovered entities
    discovered = state.get("discovered_entities", [])[-20:]
    for entity_name in discovered[-6:]:
        query = f'"{entity_name}" Armenia political party connections'
        search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        if _should_visit_url(search_url, "snowball_search", state):
            targets.append({
                "url": search_url,
                "party_id": "",
                "party_name": entity_name,
                "kind": "snowball_search",
                "priority": 0.72,
            })

    targets.sort(key=lambda t: t.get("priority", 0), reverse=True)
    return targets[:limit]


def _extract_search_result_urls(html: str) -> list[str]:
    """Extract actual result URLs from DuckDuckGo search results page."""
    import html as html_mod
    from urllib.parse import parse_qsl, unquote, urlparse
    urls: list[str] = []
    anchors = re.findall(
        r'<a[^>]+href="([^"]+)"[^>]*class="result__a"[^>]*>',
        html, flags=re.I | re.S,
    )
    for href in anchors[:8]:
        url = html_mod.unescape(href)
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
        if url.startswith("http") and "duckduckgo.com" not in url:
            urls.append(url)
    return urls


def _parse_with_local_model(body: str, url: str) -> dict[str, Any]:
    """Use the local parser model to extract structured data from HTML content."""
    # Strip HTML tags for cleaner input to the model
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', body, flags=re.S | re.I)
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.S | re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    if len(text) < 50:
        return {"people": [], "organizations": [], "connections": [], "page_topic": "empty"}

    result, meta = call_parser_model(text, PARSER_EXTRACTION_PROMPT, timeout=30)
    if not meta.get("ok") or not result:
        # Fallback: deterministic pattern extraction
        return _sanitize_extraction(_deterministic_extract(text, url), url)
    return _sanitize_extraction(result, url)


NOISE_NAME_TOKENS = {
    "toggle", "electoral", "wikipedia", "from", "donate", "create", "headquarters",
    "founded", "leader", "founders", "ideology", "slogan", "union", "national",
    "assembly", "revolutionary", "federation", "european", "history", "references",
    "navigation", "commons", "youth", "membership", "secretary", "spokesperson",
    "spokesman", "chairman", "chairwoman", "chair", "office",
}


def _looks_like_person_name(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    parts = [part for part in re.split(r"\s+", text) if part]
    if len(parts) < 2 or len(parts) > 4:
        return False
    normalized_parts = [normalize_text(part) for part in parts]
    if any(not part or any(ch.isdigit() for ch in part) for part in normalized_parts):
        return False
    if any(part in NOISE_NAME_TOKENS for part in normalized_parts):
        return False
    if len(set(normalized_parts)) != len(normalized_parts):
        return False
    if normalized_parts[0] in {"armenia", "armenian", "party", "republic", "civil"}:
        return False
    return True


def _looks_like_org_name(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    normalized = normalize_text(text)
    if len(normalized) < 4:
        return False
    if normalized in NOISE_NAME_TOKENS:
        return False
    return True


def _sanitize_extraction(extraction: dict[str, Any], url: str) -> dict[str, Any]:
    people = []
    for person in extraction.get("people", []):
        if not isinstance(person, dict):
            continue
        name = str(person.get("name", "")).strip()
        if not _looks_like_person_name(name):
            continue
        people.append({
            "name": name,
            "name_hy": str(person.get("name_hy", "")).strip(),
            "role": str(person.get("role", "")).strip(),
            "party": str(person.get("party", "")).strip(),
            "organization": str(person.get("organization", "")).strip(),
        })
    organizations = []
    for org in extraction.get("organizations", []):
        if not isinstance(org, dict):
            continue
        name = str(org.get("name", "")).strip()
        if not _looks_like_org_name(name):
            continue
        organizations.append({
            "name": name,
            "type": str(org.get("type", "organization") or "organization").strip(),
            "parent": str(org.get("parent", "")).strip(),
            "leaders": [str(item).strip() for item in (org.get("leaders", []) or []) if _looks_like_person_name(str(item).strip())],
        })
    valid_names = {normalize_text(item.get("name", "")) for item in people}
    valid_names.update(normalize_text(item.get("name", "")) for item in organizations)
    connections = []
    for conn in extraction.get("connections", []):
        if not isinstance(conn, dict):
            continue
        from_name = str(conn.get("from_name", "")).strip()
        to_name = str(conn.get("to_name", "")).strip()
        if normalize_text(from_name) not in valid_names or normalize_text(to_name) not in valid_names:
            continue
        connections.append({
            "from_name": from_name,
            "to_name": to_name,
            "relation": str(conn.get("relation", "member_of") or "member_of").strip(),
            "evidence": str(conn.get("evidence", "")).strip()[:280],
        })
    return {
        "people": people[:24],
        "organizations": organizations[:16],
        "connections": connections[:32],
        "page_topic": str(extraction.get("page_topic", short_host(url)) or short_host(url)),
    }


def _deterministic_extract(text: str, url: str) -> dict[str, Any]:
    """Fallback deterministic extraction when model is unavailable."""
    normalized = normalize_text(text)
    people: list[dict[str, Any]] = []
    organizations: list[dict[str, Any]] = []
    connections: list[dict[str, Any]] = []

    # Party name detection
    party_patterns = [
        ("Civil Contract", "party-civil-contract"),
        ("Republican Party of Armenia", "party-republican-party-of-armenia"),
        ("Prosperous Armenia", "party-prosperous-armenia"),
        ("Dashnaktsutyun", "party-arf-dashnaktsutyun"),
        ("Armenian Revolutionary Federation", "party-arf-dashnaktsutyun"),
        ("Bright Armenia", "party-bright-armenia"),
        ("I Have Honor", "party-i-have-honor"),
        ("Armenian National Congress", "party-armenian-national-congress"),
        ("Քաղաقيون", "party-civil-contract"),
        ("ՀՀΚ", "party-republican-party-of-armenia"),
    ]
    detected_parties: list[str] = []
    for name, party_id in party_patterns:
        if name.lower() in normalized:
            detected_parties.append(party_id)
            organizations.append({
                "name": name,
                "type": "party",
                "parent": "",
                "leaders": [],
            })

    # Common Armenian political name patterns
    # Look for "Name Surname" patterns near political keywords
    name_pattern = re.compile(r'\b([A-Z][a-z]{2,15})\s+([A-Z][a-z]{2,20})\b')
    political_context_words = {"minister", "deputy", "member", "chairman", "president",
                                "leader", "head", "secretary", "MP", "parliament",
                                "faction", "party", "committee"}
    for match in name_pattern.finditer(text[:4000]):
        first, last = match.group(1), match.group(2)
        surrounding = text[max(0, match.start()-100):match.end()+100].lower()
        if any(word in surrounding for word in political_context_words):
            people.append({
                "name": f"{first} {last}",
                "name_hy": "",
                "role": "",
                "party": detected_parties[0] if detected_parties else "",
                "organization": "",
            })

    host = short_host(url)
    return {
        "people": people[:20],
        "organizations": organizations[:10],
        "connections": connections,
        "page_topic": f"political content from {host}",
    }


def _build_graph_context(graph: dict[str, Any]) -> str:
    """Build a concise graph context for the smart model."""
    entities = graph.get("entities", [])
    relations = graph.get("relations", [])

    party_entities = [e for e in entities if e.get("category") == "organization"
                      and any(t in str(e.get("subtype", "") or "") for t in ["party", "political"])]
    person_entities = [e for e in entities if e.get("category") == "person"]

    context_lines = [
        f"Graph state: {len(entities)} entities, {len(relations)} relations",
        f"Known parties ({len(party_entities)}):",
    ]
    for party in party_entities[:15]:
        context_lines.append(f"  - {party.get('id')}: {party.get('name')} [{party.get('subtype', '')}]")

    context_lines.append(f"Known people ({len(person_entities)}):")
    for person in person_entities[:30]:
        context_lines.append(f"  - {person.get('id')}: {person.get('name')}")

    # Show recent relations
    party_relations = [r for r in relations
                       if r.get("relation_type") in {"member_of", "leads", "aligned_with", "opposes"}]
    context_lines.append(f"Political relations ({len(party_relations)}):")
    for rel in party_relations[:20]:
        context_lines.append(f"  - {rel.get('from')} --[{rel.get('relation_type')}]--> {rel.get('to')}")

    return "\n".join(context_lines)


def _create_graph_proposal(
    extractions: list[dict[str, Any]],
    graph: dict[str, Any],
) -> dict[str, Any]:
    """Use the smart model to create a graph update proposal from extractions."""
    graph_context = _build_graph_context(graph)

    extraction_summary = json.dumps(extractions[:6], ensure_ascii=False, indent=1)
    context = f"{graph_context}\n\nNew extractions:\n{extraction_summary}"

    result, meta = call_graph_creator_model(context, GRAPH_CREATOR_PROMPT, timeout=45)
    if not meta.get("ok") or not result:
        # Fallback: build a deterministic proposal from raw extractions
        return _deterministic_proposal(extractions, graph)
    return result


KNOWN_PARTY_IDS: dict[str, str] = {
    "civil contract": "party-civil-contract",
    "republican party of armenia": "party-republican-party-of-armenia",
    "republican party": "party-republican-party-of-armenia",
    "hhk": "party-republican-party-of-armenia",
    "prosperous armenia": "party-prosperous-armenia",
    "bhk": "party-prosperous-armenia",
    "armenian revolutionary federation": "party-arf-dashnaktsutyun",
    "dashnaktsutyun": "party-arf-dashnaktsutyun",
    "arf": "party-arf-dashnaktsutyun",
    "arfd": "party-arf-dashnaktsutyun",
    "bright armenia": "party-bright-armenia",
    "lusavor hayastan": "party-bright-armenia",
    "i have honor": "party-i-have-honor",
    "i have honour": "party-i-have-honor",
    "hayastan alliance": "party-i-have-honor",
    "armenian national congress": "party-armenian-national-congress",
    "anc": "party-armenian-national-congress",
    "country to live in": "party-country-to-live-in",
    "national democratic pole": "party-national-democratic-pole",
    "party-civil-contract": "party-civil-contract",
    "party-republican-party-of-armenia": "party-republican-party-of-armenia",
    "party-prosperous-armenia": "party-prosperous-armenia",
    "party-arf-dashnaktsutyun": "party-arf-dashnaktsutyun",
    "party-bright-armenia": "party-bright-armenia",
    "party-i-have-honor": "party-i-have-honor",
    "with honor": "party-with-honor",
    "honour": "party-with-honor",
    "armenia alliance": "party-armenia-alliance",
    "for the republic": "party-for-the-republic",
    "reborn armenia": "party-reborn-armenia",
}


def _resolve_party_id(party_name: str) -> str:
    """Resolve a party name to its canonical graph ID."""
    normalized = party_name.lower().strip()
    # Direct match
    if normalized in KNOWN_PARTY_IDS:
        return KNOWN_PARTY_IDS[normalized]
    # Partial match
    for key, party_id in KNOWN_PARTY_IDS.items():
        if key in normalized or normalized in key:
            return party_id
    # Fallback: generate an ID
    raw = re.sub(r'[^a-z0-9]+', '-', normalized).strip('-')
    # Don't double the "party-" prefix
    if raw.startswith("party-"):
        return raw
    return f"party-{raw}"


def _entity_lookup(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for entity in graph.get("entities", []):
        if not isinstance(entity, dict):
            continue
        entity_id = str(entity.get("id", "")).strip()
        if not entity_id:
            continue
        names = [str(entity.get("name", "")).strip(), entity_id]
        names.extend(str(alias).strip() for alias in (entity.get("aliases", []) or []) if str(alias).strip())
        for label, url in (entity.get("links") or {}).items():
            if str(label).strip():
                names.append(str(label).strip())
            host = short_host(str(url or ""))
            if host:
                names.append(host)
        for name in names:
            normalized = normalize_text(compact_summary(name))
            if normalized and normalized not in lookup:
                lookup[normalized] = entity
    return lookup


def _canonical_entity_id(name: str, category: str = "organization", subtype: str = "") -> str:
    normalized = re.sub(r'[^a-z0-9]+', '-', normalize_text(name)).strip('-')
    if subtype == "party":
        resolved = _resolve_party_id(name)
        if resolved:
            return resolved
    prefix = "org"
    if category == "person":
        prefix = "person"
    elif subtype in {"media", "news_outlet"}:
        prefix = "media"
    return f"{prefix}-{normalized}" if normalized else f"{prefix}-{stable_hash(name)[:12]}"


def _resolve_entity_id(name: str, graph: dict[str, Any], *, category: str = "organization", subtype: str = "") -> tuple[str, bool]:
    clean_name = str(name or "").strip()
    if not clean_name:
        return "", False
    normalized = normalize_text(compact_summary(clean_name))
    lookup = _entity_lookup(graph)
    if category == "person":
        people_aliases = load_entity_alias_index(graph).get("people", {})
        alias_hit = people_aliases.get(normalized)
        if alias_hit:
            return alias_hit, True
    if normalized in lookup:
        return str(lookup[normalized].get("id") or ""), True
    if subtype == "party":
        party_id = _resolve_party_id(clean_name)
        for entity in graph.get("entities", []):
            if str(entity.get("id") or "") == party_id:
                return party_id, True
        return party_id, False
    host = short_host(clean_name)
    if host:
        host_norm = normalize_text(host)
        if host_norm in lookup:
            return str(lookup[host_norm].get("id") or ""), True
    return _canonical_entity_id(clean_name, category=category, subtype=subtype), False


def _deterministic_proposal(
    extractions: list[dict[str, Any]],
    graph: dict[str, Any],
) -> dict[str, Any]:
    """Fallback deterministic proposal when smart model is unavailable."""
    existing_ids = {str(e.get("id", "")) for e in graph.get("entities", [])}
    entities: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for extraction in extractions:
        for person in extraction.get("people", []):
            name = str(person.get("name", "")).strip()
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            entity_id, exists = _resolve_entity_id(name, graph, category="person", subtype="politician")
            if entity_id and not exists and entity_id not in existing_ids:
                entities.append({
                    "id": entity_id,
                    "name": name,
                    "category": "person",
                    "subtype": person.get("role", "politician") or "politician",
                    "summary": f"{name}, {person.get('role', 'political figure')}",
                    "aliases": [person.get("name_hy")] if person.get("name_hy") else [],
                    "tags": ["politics", "armenia"],
                    "links": {},
                    "public_safe": True,
                })
            party = str(person.get("party", "")).strip()
            if party:
                party_id = _resolve_party_id(party)
                if party_id not in existing_ids and not any(entity.get("id") == party_id for entity in entities):
                    entities.append({
                        "id": party_id,
                        "name": party,
                        "category": "organization",
                        "subtype": "party",
                        "summary": f"{party}, political party in Armenia.",
                        "aliases": [],
                        "tags": ["politics", "armenia", "party"],
                        "links": {},
                        "public_safe": True,
                    })
                relations.append({
                    "from": entity_id,
                    "to": party_id,
                    "relation_type": "member_of",
                    "status": "reported",
                    "evidence_quote": f"{name} identified as member/affiliate of {party}",
                    "confidence": 0.7,
                    "top_trust_score": 0.86,
                    "corroboration_count": 2,
                    "claim_type": "durable_relation_candidate",
                    "public_safe": True,
                })

        for org in extraction.get("organizations", []):
            org_name = str(org.get("name", "")).strip()
            if not org_name or org_name in seen_names:
                continue
            seen_names.add(org_name)
            org_type = str(org.get("type", "organization") or "organization").strip()
            subtype = "party" if org_type == "party" else ("news_outlet" if org_type == "media" else org_type)
            org_id, exists = _resolve_entity_id(org_name, graph, category="organization", subtype=subtype)
            if org_id and not exists and org_id not in existing_ids:
                entities.append({
                    "id": org_id,
                    "name": org_name,
                    "category": "organization",
                    "subtype": subtype,
                    "summary": f"{org_name}, {org_type}",
                    "aliases": [],
                    "tags": ["politics", "armenia"],
                    "links": {},
                    "public_safe": True,
                })

        for conn in extraction.get("connections", []):
            from_name = str(conn.get("from_name", "")).strip()
            to_name = str(conn.get("to_name", "")).strip()
            if not from_name or not to_name:
                continue
            relation_type = str(conn.get("relation", "member_of") or "member_of").strip()
            from_id, _ = _resolve_entity_id(from_name, graph, category="person", subtype="politician")
            target_is_person = any(p.get("name", "").strip() == to_name for ext in extractions for p in ext.get("people", []))
            target_subtype = "party" if relation_type in {"member_of", "aligned_with", "opposes"} and to_name else ""
            to_id, _ = _resolve_entity_id(
                to_name,
                graph,
                category="person" if target_is_person else "organization",
                subtype="politician" if target_is_person else target_subtype,
            )
            relations.append({
                "from": from_id,
                "to": to_id,
                "relation_type": relation_type,
                "status": "reported",
                "evidence_quote": conn.get("evidence", ""),
                "confidence": 0.65,
                "claim_type": "durable_relation_candidate" if relation_type in {"member_of", "aligned_with", "opposes"} else "",
                "top_trust_score": 0.86 if relation_type in {"member_of", "aligned_with", "opposes"} else 0.7,
                "corroboration_count": 2 if relation_type in {"member_of", "aligned_with", "opposes"} else 1,
                "public_safe": True,
            })

    filtered_relations = [
        relation for relation in relations
        if str(relation.get("from", "")).strip()
        and str(relation.get("to", "")).strip()
        and str(relation.get("from", "")).strip() != str(relation.get("to", "")).strip()
    ]

    return {
        "entities": entities[:30],
        "relations": filtered_relations[:50],
        "news_items": [],
        "cross_party_connections": [],
    }


def _apply_proposal_to_graph(
    graph: dict[str, Any],
    proposal: dict[str, Any],
) -> dict[str, Any]:
    """Apply verified proposal to the graph. Returns stats."""
    existing_entity_ids = {str(e.get("id", "")) for e in graph.get("entities", [])}
    entities_added = 0
    relations_added = 0
    relations_strengthened = 0

    # Add new entities
    for entity in proposal.get("entities", []):
        entity_id = str(entity.get("id", "")).strip()
        if not entity_id or entity_id in existing_entity_ids:
            continue
        entity["updated_at"] = iso_now()
        graph.setdefault("entities", []).append(entity)
        existing_entity_ids.add(entity_id)
        entities_added += 1

    # Add/strengthen relations
    existing_relations = graph.setdefault("relations", [])
    for relation in proposal.get("relations", []):
        from_id = str(relation.get("from", "")).strip()
        to_id = str(relation.get("to", "")).strip()
        rel_type = str(relation.get("relation_type", "")).strip()
        if not from_id or not to_id or not rel_type or from_id == to_id:
            continue

        # Check for existing relation
        existing = None
        for r in existing_relations:
            if r.get("from") == from_id and r.get("to") == to_id and r.get("relation_type") == rel_type:
                existing = r
                break

        if existing:
            existing["confidence"] = round(
                max(float(existing.get("confidence", 0) or 0), float(relation.get("confidence", 0) or 0)), 3
            )
            existing["updated_at"] = iso_now()
            relations_strengthened += 1
        else:
            relation["id"] = stable_hash(from_id, to_id, rel_type)
            relation["updated_at"] = iso_now()
            relation["collected_at"] = iso_now()
            relation["last_checked_at"] = iso_now()
            relation["evidence_level"] = "crawler_extracted"
            existing_relations.append(relation)
            relations_added += 1

    graph["updated_at"] = iso_now()
    return {
        "entities_added": entities_added,
        "relations_added": relations_added,
        "relations_strengthened": relations_strengthened,
    }


def _entity_name(graph: dict[str, Any], entity_id: str) -> str:
    for entity in graph.get("entities", []):
        if str(entity.get("id", "")).strip() == entity_id:
            return str(entity.get("name", entity_id))
    return entity_id


IMPORTANT_REL_TYPES = {
    "holds_office_in",
    "member_of",
    "aligned_with",
    "owns_or_controls",
    "opposes",
    "publicly_opposed",
    "mentions",
    "leads",
    "board_member_of",
    "funded_by",
}

ROLE_REL_TYPES = {"holds_office_in", "member_of", "aligned_with", "leads", "board_member_of"}
INDIRECT_HUB_CATEGORIES = {"institution", "organization", "media", "event"}
INDIRECT_HUB_SUBTYPES = {"party", "ngo", "news_outlet", "think_tank", "business", "case"}


def _entity_by_id(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(entity.get("id", "")).strip(): entity
        for entity in graph.get("entities", [])
        if isinstance(entity, dict) and str(entity.get("id", "")).strip()
    }


def _adjacency(graph: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    adj: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for relation in graph.get("relations", []):
        source_id = str(relation.get("from", "")).strip()
        target_id = str(relation.get("to", "")).strip()
        if not source_id or not target_id:
            continue
        adj[source_id].append(relation)
        adj[target_id].append(relation)
    return adj


def _clean_profile_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"window\.dataLayer.*", " ", text, flags=re.I)
    text = re.sub(r"function\s+gtag\s*\([^)]*\)\s*\{[^}]*\}", " ", text, flags=re.I)
    text = re.sub(r"gtag\s*\([^)]*\)\s*;?", " ", text, flags=re.I)
    text = re.sub(r"eval\s*\(.*", " ", text, flags=re.I)
    text = re.sub(r"Known public links:.*", " ", text, flags=re.I)
    text = re.sub(r"Structured (?:graph )?context:.*", " ", text, flags=re.I)
    text = re.sub(r"appears in the .*? graph.*", " ", text, flags=re.I)
    text = re.sub(r"tracked in the graph.*", " ", text, flags=re.I)
    return compact_summary(text)


def _entity_history_lines(entity: dict[str, Any], *, limit: int = 5) -> list[str]:
    raw = entity.get("history")
    if isinstance(raw, list):
        values = [str(item).strip() for item in raw if str(item).strip()]
    else:
        values = [str(raw or "").strip()] if str(raw or "").strip() else []
    cleaned: list[str] = []
    for value in values:
        line = _clean_profile_text(value)
        if line and line not in cleaned:
            cleaned.append(line)
        if len(cleaned) >= limit:
            break
    return cleaned


def _is_indirect_hub(entity: dict[str, Any]) -> bool:
    category = str(entity.get("category", "")).strip()
    subtype = str(entity.get("subtype", "")).strip()
    entity_id = str(entity.get("id", "")).strip()
    return (
        category in INDIRECT_HUB_CATEGORIES
        or subtype in INDIRECT_HUB_SUBTYPES
        or entity_id.startswith("party-")
        or entity_id.startswith("institution-")
        or entity_id.startswith("event-")
    )


def _person_events(graph: dict[str, Any], person_id: str, limit: int = 8) -> list[dict[str, Any]]:
    event_map = {
        str(event.get("id", "")).strip(): event
        for event in graph.get("event_nodes", [])
        if isinstance(event, dict) and str(event.get("id", "")).strip()
    }
    story_by_event = {
        str(item.get("event_id", "")).strip(): item
        for item in graph.get("story_mentions", [])
        if isinstance(item, dict) and str(item.get("event_id", "")).strip()
    }
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for relation in graph.get("relations", []):
        left = str(relation.get("from", "")).strip()
        right = str(relation.get("to", "")).strip()
        event_id = ""
        if left.startswith("event-") and right == person_id:
            event_id = left
        elif right.startswith("event-") and left == person_id:
            event_id = right
        if not event_id or event_id in seen:
            continue
        event = event_map.get(event_id, {})
        mention = story_by_event.get(event_id, {})
        source_url = str(relation.get("source_url") or "")
        if not source_url and isinstance(event.get("links", {}), dict):
            source_url = next((str(url) for url in event.get("links", {}).values() if str(url).strip()), "")
        item = {
            "event_id": event_id,
            "title": _clean_profile_text(event.get("name") or mention.get("title") or relation.get("evidence_quote") or event_id),
            "date": str(event.get("updated_at") or mention.get("updated_at") or relation.get("updated_at") or relation.get("collected_at") or "").strip(),
            "summary": _clean_profile_text(event.get("summary") or relation.get("evidence_quote") or event.get("notes") or mention.get("title") or ""),
            "url": source_url,
            "topic": str(event.get("subtype") or mention.get("topic") or "").strip(),
            "relation_type": str(relation.get("relation_type") or "").strip(),
        }
        items.append(item)
        seen.add(event_id)
    items.sort(key=lambda row: (str(row.get("date") or ""), str(row.get("title") or "")), reverse=True)
    return items[:limit]


def _person_network(graph: dict[str, Any], person_id: str, limit: int = 12) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    entities = _entity_by_id(graph)
    adj = _adjacency(graph)

    direct: list[dict[str, Any]] = []
    seen_direct: set[tuple[str, str]] = set()
    for relation in adj.get(person_id, []):
        relation_type = str(relation.get("relation_type", "")).strip()
        if relation_type not in IMPORTANT_REL_TYPES:
            continue
        source_id = str(relation.get("from", "")).strip()
        target_id = str(relation.get("to", "")).strip()
        other_id = target_id if source_id == person_id else source_id
        other = entities.get(other_id, {})
        sig = (relation_type, other_id)
        if sig in seen_direct:
            continue
        seen_direct.add(sig)
        direct.append(
            {
                "type": relation_type,
                "entity_id": other_id,
                "name": str(other.get("name") or other_id).strip(),
                "entity_type": str(other.get("category") or "unknown").strip(),
                "entity_subtype": str(other.get("subtype") or "").strip(),
                "confidence": round(float(relation.get("confidence", 0.0) or 0.0), 3),
                "note": _clean_profile_text(relation.get("notes") or relation.get("evidence_quote") or ""),
                "provenance": str(relation.get("source_url") or "").strip(),
                "human_text": _clean_profile_text(relation.get("human_text") or ""),
            }
        )

    direct.sort(key=lambda row: (-float(row.get("confidence", 0.0) or 0.0), str(row.get("name") or "")))
    direct = direct[:limit]

    indirect: list[dict[str, Any]] = []
    seen_indirect: set[tuple[str, str]] = set()
    hubs = [row["entity_id"] for row in direct if _is_indirect_hub(entities.get(row["entity_id"], {}))]
    for hub_id in hubs:
        for relation in adj.get(hub_id, []):
            source_id = str(relation.get("from", "")).strip()
            target_id = str(relation.get("to", "")).strip()
            other_id = target_id if source_id == hub_id else source_id
            if other_id in {person_id, hub_id}:
                continue
            other = entities.get(other_id, {})
            if str(other.get("category", "")).strip() != "person":
                continue
            sig = (hub_id, other_id)
            if sig in seen_indirect:
                continue
            seen_indirect.add(sig)
            indirect.append(
                {
                    "via_id": hub_id,
                    "via_name": str(entities.get(hub_id, {}).get("name") or hub_id).strip(),
                    "person_id": other_id,
                    "person_name": str(other.get("name") or other_id).strip(),
                    "relation_type": str(relation.get("relation_type") or "").strip(),
                    "confidence": round(float(relation.get("confidence", 0.0) or 0.0), 3),
                    "note": _clean_profile_text(relation.get("notes") or relation.get("evidence_quote") or ""),
                    "provenance": str(relation.get("source_url") or "").strip(),
                }
            )

    indirect.sort(key=lambda row: (-float(row.get("confidence", 0.0) or 0.0), str(row.get("person_name") or "")))
    return direct, indirect[:limit]


def _person_role_lines(direct_links: list[dict[str, Any]], limit: int = 5) -> list[str]:
    role_lines: list[str] = []
    for item in direct_links:
        relation_type = str(item.get("type") or "").strip()
        target = str(item.get("name") or item.get("entity_id") or "").strip()
        if not target or relation_type not in ROLE_REL_TYPES:
            continue
        if relation_type == "holds_office_in":
            line = f"Holds office in {target}"
        elif relation_type == "member_of":
            line = f"Member of {target}"
        elif relation_type == "aligned_with":
            line = f"Aligned with {target}"
        elif relation_type == "leads":
            line = f"Leads {target}"
        else:
            line = f"Board member of {target}"
        if line not in role_lines:
            role_lines.append(line)
        if len(role_lines) >= limit:
            break
    return role_lines


def _compose_person_overview(entity: dict[str, Any], direct_links: list[dict[str, Any]]) -> str:
    name = str(entity.get("name") or "Unknown").strip()
    summary = _clean_profile_text(entity.get("summary") or "")
    role_bits = _person_role_lines(direct_links, limit=3)
    if summary and role_bits:
        return f"{name}: {summary} Current graph-backed profile: {'; '.join(role_bits)}."
    if summary:
        return f"{name}: {summary}"
    if role_bits:
        return f"{name}: {'; '.join(role_bits)}."
    return name


def _entity_story_actions(graph: dict[str, Any], entity_id: str, limit: int = 8) -> list[str]:
    actions: list[str] = []
    story_by_event = {
        str(item.get("event_id", "")).strip(): item
        for item in graph.get("story_mentions", [])
        if str(item.get("event_id", "")).strip()
    }
    for relation in graph.get("relations", []):
        if str(relation.get("from", "")).startswith("event-") and str(relation.get("to", "")).strip() == entity_id:
            event_id = str(relation.get("from", "")).strip()
            mention = story_by_event.get(event_id, {})
            title = str(mention.get("title", "")).strip()
            if title and title not in actions:
                actions.append(title)
        elif str(relation.get("to", "")).startswith("event-") and str(relation.get("from", "")).strip() == entity_id:
            event_id = str(relation.get("to", "")).strip()
            mention = story_by_event.get(event_id, {})
            title = str(mention.get("title", "")).strip()
            if title and title not in actions:
                actions.append(title)
    return actions[:limit]


def _relation_action_lines(graph: dict[str, Any], entity_id: str, limit: int = 10) -> list[str]:
    lines: list[str] = []
    action_relations = {
        "holds_office_in": "holds office in",
        "leads": "leads",
        "member_of": "member of",
        "board_member_of": "board member of",
        "owns_or_controls": "controls",
        "funded_by": "funded by",
        "authored": "authored",
        "coauthored": "coauthored",
        "voted_for": "voted for",
        "voted_against": "voted against",
        "implemented_by": "implemented",
        "announced_by": "announced",
        "criticized_by": "criticized by",
        "publicly_supported": "publicly supported",
        "publicly_opposed": "publicly opposed",
        "aligned_with": "aligned with",
        "opposes": "opposes",
        "monitors": "monitors",
        "covers": "covers",
    }
    for relation in graph.get("relations", []):
        relation_type = str(relation.get("relation_type", "")).strip()
        if relation_type not in action_relations:
            continue
        if str(relation.get("from", "")).strip() == entity_id:
            other_id = str(relation.get("to", "")).strip()
            line = f"{action_relations[relation_type]} {_entity_name(graph, other_id)}"
        elif str(relation.get("to", "")).strip() == entity_id:
            other_id = str(relation.get("from", "")).strip()
            reverse_type = "covered by" if relation_type == "covers" else ("monitored by" if relation_type == "monitors" else f"linked to {_entity_name(graph, other_id)} via {relation_type}")
            line = reverse_type if relation_type in {"covers", "monitors"} else f"{action_relations[relation_type]} {_entity_name(graph, other_id)}"
        else:
            continue
        if line not in lines:
            lines.append(line)
    return lines[:limit]


def _profile_perspectives(graph: dict[str, Any], entity: dict[str, Any], limit: int = 5) -> list[dict[str, str]]:
    entity_id = str(entity.get("id", "")).strip()
    perspectives: list[dict[str, str]] = []
    relation_lines: dict[str, list[str]] = {
        "party": [],
        "opponents": [],
        "media": [],
        "institutions": [],
    }
    for relation in graph.get("relations", []):
        from_id = str(relation.get("from", "")).strip()
        to_id = str(relation.get("to", "")).strip()
        if entity_id not in {from_id, to_id}:
            continue
        other_id = to_id if from_id == entity_id else from_id
        other_name = _entity_name(graph, other_id)
        other_entity = next((row for row in graph.get("entities", []) if str(row.get("id", "")).strip() == other_id), {})
        other_subtype = str(other_entity.get("subtype", "")).strip()
        other_category = str(other_entity.get("category", "")).strip()
        relation_type = str(relation.get("relation_type", "")).strip()
        if "party" in other_subtype or other_id.startswith("party-"):
            relation_lines["party"].append(f"{relation_type} {other_name}")
        elif relation_type in {"opposes", "publicly_opposed", "criticized_by"}:
            relation_lines["opponents"].append(f"{relation_type} {other_name}")
        elif "media" in other_subtype or other_id.startswith("media-"):
            relation_lines["media"].append(f"{relation_type} {other_name}")
        elif other_category in {"institution", "organization"}:
            relation_lines["institutions"].append(f"{relation_type} {other_name}")
    labels = {
        "party": "Party perspective",
        "opponents": "Opponent perspective",
        "media": "Media perspective",
        "institutions": "Institutional perspective",
    }
    for key, lines in relation_lines.items():
        unique = []
        for line in lines:
            if line not in unique:
                unique.append(line)
        if unique:
            perspectives.append({"label": labels[key], "text": "; ".join(unique[:4])})
    return perspectives[:limit]


def _build_entity_profile(graph: dict[str, Any], entity: dict[str, Any]) -> dict[str, Any]:
    entity_id = str(entity.get("id", "")).strip()
    category = str(entity.get("category", "")).strip()
    subtype = str(entity.get("subtype", "")).strip()
    links = entity.get("links", {}) if isinstance(entity.get("links", {}), dict) else {}
    if category == "person":
        direct_links, indirect_links = _person_network(graph, entity_id)
        events = _person_events(graph, entity_id)
        role_lines = _person_role_lines(direct_links)
        biography: list[str] = []
        for item in [_clean_profile_text(entity.get("summary") or ""), *_entity_history_lines(entity)]:
            if item and item not in biography:
                biography.append(item)
        for event in events[:5]:
            event_line = f"{event.get('date')}: {event.get('summary') or event.get('title')}".strip(": ")
            event_line = _clean_profile_text(event_line)
            if event_line and event_line not in biography:
                biography.append(event_line)
        evidence = []
        for item in direct_links:
            url = str(item.get("provenance") or "").strip()
            if url and url not in evidence:
                evidence.append(url)
        for item in events:
            url = str(item.get("url") or "").strip()
            if url and url not in evidence:
                evidence.append(url)
        overview = _compose_person_overview(entity, direct_links)
        actions = []
        for event in events[:6]:
            line = _clean_profile_text(event.get("summary") or event.get("title") or "")
            if line and line not in actions:
                actions.append(line)
        if not actions:
            for item in direct_links[:6]:
                line = str(item.get("human_text") or item.get("note") or "").strip()
                if not line:
                    name = str(item.get("name") or item.get("entity_id") or "").strip()
                    line = f"{entity.get('name')} {item.get('type', '').replace('_', ' ')} {name}".strip()
                line = _clean_profile_text(line)
                if line and line not in actions:
                    actions.append(line)
        perspectives = [
            {"label": "Current roles", "text": "; ".join(role_lines)} if role_lines else None,
            {"label": "Direct network", "text": f"{len(direct_links)} direct links across parties, institutions, organizations, and events."},
            {"label": "Indirect network", "text": f"{len(indirect_links)} second-hop person links through shared parties, institutions, or events."},
            {"label": "Event coverage", "text": f"{len(events)} linked events in the current graph timeline."},
        ]
        return {
            "updated_at": iso_now(),
            "overview": overview,
            "biography": biography[:8],
            "history": [f"{row.get('date')}: {row.get('title')}".strip(": ") for row in events[:8] if row.get("title")],
            "perspectives": [item for item in perspectives if item],
            "actions": actions[:12],
            "links": evidence[:8],
            "evidence": evidence[:8],
            "current_roles": role_lines[:8],
            "network": {
                "direct": direct_links,
                "indirect": indirect_links,
            },
            "timeline": events[:8],
            "source_labels": list(links.keys())[:8],
            "recent_event_count": len(events),
        }
    relation_actions = _relation_action_lines(graph, entity_id, limit=10)
    story_actions = _entity_story_actions(graph, entity_id, limit=8)
    combined_actions = []
    for item in [*relation_actions, *story_actions]:
        cleaned = _clean_profile_text(item)
        if cleaned and cleaned not in combined_actions:
            combined_actions.append(cleaned)
    history = _clean_profile_text(entity.get("summary") or entity.get("notes") or "")
    if not history:
        fallback_parts = [f"{entity.get('name')} is an Armenia-related {subtype or category or 'entity'}."]
        if relation_actions:
            fallback_parts.append(f"Known links: {', '.join(relation_actions[:4])}.")
        history = " ".join(fallback_parts)
    overview_parts = [_clean_profile_text(entity.get("summary") or ""), history]
    overview = " ".join(part for part in overview_parts if part).strip()
    return {
        "updated_at": iso_now(),
        "overview": overview,
        "history": history,
        "perspectives": _profile_perspectives(graph, entity),
        "actions": combined_actions[:12],
        "source_labels": list(links.keys())[:8],
        "recent_event_count": len(story_actions),
    }


def _touched_entity_ids_from_extractions(extractions: list[dict[str, Any]], graph: dict[str, Any]) -> list[str]:
    touched: list[str] = []
    seen: set[str] = set()
    for extraction in extractions:
        for person in extraction.get("people", []):
            entity_id, _ = _resolve_entity_id(
                str(person.get("name", "")).strip(),
                graph,
                category="person",
                subtype="politician",
            )
            if entity_id and entity_id not in seen:
                seen.add(entity_id)
                touched.append(entity_id)
        for org in extraction.get("organizations", []):
            org_name = str(org.get("name", "")).strip()
            org_type = str(org.get("type", "organization") or "organization").strip()
            subtype = "party" if org_type == "party" else ("news_outlet" if org_type == "media" else org_type)
            entity_id, _ = _resolve_entity_id(org_name, graph, category="organization", subtype=subtype)
            if entity_id and entity_id not in seen:
                seen.add(entity_id)
                touched.append(entity_id)
    return touched


def _pruned_discovered_entities(names: list[str]) -> list[str]:
    pruned: list[str] = []
    seen: set[str] = set()
    for raw in names:
        name = str(raw or "").strip()
        if not name:
            continue
        if not (_looks_like_person_name(name) or _looks_like_org_name(name)):
            continue
        normalized = normalize_text(name)
        if normalized in seen:
            continue
        seen.add(normalized)
        pruned.append(name)
    return pruned[-DISCOVERED_ENTITY_LIMIT:]


def _enrich_entity_profiles(graph: dict[str, Any], entity_ids: list[str]) -> int:
    touched = 0
    wanted = {str(item).strip() for item in entity_ids if str(item).strip()}
    if not wanted:
        return 0
    for entity in graph.get("entities", []):
        entity_id = str(entity.get("id", "")).strip()
        if entity_id not in wanted:
            continue
        if str(entity.get("category", "")).strip() not in {"person", "organization", "media", "institution"}:
            continue
        profile = _build_entity_profile(graph, entity)
        entity["profile"] = profile
        entity["summary"] = profile.get("overview", entity.get("summary", ""))
        entity["updated_at"] = iso_now()
        touched += 1
    return touched


def run_crawl_round(
    budget: int = 12,
    verbose: bool = False,
) -> dict[str, Any]:
    """Execute a single crawl round."""
    ensure_layout()
    # Ensure logs dir exists
    CRAWL_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    graph = load_graph()
    seeds = load_party_seeds()
    state = load_crawl_state()

    targets = _build_search_urls(seeds, state, limit=budget)
    if verbose:
        print(f"[party_crawler] Round {state.get('round_count', 0) + 1}: {len(targets)} targets", file=sys.stderr)

    all_extractions: list[dict[str, Any]] = []
    visited_this_round: list[str] = []
    failed: list[dict[str, Any]] = []

    for target in targets:
        url = target["url"]
        visited_this_round.append(url)

        body, content_type = fetch_url(url, timeout=10)
        if not body:
            failed.append({"url": url, "error": content_type or "fetch_failed"})
            if verbose:
                print(f"  [FAIL] {url}: {content_type}", file=sys.stderr)
            continue

        # For search result pages, extract actual URLs and crawl those too
        if target["kind"] in {"web_search", "snowball_search"}:
            result_urls = _extract_search_result_urls(body)
            already_visited = set(_visited_round_map(state))
            already_visited.update(visited_this_round)
            for result_url in result_urls[:4]:
                if result_url in already_visited and not _should_visit_url(result_url, "search_result", state):
                    continue
                visited_this_round.append(result_url)
                result_body, result_ct = fetch_url(result_url, timeout=8)
                if result_body:
                    extraction = _parse_with_local_model(result_body, result_url)
                    extraction["source_url"] = result_url
                    extraction["source_kind"] = "search_result"
                    extraction["source_party"] = target.get("party_name", "")
                    if extraction.get("people") or extraction.get("organizations") or extraction.get("connections"):
                        all_extractions.append(extraction)
                        if verbose:
                            print(f"  [OK] {result_url}: {len(extraction.get('people', []))}p {len(extraction.get('organizations', []))}o", file=sys.stderr)
        else:
            extraction = _parse_with_local_model(body, url)
            extraction["source_url"] = url
            extraction["source_kind"] = target.get("kind", "direct")
            extraction["source_party"] = target.get("party_name", "")
            if extraction.get("people") or extraction.get("organizations") or extraction.get("connections"):
                all_extractions.append(extraction)
                if verbose:
                    print(f"  [OK] {url}: {len(extraction.get('people', []))}p {len(extraction.get('organizations', []))}o", file=sys.stderr)

    # Phase 2: Use smart model to create graph proposal
    proposal = {}
    touched_ids = set(_touched_entity_ids_from_extractions(all_extractions, graph))
    if all_extractions:
        if verbose:
            print(f"[party_crawler] Creating graph proposal from {len(all_extractions)} extractions...", file=sys.stderr)
        graph = load_graph()  # Reload in case it changed
        proposal = _create_graph_proposal(all_extractions, graph)

    # Phase 3: Apply entities first (always safe), then verify+apply relations
    stats = {"entities_added": 0, "relations_added": 0, "relations_strengthened": 0}
    profile_updates = 0
    if proposal and (proposal.get("entities") or proposal.get("relations")):
        verification = verify_graph_proposal(graph, {
            "entities": proposal.get("entities", []),
            "relations": proposal.get("relations", []),
            "proposal_kind": "party_crawler_round",
        })
        if verification.get("verdict") == "reject":
            rejected = []
            valid_relations = []
            for relation in proposal.get("relations", []):
                relation_check = verify_graph_proposal(graph, {
                    "entities": [],
                    "relations": [relation],
                    "proposal_kind": "party_crawler_relation",
                })
                if relation_check.get("verdict") == "reject":
                    rejected.append(relation)
                    continue
                valid_relations.append(relation)
            proposal = {
                **proposal,
                "relations": valid_relations,
                "rejected_relations": rejected,
                "verification": verification,
            }
        # Always add new entities — they're safe (just new nodes)
        entity_stats = _apply_proposal_to_graph(graph, {
            "entities": proposal.get("entities", []),
            "relations": [],  # Relations applied separately after safety check
        })
        stats["entities_added"] = entity_stats["entities_added"]

        # Now apply relations — only where both endpoints exist in the graph
        existing_entity_ids = {str(e.get("id", "")) for e in graph.get("entities", [])}
        valid_relations = [
            r for r in proposal.get("relations", [])
            if str(r.get("from", "")).strip() in existing_entity_ids
            and str(r.get("to", "")).strip() in existing_entity_ids
        ]
        if valid_relations:
            rel_stats = _apply_proposal_to_graph(graph, {
                "entities": [],
                "relations": valid_relations,
            })
            stats["relations_added"] = rel_stats["relations_added"]
            stats["relations_strengthened"] = rel_stats["relations_strengthened"]

        if stats["entities_added"] or stats["relations_added"]:
            for entity in proposal.get("entities", []):
                if isinstance(entity, dict):
                    entity_id = str(entity.get("id", "")).strip()
                    if entity_id:
                        touched_ids.add(entity_id)
            for relation in proposal.get("relations", []):
                if isinstance(relation, dict):
                    for key in ("from", "to"):
                        value = str(relation.get(key, "")).strip()
                        if value and not value.startswith("event-"):
                            touched_ids.add(value)
        elif verbose:
            print(f"[party_crawler] No new entities or valid relations to add", file=sys.stderr)
    if touched_ids:
        profile_updates = _enrich_entity_profiles(graph, sorted(touched_ids))
    if stats["entities_added"] or stats["relations_added"] or stats["relations_strengthened"] or profile_updates:
        write_json(CANONICAL_GRAPH, graph)
        if verbose:
            print(f"[party_crawler] Applied: +{stats['entities_added']}e +{stats['relations_added']}r ~{stats['relations_strengthened']}r profiles={profile_updates}", file=sys.stderr)

    # Update crawl state
    existing_visited_log = [row for row in state.get("visited_log", []) if isinstance(row, dict)]
    current_round = int(state.get("round_count", 0) or 0) + 1
    for url in visited_this_round:
        clean_url = str(url).strip()
        if not clean_url:
            continue
        existing_visited_log.append({
            "url": clean_url,
            "kind": "round_visit",
            "round": current_round,
            "visited_at": iso_now(),
        })
    state["visited_log"] = existing_visited_log[-VISITED_LOG_LIMIT:]
    recent_urls: list[str] = []
    seen_recent: set[str] = set()
    for entry in reversed(state["visited_log"]):
        url = str(entry.get("url", "")).strip()
        if url and url not in seen_recent:
            seen_recent.add(url)
            recent_urls.append(url)
        if len(recent_urls) >= VISITED_URL_LIMIT:
            break
    state["visited_urls"] = list(reversed(recent_urls))

    # Track discovered entities for snowball
    new_names = []
    for extraction in all_extractions:
        for person in extraction.get("people", []):
            name = str(person.get("name", "")).strip()
            if name:
                new_names.append(name)
        for org in extraction.get("organizations", []):
            name = str(org.get("name", "")).strip()
            if name:
                new_names.append(name)
    existing_discovered = list(state.get("discovered_entities", []))
    existing_discovered.extend(new_names)
    state["discovered_entities"] = _pruned_discovered_entities(existing_discovered)

    state["round_count"] = int(state.get("round_count", 0)) + 1
    state["last_round_at"] = iso_now()
    state["total_entities_added"] = int(state.get("total_entities_added", 0)) + stats["entities_added"]
    state["total_relations_added"] = int(state.get("total_relations_added", 0)) + stats["relations_added"]
    save_crawl_state(state)

    # Log round
    round_log = {
        "recorded_at": iso_now(),
        "action": "party_crawl_round",
        "round": state["round_count"],
        "targets": len(targets),
        "visited": len(visited_this_round),
        "extractions": len(all_extractions),
        "failed": len(failed),
        "entities_added": stats["entities_added"],
        "relations_added": stats["relations_added"],
        "relations_strengthened": stats["relations_strengthened"],
        "news_items": len(proposal.get("news_items", [])) if proposal else 0,
        "cross_party_connections": len(proposal.get("cross_party_connections", [])) if proposal else 0,
        "profile_updates": profile_updates,
    }
    append_jsonl(EVIDENCE_LOG, [round_log])
    append_jsonl(CRAWL_LOG_FILE, [round_log])

    return {
        "ok": True,
        "round": state["round_count"],
        "targets": len(targets),
        "visited": len(visited_this_round),
        "extractions": len(all_extractions),
        "failed": len(failed),
        "stats": stats,
        "proposal_entities": len(proposal.get("entities", [])) if proposal else 0,
        "proposal_relations": len(proposal.get("relations", [])) if proposal else 0,
        "news_items": proposal.get("news_items", []) if proposal else [],
        "cross_party_connections": proposal.get("cross_party_connections", []) if proposal else [],
        "verification": proposal.get("verification", {}) if proposal else {},
        "profile_updates": profile_updates,
        "touched_entity_ids": sorted(touched_ids)[:24],
        "graph_summary": {
            "entities": len(graph.get("entities", [])),
            "relations": len(graph.get("relations", [])),
        },
    }


def run_continuous(interval: int = 600, budget: int = 12, verbose: bool = True) -> None:
    """Run continuous crawl loop."""
    print(f"[party_crawler] Starting continuous crawl (interval={interval}s, budget={budget})", file=sys.stderr)
    round_number = 0
    while True:
        round_number += 1
        try:
            result = run_crawl_round(budget=budget, verbose=verbose)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print(f"\n[party_crawler] Round {round_number} complete. "
                  f"+{result['stats']['entities_added']}e +{result['stats']['relations_added']}r. "
                  f"Graph: {result['graph_summary']['entities']}e {result['graph_summary']['relations']}r. "
                  f"Sleeping {interval}s...",
                  file=sys.stderr)
        except KeyboardInterrupt:
            print("\n[party_crawler] Interrupted. Exiting.", file=sys.stderr)
            break
        except Exception as exc:
            print(f"[party_crawler] Round {round_number} error: {exc}", file=sys.stderr)
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[party_crawler] Interrupted. Exiting.", file=sys.stderr)
            break


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Continuous political party crawler for Thiezer graph")
    parser.add_argument("--once", action="store_true", help="Run a single round then exit")
    parser.add_argument("--interval", type=int, default=600, help="Seconds between crawl rounds (default: 600)")
    parser.add_argument("--budget", type=int, default=12, help="Max URLs to process per round (default: 12)")
    parser.add_argument("--verbose", action="store_true", default=True, help="Print progress to stderr")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    verbose = not args.quiet

    if args.once:
        result = run_crawl_round(budget=max(1, args.budget), verbose=verbose)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    run_continuous(interval=max(30, args.interval), budget=max(1, args.budget), verbose=verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
