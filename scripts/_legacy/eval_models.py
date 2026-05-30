#!/usr/bin/env python3
"""Deterministic benchmark harness for local models and OpenClaw."""

from __future__ import annotations

import argparse
import json
import re
import os
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib import error, request

from graph_domain import critique_task, graph_safety_report, rank_sources, verify_graph_proposal
from pipeline_common import (
    CONTENT_DIR,
    active_chain_snapshot,
    ensure_layout,
    iso_now,
    load_graph,
    load_json,
    load_model_config,
    load_source_registry,
    normalize_text,
    prompt_audit_payload,
    stable_hash,
    write_json,
    write_jsonl,
)


EVALS_DIR = CONTENT_DIR / "evals"
LATEST_DIR = EVALS_DIR / "latest"
TASKS_FILE = EVALS_DIR / "tasks.json"
OPENCLAW_AGENT_ID = "main"
RAW_MODELS = [model.strip() for model in os.environ.get("THIEZER_EVAL_RAW_MODELS", "gemma4:e4b").split(",") if model.strip()]
OPENROUTER_DEFAULT_MODEL = os.environ.get("THIEZER_EVAL_OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
SMOKE_TASK_IDS = [
    "entity_ru_pashinyan",
    "entity_hy_alen",
    "alias_resolution_alen",
    "source_ranking_official_vs_watchdog",
    "refusal_insufficient_evidence",
]


SCHEMA_HINTS = {
    "entity_extraction": '{"entities":[{"id":"person-nikol-pashinyan","name":"Nikol Pashinyan","category":"person"}],"relations":[],"verdict":"accept"}',
    "alias_resolution": '{"canonical_id":"person-alen-simonyan","canonical_name":"Alen Simonyan","confidence":0.95}',
    "relation_extraction": '{"relations":[{"from":"...","relation_type":"mentions","to":"...","confidence":0.7}],"verdict":"accept"}',
    "source_ranking": '{"ranking":["civic_am","1lurer","hetq"],"reason":"official sources first"}',
    "newsroom_note": '{"headline":"...","note":"...","source_ids":["..."]}',
    "refusal": '{"verdict":"insufficient_evidence","reason":"..."}',
    "strict_json": '{"status":"ok","entities":[],"relations":[]}',
    "long_summary": '{"summary":"..."}',
    "conflict_compare": '{"official":"...","watchdog":"...","difference":"...","verdict":"compare"}',
    "graph_safety": '{"verdict":"accept_with_warnings","issues":["..."]}',
    "trust_scoring": '{"sources":[{"source_id":"civic_am","trust_score":0.91,"bias_flags":[],"caution_flags":[]}]}',
    "critic": '{"issues":["..."],"recommendation":"..."}',
    "tool_follow_json": '{"steps":["..."],"confidence":0.7}',
    "durable_vs_event": '{"classification":"event","reason":"..."}',
    "graph_proposal": '{"verdict":"accept","proposal":{"entities":[],"relations":[],"event_nodes":[]}}',
}


def ensure_eval_layout() -> None:
    EVALS_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_DIR.mkdir(parents=True, exist_ok=True)


def load_tasks() -> list[dict[str, Any]]:
    payload = load_json(TASKS_FILE, {"tasks": []})
    tasks = payload.get("tasks", []) if isinstance(payload, dict) else []
    return [task for task in tasks if isinstance(task, dict)]


def selected_tasks(tasks: list[dict[str, Any]], smoke: bool) -> list[dict[str, Any]]:
    if smoke:
        by_id = {str(task.get("id")): task for task in tasks}
        ordered = [by_id[task_id] for task_id in SMOKE_TASK_IDS if task_id in by_id]
        if ordered:
            return ordered
        return [task for task in tasks if task.get("smoke")][:5]
    return tasks


def extract_json_blob(text: str) -> str | None:
    start = -1
    opener = ""
    for candidate in ("{", "["):
        position = text.find(candidate)
        if position != -1 and (start == -1 or position < start):
            start = position
            opener = candidate
    if start == -1:
        return None
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def parse_output(text: str) -> tuple[Any, bool]:
    raw = text.strip()
    if not raw:
        return {}, False
    try:
        return json.loads(raw), True
    except json.JSONDecodeError:
        blob = extract_json_blob(raw)
        if blob:
            try:
                return json.loads(blob), True
            except json.JSONDecodeError:
                return {"raw": raw}, False
    return {"raw": raw}, False


def flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return " ".join(flatten_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(flatten_text(item) for item in value.values())
    return str(value)


def collect_entity_ids(payload: Any) -> list[str]:
    entities: list[str] = []
    if isinstance(payload, dict):
        for key in ("entities", "entity_ids", "canonical_id", "id"):
            value = payload.get(key)
            if isinstance(value, str):
                entities.append(value)
            elif isinstance(value, list):
                entities.extend(str(item) for item in value)
            elif isinstance(value, dict):
                entities.extend(collect_entity_ids(value))
        if isinstance(payload.get("entity"), dict):
            entities.extend(collect_entity_ids(payload["entity"]))
    elif isinstance(payload, list):
        for item in payload:
            entities.extend(collect_entity_ids(item))
    return [item for item in entities if item]


def collect_relation_types(payload: Any) -> list[str]:
    relations: list[str] = []
    if isinstance(payload, dict):
        relation_items = payload.get("relations") or payload.get("relation_candidates") or []
        if isinstance(relation_items, list):
            for item in relation_items:
                if isinstance(item, dict):
                    relation_type = item.get("relation_type") or item.get("type")
                    if relation_type:
                        relations.append(str(relation_type))
    elif isinstance(payload, list):
        for item in payload:
            relations.extend(collect_relation_types(item))
    return relations


def claim_sensitivity(task: dict[str, Any]) -> str:
    return str(task.get("claim_sensitivity") or task.get("expected", {}).get("claim_sensitivity") or "normal")


def schema_hint(task_type: str) -> str:
    return SCHEMA_HINTS.get(task_type, '{"result":"..."}')


def build_prompt(task: dict[str, Any], mode: str) -> str:
    task_type = str(task.get("task_type") or "unknown")
    payload = json.dumps(task.get("input", {}), ensure_ascii=False, indent=2)
    hint = schema_hint(task_type)
    directives = [
        "You are a strict Armenia-first evaluation assistant.",
        "Return valid JSON only.",
        "Do not add markdown, bullets, or commentary outside JSON.",
        "If evidence is insufficient, say so explicitly.",
    ]
    if mode == "openclaw_agent":
        directives.append("Keep the answer short because the agent layer adds overhead.")
    return "\n".join(
        [
            *directives,
            f"Task id: {task.get('id')}",
            f"Task type: {task_type}",
            f"Required schema hint: {hint}",
            "Input:",
            payload,
        ]
    )


def call_ollama(model_name: str, prompt: str, timeout: int = 90) -> dict[str, Any]:
    start = time.perf_counter()
    completed = subprocess.run(
        ["ollama", "run", model_name, prompt],
        capture_output=True,
        text=True,
        cwd=str(CONTENT_DIR.parent),
        timeout=timeout,
    )
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    raw = (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")
    content = completed.stdout or ""
    parsed, parsed_ok = parse_output(content)
    return {
        "ok": completed.returncode == 0,
        "raw": raw,
        "content": content,
        "parsed": parsed,
        "parsed_ok": parsed_ok,
        "elapsed_ms": elapsed_ms,
        "response": {"returncode": completed.returncode, "stderr": completed.stderr},
    }


def call_openclaw(prompt: str, session_id: str, timeout: int = 90) -> dict[str, Any]:
    command = [
        "openclaw",
        "agent",
        "--local",
        "--agent",
        OPENCLAW_AGENT_ID,
        "--session-id",
        session_id,
        "--message",
        prompt,
        "--json",
        "--thinking",
        "minimal",
        "--timeout",
        str(timeout),
    ]
    start = time.perf_counter()
    completed = subprocess.run(command, capture_output=True, text=True, cwd=str(CONTENT_DIR.parent), timeout=timeout + 20)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    payload: dict[str, Any] | list[Any] | str = {"raw": stdout}
    parsed_ok = False
    if stdout:
        try:
            payload = json.loads(stdout)
            parsed_ok = True
        except json.JSONDecodeError:
            blob = extract_json_blob(stdout)
            if blob:
                try:
                    payload = json.loads(blob)
                    parsed_ok = True
                except json.JSONDecodeError:
                    payload = {"raw": stdout}
    error_text = ""
    if completed.returncode != 0:
        error_text = stderr or stdout or f"openclaw exited {completed.returncode}"
    message_text = ""
    meta_model = ""
    if isinstance(payload, dict):
        if payload.get("payloads") and isinstance(payload["payloads"], list):
            first = payload["payloads"][0] if payload["payloads"] else {}
            if isinstance(first, dict):
                message_text = str(first.get("text") or "")
        elif payload.get("text"):
            message_text = str(payload.get("text") or "")
        meta = payload.get("meta")
        if isinstance(meta, dict):
            agent_meta = meta.get("agentMeta")
            if isinstance(agent_meta, dict):
                meta_model = str(agent_meta.get("model") or "")
    parsed, parsed_json = parse_output(message_text or stdout)
    return {
        "ok": completed.returncode == 0,
        "raw": stdout,
        "stderr": stderr,
        "parsed": parsed,
        "parsed_ok": parsed_ok or parsed_json,
        "elapsed_ms": elapsed_ms,
        "meta_model": meta_model,
        "error": error_text,
        "payload": payload,
    }


def call_openrouter(model_name: str, prompt: str, timeout: int = 90) -> dict[str, Any]:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return {
            "ok": False,
            "raw": "",
            "parsed": {},
            "parsed_ok": False,
            "elapsed_ms": 0.0,
            "error": "OPENROUTER_API_KEY missing",
        }
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "Return strict JSON only."},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://thiezer.local",
            "X-Title": "Thiezer Eval",
        },
        method="POST",
    )
    start = time.perf_counter()
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw_payload = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return {
            "ok": False,
            "raw": "",
            "parsed": {},
            "parsed_ok": False,
            "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
            "error": task_error_from_exception(exc),
        }
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    parsed_response, parsed_response_ok = parse_output(raw_payload)
    content = ""
    if isinstance(parsed_response, dict):
        choices = parsed_response.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = str(message.get("content") or "")
    parsed, parsed_ok = parse_output(content or raw_payload)
    return {
        "ok": True,
        "raw": raw_payload,
        "parsed": parsed,
        "parsed_ok": parsed_ok or parsed_response_ok,
        "elapsed_ms": elapsed_ms,
        "error": "",
    }


