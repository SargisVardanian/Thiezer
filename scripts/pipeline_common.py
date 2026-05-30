#!/usr/bin/env python3
"""Shared deterministic helpers for the Thiezer Armenia-first pipeline."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import difflib
import subprocess
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urljoin, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
CONTENT_DIR = ROOT / "content"
GRAPH_DIR = CONTENT_DIR / "graph"
GRAPH_MIGRATIONS_DIR = GRAPH_DIR / "migrations"
EVALS_DIR = CONTENT_DIR / "evals"
EVALS_LATEST_DIR = EVALS_DIR / "latest"
PROMPTS_DIR = CONTENT_DIR / "prompts"
GRAPH_DIFFS_DIR = GRAPH_DIR / "diffs"
SESSIONS_DIR = CONTENT_DIR / "sessions"
ALIASES_DIR = CONTENT_DIR / "aliases"
DOSSIERS_DIR = CONTENT_DIR / "dossiers"
SOURCES_DIR = CONTENT_DIR / "sources"
RESEARCH_DIR = CONTENT_DIR / "research"
HISTORICAL_RESEARCH_DIR = RESEARCH_DIR / "historical"
HISTORICAL_BATCHES_DIR = HISTORICAL_RESEARCH_DIR / "batches"
HISTORICAL_STATE_FILE = HISTORICAL_RESEARCH_DIR / "state.json"
HISTORICAL_MANIFEST_FILE = HISTORICAL_RESEARCH_DIR / "manifest.json"
SYSTEM_DIR = CONTENT_DIR / "system"
PROMPT_STACK_FILE = PROMPTS_DIR / "prompt-stack.json"
TASK_RUNTIME_FILE = SYSTEM_DIR / "task-runtime.json"
TASK_RUNS_FILE = SYSTEM_DIR / "task-runs.jsonl"
EXPLORATION_QUEUE_FILE = SYSTEM_DIR / "exploration-queue.jsonl"
EXPLORATION_RUNTIME_FILE = SYSTEM_DIR / "exploration-runtime.json"
GRAPH_DIFF_LATEST_FILE = SYSTEM_DIR / "graph-diff-latest.json"
PUBLICATION_LEDGER_FILE = SYSTEM_DIR / "publication-ledger.jsonl"
PROPOSAL_LEDGER_FILE = SYSTEM_DIR / "proposal-ledger.jsonl"
CHANNEL_MIRROR_FILE = SYSTEM_DIR / "telegram-channel-mirror.json"

PIPELINE_CONFIG = CONFIG_DIR / "pipeline.yaml"
SOURCE_CAPABILITIES = CONFIG_DIR / "source_capabilities.yaml"
SOURCE_REGISTRY = SOURCES_DIR / "source-registry.json"
LEGACY_SOURCE_SEED = SOURCES_DIR / "armenia-source-seed.json"
CANONICAL_GRAPH = GRAPH_DIR / "country-graph.json"
EVIDENCE_LOG = GRAPH_DIR / "evidence-log.jsonl"
SCHEMA_FILE = GRAPH_DIR / "schema-v2.json"
SCHEMA_V3_FILE = GRAPH_DIR / "schema-v3.json"
GRAPH_MIGRATION_REPORT = GRAPH_MIGRATIONS_DIR / "latest-report.json"
RELATION_TYPES_FILE = GRAPH_DIR / "relation-types.json"
LOCAL_MODEL_CONFIG = SYSTEM_DIR / "local-model-config.json"
LEGACY_ENTITIES = GRAPH_DIR / "entities.json"
LEGACY_RELATIONS = GRAPH_DIR / "relations.json"
LEGACY_RELATION_TYPES = GRAPH_DIR / "relation-types.json"

DEFAULT_HEADERS = {
    "User-Agent": "ThiezerNewsroomBot/2.0 (+https://thiezer.local)",
    "Accept-Language": "hy,en,ru;q=0.8",
}

PUBLIC_POST_CHAT_HANDLE = "@thiezerarm"

OPS_VERBOSE_EVENT_TYPES = {
    "run_started",
    "stage_started",
    "stage_finished",
    "browser_mode_started",
    "browser_playwright_started",
    "browser_cdp_attached",
    "browser_visible_opened",
    "browser_fallback_system_open",
    "browser_mode_degraded",
    "entity_extracted",
    "page_visit_started",
    "page_visit_finished",
    "armenia_gate_reject",
    "dossier_refreshed",
    "relation_candidate_added",
    "relation_updated",
    "rerank_selected",
    "graph_update_applied",
    "memory_update_applied",
    "publish_candidate_ready",
    "publish_sent",
    "publish_skipped_duplicate",
    "self_repair_started",
    "self_repair_changed_file",
    "self_repair_finished",
    "browser_mode_started",
    "browser_playwright_started",
    "browser_cdp_attached",
    "browser_visible_opened",
    "browser_fallback_system_open",
    "browser_mode_degraded",
    "run_failed",
    "run_finished",
}

ARMENIA_KEYWORDS = {
    "armenia",
    "armenian",
    "yerevan",
    "syunik",
    "gegharkunik",
    "tavush",
    "kotayk",
    "gyumri",
    "artsakh",
    "armavir",
    "aragatsotn",
    "ararat",
    "armeni",
    "ереван",
    "армени",
    "армян",
    "հայաստան",
    "հայաստանի",
    "երևան",
    "գյումրի",
    "սյունիք",
    "տավուշ",
    "կոտայք",
    "արարատ",
    "արագածոտն",
    "արմավիր",
}

INSTITUTION_KEYWORDS = {
    "government of armenia",
    "ministry of economy",
    "ministry of foreign affairs",
    "national assembly",
    "constitutional court",
    "prime minister",
    "central bank of armenia",
    "government",
    "parliament",
    "նախարարություն",
    "կառավարություն",
    "ազգային ժողով",
    "վարչապետ",
    "մայրաքաղաք",
    "правительство армении",
    "национальное собрание армении",
    "конституционный суд",
    "мид армении",
}

UTILITY_PATTERNS = [
    r"\bweather\b",
    r"\bforecast\b",
    r"\btraffic\b",
    r"\bmaintenance\b",
    r"\boutage\b",
    r"\bplanned\b",
    r"\bhoroscope\b",
    r"\bsports?\b",
    r"\bcelebrity\b",
    r"\btest\b",
    r"\bquiz\b",
    r"եղանակ",
    r"կանխատես",
    r"հորոսկոպ",
    r"ֆուտբոլ",
    r"հավաքական",
    r"խաղ",
    r"մրցավեճ",
    r"спорт",
    r"футбол",
    r"сборн",
    r"погод",
    r"гороскоп",
]

TOPIC_PATTERNS = [
    ("economy", [r"econom", r"budget", r"tax", r"business", r"finance", r"investment", r"դրամ", r"տնտես", r"բյուջե", r"рынок", r"эконом", r"финанс"]),
    ("foreign_policy", [r"diplom", r"eu", r"russia", r"iran", r"turkey", r"azerbaijan", r"border", r"արտաքին", r"եվրամի", r"ռուսաստան", r"իրան", r"азербайдж", r"евросоюз"]),
    ("legal_human_rights", [r"court", r"rights", r"justice", r"corruption", r"prosecut", r"investigat", r"դատարան", r"իրավունք", r"կոռուպ", r"суд", r"прав", r"корруп"]),
    ("internal_politics", [r"parliament", r"prime minister", r"government", r"election", r"party", r"candidate", r"քպ", r"վարչապետ", r"կառավար", r"ընտր", r"кандидат", r"парламент", r"правитель", r"выбор"]),
    ("local_governance", [r"community", r"mayor", r"region", r"municipal", r"համայնք", r"մարզ", r"քաղաքապետ", r"регион", r"муницип"]),
    ("social_infrastructure_culture", [r"school", r"health", r"hospital", r"culture", r"infrastructure", r"housing", r"social", r"դպրոց", r"մշակույթ", r"առողջ", r"социаль", r"культур"]),
]

TOPIC_PRIORITY = {
    "internal_politics": 6,
    "economy": 5,
    "foreign_policy": 4,
    "legal_human_rights": 3,
    "local_governance": 2,
    "social_infrastructure_culture": 1,
    "utility": 0,
}

RELATION_TYPES = [
    "holds_office_in",
    "member_of",
    "appointed_by",
    "aligned_with",
    "opposes",
    "authored",
    "coauthored",
    "voted_for",
    "voted_against",
    "implemented_by",
    "licensed_by",
    "funded_by",
    "contracted_with_state",
    "owns_or_controls",
    "beneficial_owner_reported",
    "family_tie_public",
    "subject_of_legal_case",
    "watchdog_allegation",
    "media_claim_disputed",
    "criticized_by",
    "investigated_by",
    "publicly_supported",
    "publicly_opposed",
]


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_layout() -> None:
    for directory in [CONFIG_DIR, GRAPH_DIR, GRAPH_MIGRATIONS_DIR, SOURCES_DIR, SYSTEM_DIR, EVALS_LATEST_DIR, PROMPTS_DIR]:
        directory.mkdir(parents=True, exist_ok=True)
    for file_path in [TASK_RUNTIME_FILE, EXPLORATION_RUNTIME_FILE]:
        if not file_path.exists():
            write_json(file_path, {})
    if not GRAPH_DIFF_LATEST_FILE.exists():
        write_json(GRAPH_DIFF_LATEST_FILE, {})
    for file_path in [TASK_RUNS_FILE, EXPLORATION_QUEUE_FILE]:
        if not file_path.exists():
            file_path.write_text("", encoding="utf-8")
    if not PUBLICATION_LEDGER_FILE.exists():
        PUBLICATION_LEDGER_FILE.write_text("", encoding="utf-8")
    if not PROPOSAL_LEDGER_FILE.exists():
        PROPOSAL_LEDGER_FILE.write_text("", encoding="utf-8")
    if not CHANNEL_MIRROR_FILE.exists():
        write_json(CHANNEL_MIRROR_FILE, {"updated_at": iso_now(), "targets": {}})

    if not CANONICAL_GRAPH.exists():
        from graph_domain import default_graph_bundle

        write_json(CANONICAL_GRAPH, default_graph_bundle())
    if not EVIDENCE_LOG.exists():
        EVIDENCE_LOG.write_text("", encoding="utf-8")
    if not RELATION_TYPES_FILE.exists():
        write_json(RELATION_TYPES_FILE, relation_types_payload())
    if not SCHEMA_FILE.exists():
        write_json(
            SCHEMA_FILE,
            {
                "version": 2,
                "nodes": ["person", "organization", "institution", "party", "region", "country", "event"],
                "relations": RELATION_TYPES,
            },
        )
    if not SCHEMA_V3_FILE.exists():
        write_json(
            SCHEMA_V3_FILE,
            {
                "version": 3,
                "terminology": {
                    "entity": "вершина",
                    "relation": "ребро",
                    "claim": "утверждение",
                    "perspective": "перспектива",
                },
                "top_level": [
                    "schema_version",
                    "vertices",
                    "edges",
                    "claims",
                    "events",
                    "sources",
                    "evidence",
                    "perspectives",
                    "narratives",
                    "story_mentions",
                    "runtime",
                    "indexes",
                    "migration",
                ],
                "claim_confidence_dimensions": [
                    "extraction_confidence",
                    "source_reliability",
                    "cross_source_confirmation",
                    "interpretive_degree",
                    "publication_risk",
                    "entity_linking_confidence",
                    "temporal_consistency_confidence",
                    "graph_consistency_confidence",
                ],
            },
        )
    if not SOURCE_REGISTRY.exists():
        load_source_registry()
    if not LOCAL_MODEL_CONFIG.exists():
        write_json(LOCAL_MODEL_CONFIG, {})


def load_text(path: Path, default: str = "") -> str:
    if not path.exists():
        return default
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, UnicodeDecodeError):
        try:
            raw = path.read_bytes().decode("utf-8", errors="replace")
            return json.loads(raw)
        except Exception:
            return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path == CANONICAL_GRAPH and isinstance(payload, dict):
        from graph_domain import merge_graph_bundle

        existing = load_json(path, {})
        payload = merge_graph_bundle(existing if isinstance(existing, dict) else {}, payload)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def tail_jsonl(path: Path, limit: int = 20) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    result = []
    for line in lines[-limit:]:
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return result


def load_structured(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text)
    except Exception:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return default


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s\u0400-\u04ff\u0530-\u058f\u0590-\u05ff]", " ", value.lower())).strip()


_LATIN_TRANSLIT_MAP = {
    # Armenian
    "ա": "a", "բ": "b", "գ": "g", "դ": "d", "ե": "e", "զ": "z", "է": "e", "ը": "y", "թ": "t",
    "ժ": "zh", "ի": "i", "լ": "l", "խ": "kh", "ծ": "ts", "կ": "k", "հ": "h", "ձ": "dz", "ղ": "gh",
    "ճ": "ch", "մ": "m", "յ": "y", "ն": "n", "շ": "sh", "ո": "o", "չ": "ch", "պ": "p", "ջ": "j",
    "ռ": "r", "ս": "s", "վ": "v", "տ": "t", "ր": "r", "ց": "ts", "ւ": "v", "փ": "p", "ք": "q",
    "օ": "o", "ֆ": "f", "և": "ev",
    "Ա": "a", "Բ": "b", "Գ": "g", "Դ": "d", "Ե": "e", "Զ": "z", "Է": "e", "Ը": "y", "Թ": "t",
    "Ժ": "zh", "Ի": "i", "Լ": "l", "Խ": "kh", "Ծ": "ts", "Կ": "k", "Հ": "h", "Ձ": "dz", "Ղ": "gh",
    "Ճ": "ch", "Մ": "m", "Յ": "y", "Ն": "n", "Շ": "sh", "Ո": "o", "Չ": "ch", "Պ": "p", "Ջ": "j",
    "Ռ": "r", "Ս": "s", "Վ": "v", "Տ": "t", "Ր": "r", "Ց": "ts", "Ւ": "v", "Փ": "p", "Ք": "q",
    "Օ": "o", "Ֆ": "f",
    # Cyrillic
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ы": "y", "э": "e", "ю": "yu", "я": "ya", "ь": "", "ъ": "",
    "А": "a", "Б": "b", "В": "v", "Г": "g", "Д": "d", "Е": "e", "Ё": "e", "Ж": "zh", "З": "z",
    "И": "i", "Й": "y", "К": "k", "Л": "l", "М": "m", "Н": "n", "О": "o", "П": "p", "Р": "r",
    "С": "s", "Т": "t", "У": "u", "Ф": "f", "Х": "kh", "Ц": "ts", "Ч": "ch", "Ш": "sh", "Щ": "shch",
    "Ы": "y", "Э": "e", "Ю": "yu", "Я": "ya", "Ь": "", "Ъ": "",
}


def transliterate_text(value: str) -> str:
    return "".join(_LATIN_TRANSLIT_MAP.get(ch, ch) for ch in str(value or ""))


def canonical_name_key(value: str) -> str:
    text = transliterate_text(str(value or ""))
    text = normalize_text(text)
    text = re.sub(r"\b(mr|mrs|ms|dr|prof|hon)\b\.?", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def canonical_person_key(value: str) -> str:
    text = canonical_name_key(value)
    parts = text.split()
    if len(parts) >= 2 and parts[0].endswith("."):
        parts = parts[1:]
    return " ".join(parts)


def slugify(value: str) -> str:
    slug = normalize_text(value)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "item"


def short_host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").replace("www.", "")
    except ValueError:
        return ""


def stable_hash(*parts: str) -> str:
    digest = hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def score_overlap(left: str, right: str) -> float:
    left_tokens = set(normalize_text(left).split())
    right_tokens = set(normalize_text(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))


def tokenize(value: str) -> list[str]:
    return [token for token in normalize_text(value).split() if len(token) > 2]


def classify_topic(title: str, summary: str) -> str:
    text = normalize_text(f"{title} {summary}")
    for topic, patterns in TOPIC_PATTERNS:
        if any(re.search(pattern, text) for pattern in patterns):
            return topic
    if is_utility(title, summary):
        return "utility"
    return "social_infrastructure_culture"


def is_utility(title: str, summary: str) -> bool:
    text = normalize_text(f"{title} {summary}")
    return any(re.search(pattern, text) for pattern in UTILITY_PATTERNS)


def _source_registry_key(item: dict[str, Any]) -> str:
    url = str(item.get("url") or item.get("siteUrl") or "").strip()
    if url:
        host = short_host(url)
        if host:
            return host
    source_id = str(item.get("id") or item.get("source_id") or "").strip()
    if source_id:
        return source_id
    source_name = str(item.get("source_name") or item.get("name") or "").strip()
    return slugify(source_name)


def _normalize_source_registry_item(
    item: dict[str, Any],
    *,
    capability: dict[str, Any] | None = None,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    capability = capability or {}
    defaults = defaults or {}
    url = str(item.get("url") or item.get("siteUrl") or "").strip()
    host = short_host(url)
    category = str(item.get("category") or item.get("biasBucket") or capability.get("coverage_bucket") or "independent_watchdog")
    raw_source_type = str(item.get("source_type") or item.get("sourceType") or capability.get("source_type") or "")
    enabled_value = item.get("enabled", True)
    if isinstance(enabled_value, dict):
        enabled = bool(enabled_value.get("web", True))
    else:
        enabled = bool(enabled_value)
    normalized = {
        "id": str(item.get("id") or item.get("source_id") or slugify(str(item.get("name") or item.get("source_name") or host))),
        "url": url,
        "source_name": str(item.get("source_name") or item.get("name") or host or item.get("id") or "").strip(),
        "category": category,
        "source_type": map_source_type(raw_source_type, category),
        "fetch_mode": str(item.get("fetch_mode") or capability.get("fetch_mode") or defaults.get("fetch_mode") or "rss"),
        "crawl_frequency_minutes": int(item.get("crawl_frequency_minutes") or capability.get("crawl_frequency_minutes") or defaults.get("crawl_frequency_minutes") or 180),
        "needs_js": bool(item.get("needs_js", capability.get("needs_js", False))),
        "lang_primary": str(item.get("lang_primary") or (item.get("languages") or ["hy"])[0]),
        "armenia_relevance_default": float(item.get("armenia_relevance_default", capability.get("armenia_relevance_default", 1.0)) or 1.0),
        "trust_weight": float(item.get("trust_weight", capability.get("trust_weight", defaults.get("trust_weight", 0.7))) or 0.7),
        "freshness_weight": float(item.get("freshness_weight", capability.get("freshness_weight", defaults.get("freshness_weight", 0.7))) or 0.7),
        "coverage_tags": list(item.get("coverage_tags") or capability.get("coverage_tags") or defaults.get("coverage_tags") or [category]),
        "enabled": enabled,
        "telegram_url": str(item.get("telegram_url") or item.get("telegramUrl") or ""),
        "notes": str(item.get("notes") or ""),
    }
    for key in ("last_success_at", "last_failure_at", "consecutive_failures", "avg_fetch_ms", "items_last_7_runs", "parse_quality_score", "status", "last_error_class", "last_status_code", "coverage_contribution_last_7_runs"):
        if key in item:
            normalized[key] = item.get(key)
    if "items_last_7_runs" not in normalized or not isinstance(normalized.get("items_last_7_runs"), list):
        normalized["items_last_7_runs"] = list(item.get("items_last_7_runs", [])) if isinstance(item.get("items_last_7_runs", []), list) else []
    if "coverage_contribution_last_7_runs" not in normalized:
        normalized["coverage_contribution_last_7_runs"] = sum(int(value or 0) for value in normalized.get("items_last_7_runs", []) if isinstance(value, (int, float)))
    return normalized


def load_source_registry() -> list[dict[str, Any]]:
    registry = load_json(SOURCE_REGISTRY, [])
    legacy = load_json(LEGACY_SOURCE_SEED, {})
    capabilities = load_structured(SOURCE_CAPABILITIES, {}) or {}
    defaults = (capabilities.get("defaults") or {}) if isinstance(capabilities, dict) else {}
    capability_sources = capabilities.get("sources", {}) if isinstance(capabilities, dict) else {}

    merged: dict[str, dict[str, Any]] = {}
    for item in registry if isinstance(registry, list) else []:
        if not isinstance(item, dict):
            continue
        key = _source_registry_key(item)
        merged[key] = _normalize_source_registry_item(item, capability=(capability_sources.get(key) or {}), defaults=defaults)

    for item in legacy.get("sources", []) if isinstance(legacy, dict) else []:
        if not isinstance(item, dict):
            continue
        key = _source_registry_key(item)
        capability = capability_sources.get(key) or capability_sources.get(short_host(str(item.get("siteUrl") or ""))) or {}
        existing = merged.get(key, {})
        merged[key] = _normalize_source_registry_item({**item, **existing}, capability=capability, defaults=defaults)

    for host, capability in capability_sources.items():
        if not isinstance(capability, dict):
            continue
        if host in merged:
            merged[host] = _normalize_source_registry_item(merged[host], capability=capability, defaults=defaults)

    normalized = sorted(merged.values(), key=lambda item: (float(item.get("trust_weight", 0.0) or 0.0), float(item.get("freshness_weight", 0.0) or 0.0), item.get("source_name", "")), reverse=True)
    write_json(SOURCE_REGISTRY, normalized)
    return normalized


def load_model_config() -> dict[str, Any]:
    return load_json(LOCAL_MODEL_CONFIG, {})


def active_chain_snapshot(model_config: dict[str, Any]) -> dict[str, Any]:
    roles = model_config.get("roles", {}) if isinstance(model_config, dict) else {}

    def role_spec(role: str) -> dict[str, Any]:
        item = roles.get(role, {}) if isinstance(roles, dict) else {}
        preferred = item.get("preferred", [])
        if isinstance(preferred, str):
            preferred = [preferred]
        preferred_id = ""
        if preferred:
            first = preferred[0]
            if isinstance(first, dict):
                preferred_id = f"{first.get('provider', '')}/{first.get('id', '')}".strip("/")
            else:
                preferred_id = str(first)
        return {
            "preferred": preferred_id,
            "fallback": item.get("fallback", ""),
        }

    return {
        "classifier": role_spec("classifier"),
        "extractor": role_spec("extractor"),
        "embedding": role_spec("embedding"),
        "reranker": role_spec("reranker"),
        "source_judge": role_spec("source_judge"),
        "graph_critic": role_spec("graph_critic"),
        "graph_native_assistant": role_spec("graph_native_assistant"),
        "social_operator": role_spec("social_operator"),
        "writer": role_spec("writer"),
    }


def load_prompt_stack() -> dict[str, Any]:
    return load_json(PROMPT_STACK_FILE, {"version": 1, "roles": [], "tools": []})


def prompt_audit_payload(model_config: dict[str, Any] | None = None) -> dict[str, Any]:
    stack = load_prompt_stack()
    model_config = model_config or load_model_config()
    roles = stack.get("roles", []) if isinstance(stack, dict) else []
    tools = stack.get("tools", []) if isinstance(stack, dict) else []
    chain = active_chain_snapshot(model_config)
    audited_roles: list[dict[str, Any]] = []
    missing_prompt_files: list[str] = []
    for role in roles:
        if not isinstance(role, dict):
            continue
        role_id = str(role.get("id") or "")
        prompt_file = PROMPTS_DIR / str(role.get("file") or "")
        exists = prompt_file.exists()
        if not exists:
            missing_prompt_files.append(str(prompt_file.relative_to(ROOT)))
        audited_roles.append(
            {
                "id": role_id,
                "file": str(prompt_file.relative_to(ROOT)),
                "exists": exists,
                "allowed_tools": role.get("allowed_tools", []),
                "forbidden_actions": role.get("forbidden_actions", []),
                "model_role": chain.get(role_id, {}),
            }
        )
    return {
        "generated_at": iso_now(),
        "role_count": len(audited_roles),
        "tool_count": len(tools) if isinstance(tools, list) else 0,
        "roles": audited_roles,
        "tools": tools if isinstance(tools, list) else [],
        "missing_prompt_files": missing_prompt_files,
        "ok": not missing_prompt_files,
    }


def map_source_type(raw_type: str, category: str) -> str:
    lowered = normalize_text(raw_type)
    if "official" in lowered or category == "official_baseline":
        return "official"
    if "watchdog" in lowered or category == "independent_watchdog":
        return "watchdog"
    if "critical" in lowered or category == "critical_opposition_adjacent":
        return "opposition_adjacent"
    if category == "external_analysis":
        return "external"
    return "independent"


def fetch_url(url: str, timeout: int = 20) -> tuple[str, str]:
    request = Request(url, headers=DEFAULT_HEADERS)
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            content_type = response.headers.get("Content-Type", "")
            return body, content_type
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        return "", f"error:{type(exc).__name__}"


def discover_feed_links(html_text: str, base_url: str) -> list[str]:
    links = re.findall(r"""<link[^>]+type=["'](?:application|text)/(?:rss|atom)\+xml["'][^>]+href=["']([^"']+)""", html_text, flags=re.I)
    return [urljoin(base_url, link) for link in links]


def parse_feed_items(xml_text: str, source_url: str, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return items
    namespaces = {"atom": "http://www.w3.org/2005/Atom"}
    nodes = root.findall(".//item") or root.findall(".//atom:entry", namespaces)
    for node in nodes[:limit]:
        title = find_xml_text(node, ["title", "{http://www.w3.org/2005/Atom}title"])
        link = find_xml_text(node, ["link", "{http://www.w3.org/2005/Atom}link"])
        if not link:
            link = node.attrib.get("href", "")
            if not link:
                link_element = node.find("{http://www.w3.org/2005/Atom}link")
                if link_element is not None:
                    link = link_element.attrib.get("href", "")
        summary = find_xml_text(node, ["description", "summary", "{http://www.w3.org/2005/Atom}summary"])
        published = find_xml_text(node, ["pubDate", "published", "{http://www.w3.org/2005/Atom}published"])
        if title and link:
            items.append(
                {
                    "id": stable_hash(source_url, title, link),
                    "title": compact_title(title),
                    "summary": compact_summary(summary),
                    "url": link.strip(),
                    "published_at": published.strip(),
                }
            )
    return items


def find_xml_text(node: ElementTree.Element, tags: list[str]) -> str:
    for tag in tags:
        child = node.find(tag)
        if child is not None:
            text = child.text or ""
            if text.strip():
                return text
    return ""


def extract_html_items(html_text: str, base_url: str, limit: int) -> list[dict[str, Any]]:
    anchors = re.findall(r"""<a[^>]+href=["']([^"']+)["'][^>]*>(.*?)</a>""", html_text, flags=re.I | re.S)
    items: list[dict[str, Any]] = []
    for href, raw_text in anchors:
        text = compact_title(strip_html(raw_text))
        if len(text) < 25:
            continue
        if any(skip in href.lower() for skip in ["javascript:", "#", "mailto:"]):
            continue
        url = urljoin(base_url, href.strip())
        items.append(
            {
                "id": stable_hash(base_url, text, url),
                "title": text,
                "summary": "",
                "url": url,
                "published_at": "",
            }
        )
        if len(items) >= limit:
            break
    return dedupe_items(items)


def compact_title(value: str) -> str:
    return re.sub(r"\s+", " ", strip_html(value)).strip()


def compact_summary(value: str) -> str:
    return re.sub(r"\s+", " ", strip_html(value)).strip()[:420]


def strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value or "")


def dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        key = item["url"]
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def load_aliases() -> dict[str, set[str]]:
    buckets: dict[str, set[str]] = {"people": set(), "orgs": set(), "places": set()}
    for key, path in {
        "people": ALIASES_DIR / "people.json",
        "orgs": ALIASES_DIR / "orgs.json",
        "places": ALIASES_DIR / "places.json",
    }.items():
        payload = load_json(path, {})
        if isinstance(payload, dict):
            for canonical, aliases in payload.items():
                buckets[key].add(normalize_text(canonical))
                if isinstance(aliases, list):
                    for alias in aliases:
                        buckets[key].add(normalize_text(str(alias)))
        elif isinstance(payload, list):
            for item in payload:
                buckets[key].add(normalize_text(str(item.get("name") or "")))
                for alias in item.get("aliases", []) or []:
                    buckets[key].add(normalize_text(str(alias)))
    return {key: {value for value in values if len(value) >= 3} for key, values in buckets.items()}


def load_entity_alias_index(graph: dict[str, Any] | None = None) -> dict[str, dict[str, str]]:
    alias_index: dict[str, dict[str, str]] = {"people": {}, "orgs": {}, "places": {}}
    graph = graph or load_graph()
    entity_index_by_name: dict[str, dict[str, Any]] = {}
    for entity in graph.get("entities", []):
        names = [entity.get("name", "")] + [str(alias) for alias in entity.get("aliases", []) or []]
        for name in names:
            normalized = normalize_text(name)
            if normalized:
                entity_index_by_name[normalized] = entity
            canonical = canonical_name_key(name)
            if canonical:
                entity_index_by_name.setdefault(canonical, entity)
            person_canonical = canonical_person_key(name)
            if person_canonical:
                entity_index_by_name.setdefault(person_canonical, entity)
    alias_payloads = {
        "people": ALIASES_DIR / "people.json",
        "orgs": ALIASES_DIR / "orgs.json",
        "places": ALIASES_DIR / "places.json",
    }
    for bucket, path in alias_payloads.items():
        payload = load_json(path, {})
        if isinstance(payload, dict):
            for canonical, aliases in payload.items():
                candidates = [canonical] + [str(alias) for alias in aliases or []]
                entity = None
                for candidate in candidates:
                    entity = entity_index_by_name.get(normalize_text(candidate))
                    if entity:
                        break
                if not entity:
                    continue
                for candidate in candidates:
                    normalized = normalize_text(candidate)
                    if normalized:
                        alias_index[bucket][normalized] = entity["id"]
                    canonical = canonical_name_key(candidate)
                    if canonical:
                        alias_index[bucket][canonical] = entity["id"]
                    person_canonical = canonical_person_key(candidate)
                    if person_canonical:
                        alias_index[bucket][person_canonical] = entity["id"]
    return alias_index


def resolve_entity(name: str, alias_index: dict[str, dict[str, str]] | dict[str, str], bucket: str = "") -> str | None:
    normalized = normalize_text(str(name or ""))
    if not normalized:
        return None
    canonical = canonical_name_key(name)
    person_canonical = canonical_person_key(name)
    if bucket:
        scoped = alias_index.get(bucket, {}) if isinstance(alias_index, dict) else {}
        if isinstance(scoped, dict) and normalized in scoped:
            return str(scoped[normalized])
        if isinstance(scoped, dict) and canonical in scoped:
            return str(scoped[canonical])
        if isinstance(scoped, dict) and person_canonical in scoped:
            return str(scoped[person_canonical])
        if isinstance(scoped, dict) and scoped:
            best_score = 0.0
            best_id: str | None = None
            candidate_key = person_canonical or canonical or normalized
            for alias, entity_id in scoped.items():
                alias_key = canonical_name_key(alias)
                if not alias_key:
                    continue
                score = difflib.SequenceMatcher(None, candidate_key, alias_key).ratio()
                if score > best_score:
                    best_score = score
                    best_id = str(entity_id)
            if best_id and best_score >= 0.88:
                return best_id
        return None
    if isinstance(alias_index, dict):
        direct = alias_index.get(normalized)
        if isinstance(direct, str):
            return direct
        direct = alias_index.get(canonical)
        if isinstance(direct, str):
            return direct
        direct = alias_index.get(person_canonical)
        if isinstance(direct, str):
            return direct
        for scoped in alias_index.values():
            if isinstance(scoped, dict) and normalized in scoped:
                return str(scoped[normalized])
            if isinstance(scoped, dict) and canonical in scoped:
                return str(scoped[canonical])
            if isinstance(scoped, dict) and person_canonical in scoped:
                return str(scoped[person_canonical])
    return None


RELATION_LABELS_RU = {
    "holds_office_in": "занимает должность в",
    "member_of": "состоит в",
    "appointed_by": "назначен",
    "aligned_with": "связан с",
    "opposes": "выступает против",
    "authored": "автор",
    "coauthored": "соавтор",
    "voted_for": "голосовал за",
    "voted_against": "голосовал против",
    "implemented_by": "реализован через",
    "licensed_by": "лицензирован",
    "funded_by": "финансируется",
    "contracted_with_state": "имеет контракт с государством",
    "owns_or_controls": "владеет или контролирует",
    "beneficial_owner_reported": "сообщается как конечный бенефициар",
    "family_tie_public": "имеет публично известную семейную связь",
    "subject_of_legal_case": "является предметом судебного дела",
    "watchdog_allegation": "фигурирует в жалобе watchdog",
    "media_claim_disputed": "оспаривается в медиа",
    "criticized_by": "подвергся критике со стороны",
    "investigated_by": "расследуется",
    "publicly_supported": "публично поддержан",
    "publicly_opposed": "публично выступает против",
    "mentions": "упоминается рядом с",
}


def relation_types_payload() -> list[dict[str, str]]:
    return [{"id": relation_type, "label": relation_type.replace("_", " ")} for relation_type in RELATION_TYPES]


def relation_label_ru(relation_type: str) -> str:
    return RELATION_LABELS_RU.get(relation_type, relation_type.replace("_", " "))


def load_graph() -> dict[str, Any]:
    if CANONICAL_GRAPH.exists():
        from graph_domain import migrate_graph_bundle

        raw_graph = load_json(CANONICAL_GRAPH, {})
        graph, report = migrate_graph_bundle(raw_graph)
        report_status = str(report.get("status") or "") if isinstance(report, dict) else ""
        if report_status == "migrated_to_v3":
            write_json(CANONICAL_GRAPH, graph)
            write_json(GRAPH_MIGRATION_REPORT, report)
            append_jsonl(
                EVIDENCE_LOG,
                [
                    {
                        "recorded_at": iso_now(),
                        "action": "migrated_to_v3",
                        "schema_version": 3,
                        "old_counts": report.get("old_counts", {}),
                        "new_counts": report.get("new_counts", {}),
                        "claim_only_relations": report.get("claim_only_relations", 0),
                        "canonical_edges_admitted": report.get("canonical_edges_admitted", 0),
                    }
                ],
            )
        return graph
    return migrate_legacy_graph()


def migrate_legacy_graph() -> dict[str, Any]:
    relation_types = load_json(LEGACY_RELATION_TYPES, [])
    legacy_entities = load_json(LEGACY_ENTITIES, [])
    legacy_relations = load_json(LEGACY_RELATIONS, [])

    entities: list[dict[str, Any]] = []
    entity_ids: set[str] = set()
    for entity in legacy_entities:
        if entity.get("category") == "event":
            continue
        entity_id = entity.get("id") or f"entity-{stable_hash(entity.get('name', ''), entity.get('category', ''))}"
        if entity_id in entity_ids:
            continue
        entity_ids.add(entity_id)
        entities.append(
            {
                "id": entity_id,
                "name": entity.get("name", entity_id),
                "category": entity.get("category", "organization"),
                "subtype": entity.get("subtype", ""),
                "aliases": entity.get("aliases", []),
                "tags": entity.get("tags", []),
                "summary": entity.get("summary", ""),
                "links": entity.get("links", {}),
                "public_safe": bool(entity.get("public_safe", True)),
                "notes": entity.get("notes", ""),
                "updated_at": entity.get("updatedAt") or iso_now(),
            }
        )

    relations: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    for relation in legacy_relations:
        if relation.get("type") not in RELATION_TYPES:
            continue
        if relation.get("from") not in entity_ids or relation.get("to") not in entity_ids:
            continue
        evidence = relation.get("evidence") or []
        source_url = ""
        source_type = "legacy_migration"
        evidence_quote = relation.get("evidence_notes") or relation.get("notes", "")
        collected_at = relation.get("last_checked_at") or iso_now()
        if evidence:
            first = evidence[0]
            if isinstance(first, dict):
                source_url = first.get("url", "")
                source_type = first.get("kind", source_type)
                collected_at = first.get("capturedAt") or collected_at
            elif isinstance(first, str):
                source_url = first
        converted = {
            "id": relation.get("id") or f"rel-{stable_hash(relation.get('from', ''), relation.get('to', ''), relation.get('type', ''))}",
            "from": relation.get("from"),
            "to": relation.get("to"),
            "relation_type": relation.get("type"),
            "status": relation.get("status", "reported"),
            "source_url": source_url,
            "source_type": source_type,
            "evidence_quote": evidence_quote,
            "evidence_level": relation.get("evidence_level", "single_source"),
            "confidence": round(min(0.99, 0.45 + 0.1 * int(bool(source_url)) + 0.05 * len(evidence)), 2),
            "collected_at": collected_at,
            "last_checked_at": relation.get("last_checked_at") or collected_at,
            "public_safe": bool(relation.get("public_safe", relation.get("status") not in {"disputed", "watchdog_attributed"})),
            "notes": relation.get("notes", ""),
        }
        relations.append(converted)
        evidence_rows.append(
            {
                "recorded_at": iso_now(),
                "run_id": "legacy-migration",
                "entity_from": converted["from"],
                "entity_to": converted["to"],
                "relation_type": converted["relation_type"],
                "source_url": converted["source_url"],
                "evidence_level": converted["evidence_level"],
                "confidence": converted["confidence"],
                "action": "migrated_from_legacy",
            }
        )

    graph = {
        "version": 1,
        "updated_at": iso_now(),
        "source_of_truth": str(CANONICAL_GRAPH.relative_to(ROOT)),
        "relation_types": relation_types or [{"id": item, "label": item.replace("_", " ")} for item in RELATION_TYPES],
        "entities": sorted(entities, key=lambda item: item["name"]),
        "relations": sorted(relations, key=lambda item: item["id"]),
        "story_mentions": [],
    }
    write_json(CANONICAL_GRAPH, graph)
    if not EVIDENCE_LOG.exists():
        append_jsonl(EVIDENCE_LOG, evidence_rows)
    return graph


def entity_index(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entity["id"]: entity for entity in graph.get("entities", [])}


def relation_index(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {relation["id"]: relation for relation in graph.get("relations", [])}


def load_pipeline_state() -> dict[str, Any]:
    return load_json(PIPELINE_STATE, {"known_blockers": [], "last_runs": {}})


def save_pipeline_state(state: dict[str, Any]) -> None:
    write_json(PIPELINE_STATE, state)


def load_run_state() -> dict[str, Any]:
    return load_json(
        RUN_STATE,
        {
            "current_run": {"run_id": None, "mode": None, "status": "idle", "started_at": None, "finished_at": None},
            "current_stage": {"run_id": None, "stage": None, "status": "idle", "updated_at": None},
        },
    )


def save_run_state(*, current_run: dict[str, Any] | None = None, current_stage: dict[str, Any] | None = None) -> None:
    payload = load_run_state()
    if current_run is not None:
        payload["current_run"] = current_run
    if current_stage is not None:
        payload["current_stage"] = current_stage
    write_json(RUN_STATE, payload)


def load_ops_settings() -> dict[str, Any]:
    return load_json(OPS_SETTINGS, {"mode": "quiet", "admin_chat_id": "", "updated_at": None})


def save_ops_settings(settings: dict[str, Any]) -> None:
    settings["updated_at"] = iso_now()
    write_json(OPS_SETTINGS, settings)


def current_run_context() -> dict[str, Any]:
    settings = load_ops_settings()
    run_state = load_run_state()
    current_run = run_state.get("current_run", {})
    current_stage = run_state.get("current_stage", {})
    return {
        "run_id": os.environ.get("THIEZER_RUN_ID", "") or current_run.get("run_id", ""),
        "mode": os.environ.get("THIEZER_RUN_MODE", "") or current_run.get("mode", ""),
        "stage": os.environ.get("THIEZER_STAGE", "") or current_stage.get("stage", ""),
        "ops_mode": os.environ.get("THIEZER_OPS_MODE") or settings.get("mode", "quiet"),
        "ops_chat_id": os.environ.get("THIEZER_OPS_CHAT_ID") or settings.get("admin_chat_id", ""),
        "model": os.environ.get("THIEZER_MODEL", ""),
    }


def update_ops_status() -> None:
    run_state = load_run_state()
    current_run = run_state.get("current_run", {})
    current_stage = run_state.get("current_stage", {})
    graph_diff_index = load_json(GRAPH_DIFF_INDEX, {"latest": None, "stories": []})
    browser_session_index = load_json(SESSION_INDEX, {"sessions": [], "latest": None})
    page_research_index = load_json(PAGE_RESEARCH_INDEX, {"pages": [], "latest": None})
    social_actions = load_json(SOCIAL_ACTIONS_FILE, {})
    control_jobs = load_json(CONTROL_JOBS_FILE, {"jobs": [], "latest": None})
    recent_browser_events = [
        event
        for event in tail_jsonl(LIVE_RUN_EVENTS, 20)
        if str(event.get("stage", "")).startswith("browser") or str(event.get("event_type", "")).startswith("browser_")
    ]
    recent_browser_actions = tail_jsonl(LIVE_BROWSER_ACTIONS, 12)
    browser_snapshot = {}
    for event in reversed(recent_browser_events):
        details = event.get("details", {}) or {}
        if details.get("browser_backend") or details.get("visible_mode") is not None or event.get("fallback_used") is not None:
            browser_snapshot = {
                "enabled": True,
                "current_backend": details.get("browser_backend"),
                "visible": details.get("visible_mode"),
                "fallback_used": event.get("fallback_used"),
            }
            break
    payload = {
        "updated_at": iso_now(),
        "current_run_id": current_run.get("run_id"),
        "current_mode": current_run.get("mode"),
        "current_stage": current_stage.get("stage"),
        "current_stage_status": current_stage.get("status"),
        "browser_mode": browser_snapshot or {
            "enabled": current_run.get("mode") == "browser-research" or current_stage.get("stage") == "browser_research",
            "current_backend": None,
            "visible": None,
            "fallback_used": None,
        },
        "recent_urls": tail_jsonl(LIVE_VISITED_URLS, 12),
        "recent_decisions": tail_jsonl(LIVE_STORY_DECISIONS, 12),
        "recent_repairs": tail_jsonl(LIVE_SELF_REPAIR, 12),
        "recent_publish_actions": tail_jsonl(TRACE_PUBLISH, 12),
        "recent_graph_updates": tail_jsonl(TRACE_GRAPH, 12),
        "recent_graph_diffs": graph_diff_index.get("stories", [])[:12],
        "latest_graph_diff": graph_diff_index.get("latest"),
        "recent_browser_events": recent_browser_events,
        "recent_browser_actions": recent_browser_actions,
        "recent_page_cards": page_research_index.get("pages", [])[:12],
        "current_browser_session": browser_session_index.get("latest"),
        "social_actions": social_actions,
        "control_jobs": control_jobs,
    }
    write_json(OPS_STATUS_FILE, payload)


def telegram_bot_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if token:
        return token
    openclaw_config = load_json(Path("/Users/sargisvardanyan/.openclaw/openclaw.json"), {})
    return (
        openclaw_config.get("channels", {})
        .get("telegram", {})
        .get("botToken", "")
    )


def send_telegram_via_bot_api_receipt(text: str, chat_id: str, thread_id: str = "") -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "transport": "bot_api",
        "target": chat_id,
        "thread_id": thread_id or "",
        "status": "dry_run_only" if not chat_id else "failed",
        "message_id": None,
        "ok": False,
        "error": "",
        "raw": None,
    }
    if not chat_id:
        return receipt
    token = telegram_bot_token()
    if not token:
        receipt["error"] = "missing_bot_token"
        return receipt
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if thread_id:
        payload["message_thread_id"] = int(thread_id)
    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=12) as response:
            body = response.read().decode("utf-8", errors="replace")
            receipt["raw"] = body
            parsed = json.loads(body) if body else {}
            if isinstance(parsed, dict) and parsed.get("ok"):
                receipt["ok"] = True
                receipt["status"] = "sent"
                result = parsed.get("result", {}) if isinstance(parsed.get("result", {}), dict) else {}
                receipt["message_id"] = result.get("message_id")
            else:
                receipt["error"] = "bot_api_not_ok"
            return receipt
    except Exception as exc:
        receipt["error"] = str(exc)
        return receipt


