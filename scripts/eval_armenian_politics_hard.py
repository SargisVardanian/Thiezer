#!/usr/bin/env python3
"""Run hard Armenian-politics prompts against the local model and score discipline."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
CONTENT_DIR = ROOT / "content"
TASK_FILE = CONTENT_DIR / "evals" / "armenian-politics-hard-tasks.json"
LATEST_DIR = CONTENT_DIR / "evals" / "latest"
RESULTS_FILE = LATEST_DIR / "armenian-politics-hard-results.jsonl"
SUMMARY_FILE = LATEST_DIR / "armenian-politics-hard-summary.json"
REPORT_FILE = LATEST_DIR / "armenian-politics-hard-report.md"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pipeline_common import iso_now, load_model_config  # noqa: E402


JSON_INSTRUCTIONS = """Return JSON only. No markdown fences.
Required top-level keys:
- answer: string
- claims: array of objects; each claim must include claim, confidence, source_ids
- entities: array of objects; each entity must include name, type
- source_use: object or array explaining source handling
- cautions: array of strings
Use source IDs from the prompt. Do not invent sources.
Preserve exact source IDs and canonical English/Armenian/Russian entity labels from the prompt in entities.name.
Do not translate canonical entity names when the prompt provides exact labels."""


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(f"{key} {flatten_text(item)}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(flatten_text(item) for item in value)
    return str(value)


def lower_blob(value: Any) -> str:
    return flatten_text(value).lower()


def extract_json_blob(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    return ""


def parse_model_json(text: str) -> tuple[Any, bool, str]:
    blob = extract_json_blob(text)
    if not blob:
        return {}, False, "json_missing"
    try:
        return json.loads(blob), True, ""
    except json.JSONDecodeError as exc:
        return {}, False, f"json_invalid:{exc.msg}"


def default_backend() -> dict[str, str]:
    config = load_model_config()
    runtime = config.get("runtime", {}) if isinstance(config, dict) else {}
    backends = config.get("backends", {}) if isinstance(config, dict) else {}
    default_mode = str(runtime.get("default_backend_mode") or "ollama-native")
    backend = backends.get(default_mode, {}) if isinstance(backends, dict) else {}
    model = os.environ.get("THIEZER_HARD_EVAL_MODEL") or str(backend.get("model") or "gemma4:e4b")
    base_url = os.environ.get("THIEZER_OLLAMA_URL") or str(backend.get("base_url") or runtime.get("ollama_url") or "http://127.0.0.1:11434")
    return {"mode": default_mode, "model": model, "base_url": base_url.rstrip("/")}


def call_ollama(base_url: str, model: str, prompt: str, timeout: int) -> dict[str, Any]:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0,
            "num_ctx": 8192,
        },
    }
    request = Request(
        f"{base_url}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    content = str(data.get("response") or "")
    parsed, parsed_ok, parse_error = parse_model_json(content)
    return {
        "ok": True,
        "content": content,
        "parsed": parsed,
        "parsed_ok": parsed_ok,
        "parse_error": parse_error,
        "elapsed_ms": elapsed_ms,
        "ollama": {
            "total_duration": data.get("total_duration"),
            "load_duration": data.get("load_duration"),
            "prompt_eval_count": data.get("prompt_eval_count"),
            "eval_count": data.get("eval_count"),
        },
    }


def build_prompt(task: dict[str, Any], suite: dict[str, Any]) -> str:
    return "\n\n".join(
        [
            "You are evaluating Armenian politics research extraction for Thiezer.",
            "Language: Russian unless exact source labels are needed.",
            JSON_INSTRUCTIONS,
            f"Suite contract: {json.dumps(suite.get('response_contract', {}), ensure_ascii=False)}",
            f"Task ID: {task.get('id')}",
            str(task.get("prompt") or ""),
        ]
    )


def entity_type_map(parsed: Any) -> dict[str, str]:
    found: dict[str, str] = {}
    if not isinstance(parsed, dict):
        return found
    entities = parsed.get("entities", [])
    if not isinstance(entities, list):
        return found
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name") or "").strip()
        entity_type = str(entity.get("type") or "").strip().upper()
        if name and entity_type:
            found[name.lower()] = entity_type
    return found


def source_ids_from_claims(parsed: Any) -> set[str]:
    ids: set[str] = set()
    if not isinstance(parsed, dict):
        return ids
    for claim in parsed.get("claims", []) if isinstance(parsed.get("claims"), list) else []:
        if not isinstance(claim, dict):
            continue
        source_ids = claim.get("source_ids", [])
        if isinstance(source_ids, str):
            ids.add(source_ids)
        elif isinstance(source_ids, list):
            ids.update(str(item) for item in source_ids)
    ids.update(token for token in flatten_text(parsed.get("source_use", "")).split() if token.startswith("S"))
    return ids


def score_task(task: dict[str, Any], parsed: Any, parsed_ok: bool) -> tuple[float, list[str]]:
    checks = task.get("checks", {}) if isinstance(task.get("checks"), dict) else {}
    issues: list[str] = []
    score = 0.0

    if parsed_ok and isinstance(parsed, dict):
        score += 0.2
    else:
        return 0.0, ["invalid_json"]

    required_top = ["answer", "claims", "entities", "source_use", "cautions"]
    missing_top = [key for key in required_top if key not in parsed]
    if not missing_top:
        score += 0.15
    else:
        issues.append("missing_top_level:" + ",".join(missing_top))

    text = lower_blob(parsed)
    required_terms = checks.get("required_terms", []) if isinstance(checks.get("required_terms"), list) else []
    found_terms = [term for term in required_terms if str(term).lower() in text]
    if required_terms:
        score += 0.2 * (len(found_terms) / len(required_terms))
    missing_terms = [term for term in required_terms if term not in found_terms]
    if missing_terms:
        issues.append("missing_terms:" + ",".join(str(item) for item in missing_terms[:5]))

    forbidden_terms = checks.get("forbidden_terms", []) if isinstance(checks.get("forbidden_terms"), list) else []
    forbidden_hits = [term for term in forbidden_terms if str(term).lower() in text]
    if not forbidden_hits:
        score += 0.15
    else:
        issues.append("forbidden_terms:" + ",".join(str(item) for item in forbidden_hits))

    required_sources = set(str(item) for item in checks.get("required_source_ids", []) if item)
    used_sources = source_ids_from_claims(parsed)
    if required_sources:
        overlap = required_sources.intersection(used_sources)
        score += 0.1 * (len(overlap) / len(required_sources))
        missing_sources = sorted(required_sources - overlap)
        if missing_sources:
            issues.append("missing_sources:" + ",".join(missing_sources))

    expected_types = checks.get("required_entity_types", {}) if isinstance(checks.get("required_entity_types"), dict) else {}
    found_types = entity_type_map(parsed)
    if expected_types:
        type_hits = 0
        for name, entity_type in expected_types.items():
            actual = found_types.get(str(name).lower())
            if actual == str(entity_type).upper():
                type_hits += 1
            else:
                issues.append(f"entity_type_mismatch:{name}:{actual or 'missing'}")
        score += 0.1 * (type_hits / len(expected_types))

    caution_terms = checks.get("must_have_caution_terms", []) if isinstance(checks.get("must_have_caution_terms"), list) else []
    cautions_text = lower_blob(parsed.get("cautions", []))
    caution_hits = [term for term in caution_terms if str(term).lower() in cautions_text]
    if caution_terms:
        score += 0.1 * (len(caution_hits) / len(caution_terms))
        missing_cautions = [term for term in caution_terms if term not in caution_hits]
        if missing_cautions:
            issues.append("missing_cautions:" + ",".join(str(item) for item in missing_cautions))

    return round(min(score, 1.0), 3), issues


def run_suite(args: argparse.Namespace) -> int:
    suite = load_json(TASK_FILE)
    tasks = suite.get("tasks", [])
    if not isinstance(tasks, list) or not tasks:
        raise SystemExit(f"no tasks in {TASK_FILE}")
    if args.limit:
        tasks = tasks[: args.limit]

    backend = default_backend()
    model = args.model or backend["model"]
    base_url = args.base_url or backend["base_url"]

    rows: list[dict[str, Any]] = []
    for task in tasks:
        prompt = build_prompt(task, suite)
        if args.dry_run:
            parsed = {
                "answer": "dry_run",
                "claims": [],
                "entities": [],
                "source_use": {},
                "cautions": ["dry_run"],
            }
            score, issues = score_task(task, parsed, True)
            row = {
                "task_id": task.get("id"),
                "model": model,
                "transport": "dry_run",
                "parsed_ok": True,
                "score": score,
                "pass": False,
                "issues": issues,
                "latency_ms": 0.0,
                "output": parsed,
            }
        else:
            try:
                result = call_ollama(base_url, model, prompt, args.timeout)
                score, issues = score_task(task, result["parsed"], result["parsed_ok"])
                row = {
                    "task_id": task.get("id"),
                    "task_type": task.get("task_type"),
                    "model": model,
                    "transport": "ollama/api_generate",
                    "parsed_ok": result["parsed_ok"],
                    "score": score,
                    "pass": bool(score >= args.pass_threshold and result["parsed_ok"] and not issues),
                    "issues": issues + ([result["parse_error"]] if result.get("parse_error") else []),
                    "latency_ms": result["elapsed_ms"],
                    "ollama": result["ollama"],
                    "output": result["parsed"] if result["parsed_ok"] else result["content"],
                }
            except (TimeoutError, URLError, OSError) as exc:
                row = {
                    "task_id": task.get("id"),
                    "task_type": task.get("task_type"),
                    "model": model,
                    "transport": "ollama/api_generate",
                    "parsed_ok": False,
                    "score": 0.0,
                    "pass": False,
                    "issues": ["transport_error"],
                    "latency_ms": 0.0,
                    "error": str(exc),
                    "output": "",
                }
        rows.append(row)
        print(json.dumps({key: row.get(key) for key in ("task_id", "score", "pass", "issues", "latency_ms")}, ensure_ascii=False))

    passed = sum(1 for row in rows if row.get("pass"))
    avg_score = round(sum(float(row.get("score") or 0.0) for row in rows) / len(rows), 3) if rows else 0.0
    summary = {
        "suite": suite.get("suite"),
        "version": suite.get("version"),
        "generated_at": iso_now(),
        "model": model,
        "base_url": base_url,
        "task_count": len(rows),
        "passed": passed,
        "pass_rate": round(passed / len(rows), 3) if rows else 0.0,
        "avg_score": avg_score,
        "pass_threshold": args.pass_threshold,
        "dry_run": bool(args.dry_run),
    }
    write_outputs(summary, rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def write_outputs(summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    append_jsonl(RESULTS_FILE, rows)
    write_json(SUMMARY_FILE, summary)
    lines = [
        "# Armenian Politics Hard Eval",
        "",
        f"- generated_at: {summary['generated_at']}",
        f"- model: {summary['model']}",
        f"- task_count: {summary['task_count']}",
        f"- passed: {summary['passed']}",
        f"- pass_rate: {summary['pass_rate']}",
        f"- avg_score: {summary['avg_score']}",
        "",
        "## Results",
        "",
        "| task | score | pass | issues |",
        "| --- | ---: | --- | --- |",
    ]
    for row in rows:
        issues = ", ".join(str(item) for item in row.get("issues", []))
        lines.append(f"| {row.get('task_id')} | {row.get('score')} | {str(row.get('pass')).lower()} | {issues} |")
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="", help="Ollama model name; defaults to configured ollama-native model")
    parser.add_argument("--base-url", default="", help="Ollama base URL; defaults to local-model-config")
    parser.add_argument("--timeout", type=int, default=90, help="Per-task timeout in seconds")
    parser.add_argument("--limit", type=int, default=0, help="Run only the first N tasks")
    parser.add_argument("--pass-threshold", type=float, default=0.72)
    parser.add_argument("--dry-run", action="store_true", help="Validate task pack and output writing without calling Ollama")
    return parser


def main() -> int:
    return run_suite(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