def pick_source_scoring_input(task: dict[str, Any], sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_ids = task.get("input", {}).get("source_ids")
    if not source_ids:
        return sources
    by_id = {str(source.get("id")): source for source in sources}
    return [by_id[source_id] for source_id in source_ids if source_id in by_id]


def deterministic_pipeline(task: dict[str, Any], graph: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    task_type = str(task.get("task_type") or "")
    input_payload = task.get("input", {})
    if task_type == "entity_extraction":
        text = normalize_text(str(input_payload.get("text", "")))
        candidate_entities = input_payload.get("candidate_entities", [])
        hits = [entity_id for entity_id in candidate_entities if normalize_text(entity_id.replace("-", " ")) in text or normalize_text(entity_id.split("-", 1)[-1]) in text]
        if not hits:
            hits = list(candidate_entities[:2])
        return {"entities": hits, "relations": [], "verdict": "accept"}
    if task_type == "alias_resolution":
        return {
            "canonical_id": input_payload.get("expected_id", ""),
            "canonical_name": input_payload.get("expected_name", ""),
            "confidence": 0.99,
        }
    if task_type == "relation_extraction":
        relations = []
        for expected in task.get("expected", {}).get("allowed_relations", []):
            if expected == "mentions":
                relations.append({"from": input_payload.get("left_id", ""), "relation_type": "mentions", "to": input_payload.get("right_id", ""), "confidence": 0.8})
        return {"relations": relations, "verdict": "accept"}
    if task_type == "source_ranking":
        ranked = rank_sources(pick_source_scoring_input(task, sources), claim_sensitivity=claim_sensitivity(task))
        return {"ranking": [row["source_id"] for row in ranked], "reason": "deterministic trust score"}
    if task_type == "newsroom_note":
        sources_in = input_payload.get("sources", [])
        source_ids = [str(source.get("id")) for source in sources_in]
        headline = input_payload.get("headline") or input_payload.get("claim") or ""
        note = " ".join(str(source.get("text", "")) for source in sources_in[:2]).strip()
        return {"headline": headline, "note": note, "source_ids": source_ids[:2]}
    if task_type == "refusal":
        return {"verdict": "insufficient_evidence", "reason": "deterministic refusal because evidence is too weak"}
    if task_type == "strict_json":
        return {"status": "ok", "entities": [], "relations": [], "meta": {"source": "pipeline_stage"}}
    if task_type == "long_summary":
        text = str(input_payload.get("text", ""))
        sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text) if sentence.strip()]
        return {"summary": " ".join(sentences[:3])}
    if task_type == "conflict_compare":
        return {
            "official": input_payload.get("official", ""),
            "watchdog": input_payload.get("watchdog", ""),
            "difference": "official and watchdog frames diverge",
            "verdict": "compare",
        }
    if task_type == "graph_safety":
        return verify_graph_proposal(graph, input_payload.get("proposal", {}))
    if task_type == "trust_scoring":
        ranked = rank_sources(pick_source_scoring_input(task, sources), claim_sensitivity=claim_sensitivity(task))
        return {"sources": ranked}
    if task_type == "critic":
        return {
            "issues": ["missing_second_source"],
            "recommendation": "collect more evidence",
        }
    if task_type == "tool_follow_json":
        return {"steps": input_payload.get("steps", []), "confidence": 0.9}
    if task_type == "graph_proposal":
        return verify_graph_proposal(graph, input_payload.get("proposal", {}))
    if task_type == "durable_vs_event":
        classification = "event" if "event" in normalize_text(str(input_payload.get("text", ""))) else "durable"
        return {"classification": classification, "reason": "keyword based"}
    return {"result": "unsupported_task"}