def send_telegram_via_bot_api(text: str, chat_id: str, thread_id: str = "") -> bool:
    return send_telegram_via_bot_api_receipt(text, chat_id, thread_id=thread_id).get("ok", False)


def send_telegram_via_openclaw_receipt(text: str, chat_id: str, thread_id: str = "") -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "transport": "openclaw",
        "target": chat_id,
        "thread_id": thread_id or "",
        "status": "dry_run_only" if not chat_id else "failed",
        "message_id": None,
        "ok": False,
        "error": "",
        "raw": None,
    }
    if not chat_id:
        return receipt
    command = [
        "openclaw",
        "message",
        "send",
        "--channel",
        "telegram",
        "--target",
        chat_id,
        "--message",
        text,
        "--json",
    ]
    if thread_id:
        command.extend(["--thread-id", thread_id])
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=20)
    except Exception as exc:
        receipt["error"] = str(exc)
        return receipt
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    receipt["raw"] = stdout or stderr or None
    if completed.returncode != 0:
        receipt["error"] = stderr or stdout or f"openclaw exited {completed.returncode}"
        return receipt
    receipt["ok"] = True
    receipt["status"] = "sent"
    if stdout:
        try:
            parsed = json.loads(stdout)
            if isinstance(parsed, dict):
                parsed_result = parsed.get("result", {}) if isinstance(parsed.get("result", {}), dict) else {}
                payload = parsed.get("payload", {}) if isinstance(parsed.get("payload", {}), dict) else {}
                receipt["message_id"] = (
                    parsed.get("message_id")
                    or parsed.get("id")
                    or parsed_result.get("message_id")
                    or payload.get("messageId")
                    or payload.get("message_id")
                )
        except Exception:
            pass
    return receipt


