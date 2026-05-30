"""Durable run loop with checkpoints and latest trace persistence."""

from __future__ import annotations

import threading
import time
from typing import Any

try:
    from ..store import LATEST_RESEARCH_RUN_FILE, RESEARCH_RUNS_LOG, append_jsonl, write_json
    from ..research_tools import build_search_provider
    from .planner import classify_user_query, create_initial_plan
    from .task_db import (
        build_research_trace,
        create_run,
        get_run,
        latest_run,
        list_items,
        fail_waiting_items,
        mark_item_done,
        mark_item_failed,
        mark_item_running,
        next_item,
        reset_incomplete_items,
        save_graph_diff,
        summarize_counts,
        update_run_status,
    )
    from .workers import execute_item
    from pipeline_common import active_chain_snapshot, load_model_config
except ImportError:  # pragma: no cover
    from living_graph.store import LATEST_RESEARCH_RUN_FILE, RESEARCH_RUNS_LOG, append_jsonl, write_json
    from living_graph.research_tools import build_search_provider
    from living_graph.agent_runtime.planner import classify_user_query, create_initial_plan
    from living_graph.agent_runtime.task_db import (
        build_research_trace,
        create_run,
        get_run,
        latest_run,
        list_items,
        fail_waiting_items,
        mark_item_done,
        mark_item_failed,
        mark_item_running,
        next_item,
        reset_incomplete_items,
        save_graph_diff,
        summarize_counts,
        update_run_status,
    )
    from living_graph.agent_runtime.workers import execute_item
    from pipeline_common import active_chain_snapshot, load_model_config


_BACKGROUND_RUNS: dict[str, threading.Thread] = {}
_BACKGROUND_RUNS_LOCK = threading.Lock()


def _preferred_model_id(value: Any) -> str:
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            provider = str(first.get("provider") or "").strip()
            model = str(first.get("id") or first.get("model") or "").strip()
            if "/" in model:
                return model
            if provider and model:
                return f"{provider}/{model}"
            return model or provider
        return str(first).strip()
    if isinstance(value, dict):
        provider = str(value.get("provider") or "").strip()
        model = str(value.get("id") or value.get("model") or "").strip()
        if "/" in model:
            return model
        if provider and model:
            return f"{provider}/{model}"
        return model or provider
    return str(value or "").strip()


def _work_item_context(item: dict[str, Any], result: Any | None = None) -> dict[str, Any]:
    payload = dict(item.get("input_json", {}) or {})
    item_type = str(item.get("item_type") or "").strip()
    entity_name = str(
        payload.get("name")
        or payload.get("candidate_name")
        or payload.get("page_title")
        or payload.get("office_title")
        or payload.get("ministry_name")
        or payload.get("title")
        or item.get("title")
        or ""
    ).strip()
    source_url = str(
        payload.get("source_url")
        or payload.get("profile_url")
        or payload.get("url")
        or ""
    ).strip()
    source_title = str(
        payload.get("source_title")
        or payload.get("page_title")
        or payload.get("title")
        or item.get("title")
        or entity_name
        or ""
    ).strip()
    relation_name = str(
        payload.get("relation_type")
        or payload.get("office_title")
        or payload.get("ministry_name")
        or payload.get("target_name")
        or payload.get("page_title")
        or ""
    ).strip()
    if result is None:
        if item_type.startswith("fetch"):
            source_status = "opened"
        elif item_type.startswith("extract"):
            source_status = "opened"
        elif item_type.startswith("rebuild") or item_type.startswith("build") or item_type.startswith("link") or item_type.startswith("admit") or item_type.startswith("merge"):
            source_status = "processing"
        else:
            source_status = "searching"
    else:
        source_status = "searching"
        if item_type.startswith("fetch"):
            source_status = "opened"
        elif item_type.startswith("extract"):
            source_status = "accepted" if getattr(result, "ok", False) else "rejected"
        elif item_type.startswith("rebuild") or item_type.startswith("build") or item_type.startswith("link") or item_type.startswith("admit") or item_type.startswith("merge"):
            source_status = "accepted"
        if getattr(result, "status", "") in {"failed", "failed_retryable"}:
            source_status = "failed"
        if getattr(result, "ok", False) and item_type.startswith("discover"):
            source_status = "searching"
    current_claim = ""
    if isinstance(getattr(result, "output", None), dict):
        current_claim = str(
            result.output.get("statement")
            or result.output.get("claim")
            or result.output.get("profile_url")
            or result.output.get("entity_id")
            or ""
        ).strip()
        if result.output.get("entity_name"):
            entity_name = str(result.output.get("entity_name") or entity_name).strip()
    return {
        "current_work_item_type": item_type,
        "current_work_item_title": str(item.get("title") or "").strip(),
        "current_entity_name": entity_name,
        "current_entity_id": str(item.get("entity_id") or payload.get("entity_id") or payload.get("subject_id") or "").strip(),
        "current_relation_name": relation_name,
        "current_source_title": source_title,
        "current_source_url": source_url,
        "current_source_status": source_status,
        "current_extracted_quote": "",
        "current_extracted_claim": current_claim,
    }