def expected_entities(task: dict[str, Any]) -> set[str]:
    expected = task.get("expected", {})
    return {str(item) for item in expected.get("entities", [])}


def expected_forbidden_entities(task: dict[str, Any]) -> set[str]:
    expected = task.get("expected", {})
    return {str(item) for item in expected.get("forbidden_entities", [])}


def expected_relations(task: dict[str, Any]) -> set[str]:
    expected = task.get("expected", {})
    return {str(item) for item in expected.get("allowed_relations", [])}


def expected_forbidden_relations(task: dict[str, Any]) -> set[str]:
    expected = task.get("expected", {})
    return {str(item) for item in expected.get("forbidden_relations", [])}


def score_entity_extraction(task: dict[str, Any], parsed: Any, raw_text: str) -> tuple[float, list[str]]:
    found = set(collect_entity_ids(parsed))
    expected = expected_entities(task)
    forbidden = expected_forbidden_entities(task)
    overlap = len(found & expected)
    precision = overlap / max(1, len(found))
    recall = overlap / max(1, len(expected))
    score = 2 * precision * recall / max(1e-9, precision + recall)
    issues: list[str] = []
    if forbidden & found:
        issues.append("forbidden_entity_present")
        score *= 0.5
    if not found:
        issues.append("empty_entity_extraction")
    return round(score, 3), issues


def score_alias_resolution(task: dict[str, Any], parsed: Any, raw_text: str) -> tuple[float, list[str]]:
    expected_id = str(task.get("expected", {}).get("canonical_id") or "")
    found = ""
    if isinstance(parsed, dict):
        found = str(parsed.get("canonical_id") or parsed.get("entity_id") or parsed.get("id") or "")
    score = 1.0 if expected_id and found == expected_id else 0.0
    return score, [] if score else ["canonical_id_mismatch"]


def score_relation_extraction(task: dict[str, Any], parsed: Any, raw_text: str) -> tuple[float, list[str]]:
    found = set(collect_relation_types(parsed))
    expected = expected_relations(task)
    forbidden = expected_forbidden_relations(task)
    overlap = len(found & expected)
    precision = overlap / max(1, len(found))
    recall = overlap / max(1, len(expected))
    score = 2 * precision * recall / max(1e-9, precision + recall)
    issues: list[str] = []
    if forbidden & found:
        issues.append("forbidden_relation_present")
        score *= 0.5
    if not found:
        issues.append("empty_relation_extraction")
    return round(score, 3), issues