def send_telegram_via_openclaw(text: str, chat_id: str, thread_id: str = "") -> bool:
    return send_telegram_via_openclaw_receipt(text, chat_id, thread_id=thread_id).get("ok", False)


def send_telegram_message(text: str, chat_id: str, thread_id: str = "") -> bool:
    if send_telegram_via_openclaw(text, chat_id, thread_id=thread_id):
        return True
    return send_telegram_via_bot_api(text, chat_id, thread_id=thread_id)


def send_telegram_message_receipt(text: str, chat_id: str, thread_id: str = "") -> dict[str, Any]:
    if not chat_id:
        return {
            "status": "dry_run_only",
            "transport": "none",
            "target": "",
            "thread_id": thread_id or "",
            "message_id": None,
            "ok": False,
            "error": "",
            "raw": None,
        }
    openclaw_receipt = send_telegram_via_openclaw_receipt(text, chat_id, thread_id=thread_id)
    if openclaw_receipt.get("ok"):
        return openclaw_receipt
    bot_receipt = send_telegram_via_bot_api_receipt(text, chat_id, thread_id=thread_id)
    if bot_receipt.get("ok"):
        return bot_receipt
    return {
        "status": "failed",
        "transport": "openclaw+bot_api",
        "target": chat_id,
        "thread_id": thread_id or "",
        "message_id": None,
        "ok": False,
        "error": "; ".join(filter(None, [str(openclaw_receipt.get("error") or ""), str(bot_receipt.get("error") or "")])),
        "raw": {
            "openclaw": openclaw_receipt.get("raw"),
            "bot_api": bot_receipt.get("raw"),
        },
    }


