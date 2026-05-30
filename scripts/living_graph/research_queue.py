"""Consume graph-generated research questions into bounded agent runs."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pipeline_common import EXPLORATION_QUEUE_FILE, SYSTEM_DIR, iso_now  # noqa: E402

QUEUE_RECEIPTS_FILE = SYSTEM_DIR / "exploration-queue-receipts.jsonl"


def load_question_queue(path: Path = EXPLORATION_QUEUE_FILE) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def write_question_queue(rows: list[dict[str, Any]], path: Path = EXPLORATION_QUEUE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def next_queued_question(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    queued = [row for row in rows if str(row.get("status") or "queued") == "queued"]
    if not queued:
        return None
    return sorted(queued, key=lambda row: (-float(row.get("priority_score") or 0.0), str(row.get("created_at") or ""), str(row.get("id") or "")))[0]


def mark_question_status(question_id: str, status: str, *, run_id: str = "", error: str = "", path: Path = EXPLORATION_QUEUE_FILE) -> dict[str, Any]:
    rows = load_question_queue(path)
    updated: dict[str, Any] = {}
    for row in rows:
        if str(row.get("id") or "") != question_id:
            continue
        row["status"] = status
        row["updated_at"] = iso_now()
        if run_id:
            row["run_id"] = run_id
        if error:
            row["error"] = error
        updated = dict(row)
        break
    if updated:
        write_question_queue(rows, path)
    return updated


def append_queue_receipt(receipt: dict[str, Any], path: Path = QUEUE_RECEIPTS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")


def question_to_run_payload(question: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    query = str(question.get("question") or "").strip()
    budget = question.get("budget_estimate", {}) if isinstance(question.get("budget_estimate"), dict) else {}
    search_queries = question.get("search_queries", {}) if isinstance(question.get("search_queries"), dict) else {}
    flat_queries: list[str] = []
    for values in search_queries.values():
        if isinstance(values, list):
            flat_queries.extend(str(value).strip() for value in values if str(value).strip())
    payload = {
        "budget_pages": int(budget.get("pages") or 6),
        "max_depth": int(budget.get("max_depth") or 2),
        "question_id": question.get("id"),
        "question_type": question.get("question_type"),
        "target_entities": question.get("target_entities", []),
        "expected_claim_types": question.get("expected_claim_types", []),
        "suggested_source_types": question.get("suggested_source_types", []),
        "seed_queries": flat_queries[:6],
        "source": "exploration_queue",
    }
    return query, payload


def start_next_question_run(*, queue_path: Path = EXPLORATION_QUEUE_FILE, receipt_path: Path | None = None, run_steps: int = 0) -> dict[str, Any]:
    try:
        from .agent_runtime import runtime
    except ImportError:  # pragma: no cover
        from living_graph.agent_runtime import runtime

    rows = load_question_queue(queue_path)
    target_receipt_path = receipt_path or (QUEUE_RECEIPTS_FILE if queue_path == EXPLORATION_QUEUE_FILE else queue_path.with_suffix(".receipts.jsonl"))
    question = next_queued_question(rows)
    if not question:
        receipt = {
            "contract": "ExplorationQueueReceipt.v1",
            "status": "empty",
            "created_at": iso_now(),
            "question_id": "",
            "run_id": "",
        }
        append_queue_receipt(receipt, path=target_receipt_path)
        return receipt
    query, payload = question_to_run_payload(question)
    try:
        run = runtime.start_run(query, payload)
        question_id = str(question.get("id") or "")
        mark_question_status(question_id, "running", run_id=run["run_id"], path=queue_path)
        trace: dict[str, Any] = {}
        final_question_status = "running"
        if run_steps > 0:
            trace = runtime.run_steps(run["run_id"], max_steps=run_steps)
            run_status = str(trace.get("status") or "").strip()
            if run_status in {"completed", "completed_no_changes", "completed_with_warnings", "no_results"}:
                final_question_status = "completed"
            elif run_status == "failed_retryable":
                final_question_status = "retryable_failed"
            elif run_status == "failed":
                final_question_status = "failed"
            mark_question_status(question_id, final_question_status, run_id=run["run_id"], path=queue_path)
        receipt = {
            "contract": "ExplorationQueueReceipt.v1",
            "status": "advanced" if run_steps > 0 else "started",
            "created_at": iso_now(),
            "question_id": question_id,
            "run_id": run["run_id"],
            "run_type": run.get("run_type"),
            "run_status": trace.get("status", "queued"),
            "question_status": final_question_status,
            "steps_requested": run_steps,
            "question_type": question.get("question_type"),
            "target_entities": question.get("target_entities", []),
        }
    except Exception as exc:
        question_id = str(question.get("id") or "")
        mark_question_status(question_id, "failed", error=str(exc), path=queue_path)
        receipt = {
            "contract": "ExplorationQueueReceipt.v1",
            "status": "failed",
            "created_at": iso_now(),
            "question_id": question_id,
            "run_id": "",
            "error": str(exc),
        }
    append_queue_receipt(receipt, path=target_receipt_path)
    return receipt
