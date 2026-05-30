#!/usr/bin/env python3
"""Budgeted exploration worker for iterative Armenia-first graph expansion."""

from __future__ import annotations

import argparse
import base64
import html
import json
import re
from collections import defaultdict
from typing import Any
from urllib.parse import parse_qsl, quote_plus, unquote, urlparse

from ingest import build_candidate, entity_alias_terms, extract_source_items
from pipeline_common import (
    CANONICAL_GRAPH,
    EVIDENCE_LOG,
    EXPLORATION_QUEUE_FILE,
    EXPLORATION_RUNTIME_FILE,
    TASK_RUNTIME_FILE,
    append_jsonl,
    compact_summary,
    compact_title,
    ensure_layout,
    fetch_url,
    iso_now,
    load_graph,
    load_source_registry,
    normalize_text,
    short_host,
    stable_hash,
    translate_to_russian,
    write_json,
    write_jsonl,
)


def _query_terms(value: str) -> set[str]:
    normalized = normalize_text(value or "")
    if not normalized:
        return set()
    return {part for part in normalized.replace("-", " ").split() if part}


def _entity_blob(entity: dict[str, Any]) -> str:
    parts = [
        str(entity.get("id", "")),
        str(entity.get("name", "")),
        str(entity.get("summary", "")),
        str(entity.get("subtype", "")),
        str(entity.get("category", "")),
        " ".join(str(tag) for tag in entity.get("tags", []) or []),
        " ".join(str(alias) for alias in entity.get("aliases", []) or []),
    ]
    return normalize_text(" ".join(parts))


def _is_local_governance_query(query: str) -> bool:
    text = normalize_text(query or "")
    if not text:
        return False
    return any(
        token in text
        for token in [
            "local governance",
            "district",
            "district head",
            "head of community",
            "community head",
            "mayor",
            "governor",
            "marz",
            "marzpet",
            "region",
            "район",
            "мэр",
            "губернат",
            "главам районов",
            "главы районов",
            "համայնք",
            "մարզ",
            "մարզպետ",
            "քաղաքապետ",
        ]
    )


def _is_party_roster_query(query: str) -> bool:
    text = normalize_text(query or "")
    if not text:
        return False
    election_markers = [
        "election",
        "elections",
        "parliament",
        "parliamentary",
        "выбор",
        "парламент",
        "депутат",
        "պատգամավոր",
        "ընտր",
        "партии",
        "parties",
    ]
    roster_markers = [
        "all members",
        "members of",
        "party members",
        "member roster",
        "add them to graph",
        "connect all edges",
        "member_of",
        "which parties",
        "who is affiliated",
        "party affiliations",
        "affiliated with",
        "подробный блог",
        "какие партии",
        "аффилированы",
    ]
    party_markers = [
        "civil contract",
        "republican party of armenia",
        "hhk",
        "քաղաքացիական պայմանագիր",
        "հհկ",
    ]
    return any(marker in text for marker in election_markers) or (any(marker in text for marker in roster_markers) and any(marker in text for marker in party_markers))


def _is_cabinet_query(query: str) -> bool:
    text = normalize_text(query or "")
    if not text:
        return False
    ministerial_markers = [
        "minister",
        "ministers",
        "ministry",
        "ministries",
        "cabinet",
        "министр",
        "министры",
        "министер",
        "кабинет",
        "նախարար",
        "նախարարներ",
        "gov-members",
        "government team members",
        "government composition",
        "ministry of",
    ]
    government_markers = [
        "government",
        "government of armenia",
        "prime minister",
        "правительство",
        "премьер",
        "կառավարություն",
        "վարչապետ",
    ]
    scope_markers = [
        "current",
        "history",
        "former",
        "period",
        "current roster",
        "composition",
        "сейчас",
        "были",
        "за период",
        "состав",
        "какие",
        "в целом",
    ]
    governance_structure_markers = [
        "structure",
        "gov-members",
        "team members",
        "composition",
        "government composition",
        "government structure",
        "minister roster",
        "cabinet roster",
        "structure of government",
        "структур",
        "состав",
        "կառուցվածք",
    ]
    has_ministerial = any(marker in text for marker in ministerial_markers)
    has_government = any(marker in text for marker in government_markers)
    has_government_structure = has_government and any(marker in text for marker in governance_structure_markers)
    return (has_ministerial or has_government_structure) and any(marker in text for marker in scope_markers)


def _is_institutional_roster_query(query: str) -> bool:
    text = normalize_text(query or "")
    if not text:
        return False
    if _is_cabinet_query(query):
        return True
    staff_markers = [
        "general staff",
        "chief of the general staff",
        "chief of general staff",
        "chiefs of the general staff",
        "chiefs of general staff",
        "defence staff",
        "defense staff",
        "генштаб",
        "начальник генштаба",
        "начальники генштаба",
        "генеральный штаб",
        "глава генштаба",
        "գլխավոր շտաբ",
        "գլխավոր շտաբի պետ",
        "գլխավոր շտաբի պետեր",
    ]
    scope_markers = [
        "current",
        "history",
        "former",
        "period",
        "list",
        "appointments",
        "dismissals",
        "changes",
        "timeline",
        "сейчас",
        "были",
        "за период",
        "назнач",
        "сняти",
        "истори",
        "изменени",
        "в целом",
        "պատմ",
        "նշանակ",
        "ազատ",
        "փոփոխ",
    ]
    return any(marker in text for marker in staff_markers) and any(marker in text for marker in scope_markers)