def publication_fingerprint(story_id: str = "", target: str = "", text: str = "", source_links: list[str] | None = None) -> str:
    normalized_text = normalize_text(text)
    normalized_sources = " ".join(
        sorted(normalize_text(item) for item in (source_links or []) if str(item).strip())
    )
    return stable_hash(
        "publication",
        normalize_text(target),
        normalize_text(story_id),
        normalized_text,
        normalized_sources,
    )


def load_publication_ledger(limit: int = 400) -> list[dict[str, Any]]:
    if not PUBLICATION_LEDGER_FILE.exists():
        return []
    if PUBLICATION_LEDGER_FILE.stat().st_size == 0:
        backfill_publication_ledger_from_runtime()
    rows: list[dict[str, Any]] = []
    try:
        for raw_line in PUBLICATION_LEDGER_FILE.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
    except FileNotFoundError:
        return []
    return rows[-limit:] if limit > 0 else rows


def backfill_publication_ledger_from_runtime() -> None:
    task_runtime = load_json(TASK_RUNTIME_FILE, {}) if TASK_RUNTIME_FILE.exists() else {}
    if not isinstance(task_runtime, dict):
        return
    receipts = task_runtime.get("transport_receipts", [])
    graph = load_graph()
    publication = (
        graph.get("runtime", {}).get("publication", {})
        if isinstance(graph.get("runtime", {}), dict)
        else {}
    )
    social_outputs = list(publication.get("social_outputs", [])) if isinstance(publication.get("social_outputs"), list) else []
    if not isinstance(receipts, list) or not receipts or not social_outputs:
        return
    public_receipts = [
        row for row in receipts
        if isinstance(row, dict)
        and row.get("ok")
        and str(row.get("target") or "").strip() == PUBLIC_POST_CHAT_HANDLE
    ]
    if not public_receipts:
        return
    entries: list[dict[str, Any]] = []
    for receipt, item in zip(public_receipts, social_outputs):
        if not isinstance(item, dict):
            continue
        story_id = str(item.get("story_id") or "").strip()
        text = str(item.get("telegram_post") or "").strip()
        if not text:
            continue
        source_links: list[str] = []
        for publication_item in list(publication.get("items", [])) if isinstance(publication.get("items"), list) else []:
            if isinstance(publication_item, dict) and str(publication_item.get("story_id") or "").strip() == story_id:
                source_links = [
                    str(link).strip()
                    for link in publication_item.get("source_links", [])
                    if str(link).strip()
                ][:4]
                break
        entries.append(
            {
                "recorded_at": task_runtime.get("finished_at") or iso_now(),
                "run_id": task_runtime.get("run_id"),
                "target": PUBLIC_POST_CHAT_HANDLE,
                "thread_id": str(receipt.get("thread_id") or ""),
                "status": "sent",
                "message_id": receipt.get("message_id"),
                "story_id": story_id,
                "fingerprint": publication_fingerprint(
                    story_id=story_id,
                    target=PUBLIC_POST_CHAT_HANDLE,
                    text=text,
                    source_links=source_links,
                ),
                "text": text,
                "title": str(item.get("telegram_thread", [""])[0] if isinstance(item.get("telegram_thread"), list) else ""),
                "summary": str(item.get("telegram_thread", ["", ""])[1] if isinstance(item.get("telegram_thread"), list) and len(item.get("telegram_thread")) > 1 else ""),
                "source_links": source_links,
            }
        )
    if entries:
        append_jsonl(PUBLICATION_LEDGER_FILE, entries)