def _persist_trace(run_id: str) -> dict[str, Any]:
    trace = build_research_trace(run_id)
    if trace.get("ok"):
        write_json(LATEST_RESEARCH_RUN_FILE, trace)
        append_jsonl(RESEARCH_RUNS_LOG, [trace])
    return trace


def start_run(query: str, budget_json: dict[str, Any]) -> dict[str, Any]:
    run_type = classify_user_query(query)
    run_id = create_run(query, run_type, budget_json)
    plan = create_initial_plan(query, run_id, budget_json)
    _, search_meta = build_search_provider()
    model_config = load_model_config()
    chain = active_chain_snapshot(model_config)
    selected_model = _preferred_model_id(chain.get("writer", {}).get("preferred") or chain.get("parser", {}).get("preferred") or chain.get("classifier", {}).get("preferred") or "ollama/gemma4:e4b")
    role_history_context = dict(plan.get("role_history_context", {}) or {})
    update_run_status(run_id, "queued", current_stage=plan["stages"][0] if plan.get("stages") else "")
    update_run_status(
        run_id,
        "queued",
        summary_json={
            "seed_queries": [query],
            "frontier": [],
            "stages": plan.get("stages", []),
            "search_provider": search_meta.get("provider", "unknown"),
            "internet_search_available": bool(search_meta.get("available", False)),
            "selected_model": selected_model,
            "resolved_model": selected_model,
            "model_used": selected_model,
            "planner_status": "deterministic_routes_with_model_ready",
            "target_entity": role_history_context.get("target_role") or "",
            "target_type": role_history_context.get("target_type") or run_type,
            "target_role": role_history_context.get("target_role") or "",
            "date_from": role_history_context.get("date_from"),
            "date_to": role_history_context.get("date_to"),
            "context_person": role_history_context.get("context_person") or "",
            "requested_entities": role_history_context.get("requested_entities", []),
            "temporal_granularity": role_history_context.get("temporal_granularity") or "",
            "limited_search_mode": bool(search_meta.get("provider") == "fallback_official_seed_only" and not search_meta.get("available", False)),
        },
    )
    return {"run_id": run_id, "run_type": run_type, "stages": plan.get("stages", [])}


def run_steps(run_id: str, max_steps: int = 10) -> dict[str, Any]:
    run = get_run(run_id)
    if run is None:
        return {"ok": False, "error": "run_not_found", "run_id": run_id}
    update_run_status(run_id, "running", current_stage=run.get("current_stage") or "")
    steps = 0
    finalized = False
    while steps < max_steps:
        item = next_item(run_id)
        if item is None:
            _finalize_run(run_id)
            finalized = True
            break
        mark_item_running(item["item_id"])
        update_run_status(run_id, "running", current_stage=item["item_type"], summary_json=_work_item_context(item))
        result = execute_item(run_id, item)
        if result.ok:
            mark_item_done(item["item_id"], result.output)
            save_graph_diff(run_id, result.graph_diff.to_dict())
            update_run_status(run_id, "running", current_stage=result.current_stage or item["item_type"], summary_json=_work_item_context(item, result))
        else:
            retryable = result.status in {"waiting", "failed_retryable"}
            mark_item_failed(item["item_id"], result.error, retryable=retryable)
            update_run_status(run_id, "running" if retryable else "failed_retryable" if result.status == "failed_retryable" else "running", current_stage=result.current_stage or item["item_type"], summary_json={**_work_item_context(item, result), "failure_reasons": [result.error] if result.error else []})
        steps += 1
        _persist_trace(run_id)
    if not finalized:
        _finalize_run(run_id)
    return _persist_trace(run_id)


def resume_run(run_id: str, max_steps: int = 20) -> dict[str, Any]:
    return run_steps(run_id, max_steps=max_steps)


def run_until_idle(run_id: str, max_steps_per_call: int = 20) -> dict[str, Any]:
    trace = run_steps(run_id, max_steps=max_steps_per_call)
    return trace