def _is_election_theme_query(query: str) -> bool:
    text = normalize_text(query or "")
    if not text:
        return False
    return any(
        marker in text
        for marker in [
            "election",
            "elections",
            "parliament",
            "parliamentary",
            "выбор",
            "парламент",
            "депутат",
            "politic",
            "полит",
            "party",
            "parties",
            "парт",
            "affiliat",
            "аффили",
            "coalition",
            "bloc",
        ]
    )


def _governance_seed_entities(graph: dict[str, Any], query: str) -> list[dict[str, Any]]:
    entities = list(graph.get("entities", []))
    query_terms = _query_terms(query)
    seeds: list[dict[str, Any]] = []
    for entity in entities:
        links = entity.get("links") or {}
        official_url = str(links.get("official") or "").strip()
        if not official_url:
            continue
        subtype = str(entity.get("subtype", "") or "")
        tags = {str(tag) for tag in entity.get("tags", []) or []}
        is_governance = subtype in {"marz", "marzpet", "district_head", "district", "mayor", "capital_city"} or "local-government" in tags
        if not is_governance:
            continue
        blob = _entity_blob(entity)
        lexical_hits = sum(1 for term in query_terms if term in blob)
        if _is_local_governance_query(query):
            lexical_hits += 3
        priority = 0.45 + min(0.45, lexical_hits * 0.08)
        if subtype in {"marz", "marzpet"}:
            priority += 0.12
        elif subtype in {"district_head", "district", "mayor", "capital_city"}:
            priority += 0.08
        seeds.append(
            {
                "id": str(entity.get("id") or ""),
                "name": str(entity.get("name") or ""),
                "subtype": subtype,
                "official_url": official_url,
                "priority": round(priority, 3),
                "summary": str(entity.get("summary") or ""),
            }
        )
    seeds.sort(key=lambda item: (float(item.get("priority", 0.0)), item.get("subtype", ""), item.get("name", "")), reverse=True)
    return seeds


def _party_seed_entities(graph: dict[str, Any], query: str) -> list[dict[str, Any]]:
    entities = list(graph.get("entities", []))
    query_blob = normalize_text(query)
    seeds: list[dict[str, Any]] = []
    for entity in entities:
        blob = _entity_blob(entity)
        if "party" not in blob and str(entity.get("category", "")) != "organization":
            continue
        if not any(token in blob for token in ["civil contract", "republican party of armenia", "hhk", "քաղաքացիական պայմանագիր", "հհկ"]):
            continue
        links = entity.get("links") or {}
        official_url = str(links.get("official") or links.get("site") or links.get("home") or "").strip()
        if not official_url:
            continue
        lexical_hits = sum(1 for term in _query_terms(query_blob) if term and term in blob)
        priority = 0.62 + min(0.28, lexical_hits * 0.04)
        if "civil contract" in blob or "republican party of armenia" in blob:
            priority += 0.08
        seeds.append(
            {
                "id": str(entity.get("id") or ""),
                "name": str(entity.get("name") or ""),
                "subtype": str(entity.get("subtype") or "party"),
                "official_url": official_url,
                "priority": round(priority, 3),
                "summary": str(entity.get("summary") or ""),
            }
        )
    seeds.sort(key=lambda item: (float(item.get("priority", 0.0)), item.get("name", "")), reverse=True)
    return seeds


def _decode_bing_url(href: str) -> str:
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
        return href
    except Exception:
        return href