def refresh_channel_mirror() -> dict[str, Any]:
    ledger = load_publication_ledger(limit=800)
    targets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ledger:
        if not isinstance(row, dict) or str(row.get("status") or "") != "sent":
            continue
        target = str(row.get("target") or "").strip()
        if not target:
            continue
        targets[target].append(
            {
                "recorded_at": row.get("recorded_at"),
                "story_id": row.get("story_id"),
                "message_id": row.get("message_id"),
                "fingerprint": row.get("fingerprint"),
                "title": row.get("title"),
                "summary": row.get("summary"),
                "text": row.get("text"),
                "source_links": row.get("source_links", []),
            }
        )
    snapshot = {
        "updated_at": iso_now(),
        "targets": {target: items[-50:] for target, items in targets.items()},
    }
    write_json(CHANNEL_MIRROR_FILE, snapshot)
    return snapshot


def load_channel_mirror() -> dict[str, Any]:
    if CHANNEL_MIRROR_FILE.exists():
        data = load_json(CHANNEL_MIRROR_FILE, {})
        if isinstance(data, dict) and isinstance(data.get("targets"), dict):
            return data
    return refresh_channel_mirror()


def find_publication_duplicate(
    *,
    target: str,
    story_id: str = "",
    text: str = "",
    source_links: list[str] | None = None,
) -> dict[str, Any] | None:
    ledger = load_publication_ledger(limit=800)
    target_key = str(target or "").strip()
    story_key = str(story_id or "").strip()
    text_key = normalize_text(text)
    fingerprint = publication_fingerprint(
        story_id=story_id,
        target=target,
        text=text,
        source_links=source_links,
    )
    for row in reversed(ledger):
        if not isinstance(row, dict):
            continue
        if str(row.get("target") or "").strip() != target_key:
            continue
        if str(row.get("status") or "").strip() != "sent":
            continue
        if story_key and str(row.get("story_id") or "").strip() == story_key:
            return row
        if str(row.get("fingerprint") or "").strip() == fingerprint:
            return row
        if text_key and normalize_text(str(row.get("text") or "")) == text_key:
            return row
    return None