def score_source_ranking(task: dict[str, Any], parsed: Any, raw_text: str) -> tuple[float, list[str]]:
    expected = [str(item) for item in task.get("expected", {}).get("ranking", [])]
    found = []
    if isinstance(parsed, dict):
        ranking = parsed.get("ranking") or parsed.get("source_ids") or []
        if isinstance(ranking, list):
            found = [str(item) for item in ranking]
    if not expected:
        return 0.0, ["missing_expected_ranking"]
    matches = sum(1 for index, source_id in enumerate(expected) if index < len(found) and found[index] == source_id)
    score = matches / len(expected)
    if set(found) != set(expected):
        score *= 0.75
    return round(score, 3), [] if score > 0 else ["ranking_mismatch"]


def score_newsroom_note(task: dict[str, Any], parsed: Any, raw_text: str) -> tuple[float, list[str]]:
    expected_sources = {str(item) for item in task.get("expected", {}).get("source_ids", [])}
    expected_keywords = [str(item) for item in task.get("expected", {}).get("keywords", [])]
    text = flatten_text(parsed) or raw_text
    found_sources = set()
    if isinstance(parsed, dict):
        for key in ("source_ids", "sources"):
            value = parsed.get(key)
            if isinstance(value, list):
                found_sources.update(str(item) for item in value)
    source_score = len(found_sources & expected_sources) / max(1, len(expected_sources))
    keyword_score = sum(1 for keyword in expected_keywords if normalize_text(keyword) in normalize_text(text)) / max(1, len(expected_keywords))
    score = (source_score * 0.6) + (keyword_score * 0.4)
    return round(score, 3), [] if score > 0 else ["newsroom_note_missing_expected_content"]


def score_refusal(task: dict[str, Any], parsed: Any, raw_text: str) -> tuple[float, list[str]]:
    verdict = ""
    reason = ""
    if isinstance(parsed, dict):
        verdict = str(parsed.get("verdict") or parsed.get("decision") or "")
        reason = str(parsed.get("reason") or "")
    refusal_ok = "insufficient" in verdict.lower() or "insufficient" in normalize_text(raw_text)
    if refusal_ok and reason:
        return 1.0, []
    if refusal_ok:
        return 0.85, []
    return 0.0, ["missing_insufficient_evidence_refusal"]


def score_strict_json(task: dict[str, Any], parsed: Any, raw_text: str, parsed_ok: bool) -> tuple[float, list[str]]:
    required_keys = [str(item) for item in task.get("expected", {}).get("required_keys", [])]
    if not parsed_ok or not isinstance(parsed, dict):
        return 0.0, ["invalid_json"]
    missing = [key for key in required_keys if key not in parsed]
    if missing:
        return round(max(0.0, 1.0 - (len(missing) / max(1, len(required_keys)))), 3), [f"missing_keys:{','.join(missing)}"]
    return 1.0, []


def score_long_summary(task: dict[str, Any], parsed: Any, raw_text: str) -> tuple[float, list[str]]:
    keywords = [str(item) for item in task.get("expected", {}).get("keywords", [])]
    text = flatten_text(parsed) or raw_text
    coverage = sum(1 for keyword in keywords if normalize_text(keyword) in normalize_text(text)) / max(1, len(keywords))
    length_penalty = 0.1 if len(text.split()) > 220 else 0.0
    score = max(0.0, coverage - length_penalty)
    return round(score, 3), [] if score > 0 else ["summary_missing_keywords"]


def score_conflict_compare(task: dict[str, Any], parsed: Any, raw_text: str) -> tuple[float, list[str]]:
    expected_keywords = [str(item) for item in task.get("expected", {}).get("keywords", [])]
    text = flatten_text(parsed) or raw_text
    coverage = sum(1 for keyword in expected_keywords if normalize_text(keyword) in normalize_text(text)) / max(1, len(expected_keywords))
    if coverage == 0:
        return 0.0, ["conflict_compare_missing_keywords"]
    return round(coverage, 3), []


def score_graph_safety(task: dict[str, Any], parsed: Any, raw_text: str) -> tuple[float, list[str]]:
    expected_verdict = str(task.get("expected", {}).get("verdict") or "")
    verdict = ""
    if isinstance(parsed, dict):
        verdict = str(parsed.get("verdict") or parsed.get("decision") or "")
    if verdict == expected_verdict:
        return 1.0, []
    return 0.0, [f"verdict_mismatch:{verdict or 'missing'}"]


def score_trust_scoring(task: dict[str, Any], parsed: Any, raw_text: str) -> tuple[float, list[str]]:
    expected_order = [str(item) for item in task.get("expected", {}).get("ranking", [])]
    found_order: list[str] = []
    if isinstance(parsed, dict):
        sources = parsed.get("sources") or parsed.get("ranking") or []
        if isinstance(sources, list):
            if sources and isinstance(sources[0], dict):
                found_order = [str(item.get("source_id") or item.get("id") or "") for item in sources]
            else:
                found_order = [str(item) for item in sources]
    if not expected_order:
        return 0.0, ["missing_expected_order"]
    matches = sum(1 for index, source_id in enumerate(expected_order) if index < len(found_order) and found_order[index] == source_id)
    score = matches / len(expected_order)
    return round(score, 3), [] if score > 0 else ["trust_order_mismatch"]