def _dedupe_web_results(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(item)
    return result


def _search_web_bing(query: str, limit: int = 6) -> list[dict[str, Any]]:
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
        result_url = _decode_bing_url(raw_href)
        if not result_url or result_url.startswith("javascript:"):
            continue
        results.append({"title": title, "url": result_url, "host": short_host(result_url), "kind": "web_search"})
        if len(results) >= limit:
            break
    return _dedupe_web_results(results)


def _search_web_duckduckgo(query: str, limit: int = 6) -> list[dict[str, Any]]:
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    html_text, _ = fetch_url(url, timeout=15)
    if not html_text:
        return []
    results: list[dict[str, Any]] = []
    anchors = re.findall(r'<a[^>]+href="([^"]+)"[^>]*class="result__a"[^>]*>(.*?)</a>', html_text, flags=re.I | re.S)
    for href, raw_title in anchors[: max(limit * 2, limit)]:
        title = compact_title(re.sub(r"<[^>]+>", " ", raw_title))
        if not title:
            continue
        result_url = href
        if result_url.startswith("//"):
            result_url = "https:" + result_url
        if "duckduckgo.com/l/" in result_url and "uddg=" in result_url:
            try:
                parsed = urlparse(result_url)
                params = dict(parse_qsl(parsed.query, keep_blank_values=True))
                direct = params.get("uddg")
                if direct:
                    result_url = unquote(direct)
            except Exception:
                pass
        results.append({"title": title, "url": result_url, "host": short_host(result_url), "kind": "web_search"})
        if len(results) >= limit:
            break
    return _dedupe_web_results(results)


def _extract_cabinet_structure_items(target_url: str, body: str, *, limit: int = 24) -> list[dict[str, Any]]:
    host = short_host(target_url)
    if host not in {"gov.am", "primeminister.am"}:
        return []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    anchors = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', body, flags=re.I | re.S)
    for href, raw_text in anchors:
        title = compact_title(re.sub(r"<[^>]+>", " ", raw_text))
        if not title:
            continue
        blob = normalize_text(title)
        if not any(
            token in blob
            for token in [
                "minister",
                "ministry",
                "prime minister",
                "former prime ministers",
                "former ministers",
                "նախարար",
                "նախարարներ",
                "նախարարություն",
                "վարչապետ",
                "նախկին նախարար",
                "նախկին վարչապետ",
            ]
        ):
            continue
        url = href
        if url.startswith("/"):
            parsed = urlparse(target_url)
            url = f"{parsed.scheme}://{parsed.netloc}{url}"
        elif url.startswith("http://") or url.startswith("https://"):
            pass
        else:
            parsed = urlparse(target_url)
            base = f"{parsed.scheme}://{parsed.netloc}"
            url = f"{base}/{url.lstrip('/')}"
        if url in seen:
            continue
        seen.add(url)
        items.append(
            {
                "title": title,
                "url": url,
                "summary": title,
                "published_at": "",
            }
        )
        if len(items) >= limit:
            break
    return items


def _is_relevant_roster_result(item: dict[str, Any]) -> bool:
    title_blob = normalize_text(str(item.get("title") or ""))
    url_blob = normalize_text(str(item.get("url") or ""))
    host = short_host(str(item.get("url") or ""))
    relevant_hosts = {
        "hhk.am",
        "civilcontract.am",
        "parliament.am",
        "azatutyun.am",
        "armenpress.am",
        "1lurer.am",
        "civic.am",
        "hetq.am",
        "news.am",
        "bhk.am",
        "arfd.am",
        "brightarmenia.am",
        "elections.am",
        "factor.am",
        "civilnet.am",
        "aravot.am",
        "hraparak.am",
        "168.am",
        "evnreport.com",
        "en.wikipedia.org",
        "hy.wikipedia.org",
    }
    if host in relevant_hosts:
        return True
    must_have = [
        "armenia",
        "republican party of armenia",
        "civil contract",
        "քաղաքացիական պայմանագիր",
        "հհկ",
        "parliament.am",
    ]
    return any(token in title_blob or token in url_blob for token in must_have)


def _search_web(query: str, limit: int = 6) -> list[dict[str, Any]]:
    if not str(query or "").strip():
        return []
    candidates = _search_web_bing(query, limit=max(limit * 2, 8))
    if not candidates:
        candidates = _search_web_duckduckgo(query, limit=max(limit * 2, 8))
    return [item for item in candidates if _is_relevant_roster_result(item)][:limit]


def _cabinet_search_queries(query: str) -> list[str]:
    return [
        "site:gov.am Armenia government composition ministers official",
        "site:gov.am Armenia ministers official roster",
        "site:primeminister.am Government of Armenia structure ministers",
        "site:gov.am նախարարներ կառավարություն Հայաստան պաշտոնական",
        "site:gov.am министр Армения официальный",
        "Armenia minister appointment dismissal official gov.am",
        "Armenia cabinet ministers Pashinyan official history",
        str(query or "").strip(),
    ]


def _cabinet_seed_targets() -> list[dict[str, Any]]:
    return [
        {"name": "Government of Armenia", "url": "https://www.gov.am/en/structure/"},
        {"name": "Government Team Members", "url": "https://www.gov.am/en/gov-members/"},
        {"name": "Prime Minister of Armenia", "url": "https://www.primeminister.am/en/"},
        {"name": "Government of Armenia", "url": "https://www.gov.am/hy/structure/"},
        {"name": "Government Team Members", "url": "https://www.gov.am/hy/gov-members/"},
        {"name": "Prime Minister of Armenia", "url": "https://www.primeminister.am/hy/"},
    ]


def _general_staff_search_queries(query: str) -> list[str]:
    return [
        "site:mil.am Armenia Chief of the General Staff official",
        "site:gov.am Armenia Chief of General Staff official",
        "site:mil.am Edvard Asryan Chief of the General Staff",
        "site:mil.am Kamo Kochunts acting Chief of General Staff",
        "site:gov.am Onik Gasparyan Chief of General Staff relieved",
        "site:mil.am Armenia General Staff structure",
        "site:gov.am Armenia General Staff structure",
        str(query or "").strip(),
    ]


def _general_staff_seed_targets() -> list[dict[str, Any]]:
    return [
        {"name": "General Staff Structure", "url": "https://www.gov.am/en/structure/17"},
        {"name": "General Staff Structure", "url": "https://www.mil.am/index.php/en/structures/2"},
        {"name": "Edvard Asryan", "url": "https://www.mil.am/en/persons/99"},
        {"name": "Chief of General Staff of RA", "url": "https://www.mil.am/en/persons/99"},
    ]


def _html_to_text(body: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", body, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _html_to_lines(body: str) -> list[str]:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", body, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"</(p|div|li|h1|h2|h3|h4|tr|section|article)>", "\n", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return [line for line in lines if line]


def _clean_person_name(value: str) -> str:
    text = compact_title(value)
    if not text:
        return ""
    text = re.sub(r"\b(lieutenant general|major general|colonel general|general|lt\.?\s*gen\.?)\b", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" ,:-")
    if len(text.split()) < 2:
        return ""
    return text


def _record_key(record: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(record.get("person_name") or "").strip(),
        str(record.get("office_name") or "").strip(),
        str(record.get("institution_name") or "").strip(),
        str(record.get("event_type") or "").strip(),
        str(record.get("effective_date") or "").strip(),
    )


def _dedupe_roster_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for record in records:
        key = _record_key(record)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _extract_official_roster_records(target_url: str, body: str) -> list[dict[str, Any]]:
    host = short_host(target_url)
    text = _html_to_text(body)
    lines = _html_to_lines(body)
    blob = normalize_text(text)
    records: list[dict[str, Any]] = []

    if host == "gov.am":
        seen_pairs: set[tuple[str, str]] = set()
        for ministry, person in re.findall(
            r'class="min-name">\s*(Ministry of[^<]+?)</a>\s*<br\s*/?>\s*Minister:\s*<a [^>]+>\s*([^<]+?)\s*</a>',
            body,
            flags=re.I | re.S,
        ):
            office_name = compact_title(f"Minister of {ministry.replace('Ministry of ', '').strip()}")
            person_name = _clean_person_name(person)
            institution_name = compact_title(ministry)
            if not office_name or not person_name or not institution_name:
                continue
            key = (institution_name, person_name)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            records.append(
                {
                    "record_type": "office_holder",
                    "person_name": person_name,
                    "office_name": office_name,
                    "institution_name": institution_name,
                    "parent_institution_name": "Government of Armenia",
                    "source_url": target_url,
                    "source_type": "official",
                    "confidence": 0.93,
                    "evidence_quote": compact_summary(f"{institution_name} Minister: {person_name}"),
                }
            )
        if not records:
            for index, line in enumerate(lines):
                if not line.startswith("Ministry of "):
                    continue
                next_line = lines[index + 1] if index + 1 < len(lines) else ""
                if not next_line.startswith("Minister:"):
                    continue
                institution_name = compact_title(line)
                person_name = _clean_person_name(next_line.replace("Minister:", "", 1).strip())
                office_name = compact_title(f"Minister of {institution_name.replace('Ministry of ', '').strip()}")
                if not office_name or not person_name or not institution_name:
                    continue
                records.append(
                    {
                        "record_type": "office_holder",
                        "person_name": person_name,
                        "office_name": office_name,
                        "institution_name": institution_name,
                        "parent_institution_name": "Government of Armenia",
                        "source_url": target_url,
                        "source_type": "official",
                        "confidence": 0.93,
                        "evidence_quote": compact_summary(f"{institution_name} Minister: {person_name}"),
                    }
                )
        chief_line = next((line for line in lines if line.startswith("Chief of General Staff of RA Armed Forces:")), "")
        if chief_line:
            person_name = _clean_person_name(chief_line.split(":", 1)[1].strip())
            if person_name:
                records.append(
                    {
                        "record_type": "office_holder",
                        "person_name": person_name,
                        "office_name": "Chief of the General Staff of the Armed Forces",
                        "institution_name": "General Staff of the Armed Forces of Armenia",
                        "parent_institution_name": "Ministry of Defense of Armenia",
                        "source_url": target_url,
                        "source_type": "official",
                        "confidence": 0.94,
                        "evidence_quote": compact_summary(chief_line),
                    }
                )

    if host == "mil.am":
        current_match = re.search(r"CHIEF OF GENERAL STAFF OF RA\s+([A-Z][A-Za-z -]+)", text, flags=re.I)
        if current_match:
            person_name = _clean_person_name(current_match.group(1))
            if person_name:
                records.append(
                    {
                        "record_type": "office_holder",
                        "person_name": person_name,
                        "office_name": "Chief of the General Staff of the Armed Forces",
                        "institution_name": "General Staff of the Armed Forces of Armenia",
                        "parent_institution_name": "Ministry of Defense of Armenia",
                        "source_url": target_url,
                        "source_type": "official",
                        "confidence": 0.95,
                        "evidence_quote": compact_summary(current_match.group(0)),
                    }
                )
        appointment_match = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})\s+Has been appointed Chief of the General Staff of the RA Armed Forces", text)
        if appointment_match:
            person_name = ""
            for line_match in re.findall(r"CHIEF OF GENERAL STAFF OF RA\s+([A-Z][A-Za-z -]+)|\b([A-Z][A-Za-z -]+)\s+lieutenant general\b", text, flags=re.I):
                person_name = _clean_person_name(next((value for value in line_match if value), ""))
                if person_name:
                    break
            if person_name:
                records.append(
                    {
                        "record_type": "appointment",
                        "person_name": person_name,
                        "office_name": "Chief of the General Staff of the Armed Forces",
                        "institution_name": "General Staff of the Armed Forces of Armenia",
                        "parent_institution_name": "Ministry of Defense of Armenia",
                        "event_type": "appointed_to",
                        "effective_date": appointment_match.group(1).strip(),
                        "source_url": target_url,
                        "source_type": "official",
                        "confidence": 0.95,
                        "evidence_quote": compact_summary(appointment_match.group(0)),
                    }
                )
        acting_match = re.search(r"acting Chief of General Staff(?: of the Armed Forces)?[, ]+Lieutenant General\s+([A-Z][A-Za-z -]+)", text, flags=re.I)
        if acting_match:
            person_name = _clean_person_name(acting_match.group(1))
            if person_name:
                records.append(
                    {
                        "record_type": "office_holder",
                        "person_name": person_name,
                        "office_name": "Acting Chief of the General Staff of the Armed Forces",
                        "institution_name": "General Staff of the Armed Forces of Armenia",
                        "parent_institution_name": "Ministry of Defense of Armenia",
                        "status": "former",
                        "source_url": target_url,
                        "source_type": "official",
                        "confidence": 0.82,
                        "evidence_quote": compact_summary(acting_match.group(0)),
                    }
                )
        predecessor_match = re.search(r"thank Lieutenant General\s+([A-Z][A-Za-z -]+)\s+for performing the duties of the Chief of General Staff", text, flags=re.I)
        if predecessor_match:
            person_name = _clean_person_name(predecessor_match.group(1))
            if person_name:
                records.append(
                    {
                        "record_type": "office_holder",
                        "person_name": person_name,
                        "office_name": "Acting Chief of the General Staff of the Armed Forces",
                        "institution_name": "General Staff of the Armed Forces of Armenia",
                        "parent_institution_name": "Ministry of Defense of Armenia",
                        "status": "former",
                        "source_url": target_url,
                        "source_type": "official",
                        "confidence": 0.84,
                        "evidence_quote": compact_summary(predecessor_match.group(0)),
                    }
                )
        onik_match = re.search(r"Onik Gasparyan.*?relieved of (?:his )?post on ([A-Z][a-z]+ \d{1,2}, \d{4})", text, flags=re.I)
        if onik_match:
            records.append(
                {
                    "record_type": "removal",
                    "person_name": "Onik Gasparyan",
                    "office_name": "Chief of the General Staff of the Armed Forces",
                    "institution_name": "General Staff of the Armed Forces of Armenia",
                    "parent_institution_name": "Ministry of Defense of Armenia",
                    "event_type": "removed_from",
                    "effective_date": onik_match.group(1).strip(),
                    "source_url": target_url,
                    "source_type": "official",
                    "confidence": 0.9,
                    "evidence_quote": compact_summary(onik_match.group(0)),
                }
            )
        if "i was appointed chief of the general staff of the armed forces on june 8" in blob:
            records.append(
                {
                    "record_type": "appointment",
                    "person_name": "Onik Gasparyan",
                    "office_name": "Chief of the General Staff of the Armed Forces",
                    "institution_name": "General Staff of the Armed Forces of Armenia",
                    "parent_institution_name": "Ministry of Defense of Armenia",
                    "event_type": "appointed_to",
                    "effective_date": "June 8, 2020",
                    "source_url": target_url,
                    "source_type": "official",
                    "confidence": 0.86,
                    "evidence_quote": "I was appointed Chief of the General Staff of the Armed Forces on June 8 of this year",
                }
            )

    return _dedupe_roster_records(records)