def record_publication_ledger_entry(entry: dict[str, Any]) -> dict[str, Any]:
    append_jsonl(PUBLICATION_LEDGER_FILE, [entry])
    refresh_channel_mirror()
    return entry


def send_ops_message(text: str, chat_id: str = "") -> None:
    settings = load_ops_settings()
    target_chat = chat_id or settings.get("admin_chat_id", "")
    if not target_chat:
        return
    if target_chat == PUBLIC_POST_CHAT_HANDLE:
        return
    send_telegram_message(text, target_chat)


def maybe_send_ops_event(event: dict[str, Any]) -> None:
    context = current_run_context()
    if context.get("ops_mode") != "verbose":
        return
    if event.get("event_type") not in OPS_VERBOSE_EVENT_TYPES:
        return
    message = event.get("message") or f"{event.get('stage')}: {event.get('event_type')}"
    send_ops_message(message, str(context.get("ops_chat_id") or ""))


def emit_live_event(
    *,
    stage: str,
    event_type: str,
    status: str,
    message: str,
    source_id: str = "",
    url: str = "",
    entity_id: str = "",
    story_id: str = "",
    model: str = "",
    fallback_used: bool = False,
    latency_ms: int | float | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = current_run_context()
    event = {
        "ts": iso_now(),
        "run_id": context.get("run_id") or load_json(LIVE_CURRENT_RUN, {}).get("run_id"),
        "stage": stage,
        "event_type": event_type,
        "status": status,
        "message": message,
        "source_id": source_id or None,
        "url": url or None,
        "entity_id": entity_id or None,
        "story_id": story_id or None,
        "model": model or context.get("model") or None,
        "fallback_used": bool(fallback_used),
        "latency_ms": round(float(latency_ms), 2) if latency_ms is not None else None,
        "details": details or {},
    }
    append_jsonl(LIVE_RUN_EVENTS, [event])
    update_ops_status()
    maybe_send_ops_event(event)
    return event


def start_run(run_id: str, mode: str, ops_mode: str = "quiet", ops_chat_id: str = "") -> None:
    os.environ["THIEZER_RUN_ID"] = run_id
    os.environ["THIEZER_RUN_MODE"] = mode
    os.environ["THIEZER_OPS_MODE"] = ops_mode
    if ops_chat_id:
        os.environ["THIEZER_OPS_CHAT_ID"] = ops_chat_id
    current_run = {"run_id": run_id, "mode": mode, "status": "running", "started_at": iso_now(), "finished_at": None}
    current_stage = {"run_id": run_id, "stage": None, "status": "pending", "updated_at": iso_now()}
    write_json(LIVE_CURRENT_RUN, current_run)
    write_json(LIVE_CURRENT_STAGE, current_stage)
    save_run_state(current_run=current_run, current_stage=current_stage)
    emit_live_event(stage="run", event_type="run_started", status="running", message=f"Запуск {mode}: run_id={run_id}", details={"mode": mode, "ops_mode": ops_mode})


def finish_run(run_id: str, mode: str, status: str, message: str, details: dict[str, Any] | None = None) -> None:
    current_run = {"run_id": run_id, "mode": mode, "status": status, "started_at": load_json(LIVE_CURRENT_RUN, {}).get("started_at"), "finished_at": iso_now()}
    current_stage = {"run_id": run_id, "stage": None, "status": status, "updated_at": iso_now()}
    write_json(LIVE_CURRENT_RUN, current_run)
    write_json(LIVE_CURRENT_STAGE, current_stage)
    save_run_state(current_run=current_run, current_stage=current_stage)
    emit_live_event(stage="run", event_type="run_finished" if status == "ok" else "run_failed", status=status, message=message, details=details or {})


def set_current_stage(stage: str, status: str, message: str, details: dict[str, Any] | None = None) -> None:
    current = load_json(LIVE_CURRENT_RUN, {})
    current_stage = {"run_id": current.get("run_id"), "stage": stage, "status": status, "updated_at": iso_now(), "message": message}
    write_json(LIVE_CURRENT_STAGE, current_stage)
    save_run_state(current_stage=current_stage)
    emit_live_event(stage=stage, event_type="stage_started" if status == "running" else "stage_finished", status=status, message=message, details=details or {})


def log_visited_url(
    *,
    stage: str,
    source_name: str,
    source_type: str,
    method: str,
    url: str,
    status_code: int | None,
    fetch_status: str,
    chars_extracted: int,
    selected_for_story: bool = False,
    source_id: str = "",
    armenia_gate_score: float | None = None,
    page_type: str = "",
    browser_backend: str = "",
    visible_mode: bool | None = None,
    latency_ms: int | float | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    context = current_run_context()
    row = {
        "ts": iso_now(),
        "run_id": context.get("run_id"),
        "stage": stage,
        "source_id": source_id or None,
        "source_name": source_name,
        "source_type": source_type,
        "method": method,
        "url": url,
        "status_code": status_code,
        "fetch_status": fetch_status,
        "chars_extracted": chars_extracted,
        "armenia_gate_score": armenia_gate_score,
        "selected_for_story": selected_for_story,
        "page_type": page_type or None,
        "browser_backend": browser_backend or None,
        "visible_mode": visible_mode,
        "latency_ms": round(float(latency_ms), 2) if latency_ms is not None else None,
        "details": details or {},
    }
    append_jsonl(LIVE_VISITED_URLS, [row])
    emit_live_event(stage=stage, event_type="page_visit_finished" if fetch_status == "ok" else "source_fetch_failed", status=fetch_status, message=f"Открываю страницу: {short_host(url) or url}", source_id=source_id, url=url, latency_ms=latency_ms, details={"chars_extracted": chars_extracted, **(details or {})})


def log_story_decision(
    *,
    stage: str,
    event_type: str,
    status: str,
    message: str,
    story_id: str = "",
    source_id: str = "",
    url: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    context = current_run_context()
    row = {
        "ts": iso_now(),
        "run_id": context.get("run_id"),
        "stage": stage,
        "event_type": event_type,
        "status": status,
        "message": message,
        "story_id": story_id or None,
        "source_id": source_id or None,
        "url": url or None,
        "details": details or {},
    }
    append_jsonl(LIVE_STORY_DECISIONS, [row])
    emit_live_event(stage=stage, event_type=event_type, status=status, message=message, source_id=source_id, url=url, story_id=story_id, details=details or {})


def sha1_file(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha1(path.read_bytes()).hexdigest()


def log_self_repair_event(
    *,
    event_type: str,
    reason: str,
    file_path: str = "",
    explanation: str = "",
    restart_required: bool = False,
    old_hash: str = "",
    new_hash: str = "",
) -> None:
    row = {
        "ts": iso_now(),
        "run_id": current_run_context().get("run_id"),
        "event_type": event_type,
        "reason": reason,
        "file_changed": file_path or None,
        "old_hash": old_hash or None,
        "new_hash": new_hash or None,
        "explanation": explanation,
        "restart_required": restart_required,
    }
    append_jsonl(LIVE_SELF_REPAIR, [row])
    emit_live_event(stage="self_repair", event_type=event_type, status="ok", message=f"Self-repair: {explanation or reason}", details=row)


def record_controlled_self_repair(file_path: Path, reason: str, explanation: str, mutate: Callable[[], None] | None = None, restart_required: bool = False) -> None:
    old_hash = sha1_file(file_path)
    log_self_repair_event(event_type="self_repair_started", reason=reason, file_path=str(file_path), explanation=explanation, restart_required=restart_required, old_hash=old_hash)
    if mutate is not None:
        mutate()
    new_hash = sha1_file(file_path)
    log_self_repair_event(event_type="self_repair_changed_file", reason=reason, file_path=str(file_path), explanation=explanation, restart_required=restart_required, old_hash=old_hash, new_hash=new_hash)
    log_self_repair_event(event_type="self_repair_finished", reason=reason, file_path=str(file_path), explanation=explanation, restart_required=restart_required, old_hash=old_hash, new_hash=new_hash)


def published_registry() -> dict[str, Any]:
    return load_json(PUBLISHED_POSTS, {"stories": []})


def save_published_registry(payload: dict[str, Any]) -> None:
    write_json(PUBLISHED_POSTS, payload)


def write_graph_diff(story_id: str, payload: dict[str, Any]) -> None:
    path = GRAPH_DIFFS_DIR / f"{story_id}.json"
    write_json(path, payload)
    index = load_json(GRAPH_DIFF_INDEX, {"latest": None, "stories": []})
    normalized_existing: list[dict[str, Any]] = []
    for item in index.get("stories", []):
        item_path = Path(item.get("path", ""))
        diff_payload = load_json(item_path, {}) if item_path.exists() else {}
        normalized_existing.append(
            {
                "story_id": item.get("story_id"),
                "title": diff_payload.get("summary_line") or item.get("title") or item.get("story_id"),
                "updated_at": diff_payload.get("updated_at") or item.get("updated_at") or iso_now(),
                "path": str(item_path) if item_path else item.get("path"),
                "counts": diff_payload.get("counts") or item.get("counts", {}),
                "actors": diff_payload.get("actors") or item.get("actors", []),
                "status": diff_payload.get("status") or item.get("status", "ok"),
                "graph_scope": diff_payload.get("graph_scope") or item.get("graph_scope", "durable"),
                "significance": diff_payload.get("significance") or item.get("significance", "medium"),
                "no_durable_change": diff_payload.get("no_durable_change") if diff_payload else item.get("no_durable_change", False),
                "no_durable_change_reason": diff_payload.get("no_durable_change_reason") or item.get("no_durable_change_reason", ""),
            }
        )
    entry = {
        "story_id": story_id,
        "title": payload.get("summary_line") or payload.get("title") or story_id,
        "updated_at": payload.get("updated_at") or iso_now(),
        "path": str(path),
        "counts": payload.get("counts", {}),
        "actors": payload.get("actors", []),
        "status": payload.get("status", "ok"),
        "graph_scope": payload.get("graph_scope", "durable"),
        "significance": payload.get("significance", "medium"),
        "no_durable_change": payload.get("no_durable_change", False),
        "no_durable_change_reason": payload.get("no_durable_change_reason", ""),
    }
    stories = [item for item in normalized_existing if item.get("story_id") != story_id]
    stories.append(entry)
    index["stories"] = stories[-20:]
    index["latest"] = entry
    write_json(GRAPH_DIFF_INDEX, index)


def update_source_registry(sources: list[dict[str, Any]]) -> None:
    write_json(SOURCE_REGISTRY, sources)


def default_source_health() -> dict[str, Any]:
    return {
        "last_success_at": None,
        "last_failure_at": None,
        "consecutive_failures": 0,
        "avg_fetch_ms": 0.0,
        "items_last_7_runs": [],
        "parse_quality_score": 0.0,
        "status": "unknown",
        "last_error_class": None,
        "last_status_code": None,
    }


def merge_source_health(source: dict[str, Any]) -> dict[str, Any]:
    merged = {**default_source_health(), **source}
    items = merged.get("items_last_7_runs", [])
    if not isinstance(items, list):
        merged["items_last_7_runs"] = []
    return merged


def update_source_health(
    source: dict[str, Any],
    *,
    success: bool,
    latency_ms: float,
    items_count: int,
    parse_quality_score: float,
    error_class: str = "",
    status_code: int | None = None,
) -> dict[str, Any]:
    source = merge_source_health(source)
    previous_avg = float(source.get("avg_fetch_ms", 0.0) or 0.0)
    if previous_avg <= 0:
        source["avg_fetch_ms"] = round(latency_ms, 2)
    else:
        source["avg_fetch_ms"] = round((previous_avg * 0.7) + (latency_ms * 0.3), 2)
    items_window = list(source.get("items_last_7_runs", []))
    items_window.append(items_count)
    source["items_last_7_runs"] = items_window[-7:]
    source["parse_quality_score"] = round(parse_quality_score, 3)
    source["last_status_code"] = status_code
    if success:
        source["last_success_at"] = iso_now()
        source["consecutive_failures"] = 0
        source["status"] = "active" if items_count > 0 else "degraded"
        source["last_error_class"] = None
    else:
        source["last_failure_at"] = iso_now()
        source["consecutive_failures"] = int(source.get("consecutive_failures", 0) or 0) + 1
        source["status"] = "broken" if source["consecutive_failures"] >= 3 else "degraded"
        source["last_error_class"] = error_class or "fetch_failed"
    source["coverage_contribution_last_7_runs"] = sum(int(value or 0) for value in items_window if isinstance(value, (int, float)))
    return source


def render_source_links(sources: list[dict[str, Any]]) -> str:
    rendered = []
    seen: set[str] = set()
    for source in sources:
        url = source.get("url", "")
        label = source.get("label") or source.get("source_name") or short_host(url)
        key = f"{label}|{url}"
        if not url or key in seen:
            continue
        seen.add(key)
        rendered.append(f'<a href="{html.escape(url, quote=True)}">{html.escape(label)}</a>')
    return " · ".join(rendered)


def score_freshness(published_at: str) -> float:
    if not published_at:
        return 0.35
    try:
        cleaned = published_at.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        return 0.35
    age_hours = max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600)
    if age_hours <= 6:
        return 1.0
    if age_hours <= 24:
        return 0.75
    if age_hours <= 48:
        return 0.45
    return 0.2


def load_translation_cache() -> dict[str, str]:
    return {}


def save_translation_cache(cache: dict[str, str]) -> None:
    return None


def translate_to_russian(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if not cleaned:
        return ""
    if re.search(r"[А-Яа-яЁё]", cleaned):
        return cleaned
    return cleaned


EDITORIAL_SERVICE_PATTERNS = [
    r"^оппозиционная или критическая версия",
    r"^watchdog",
    r"слой по этой теме",
    r"в текущем пакете выражена слабо",
]


def clean_editorial_line(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    if not cleaned:
        return ""
    lowered = normalize_text(cleaned)
    if any(re.search(pattern, lowered) for pattern in EDITORIAL_SERVICE_PATTERNS):
        return ""
    return cleaned


def filtered_story_paragraphs(analysis: dict[str, Any]) -> list[str]:
    ordered = [
        clean_editorial_line(str(analysis.get("official_framing") or analysis.get("official") or "")),
        clean_editorial_line(str(analysis.get("opposition_framing") or analysis.get("opposition") or "")),
        clean_editorial_line(str(analysis.get("watchdog_framing") or analysis.get("watchdog") or "")),
        clean_editorial_line(str(analysis.get("public_context") or "")),
        clean_editorial_line(str(analysis.get("public_impact") or "")),
    ]
    seen: set[str] = set()
    paragraphs: list[str] = []
    for line in ordered:
        key = normalize_text(line)
        if not line or key in seen:
            continue
        seen.add(key)
        paragraphs.append(line)
    return paragraphs


def armenia_gate(item: dict[str, Any], alias_terms: dict[str, set[str]], graph: dict[str, Any]) -> dict[str, Any]:
    title = item.get("title", "")
    summary = item.get("summary", "")
    url = item.get("url", "")
    host = short_host(url)
    text = normalize_text(f"{title} {summary} {url}")
    reasons: list[str] = []
    matches: list[str] = []
    score = 0.0

    keyword_hits = [keyword for keyword in ARMENIA_KEYWORDS if keyword in text]
    if keyword_hits:
        reasons.append("armenia_keywords")
        matches.extend(keyword_hits[:6])
        score += 3.0

    institution_hits = [keyword for keyword in INSTITUTION_KEYWORDS if keyword in text]
    if institution_hits:
        reasons.append("institution_keywords")
        matches.extend(institution_hits[:4])
        score += 2.0

    for bucket, terms in alias_terms.items():
        bucket_hits = [term for term in terms if term and term in text]
        if bucket_hits:
            reasons.append(f"alias:{bucket}")
            matches.extend(bucket_hits[:4])
            score += 1.6

    for entity in graph.get("entities", []):
        name = normalize_text(entity.get("name", ""))
        if len(name) >= 4 and name in text:
            reasons.append("graph_entity_match")
            matches.append(name)
            score += 1.2
            break

    if host.endswith(".am"):
        reasons.append("armenian_domain")
        score += 1.4

    reject_reason = ""
    category = item.get("category", "")
    if category == "external_analysis" and not keyword_hits and not institution_hits and "alias:places" not in reasons:
        reject_reason = "foreign_without_actor"
        reasons.append("rejected_external_without_armenia_link")
        score -= 3.0

    utility = is_utility(title, summary)
    if utility:
        reasons.append("utility_signal")
        score -= 2.2
        if not reject_reason:
            reject_reason = "utility_low_priority"

    passed = score >= 2.5 and "rejected_external_without_armenia_link" not in reasons
    if not passed and not reject_reason:
        reject_reason = "weak_armenia_link"
    return {
        "passed": passed,
        "score": round(score, 3),
        "reasons": list(dict.fromkeys(reasons)),
        "matches": list(dict.fromkeys(matches)),
        "is_utility": utility,
        "reject_reason": reject_reason if not passed else "",
    }


def build_story_cluster_key(items: list[dict[str, Any]]) -> str:
    tokens = Counter()
    for item in items:
        tokens.update(tokenize(item.get("title", "")))
    top = [token for token, _ in tokens.most_common(8)]
    return stable_hash("cluster", " ".join(top))


def build_event_fingerprint(items: list[dict[str, Any]]) -> str:
    tokens = Counter()
    hosts = Counter()
    for item in items:
        tokens.update(tokenize(item.get("title", "") + " " + item.get("summary", "")))
        hosts.update([short_host(item.get("url", ""))])
    parts = [token for token, _ in tokens.most_common(10)] + [host for host, _ in hosts.most_common(3)]
    return stable_hash("event", *parts)


def bucket_sources(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[item.get("source_type", "independent")].append(item)
    return grouped


def choose_story_summary(items: list[dict[str, Any]]) -> tuple[str, str]:
    lead = sorted(
        items,
        key=lambda item: (
            item.get("priority_score", 0.0),
            item.get("gate_score", 0.0),
            item.get("freshness_score", 0.0),
        ),
        reverse=True,
    )[0]
    summary = lead.get("summary") or lead.get("title")
    return lead.get("title", ""), summary


def visible_text_without_tags(html_text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_text)).strip()


def mixed_alphabet_tokens(text: str) -> list[str]:
    tokens = re.findall(r"\b[\w\-]+\b", text)
    bad = []
    for token in tokens:
        if re.search(r"[A-Za-z]", token) and re.search(r"[А-Яа-яЁё]", token):
            bad.append(token)
    return bad


def update_public_outputs(story_pack: dict[str, Any], graph: dict[str, Any]) -> None:
    entity_by_id = {entity.get("id"): entity for entity in graph.get("entities", [])}

    def entity_links(entity: dict[str, Any]) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for label, url in (entity.get("links") or {}).items():
            if not url:
                continue
            rows.append({"label": str(label), "url": str(url), "kind": "entity_link"})
        return rows

    def relation_card(relation: dict[str, Any]) -> dict[str, Any]:
        left = entity_by_id.get(relation.get("from"), {})
        right = entity_by_id.get(relation.get("to"), {})
        return {
            "id": relation.get("id"),
            "from": relation.get("from"),
            "to": relation.get("to"),
            "from_name": left.get("name", relation.get("from", "")),
            "to_name": right.get("name", relation.get("to", "")),
            "relation_type": relation.get("relation_type"),
            "label_ru": relation_label_ru(str(relation.get("relation_type", ""))),
            "status": relation.get("status"),
            "confidence": relation.get("confidence"),
            "source_url": relation.get("source_url", ""),
            "evidence_quote": relation.get("evidence_quote", ""),
            "public_safe": relation.get("public_safe", True),
        }

    focus_story_cards: list[dict[str, Any]] = []
    focus_entity_ids: list[str] = []
    focus_source_links: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for story in story_pack.get("stories", [])[:6]:
        story_sources = []
        for source in story.get("sources", [])[:6]:
            url = str(source.get("url", "")).strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            link = {"label": str(source.get("label") or source.get("source_name") or url), "url": url, "kind": "source"}
            story_sources.append(link)
            focus_source_links.append(link)
        actor_ids = [actor_id for actor_id in story.get("actors_detected", []) if actor_id]
        focus_entity_ids.extend(actor_ids)
        focus_story_cards.append(
            {
                "story_id": story.get("story_id"),
                "cluster_key": story.get("cluster_key"),
                "topic": story.get("topic"),
                "title": story.get("summary_line"),
                "sources": story_sources,
                "study_links": story_sources,
                "relationship_context": story.get("analysis", {}).get("relationship_context", ""),
                "public_impact": story.get("analysis", {}).get("public_impact", ""),
            }
        )

    if not focus_entity_ids:
        for relation in graph.get("relations", [])[-24:]:
            focus_entity_ids.extend([relation.get("from", ""), relation.get("to", "")])

    dedup_entity_ids: list[str] = []
    for entity_id in focus_entity_ids:
        if entity_id and entity_id not in dedup_entity_ids and entity_id in entity_by_id:
            dedup_entity_ids.append(entity_id)
        if len(dedup_entity_ids) >= 12:
            break

    focus_entities: list[dict[str, Any]] = []
    for entity_id in dedup_entity_ids:
        entity = entity_by_id.get(entity_id)
        if not entity:
            continue
        related_relations = [
            relation_card(relation)
            for relation in graph.get("relations", [])
            if relation.get("from") == entity_id or relation.get("to") == entity_id
        ][:6]
        focus_entities.append(
            {
                "id": entity.get("id"),
                "name": entity.get("name"),
                "category": entity.get("category"),
                "subtype": entity.get("subtype"),
                "summary": entity.get("summary", ""),
                "links": entity.get("links", {}),
                "study_links": entity_links(entity),
                "public_safe": entity.get("public_safe", True),
                "related_relations": related_relations,
            }
        )

    focus_relations = [
        relation_card(relation)
        for relation in graph.get("relations", [])
        if relation.get("from") in dedup_entity_ids or relation.get("to") in dedup_entity_ids
    ]
    focus_relations.sort(key=lambda item: (float(item.get("confidence", 0.0) or 0.0), item.get("relation_type", "")), reverse=True)
    focus_relations = focus_relations[:24]

    graph_context = {
        "updatedAt": iso_now(),
        "story_count": len(story_pack.get("stories", [])),
        "focusStories": focus_story_cards,
        "focusEntities": focus_entities,
        "focusRelations": focus_relations,
        "studyLinks": focus_source_links,
    }
    news_items = []
    for story in story_pack.get("stories", [])[:6]:
        news_items.append(
            {
                "id": story["story_id"],
                "category": story["topic"],
                "title": story["summary_line"],
                "summary": story["analysis"].get("public_impact") or story["analysis"].get("official") or "",
            }
        )
    write_json(
        PUBLIC_EDITORIAL_DIR / "latest-news.json",
        {
            "updatedAt": iso_now(),
            "items": news_items,
        },
    )
    lead = story_pack.get("stories", [{}])[0]
    write_json(
        PUBLIC_EDITORIAL_DIR / "latest-deep-story.json",
        {
            "updatedAt": iso_now(),
            "slug": lead.get("story_id", "no-story"),
            "theme": lead.get("topic", "internal_politics"),
            "sourceLine": {"ru": "Источники: " + " | ".join(source["label"] for source in lead.get("sources", [])[:4])},
            "ru": {
                "category": lead.get("topic", "internal_politics"),
                "title": lead.get("summary_line", ""),
                "summary": clean_editorial_line(lead.get("analysis", {}).get("public_impact", "")) or clean_editorial_line(lead.get("analysis", {}).get("official_framing", "")),
                "paragraphs": filtered_story_paragraphs(lead.get("analysis", {})),
            },
        },
    )
    relation_counts = Counter(relation.get("relation_type", "unknown") for relation in graph.get("relations", []))
    actor_counts = Counter()
    for relation in graph.get("relations", []):
        actor_counts.update([relation.get("from", ""), relation.get("to", "")])
    entity_by_id = {entity.get("id"): entity for entity in graph.get("entities", [])}
    write_json(
        PUBLIC_EDITORIAL_DIR / "graph-summary.json",
        {
            "updatedAt": iso_now(),
            "totals": {
                "entities": len(graph.get("entities", [])),
                "relations": len(graph.get("relations", [])),
            },
            "prominentActors": [
                {
                    "id": entity_id,
                    "name": entity_by_id.get(entity_id, {}).get("name", entity_id),
                    "connectionCount": count,
                }
                for entity_id, count in actor_counts.most_common(6)
                if entity_by_id.get(entity_id)
            ],
            "topRelationTypes": [
                {"label": relation_type.replace("_", " "), "count": count}
                for relation_type, count in relation_counts.most_common(6)
            ],
            "clusters": [
                {
                    "title": story["summary_line"],
                    "items": [source["label"] for source in story.get("sources", [])[:4]],
                }
                for story in story_pack.get("stories", [])[:4]
            ],
            "watchlist": [
                {
                    "label": relation.get("relation_type", "").replace("_", " "),
                    "notes": relation.get("notes", ""),
                }
                for relation in graph.get("relations", [])
                if relation.get("revalidation_required")
            ][:6],
            "recentStories": [
                {
                    "id": story["story_id"],
                    "title": story["summary_line"],
                    "topic": story["topic"],
                    "sources": [source["label"] for source in story.get("sources", [])[:4]],
                }
                for story in story_pack.get("stories", [])[:5]
            ],
        },
    )
    write_json(PUBLIC_EDITORIAL_DIR / "graph-context.json", graph_context)
    write_json(LATEST_DIR / "graph-context.json", graph_context)