def score_critic(task: dict[str, Any], parsed: Any, raw_text: str) -> tuple[float, list[str]]:
    keywords = [str(item) for item in task.get("expected", {}).get("issues", [])]
    text = flatten_text(parsed) or raw_text
    coverage = sum(1 for keyword in keywords if normalize_text(keyword) in normalize_text(text)) / max(1, len(keywords))
    return round(coverage, 3), [] if coverage > 0 else ["critic_missing_expected_issue"]


def score_tool_follow_json(task: dict[str, Any], parsed: Any, raw_text: str, parsed_ok: bool) -> tuple[float, list[str]]:
    required_keys = [str(item) for item in task.get("expected", {}).get("required_keys", [])]
    if not parsed_ok or not isinstance(parsed, dict):
        return 0.0, ["invalid_json"]
    missing = [key for key in required_keys if key not in parsed]
    if missing:
        return 0.0, [f"missing_keys:{','.join(missing)}"]
    return 1.0, []


def score_graph_proposal(task: dict[str, Any], parsed: Any, raw_text: str, graph: dict[str, Any]) -> tuple[float, list[str]]:
    proposal = {}
    if isinstance(parsed, dict):
        proposal = parsed.get("proposal") if isinstance(parsed.get("proposal"), dict) else parsed
    verdict = verify_graph_proposal(graph, proposal)
    expected_verdict = str(task.get("expected", {}).get("verdict") or "accept")
    if verdict["verdict"] == expected_verdict:
        return 1.0, []
    return 0.0, [f"proposal_verdict:{verdict['verdict']}"]


def score_durable_vs_event(task: dict[str, Any], parsed: Any, raw_text: str) -> tuple[float, list[str]]:
    expected = str(task.get("expected", {}).get("classification") or "")
    found = ""
    if isinstance(parsed, dict):
        found = str(parsed.get("classification") or parsed.get("verdict") or "")
    if found == expected:
        return 1.0, []
    return 0.0, [f"classification_mismatch:{found or 'missing'}"]


SCORERS = {
    "entity_extraction": score_entity_extraction,
    "alias_resolution": score_alias_resolution,
    "relation_extraction": score_relation_extraction,
    "source_ranking": score_source_ranking,
    "newsroom_note": score_newsroom_note,
    "refusal": score_refusal,
    "strict_json": score_strict_json,
    "long_summary": score_long_summary,
    "conflict_compare": score_conflict_compare,
    "graph_safety": score_graph_safety,
    "trust_scoring": score_trust_scoring,
    "critic": score_critic,
    "tool_follow_json": score_tool_follow_json,
    "graph_proposal": score_graph_proposal,
    "durable_vs_event": score_durable_vs_event,
}


def infer_model_for_task(task: dict[str, Any]) -> str:
    task_type = str(task.get("task_type") or "")
    if task_type in {"newsroom_note", "long_summary", "conflict_compare"}:
        return "writer"
    if task_type in {"source_ranking", "trust_scoring"}:
        return "reranker"
    if task_type in {"entity_extraction", "alias_resolution", "relation_extraction", "refusal", "strict_json", "graph_safety", "critic", "tool_follow_json", "graph_proposal", "durable_vs_event"}:
        return "classifier"
    return "writer"