def _party_roster_search_queries(query: str) -> list[str]:
    base_queries = [
        "\"Republican Party of Armenia\" members Armenia",
        "\"Republican Party of Armenia\" board members Armenia",
        "\"Civil Contract\" party members Armenia",
        "\"Civil Contract\" board members Armenia",
        "site:parliament.am \"Civil Contract\" deputies Armenia",
        "site:parliament.am \"Republican Party of Armenia\" deputies",
        "\"Prosperous Armenia\" party members Gagik Tsarukyan",
        "\"Armenian Revolutionary Federation\" Dashnaktsutyun members Armenia",
        "\"Bright Armenia\" party members Edmon Marukyan",
        "\"I Have Honor\" alliance Armenia members Robert Kocharyan",
        "\"Armenian National Congress\" members leadership",
        "site:parliament.am factions deputies list",
    ]
    normalized = normalize_text(query)
    if "connect all edges" in normalized:
        base_queries.append("Republican Party of Armenia Civil Contract relations Armenia politics")
    if _is_election_theme_query(query):
        base_queries = [
            "\"Civil Contract\" Armenia election candidates",
            "\"Republican Party of Armenia\" election Armenia",
            "\"Armenian Revolutionary Federation\" election Armenia",
            "\"Prosperous Armenia\" election Armenia",
            "\"Armenian National Congress\" election Armenia",
            "\"Bright Armenia\" election Armenia",
            "\"Armenia With Honor\" election Armenia",
            "\"Country for Life\" party Armenia election",
            "Armenia parliamentary election parties affiliations",
            "Armenia political parties alliances Russia West affiliations",
        ] + base_queries
    return base_queries