def start_background_run(run_id: str, max_steps_per_call: int = 8, pause_seconds: float = 0.25) -> bool:
    with _BACKGROUND_RUNS_LOCK:
        existing = _BACKGROUND_RUNS.get(run_id)
        if existing and existing.is_alive():
            return False
        reset_incomplete_items(run_id)

        def _worker() -> None:
            try:
                while True:
                    trace = run_steps(run_id, max_steps=max_steps_per_call)
                    run = get_run(run_id)
                    if run is None:
                        break
                    status = str(run.get("status") or trace.get("status") or "").strip()
                    if status in {"completed", "completed_no_changes", "completed_with_warnings", "failed", "failed_retryable", "no_results"}:
                        break
                    counts = summarize_counts(list_items(run_id))
                    if not (counts.get("queued", 0) or counts.get("running", 0) or counts.get("waiting", 0)):
                        _finalize_run(run_id)
                        break
                    time.sleep(pause_seconds)
            finally:
                with _BACKGROUND_RUNS_LOCK:
                    _BACKGROUND_RUNS.pop(run_id, None)

        thread = threading.Thread(target=_worker, name=f"thiezer-run-{run_id}", daemon=True)
        _BACKGROUND_RUNS[run_id] = thread
        thread.start()
        return True


def latest_trace() -> dict[str, Any]:
    run = latest_run()
    if run is None:
        return {"ok": True, "run_id": "", "status": "idle", "counts": {}, "trace": {"visited_urls": [], "accepted_sources": [], "rejected_sources": [], "extracted_claims": [], "graph_diff": {"new_nodes": [], "updated_nodes": [], "new_edges": [], "updated_edges": [], "rejected": []}}}
    return build_research_trace(run["run_id"])


def _finalize_run(run_id: str) -> None:
    run = get_run(run_id)
    if run is None:
        return
    items = list_items(run_id)
    counts = summarize_counts(items)
    summary = dict(run.get("summary_json", {}))
    last_active_stage = str(run.get("current_stage") or summary.get("last_active_stage") or "").strip()
    roster_count = int(summary.get("roster_record_count", 0) or 0)
    role_history_count = int(summary.get("role_history_record_count", 0) or 0)
    profile_pages_fetched = int(summary.get("profile_pages_fetched", 0) or 0)
    claims_extracted = int(summary.get("claims_extracted", 0) or 0)
    graph_updates = int(summary.get("graph_updates", 0) or 0)
    role_history_office_holder_claims = int(summary.get("role_history_office_holder_claims", 0) or 0)
    artifact_graph_changes = int(build_research_trace(run_id).get("run", {}).get("accepted_change_artifacts", 0) or 0)
    if counts.get("running", 0) or counts.get("queued", 0):
        return
    if counts.get("waiting", 0):
        failed_waiting = fail_waiting_items(run_id, "run finalized with waiting work items")
        update_run_status(
            run_id,
            "failed_retryable",
            current_stage="failed_retryable",
            summary_json={
                "counts": counts,
                "last_active_stage": last_active_stage,
                "failure_reasons": list(summary.get("failure_reasons", [])) + [f"{failed_waiting} waiting work items were marked failed" if failed_waiting else "one or more work items remained waiting"],
            },
        )
        return
    final_status = "completed"
    failure_reasons: list[str] = []
    if counts.get("failed", 0):
        final_status = "failed"
    elif run.get("run_type") in {"parliament_roster_enrichment", "government_ministers_enrichment", "role_history_enrichment"}:
        if run.get("run_type") == "role_history_enrichment":
            if role_history_count <= 0:
                failure_reasons.append("role history search returned 0 candidates")
            if role_history_office_holder_claims <= 0:
                failure_reasons.append("no real office-holder claims admitted")
        elif roster_count <= 0:
            failure_reasons.append(
                "minister roster parser returned 0 records"
                if run.get("run_type") == "government_ministers_enrichment"
                else "roster parser returned 0 records"
            )
        if profile_pages_fetched <= 0:
            failure_reasons.append("no accepted profile sources")
        if claims_extracted <= 0:
            failure_reasons.append("no claims extracted")
        if graph_updates <= 0:
            failure_reasons.append("no graph updates applied")
        if failure_reasons and artifact_graph_changes <= 0:
            final_status = "failed_retryable"
        elif run.get("run_type") == "role_history_enrichment" and role_history_office_holder_claims <= 0:
            final_status = "completed_no_changes"
        elif failure_reasons or profile_pages_fetched <= 0 or counts.get("failed", 0):
            final_status = "completed_with_warnings"
    if final_status == "completed" and graph_updates <= 0:
        final_status = "completed_no_changes"
    update_run_status(
        run_id,
        final_status,
        current_stage=final_status,
        summary_json={"counts": counts, "failure_reasons": failure_reasons, "last_active_stage": last_active_stage},
    )