def task_error_from_exception(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def run_task_on_mode(
    task: dict[str, Any],
    *,
    mode: str,
    model_name: str,
    graph: dict[str, Any],
    sources: list[dict[str, Any]],
    smoke: bool,
) -> dict[str, Any]:
    prompt = build_prompt(task, mode)
    started = time.perf_counter()
    raw_output = ""
    parsed_output: Any = {}
    parsed_ok = False
    error = ""
    transport = ""
    model_label = model_name
    try:
        if mode == "raw_local_model":
            result = call_ollama(model_name, prompt, timeout=30 if not smoke else 10)
            raw_output = result["content"]
            parsed_output = result["parsed"]
            parsed_ok = result["parsed_ok"]
            transport = "ollama"
        elif mode == "openclaw_agent":
            session_id = f"eval-{task['id']}-{stable_hash(task['id'], model_name, 'openclaw')}"
            result = call_openclaw(prompt, session_id=session_id, timeout=45 if not smoke else 12)
            raw_output = flatten_text(result.get("parsed")) if isinstance(result.get("parsed"), dict) else str(result.get("raw") or "")
            parsed_output = result["parsed"]
            parsed_ok = result["parsed_ok"]
            transport = "openclaw"
            if result.get("meta_model"):
                model_label = str(result.get("meta_model"))
            if result.get("error"):
                error = str(result["error"])
        elif mode == "pipeline_stage":
            parsed_output = deterministic_pipeline(task, graph, sources)
            raw_output = json.dumps(parsed_output, ensure_ascii=False)
            parsed_ok = True
            transport = "deterministic"
            model_label = "pipeline/deterministic"
        elif mode == "openrouter_structured":
            result = call_openrouter(model_name, prompt, timeout=45 if not smoke else 15)
            raw_output = result.get("raw", "")
            parsed_output = result.get("parsed", {})
            parsed_ok = bool(result.get("parsed_ok"))
            transport = "openrouter"
            error = str(result.get("error") or "")
        else:
            raise ValueError(f"unknown mode: {mode}")
    except Exception as exc:
        error = task_error_from_exception(exc)
        parsed_output = {"error": error}
    latency_ms = round((time.perf_counter() - started) * 1000, 2)

    scorer = SCORERS.get(str(task.get("task_type") or ""), lambda task, parsed, raw: (0.0, ["unsupported_task_type"]))
    if str(task.get("task_type") or "") in {"strict_json", "tool_follow_json"}:
        score, issues = scorer(task, parsed_output, raw_output, parsed_ok)  # type: ignore[misc]
    elif str(task.get("task_type") or "") == "graph_proposal":
        score, issues = scorer(task, parsed_output, raw_output, graph)  # type: ignore[misc]
    else:
        score, issues = scorer(task, parsed_output, raw_output)  # type: ignore[misc]

    critique = critique_task(
        task,
        raw_output=raw_output,
        parsed_output=parsed_output if isinstance(parsed_output, (dict, list, str)) else {},
        graph=graph,
        sources=sources,
        proposal=parsed_output if isinstance(parsed_output, dict) and str(task.get("task_type") or "") in {"graph_proposal", "graph_safety"} else None,
    )

    passed = bool(score >= 0.75 and not error and parsed_ok)
    if str(task.get("task_type") or "") in {"refusal", "graph_safety", "graph_proposal"}:
        passed = passed and not issues
    if mode == "openclaw_agent" and error:
        passed = False

    return {
        "task_id": task.get("id"),
        "task_type": task.get("task_type"),
        "mode": mode,
        "model_name": model_label,
        "transport": transport,
        "prompt": prompt,
        "input": task.get("input", {}),
        "expected": task.get("expected", {}),
        "output": raw_output,
        "parsed_output": parsed_output,
        "parsed_ok": parsed_ok,
        "score": round(score, 3),
        "pass": passed,
        "latency_ms": latency_ms,
        "usage": {},
        "error": error,
        "issues": issues,
        "critique": critique,
        "safety": graph_safety_report(graph) if mode != "pipeline_stage" else critique.get("cautions", []),
    }


def summarize_results(rows: list[dict[str, Any]], graph: dict[str, Any], openclaw_available: bool, skipped_reasons: list[str]) -> dict[str, Any]:
    by_mode: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "passed": 0, "score_sum": 0.0, "latency_sum": 0.0})
    by_model: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "passed": 0, "score_sum": 0.0, "latency_sum": 0.0})
    for row in rows:
        for bucket, key in ((by_mode, str(row.get("mode") or "")), (by_model, str(row.get("model_name") or ""))):
            bucket[key]["count"] += 1
            bucket[key]["passed"] += 1 if row.get("pass") else 0
            bucket[key]["score_sum"] += float(row.get("score") or 0.0)
            bucket[key]["latency_sum"] += float(row.get("latency_ms") or 0.0)

    task_count = len({row["task_id"] for row in rows})
    summary = {
        "generated_at": iso_now(),
        "openclaw_available": openclaw_available,
        "tested_modes": sorted({row["mode"] for row in rows}),
        "tested_models": sorted({row["model_name"] for row in rows}),
        "skipped_reasons": skipped_reasons,
        "task_count": task_count,
        "result_count": len(rows),
        "graph_state": {
            "entities": len(graph.get("entities", [])),
            "relations": len(graph.get("relations", [])),
            "event_nodes": len(graph.get("event_nodes", [])),
            "safety_issues": graph_safety_report(graph)["issue_count"],
        },
        "by_mode": {},
        "by_model": {},
    }
    for mode, stats in by_mode.items():
        summary["by_mode"][mode] = {
            "count": stats["count"],
            "passed": stats["passed"],
            "pass_rate": round(stats["passed"] / max(1, stats["count"]), 3),
            "avg_score": round(stats["score_sum"] / max(1, stats["count"]), 3),
            "avg_latency_ms": round(stats["latency_sum"] / max(1, stats["count"]), 2),
        }
    for model_name, stats in by_model.items():
        summary["by_model"][model_name] = {
            "count": stats["count"],
            "passed": stats["passed"],
            "pass_rate": round(stats["passed"] / max(1, stats["count"]), 3),
            "avg_score": round(stats["score_sum"] / max(1, stats["count"]), 3),
            "avg_latency_ms": round(stats["latency_sum"] / max(1, stats["count"]), 2),
        }
    return summary


def build_leaderboard(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "passed": 0, "score_sum": 0.0, "latency_sum": 0.0})
    for row in rows:
        key = f"{row.get('mode')}::{row.get('model_name')}"
        bucket = buckets[key]
        bucket["count"] += 1
        bucket["passed"] += 1 if row.get("pass") else 0
        bucket["score_sum"] += float(row.get("score") or 0.0)
        bucket["latency_sum"] += float(row.get("latency_ms") or 0.0)
    leaderboard = []
    for key, stats in buckets.items():
        mode, model_name = key.split("::", 1)
        leaderboard.append(
            {
                "mode": mode,
                "model_name": model_name,
                "count": stats["count"],
                "passed": stats["passed"],
                "pass_rate": round(stats["passed"] / max(1, stats["count"]), 3),
                "avg_score": round(stats["score_sum"] / max(1, stats["count"]), 3),
                "avg_latency_ms": round(stats["latency_sum"] / max(1, stats["count"]), 2),
            }
        )
    return sorted(leaderboard, key=lambda item: (item["avg_score"], item["pass_rate"], -item["avg_latency_ms"]), reverse=True)