def _affiliated_org_search_queries() -> list[str]:
    """Search queries for discovering affiliated organizations."""
    return [
        "Armenia political party affiliated NGO organizations",
        "Armenia party-linked think tanks foundations",
        "Armenia political party youth wing organizations",
        "Armenia political donors party connections",
        "Armenian diaspora political organizations party ties",
    ]


def _cross_party_connection_queries() -> list[str]:
    """Search queries for finding cross-party connections."""
    return [
        "Armenia politician switched parties defected",
        "Armenia cross-party coalition members",
        "Armenia former Republican Party now Civil Contract",
        "Armenia politician party membership history",
        "Armenia political alliance coalition members",
    ]


def _media_affiliation_queries() -> list[str]:
    """Search queries for discovering media-party connections."""
    return [
        "Armenia media ownership political parties",
        "Armenia news outlet political affiliation bias",
        "Armenia TV channel ownership political connections",
        "Armenia media mogul party connections",
    ]


def build_queue(graph: dict[str, Any], *, topic: str = "", query: str = "", limit: int = 12) -> list[dict[str, Any]]:
    runtime_graph = graph.get("runtime", {}).get("graph", {})
    verified = list(runtime_graph.get("verified_story_pack", []))
    queue: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    query_terms = _query_terms(query)
    roster_query = _is_party_roster_query(query)
    cabinet_query = _is_cabinet_query(query)
    institutional_roster_query = _is_institutional_roster_query(query)
    election_theme_query = _is_election_theme_query(query)

    if _is_local_governance_query(query):
        for index, seed in enumerate(_governance_seed_entities(graph, query)[: max(4, min(limit, 16))]):
            target_url = str(seed.get("official_url") or "").strip()
            if not target_url or target_url in seen_urls:
                continue
            seen_urls.add(target_url)
            queue.append(
                {
                    "id": stable_hash(str(seed.get("id", "")), target_url, "governance_seed"),
                    "seed_story_id": "",
                    "seed_entity_id": seed.get("id", ""),
                    "seed_entity_name": seed.get("name", ""),
                    "topic": "local_governance",
                    "target_url": target_url,
                    "priority": round(float(seed.get("priority", 0.5)) + max(0.0, 0.1 - index * 0.01), 3),
                    "depth": 1,
                    "reason": f"governance_seed:{seed.get('subtype', 'entity')}",
                    "status": "queued",
                }
            )

    if cabinet_query:
        for index, seed in enumerate(_cabinet_seed_targets()):
            target_url = str(seed.get("url") or "").strip()
            if not target_url or target_url in seen_urls:
                continue
            seen_urls.add(target_url)
            queue.append(
                {
                    "id": stable_hash(str(seed.get("name", "")), target_url, "cabinet_seed"),
                    "seed_story_id": "",
                    "seed_entity_id": "",
                    "seed_entity_name": str(seed.get("name", "")),
                    "topic": "internal_politics",
                    "target_url": target_url,
                    "priority": round(0.96 - index * 0.03, 3),
                    "depth": 1,
                    "reason": "cabinet_seed:official_government",
                    "status": "queued",
                }
            )
        for query_index, search_query in enumerate(_cabinet_search_queries(query)[:6]):
            web_results = _search_web_bing(search_query, limit=5) or _search_web_duckduckgo(search_query, limit=5)
            for result_index, result in enumerate(web_results):
                target_url = str(result.get("url") or "").strip()
                if not target_url or target_url in seen_urls:
                    continue
                host = short_host(target_url)
                if not any(domain in host for domain in ["gov.am", "primeminister.am", "mfa.am", "mineconomy.am", "mil.am", "mod.am", "moj.am", "moh.am", "edu.am", "territorial.am", "hightech.gov.am", "env.am"]):
                    continue
                seen_urls.add(target_url)
                priority = 0.9 - query_index * 0.04 - result_index * 0.03
                queue.append(
                    {
                        "id": stable_hash(search_query, target_url, "cabinet_web_search"),
                        "seed_story_id": "",
                        "seed_entity_id": "",
                        "seed_entity_name": result.get("title", ""),
                        "topic": "internal_politics",
                        "target_url": target_url,
                        "priority": round(priority, 3),
                        "depth": 1,
                        "reason": f"cabinet_web_search:{search_query}",
                        "status": "queued",
                    }
                )

    if institutional_roster_query and not cabinet_query:
        for index, seed in enumerate(_general_staff_seed_targets()):
            target_url = str(seed.get("url") or "").strip()
            if not target_url or target_url in seen_urls:
                continue
            seen_urls.add(target_url)
            queue.append(
                {
                    "id": stable_hash(str(seed.get("name", "")), target_url, "general_staff_seed"),
                    "seed_story_id": "",
                    "seed_entity_id": "",
                    "seed_entity_name": str(seed.get("name", "")),
                    "topic": "internal_politics",
                    "target_url": target_url,
                    "priority": round(0.95 - index * 0.03, 3),
                    "depth": 1,
                    "reason": "institutional_roster_seed:general_staff",
                    "status": "queued",
                }
            )
        for query_index, search_query in enumerate(_general_staff_search_queries(query)[:6]):
            web_results = _search_web_bing(search_query, limit=5) or _search_web_duckduckgo(search_query, limit=5)
            for result_index, result in enumerate(web_results):
                target_url = str(result.get("url") or "").strip()
                if not target_url or target_url in seen_urls:
                    continue
                host = short_host(target_url)
                if not any(domain in host for domain in ["mil.am", "gov.am", "mod.am"]):
                    continue
                seen_urls.add(target_url)
                priority = 0.9 - query_index * 0.04 - result_index * 0.03
                queue.append(
                    {
                        "id": stable_hash(search_query, target_url, "general_staff_web_search"),
                        "seed_story_id": "",
                        "seed_entity_id": "",
                        "seed_entity_name": result.get("title", ""),
                        "topic": "internal_politics",
                        "target_url": target_url,
                        "priority": round(priority, 3),
                        "depth": 1,
                        "reason": f"institutional_roster_web_search:{search_query}",
                        "status": "queued",
                    }
                )

    if roster_query or election_theme_query:
        for index, seed in enumerate(_party_seed_entities(graph, query)[: max(2, min(limit, 8))]):
            target_url = str(seed.get("official_url") or "").strip()
            if not target_url or target_url in seen_urls:
                continue
            seen_urls.add(target_url)
            queue.append(
                {
                    "id": stable_hash(str(seed.get("id", "")), target_url, "party_seed"),
                    "seed_story_id": "",
                    "seed_entity_id": seed.get("id", ""),
                    "seed_entity_name": seed.get("name", ""),
                    "topic": "internal_politics",
                    "target_url": target_url,
                    "priority": round(float(seed.get("priority", 0.5)) + max(0.0, 0.08 - index * 0.01), 3),
                    "depth": 1,
                    "reason": f"party_seed:{seed.get('subtype', 'party')}",
                    "status": "queued",
                }
            )
        web_queries = _party_roster_search_queries(query)
        for query_index, search_query in enumerate(web_queries[:6]):
            web_results = _search_web(search_query, limit=4)
            for result_index, result in enumerate(web_results):
                target_url = str(result.get("url") or "").strip()
                if not target_url or target_url in seen_urls:
                    continue
                seen_urls.add(target_url)
                priority = 0.82 - query_index * 0.04 - result_index * 0.03
                host = short_host(target_url)
                if any(domain in host for domain in ["hhk.am", "civilcontract.am", "parliament.am"]):
                    priority += 0.12
                queue.append(
                    {
                        "id": stable_hash(search_query, target_url, "party_web_search"),
                        "seed_story_id": "",
                        "seed_entity_id": "",
                        "seed_entity_name": result.get("title", ""),
                        "topic": "internal_politics",
                        "target_url": target_url,
                        "priority": round(priority, 3),
                        "depth": 1,
                        "reason": f"web_search:{search_query}",
                        "status": "queued",
                    }
                )

    if (cabinet_query or roster_query or election_theme_query or institutional_roster_query) and queue:
        queue.sort(key=lambda row: float(row.get("priority", 0.0)), reverse=True)
        return queue[:limit]

    for story in verified:
        story_topic = str(story.get("topic", "") or "")
        if topic and story_topic != topic:
            continue
        story_blob = normalize_text(
            " ".join(
                [
                    str(story.get("title", "")),
                    str(story.get("summary", "")),
                    str(story.get("summary_line", "")),
                    story_topic,
                    " ".join(str(actor) for actor in story.get("actors_detected", []) or []),
                ]
            )
        )
        if query_terms and not any(term in story_blob for term in query_terms):
            if not (story_topic == "local_governance" and _is_local_governance_query(query)):
                continue
        study_links = list(story.get("study_links", []) or [])
        actor_ids = list(story.get("actors_detected", []) or [])
        base_priority = float(story.get("publication_score", 0.5) or 0.5)
        for index, link in enumerate(study_links[:3]):
            url = str(link.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            queue.append(
                {
                    "id": stable_hash(str(story.get("story_id", "")), url, str(index)),
                    "seed_story_id": story.get("story_id", ""),
                    "seed_entity_id": actor_ids[0] if actor_ids else "",
                    "topic": story.get("topic", ""),
                    "target_url": url,
                    "priority": round(base_priority + max(0.0, 0.2 - index * 0.05), 3),
                    "depth": 1,
                    "reason": str(link.get("kind") or "study_link"),
                    "status": "queued",
                }
            )
    queue.sort(key=lambda row: float(row.get("priority", 0.0)), reverse=True)
    return queue[:limit]


def source_for_target(target_url: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    host = short_host(target_url)
    for source in sources:
        source_host = short_host(str(source.get("url") or ""))
        if host and source_host and (host == source_host or host.endswith(source_host) or source_host.endswith(host)):
            return dict(source)
    if host and (
        host == "gov.am"
        or host == "primeminister.am"
        or host.endswith(".gov.am")
        or host.endswith(".am") and any(token in host for token in ["ministry", "minister", "mfa", "mineconomy", "mil", "mod", "moj", "moh", "edu", "territorial", "hightech", "env"])
    ):
        return {
            "id": f"official-{host}",
            "url": target_url,
            "source_name": host,
            "source_type": "official",
            "category": "official_baseline",
            "trust_weight": 0.92,
            "freshness_weight": 0.8,
            "coverage_tags": ["official", "armenia", "government"],
        }
    return {
        "id": f"seed-{host or 'unknown'}",
        "url": target_url,
        "source_name": host or target_url,
        "source_type": "external",
        "category": "external",
        "trust_weight": 0.5,
        "freshness_weight": 0.5,
        "coverage_tags": ["exploration"],
    }


def process_queue(graph: dict[str, Any], queue: list[dict[str, Any]], *, limit: int = 6) -> dict[str, Any]:
    sources = load_source_registry()
    alias_terms = entity_alias_terms(graph)
    discovered_candidates: list[dict[str, Any]] = []
    roster_records: list[dict[str, Any]] = []
    processed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for item in queue[:limit]:
        target_url = str(item.get("target_url") or "").strip()
        body, content_type = fetch_url(target_url, timeout=8)
        if not body:
            failed.append({**item, "status": "failed", "error": content_type or "fetch_failed"})
            continue
        extracted: list[dict[str, Any]] = []
        if "xml" in content_type.lower() or body.lstrip().startswith("<rss") or body.lstrip().startswith("<feed"):
            extracted = extract_source_items(
                {"url": target_url, "id": f"seed-{short_host(target_url) or 'unknown'}", "source_name": short_host(target_url) or target_url},
                body,
                content_type,
                limit=5,
            )
        else:
            extracted = extract_source_items(
                {"url": target_url, "id": f"seed-{short_host(target_url) or 'unknown'}", "source_name": short_host(target_url) or target_url},
                body,
                content_type,
                limit=5,
            )
            if "cabinet_seed:official_government" in str(item.get("reason") or ""):
                extracted = [*_extract_cabinet_structure_items(target_url, body, limit=24), *extracted]
        extracted_records = _extract_official_roster_records(target_url, body)
        for record in extracted_records:
            record["seed_reason"] = str(item.get("reason") or "")
            record["seed_entity_name"] = str(item.get("seed_entity_name") or "")
        roster_records.extend(extracted_records)
        source = source_for_target(target_url, sources)
        row_candidates: list[dict[str, Any]] = []
        for extracted_item in extracted[:4]:
            candidate = build_candidate(source, extracted_item, graph, alias_terms)
            if not candidate:
                continue
            candidate["exploration_seed_story_id"] = item.get("seed_story_id", "")
            candidate["exploration_seed_entity_id"] = item.get("seed_entity_id", "")
            candidate["exploration_depth"] = item.get("depth", 1)
            candidate["exploration_reason"] = item.get("reason", "")
            candidate["source_url"] = target_url
            candidate["translation"] = translate_to_russian(str(candidate.get("title", "")))
            row_candidates.append(candidate)
        discovered_candidates.extend(row_candidates)
        processed.append(
            {
                **item,
                "status": "processed",
                "content_type": content_type,
                "discovered_count": len(row_candidates),
                "roster_record_count": len(extracted_records),
                "discovered_titles": [candidate.get("title", "") for candidate in row_candidates[:4]],
            }
        )

    deduped: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for candidate in discovered_candidates:
        url = str(candidate.get("url") or "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        deduped.append(candidate)

    runtime = {
        "updated_at": iso_now(),
        "queue_count": len(queue),
        "processed_count": len(processed),
        "failed_count": len(failed),
        "candidate_count": len(deduped),
        "roster_record_count": len(_dedupe_roster_records(roster_records)),
        "seed_targets": [
            {
                "seed_entity_id": item.get("seed_entity_id", ""),
                "seed_entity_name": item.get("seed_entity_name", ""),
                "target_url": item.get("target_url", ""),
                "reason": item.get("reason", ""),
            }
            for item in queue[:24]
        ],
        "queue": processed + failed,
        "candidates": deduped[:60],
        "roster_records": _dedupe_roster_records(roster_records)[:120],
    }
    graph.setdefault("runtime", {})["exploration"] = runtime
    graph["updated_at"] = iso_now()

    write_json(CANONICAL_GRAPH, graph)
    write_json(EXPLORATION_RUNTIME_FILE, runtime)
    write_json(TASK_RUNTIME_FILE, {"updated_at": iso_now(), "last_exploration": runtime})
    write_jsonl(EXPLORATION_QUEUE_FILE, queue)
    append_jsonl(
        EVIDENCE_LOG,
        [
            {
                "recorded_at": iso_now(),
                "action": "exploration",
                "queue_count": len(queue),
                "processed_count": len(processed),
                "failed_count": len(failed),
                "candidate_count": len(deduped),
            }
        ],
    )
    return runtime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="", help="Optional topic filter for queue building.")
    parser.add_argument("--query", default="", help="Optional lexical guidance for seed selection.")
    parser.add_argument("--limit", type=int, default=12, help="Queue and process budget.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ensure_layout()
    graph = load_graph()
    queue = build_queue(graph, topic=args.topic, query=args.query, limit=max(1, args.limit))
    runtime = process_queue(graph, queue, limit=max(1, min(args.limit, 6)))
    existing_task_runtime = {}
    if TASK_RUNTIME_FILE.exists():
        from pipeline_common import load_json  # local import to avoid extra top-level noise

        existing_task_runtime = load_json(TASK_RUNTIME_FILE, {})
        if not isinstance(existing_task_runtime, dict):
            existing_task_runtime = {}
    merged_task_runtime = {
        **existing_task_runtime,
        "updated_at": iso_now(),
        "last_exploration": runtime,
    }
    write_json(TASK_RUNTIME_FILE, merged_task_runtime)
    print(
        json.dumps(
            {
                "ok": True,
                "stage": "explorer",
                "topic": args.topic,
                "query": args.query,
                "queue_count": len(queue),
                "runtime": runtime,
                "summary": {
                    "candidates": runtime.get("candidate_count", 0),
                    "processed": runtime.get("processed_count", 0),
                    "failed": runtime.get("failed_count", 0),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