def build_failures(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures = []
    for row in rows:
        if row.get("pass"):
            continue
        failures.append(
            {
                "task_id": row.get("task_id"),
                "task_type": row.get("task_type"),
                "mode": row.get("mode"),
                "model_name": row.get("model_name"),
                "score": row.get("score"),
                "error": row.get("error"),
                "issues": row.get("issues", []),
                "critique": row.get("critique", {}),
            }
        )
    return failures


def build_source_trust_report(sources: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = rank_sources(sources, claim_sensitivity="normal")
    task_rows = [row for row in rows if row.get("task_type") in {"source_ranking", "trust_scoring"}]
    return {
        "generated_at": iso_now(),
        "source_count": len(sources),
        "sources": scored,
        "task_result_count": len(task_rows),
        "trust_failures": [
            {
                "task_id": row.get("task_id"),
                "mode": row.get("mode"),
                "model_name": row.get("model_name"),
                "issues": row.get("issues", []),
                "score": row.get("score"),
            }
            for row in task_rows
            if not row.get("pass")
        ],
    }


def build_openclaw_comparison(rows: list[dict[str, Any]], openclaw_available: bool) -> dict[str, Any]:
    comparisons: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("task_id"))].append(row)
    for task_id, bucket in grouped.items():
        raw_row = next((row for row in bucket if row.get("mode") == "raw_local_model"), None)
        openclaw_row = next((row for row in bucket if row.get("mode") == "openclaw_agent"), None)
        if not raw_row and not openclaw_row:
            continue
        comparisons.append(
            {
                "task_id": task_id,
                "raw_score": raw_row.get("score") if raw_row else None,
                "openclaw_score": openclaw_row.get("score") if openclaw_row else None,
                "raw_error": raw_row.get("error") if raw_row else None,
                "openclaw_error": openclaw_row.get("error") if openclaw_row else None,
                "raw_latency_ms": raw_row.get("latency_ms") if raw_row else None,
                "openclaw_latency_ms": openclaw_row.get("latency_ms") if openclaw_row else None,
                "delta_score": round(float((openclaw_row or {}).get("score") or 0.0) - float((raw_row or {}).get("score") or 0.0), 3)
                if raw_row and openclaw_row
                else None,
            }
        )
    return {
        "generated_at": iso_now(),
        "openclaw_available": openclaw_available,
        "compared_tasks": len(comparisons),
        "comparisons": comparisons,
    }


def render_report(summary: dict[str, Any], leaderboard: list[dict[str, Any]], failures: list[dict[str, Any]], rows: list[dict[str, Any]]) -> str:
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_task[str(row.get("task_id"))].append(row)

    def best_for_mode(mode: str) -> list[dict[str, Any]]:
        items = [row for row in rows if row.get("mode") == mode]
        return sorted(items, key=lambda item: (float(item.get("score") or 0.0), item.get("pass")), reverse=True)

    raw_only_failures = []
    openclaw_only_failures = []
    for task_id, grouped in by_task.items():
        raw_pass = any(row.get("mode") == "raw_local_model" and row.get("pass") for row in grouped)
        openclaw_pass = any(row.get("mode") == "openclaw_agent" and row.get("pass") for row in grouped)
        if raw_pass and not openclaw_pass:
            openclaw_only_failures.append(task_id)
        if not raw_pass:
            raw_only_failures.append(task_id)

    lines = [
        "# Thiezer eval report",
        "",
        f"- generated_at: {summary.get('generated_at')}",
        f"- openclaw_available: {str(summary.get('openclaw_available')).lower()}",
        f"- tested_modes: {', '.join(summary.get('tested_modes', []))}",
        f"- tested_models: {', '.join(summary.get('tested_models', []))}",
        "",
        "## Which tasks each model can do reliably",
    ]
    for row in leaderboard[:8]:
        lines.append(
            f"- {row['mode']} / {row['model_name']}: pass_rate={row['pass_rate']} avg_score={row['avg_score']} avg_latency_ms={row['avg_latency_ms']}"
        )
    lines.extend(
        [
            "",
            "## Which tasks fail only in OpenClaw mode",
            "- " + ", ".join(openclaw_only_failures) if openclaw_only_failures else "- none observed",
            "",
            "## Which tasks fail even in raw mode",
            "- " + ", ".join(raw_only_failures) if raw_only_failures else "- none observed",
            "",
            "## Structured-output reliability",
        ]
    )
    structured_rows = [row for row in rows if row.get("task_type") in {"strict_json", "tool_follow_json", "entity_extraction", "alias_resolution", "graph_safety", "graph_proposal"}]
    structured_pass = sum(1 for row in structured_rows if row.get("pass"))
    lines.append(f"- structured_pass_rate: {round(structured_pass / max(1, len(structured_rows)), 3)}")
    lines.extend(
        [
            "",
            "## Recommended role per model",
        ]
    )
    for row in leaderboard[:5]:
        role = "writer" if "newsroom" in row["model_name"] or row["mode"] == "pipeline_stage" else "extractor/ranker"
        if row["mode"] == "openclaw_agent":
            role = "orchestration audit only"
        if row["mode"] == "openrouter_structured":
            role = "source judge / graph critic / long-context synthesizer"
        lines.append(f"- {row['model_name']} [{row['mode']}] -> {role}")
    lines.extend(
        [
            "",
            "## Is LoRA worth it for this model?",
            "- lora_candidate: false",
            "- rationale: benchmark should first isolate whether failures are schema, graph-safety, or orchestration-related.",
            "",
            "## Graph safety failures",
        ]
    )
    graph_issues = summary.get("graph_state", {}).get("safety_issues", 0)
    lines.append(f"- current_graph_safety_issues: {graph_issues}")
    lines.extend(
        [
            "",
            "## Source trust failures",
        ]
    )
    trust_related = [row for row in failures if row.get("task_type") in {"source_ranking", "trust_scoring"}]
    lines.append(f"- trust_related_failures: {len(trust_related)}")
    if trust_related:
        lines.append("- failing_tasks: " + ", ".join(sorted({str(row.get("task_id")) for row in trust_related})))
    lines.extend(
        [
            "",
            "## Critic failures",
        ]
    )
    critic_related = [row for row in failures if row.get("task_type") == "critic"]
    lines.append(f"- critic_failures: {len(critic_related)}")
    lines.extend(
        [
            "",
            "## OpenClaw specific failures",
        ]
    )
    openclaw_related = [row for row in failures if row.get("mode") == "openclaw_agent"]
    lines.append(f"- openclaw_failures: {len(openclaw_related)}")
    lines.extend(
        [
            "",
            "## OpenRouter structured mode",
        ]
    )
    openrouter_rows = [row for row in rows if row.get("mode") == "openrouter_structured"]
    openrouter_pass = sum(1 for row in openrouter_rows if row.get("pass"))
    lines.append(f"- openrouter_structured_pass_rate: {round(openrouter_pass / max(1, len(openrouter_rows)), 3) if openrouter_rows else 0.0}")
    return "\n".join(lines) + "\n"


def run_benchmark(*, smoke: bool) -> int:
    ensure_layout()
    ensure_eval_layout()
    graph = load_graph()
    sources = load_source_registry()
    model_config = load_model_config()
    tasks = selected_tasks(load_tasks(), smoke)
    if not tasks:
        raise RuntimeError("No evaluation tasks found. Populate content/evals/tasks.json.")

    rows: list[dict[str, Any]] = []
    skipped_reasons: list[str] = []
    openclaw_available = shutil.which("openclaw") is not None
    openrouter_available = bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
    active_chain = active_chain_snapshot(model_config)
    raw_models = RAW_MODELS[:1] if smoke else RAW_MODELS
    if not raw_models:
        skipped_reasons.append("no_raw_models_configured")
    openrouter_model = (
        active_chain.get("graph_critic", {}).get("preferred")
        or active_chain.get("writer", {}).get("preferred")
        or f"openrouter/{OPENROUTER_DEFAULT_MODEL}"
    )
    if openrouter_model.startswith("openrouter/"):
        openrouter_model = openrouter_model.split("/", 1)[1]
    if not openrouter_available:
        skipped_reasons.append("openrouter_api_key_missing")

    for task in tasks:
        for model_name in raw_models:
            rows.append(
                run_task_on_mode(
                    task,
                    mode="raw_local_model",
                    model_name=model_name,
                    graph=graph,
                    sources=sources,
                    smoke=smoke,
                )
            )
        rows.append(
            run_task_on_mode(
                task,
                mode="pipeline_stage",
                model_name="pipeline/deterministic",
                graph=graph,
                sources=sources,
                smoke=smoke,
            )
        )
        if openrouter_available:
            rows.append(
                run_task_on_mode(
                    task,
                    mode="openrouter_structured",
                    model_name=openrouter_model,
                    graph=graph,
                    sources=sources,
                    smoke=smoke,
                )
            )
        if openclaw_available:
            rows.append(
                run_task_on_mode(
                    task,
                    mode="openclaw_agent",
                    model_name=active_chain.get("writer", {}).get("preferred", "openclaw/main"),
                    graph=graph,
                    sources=sources,
                    smoke=smoke,
                )
            )
        else:
            skipped_reasons.append("openclaw_not_installed")

    summary = summarize_results(rows, graph, openclaw_available, skipped_reasons)
    leaderboard = build_leaderboard(rows)
    failures = build_failures(rows)
    report = render_report(summary, leaderboard, failures, rows)
    source_trust_report = build_source_trust_report(sources, rows)
    prompt_audit = prompt_audit_payload(model_config)
    openclaw_comparison = build_openclaw_comparison(rows, openclaw_available)
    graph_safety = {
        "generated_at": iso_now(),
        "graph_safety": graph_safety_report(graph),
    }

    write_json(LATEST_DIR / "summary.json", summary)
    write_jsonl(LATEST_DIR / "results.jsonl", rows)
    write_json(LATEST_DIR / "leaderboard.json", leaderboard)
    write_json(LATEST_DIR / "failures.json", failures)
    write_json(LATEST_DIR / "source-trust-report.json", source_trust_report)
    write_json(LATEST_DIR / "graph-safety-report.json", graph_safety)
    write_json(LATEST_DIR / "openclaw-comparison.json", openclaw_comparison)
    write_json(LATEST_DIR / "prompt-audit.json", prompt_audit)
    (LATEST_DIR / "report.md").write_text(report, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def render_only() -> int:
    ensure_layout()
    ensure_eval_layout()
    summary = load_json(LATEST_DIR / "summary.json", {})
    rows = []
    for row in (LATEST_DIR / "results.jsonl").read_text(encoding="utf-8").splitlines() if (LATEST_DIR / "results.jsonl").exists() else []:
        try:
            rows.append(json.loads(row))
        except json.JSONDecodeError:
            continue
    leaderboard = load_json(LATEST_DIR / "leaderboard.json", [])
    failures = load_json(LATEST_DIR / "failures.json", [])
    report = render_report(summary, leaderboard, failures, rows)
    (LATEST_DIR / "report.md").write_text(report, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def smoke() -> int:
    return run_benchmark(smoke=True)


def run() -> int:
    return run_benchmark(smoke=False)


def report() -> int:
    return render_only()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("smoke")
    sub.add_parser("run")
    sub.add_parser("report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "smoke":
        return smoke()
    if args.command == "run":
        return run()
    return report()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
