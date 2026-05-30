"""SQLite-backed durable queue for Living Graph agent tasks."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

try:
    from ..store import ROOT, edge_rows, iso_now, load_graph, node_rows, stable_hash
    from ..research_tools import read_events
    from pipeline_common import active_chain_snapshot, load_model_config
except ImportError:  # pragma: no cover
    from living_graph.store import ROOT, edge_rows, iso_now, load_graph, node_rows, stable_hash
    from living_graph.research_tools import read_events
    from pipeline_common import active_chain_snapshot, load_model_config


DB_PATH = ROOT / "content" / "system" / "agent-runtime" / "thiezer_tasks.sqlite"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _new_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{stable_hash(*parts, str(time.time_ns()))}"


def init_db() -> None:
    with closing(_connect()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                user_query TEXT NOT NULL,
                run_type TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                current_stage TEXT,
                budget_json TEXT NOT NULL,
                summary_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS work_items (
                item_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                parent_item_id TEXT,
                item_type TEXT NOT NULL,
                entity_id TEXT,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 100,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                input_json TEXT NOT NULL,
                output_json TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                artifact_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                item_id TEXT,
                artifact_type TEXT NOT NULL,
                ref TEXT,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tool_calls (
                tool_call_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                item_id TEXT,
                tool_name TEXT NOT NULL,
                input_json TEXT NOT NULL,
                output_json TEXT,
                status TEXT NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL,
                finished_at TEXT
            );
            CREATE TABLE IF NOT EXISTS graph_diffs (
                diff_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                new_node_ids_json TEXT NOT NULL,
                updated_node_ids_json TEXT NOT NULL,
                new_edge_ids_json TEXT NOT NULL,
                updated_edge_ids_json TEXT NOT NULL,
                rejected_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.commit()


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _row_to_run(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "run_id": row["run_id"],
        "user_query": row["user_query"],
        "run_type": row["run_type"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "current_stage": row["current_stage"] or "",
        "budget_json": _loads(row["budget_json"], {}),
        "summary_json": _loads(row["summary_json"], {}),
    }


def _row_to_item(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "item_id": row["item_id"],
        "run_id": row["run_id"],
        "parent_item_id": row["parent_item_id"] or "",
        "item_type": row["item_type"],
        "entity_id": row["entity_id"] or "",
        "title": row["title"],
        "status": row["status"],
        "priority": int(row["priority"] or 100),
        "attempts": int(row["attempts"] or 0),
        "max_attempts": int(row["max_attempts"] or 3),
        "input_json": _loads(row["input_json"], {}),
        "output_json": _loads(row["output_json"], {}),
        "error": row["error"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_run(user_query: str, run_type: str, budget_json: dict[str, Any]) -> str:
    init_db()
    now = iso_now()
    run_id = f"run-{stable_hash(user_query, run_type, now)}"
    with closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO runs (run_id, user_query, run_type, status, created_at, updated_at, current_stage, budget_json, summary_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, user_query, run_type, "queued", now, now, "", json.dumps(budget_json, ensure_ascii=False), "{}"),
        )
        conn.commit()
    return run_id


def get_run(run_id: str) -> dict[str, Any] | None:
    init_db()
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return _row_to_run(row)


def update_run_status(run_id: str, status: str, current_stage: str | None = None, summary_json: dict[str, Any] | None = None) -> None:
    init_db()
    run = get_run(run_id)
    merged = dict(run.get("summary_json", {})) if run else {}
    if isinstance(summary_json, dict):
        merged.update(summary_json)
    with closing(_connect()) as conn:
        conn.execute(
            "UPDATE runs SET status = ?, updated_at = ?, current_stage = COALESCE(?, current_stage), summary_json = ? WHERE run_id = ?",
            (status, iso_now(), current_stage, json.dumps(merged, ensure_ascii=False), run_id),
        )
        conn.commit()


def increment_run_summary(run_id: str, **increments: int) -> None:
    run = get_run(run_id)
    if run is None:
        return
    summary = dict(run.get("summary_json", {}))
    for key, amount in increments.items():
        if isinstance(amount, dict):
            existing = summary.get(key, {})
            merged = dict(existing) if isinstance(existing, dict) else {}
            for sub_key, sub_value in amount.items():
                if isinstance(sub_value, (int, float)) and isinstance(merged.get(sub_key), (int, float)):
                    merged[sub_key] = merged.get(sub_key, 0) + sub_value
                else:
                    merged[sub_key] = sub_value
            summary[key] = merged
        else:
            summary[key] = int(summary.get(key, 0) or 0) + int(amount or 0)
    update_run_status(run_id, run.get("status") or "running", summary_json=summary)


def enqueue_item(run_id: str, item_type: str, title: str, input_json: dict[str, Any], priority: int = 100, parent_item_id: str | None = None, entity_id: str = "") -> str:
    init_db()
    now = iso_now()
    item_id = _new_id("item", run_id, item_type, title, entity_id, now)
    with closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO work_items (item_id, run_id, parent_item_id, item_type, entity_id, title, status, priority, attempts, max_attempts, input_json, output_json, error, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 3, ?, ?, ?, ?, ?)",
            (item_id, run_id, parent_item_id or "", item_type, entity_id, title, "queued", int(priority), json.dumps(input_json, ensure_ascii=False), "{}", "", now, now),
        )
        conn.commit()
    return item_id


def next_item(run_id: str) -> dict[str, Any] | None:
    init_db()
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT * FROM work_items WHERE run_id = ? AND status = 'queued' ORDER BY priority ASC, created_at ASC LIMIT 1",
            (run_id,),
        ).fetchone()
    return _row_to_item(row)


def mark_item_running(item_id: str) -> None:
    init_db()
    with closing(_connect()) as conn:
        conn.execute(
            "UPDATE work_items SET status = 'running', attempts = attempts + 1, updated_at = ? WHERE item_id = ?",
            (iso_now(), item_id),
        )
        conn.commit()


def mark_item_done(item_id: str, output_json: dict[str, Any]) -> None:
    init_db()
    with closing(_connect()) as conn:
        conn.execute(
            "UPDATE work_items SET status = 'done', output_json = ?, error = '', updated_at = ? WHERE item_id = ?",
            (json.dumps(output_json, ensure_ascii=False), iso_now(), item_id),
        )
        conn.commit()


def mark_item_failed(item_id: str, error: str, *, retryable: bool = False) -> None:
    init_db()
    with closing(_connect()) as conn:
        row = conn.execute("SELECT attempts, max_attempts FROM work_items WHERE item_id = ?", (item_id,)).fetchone()
        attempts = int(row["attempts"] or 0) if row else 0
        max_attempts = int(row["max_attempts"] or 3) if row else 3
        status = "waiting" if retryable and attempts < max_attempts else "failed"
        conn.execute(
            "UPDATE work_items SET status = ?, error = ?, updated_at = ? WHERE item_id = ?",
            (status, error[:1000], iso_now(), item_id),
        )
        conn.commit()


def reset_incomplete_items(run_id: str) -> int:
    init_db()
    now = iso_now()
    with closing(_connect()) as conn:
        cursor = conn.execute(
            "UPDATE work_items SET status = 'queued', updated_at = ? WHERE run_id = ? AND status IN ('running', 'waiting')",
            (now, run_id),
        )
        conn.commit()
        return int(cursor.rowcount or 0)


def fail_waiting_items(run_id: str, error: str) -> int:
    init_db()
    now = iso_now()
    with closing(_connect()) as conn:
        cursor = conn.execute(
            "UPDATE work_items SET status = 'failed', error = ?, updated_at = ? WHERE run_id = ? AND status = 'waiting'",
            (error[:1000], now, run_id),
        )
        conn.commit()
        return int(cursor.rowcount or 0)


def summarize_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"queued": 0, "running": 0, "waiting": 0, "done": 0, "failed": 0, "completed": 0, "failed_retryable": 0}
    for item in items:
        key = str(item.get("status") or "")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _displayable_trace_entity_name(name: str) -> bool:
    from ..store import normalize_text as _normalize_text

    blob = _normalize_text(name)
    if not blob:
        return False
    reject_terms = (
        "government team members",
        "official news",
        "information center",
        "anti-corruption policy council",
        "the budget",
        "today prime",
        "fra prime",
        "home",
        "search",
        "share",
        "print",
        "links",
        "site map",
        "history",
        "overview",
        "updates",
    )
    if any(term in blob for term in reject_terms):
        return False
    if len(blob.split()) == 1 and blob in {"eng", "հայ", "рус"}:
        return False
    return True


def save_artifact(run_id: str, item_id: str, artifact_type: str, payload_json: dict[str, Any], ref: str = "") -> str:
    init_db()
    artifact_id = _new_id("artifact", run_id, item_id, artifact_type, ref, iso_now())
    with closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO artifacts (artifact_id, run_id, item_id, artifact_type, ref, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (artifact_id, run_id, item_id, artifact_type, ref, json.dumps(payload_json, ensure_ascii=False), iso_now()),
        )
        conn.commit()
    return artifact_id


def save_tool_call(run_id: str, item_id: str, tool_name: str, input_json: dict[str, Any], output_json: dict[str, Any] | None = None, status: str = "completed", error: str = "") -> str:
    init_db()
    tool_call_id = _new_id("tool", run_id, item_id, tool_name, iso_now())
    with closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO tool_calls (tool_call_id, run_id, item_id, tool_name, input_json, output_json, status, error, created_at, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tool_call_id, run_id, item_id, tool_name, json.dumps(input_json, ensure_ascii=False), json.dumps(output_json or {}, ensure_ascii=False), status, error[:1000], iso_now(), iso_now()),
        )
        conn.commit()
    return tool_call_id


def save_graph_diff(run_id: str, diff: dict[str, Any]) -> str:
    init_db()
    diff_id = _new_id("diff", run_id, json.dumps(diff, ensure_ascii=False, sort_keys=True), iso_now())
    with closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO graph_diffs (diff_id, run_id, new_node_ids_json, updated_node_ids_json, new_edge_ids_json, updated_edge_ids_json, rejected_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                diff_id,
                run_id,
                json.dumps(diff.get("new_node_ids", []), ensure_ascii=False),
                json.dumps(diff.get("updated_node_ids", []), ensure_ascii=False),
                json.dumps(diff.get("new_edge_ids", []), ensure_ascii=False),
                json.dumps(diff.get("updated_edge_ids", []), ensure_ascii=False),
                json.dumps(diff.get("rejected", []), ensure_ascii=False),
                iso_now(),
            ),
        )
        conn.commit()
    return diff_id


def latest_run() -> dict[str, Any] | None:
    init_db()
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT 1").fetchone()
    return _row_to_run(row)


def list_items(run_id: str) -> list[dict[str, Any]]:
    init_db()
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM work_items WHERE run_id = ? ORDER BY priority ASC, created_at ASC", (run_id,)).fetchall()
    return [_row_to_item(row) for row in rows if row is not None]


def list_artifacts(run_id: str) -> list[dict[str, Any]]:
    init_db()
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM artifacts WHERE run_id = ? ORDER BY created_at ASC", (run_id,)).fetchall()
    return [
        {
            "artifact_id": row["artifact_id"],
            "run_id": row["run_id"],
            "item_id": row["item_id"] or "",
            "artifact_type": row["artifact_type"],
            "ref": row["ref"] or "",
            "payload_json": _loads(row["payload_json"], {}),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def list_tool_calls(run_id: str) -> list[dict[str, Any]]:
    init_db()
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM tool_calls WHERE run_id = ? ORDER BY created_at ASC", (run_id,)).fetchall()
    return [
        {
            "tool_call_id": row["tool_call_id"],
            "run_id": row["run_id"],
            "item_id": row["item_id"] or "",
            "tool_name": row["tool_name"],
            "input_json": _loads(row["input_json"], {}),
            "output_json": _loads(row["output_json"], {}),
            "status": row["status"],
            "error": row["error"] or "",
            "created_at": row["created_at"],
            "finished_at": row["finished_at"] or "",
        }
        for row in rows
    ]


def latest_graph_diff(run_id: str) -> dict[str, Any]:
    init_db()
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM graph_diffs WHERE run_id = ? ORDER BY created_at ASC", (run_id,)).fetchall()
    if not rows:
        return {"new_node_ids": [], "updated_node_ids": [], "new_edge_ids": [], "updated_edge_ids": [], "rejected": []}
    aggregated = {"new_node_ids": [], "updated_node_ids": [], "new_edge_ids": [], "updated_edge_ids": [], "rejected": []}
    for row in rows:
        aggregated["new_node_ids"].extend(_loads(row["new_node_ids_json"], []))
        aggregated["updated_node_ids"].extend(_loads(row["updated_node_ids_json"], []))
        aggregated["new_edge_ids"].extend(_loads(row["new_edge_ids_json"], []))
        aggregated["updated_edge_ids"].extend(_loads(row["updated_edge_ids_json"], []))
        aggregated["rejected"].extend(_loads(row["rejected_json"], []))
    return {
        "new_node_ids": sorted(set(aggregated["new_node_ids"])),
        "updated_node_ids": sorted(set(aggregated["updated_node_ids"])),
        "new_edge_ids": sorted(set(aggregated["new_edge_ids"])),
        "updated_edge_ids": sorted(set(aggregated["updated_edge_ids"])),
        "rejected": aggregated["rejected"],
    }


def build_research_trace(run_id: str) -> dict[str, Any]:
    run = get_run(run_id)
    if run is None:
        return {"ok": False, "error": "run_not_found", "run_id": run_id}
    items = list_items(run_id)
    artifacts = list_artifacts(run_id)
    tool_calls = list_tool_calls(run_id)
    diff = latest_graph_diff(run_id)
    graph = load_graph()
    graph_nodes = [row for row in node_rows(graph) if isinstance(row, dict)]
    graph_edges = [row for row in edge_rows(graph) if isinstance(row, dict)]
    node_map = {str(row.get("id") or row.get("vertex_id") or "").strip(): row for row in graph_nodes if str(row.get("id") or row.get("vertex_id") or "").strip()}
    edge_map = {str(row.get("id") or "").strip(): row for row in graph_edges if str(row.get("id") or "").strip()}
    counts = summarize_counts(items)
    search_calls = [call for call in tool_calls if str(call.get("tool_name") or "") == "search_web"]
    model_calls = [call for call in tool_calls if str(call.get("tool_name") or "") == "model_call"]
    search_hits: list[dict[str, Any]] = []
    visited_urls: list[dict[str, Any]] = []
    accepted_sources: list[dict[str, Any]] = []
    rejected_sources: list[dict[str, Any]] = []
    extracted_claims: list[Any] = []
    extracted_claim_items: list[dict[str, Any]] = []
    accepted_changes: list[Any] = []
    rejected_changes: list[Any] = []
    selected_model = ""
    resolved_model = ""
    fallback_used = False
    events = read_events(run_id, limit=400)
    coverage = dict(run["summary_json"].get("coverage") or {})
    if coverage:
        coverage.setdefault("years_checked", [])
        coverage.setdefault("roles_checked", [])
        coverage.setdefault("sources_checked", [])
        coverage.setdefault("confirmed_claims", 0)
        coverage.setdefault("rejected_claims", 0)
        coverage.setdefault("unresolved_candidates", 0)
    for artifact in artifacts:
        payload = artifact["payload_json"] if isinstance(artifact["payload_json"], dict) else {}
        kind = artifact["artifact_type"]
        if kind == "visited_url":
            visited_urls.append(payload)
        elif kind == "accepted_source":
            accepted_sources.append(payload)
        elif kind == "rejected_source":
            rejected_sources.append(payload)
        elif kind == "extracted_claim":
            extracted_claims.append(payload)
            extracted_claim_items.append(payload)
        elif kind == "accepted_change":
            accepted_changes.append(payload)
        elif kind == "rejected_change":
            rejected_changes.append(payload)

    event_entities: list[dict[str, Any]] = []
    event_relations: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    for event in events[-200:]:
        payload = event.get("payload", {}) if isinstance(event.get("payload", {}), dict) else {}
        event_rows.append(
            {
                "ts": event.get("ts"),
                "event_type": event.get("event_type"),
                "stage": event.get("stage"),
                "item_id": event.get("item_id"),
                "payload": payload,
            }
        )
        if event.get("event_type") in {"graph_vertex_created", "graph_vertex_updated"}:
            candidate_name = str(payload.get("name") or payload.get("label") or payload.get("entity_name") or payload.get("title") or payload.get("candidate_name") or payload.get("entity_id") or "").strip()
            if not _displayable_trace_entity_name(candidate_name):
                continue
            event_entities.append(
                {
                    "name": candidate_name,
                    "id": str(payload.get("entity_id") or payload.get("id") or "").strip(),
                    "type": str(payload.get("category") or payload.get("type") or "").strip(),
                    "status": event.get("event_type"),
                    "source_url": str(payload.get("url") or payload.get("source_url") or "").strip(),
                    "graph_action": "created" if event.get("event_type") == "graph_vertex_created" else "updated",
                }
            )
        if event.get("event_type") in {"graph_edge_created", "graph_edge_updated", "candidate_claim_accepted", "candidate_claim_rejected"}:
            event_relations.append(
                {
                    "source_name": str(payload.get("source_name") or payload.get("subject_name") or payload.get("source_id") or payload.get("claim", {}).get("subject_name") or "").strip(),
                    "target_name": str(payload.get("target_name") or payload.get("object_name") or payload.get("target_id") or payload.get("claim", {}).get("object_name") or "").strip(),
                    "relation_type": str(payload.get("relation_type") or payload.get("predicate") or payload.get("claim", {}).get("relation_type") or "").strip(),
                    "status": "candidate" if event.get("event_type") in {"candidate_claim_accepted", "candidate_claim_rejected"} else event.get("event_type"),
                    "evidence_quote": str(payload.get("evidence_quote") or payload.get("claim", {}).get("evidence_quote") or "").strip(),
                }
            )
    for call in search_calls:
        input_json = call.get("input_json", {}) if isinstance(call.get("input_json", {}), dict) else {}
        output_json = call.get("output_json", {}) if isinstance(call.get("output_json", {}), dict) else {}
        results = output_json.get("results", []) if isinstance(output_json, dict) else []
        search_hits.append(
            {
                "query": str(input_json.get("query") or "").strip(),
                "provider": str(output_json.get("provider") or "").strip(),
                "available": bool(output_json.get("available", True)),
                "result_count": len(results) if isinstance(results, list) else 0,
                "results": [
                    {
                        "title": str(row.get("title") or "").strip(),
                        "url": str(row.get("url") or "").strip(),
                        "snippet": str(row.get("snippet") or "").strip(),
                        "source": str(row.get("source") or "").strip(),
                        "score": row.get("score", 0.0),
                    }
                    for row in results[:8]
                    if isinstance(row, dict)
                ],
            }
        )
    model_meta = {}
    for call in reversed(model_calls):
        output = call.get("output_json", {}) if isinstance(call.get("output_json", {}), dict) else {}
        if output:
            model_meta = output
            break
    if not model_meta:
        try:
            model_config = load_model_config()
            chain = active_chain_snapshot(model_config)
            selected_model = str(run["summary_json"].get("selected_model") or chain.get("parser", {}).get("preferred") or chain.get("classifier", {}).get("preferred") or "").strip()
        except Exception:
            selected_model = str(run["summary_json"].get("selected_model") or run["summary_json"].get("model_used") or "").strip()
    else:
        resolved_model = f"{str(model_meta.get('provider') or '').strip()}/{str(model_meta.get('model') or '').strip()}".strip("/")
        selected_model = resolved_model
        fallback_used = not bool(model_meta.get("ok", True))
    if not selected_model:
        selected_model = str(run["summary_json"].get("model_used") or "ollama/gemma4:e4b").strip()
    if not resolved_model:
        resolved_model = str(run["summary_json"].get("resolved_model") or selected_model).strip()
    accepted_graph_changes = len(diff.get("new_node_ids", [])) + len(diff.get("updated_node_ids", [])) + len(diff.get("new_edge_ids", [])) + len(diff.get("updated_edge_ids", []))
    target_role = str(run["summary_json"].get("target_role") or run["summary_json"].get("target_entity") or "").strip()
    context_person = str(run["summary_json"].get("context_person") or "").strip()
    date_from = run["summary_json"].get("date_from")
    date_to = run["summary_json"].get("date_to")
    temporal_granularity = str(run["summary_json"].get("temporal_granularity") or "").strip()
    requested_entities = run["summary_json"].get("requested_entities", [])
    limited_search_mode = bool(run["summary_json"].get("search_provider") == "fallback_official_seed_only" and not run["summary_json"].get("internet_search_available", True))
    target_entity = target_role or context_person or run["summary_json"].get("target_entity", "")
    current_item = next((item for item in items if item["status"] == "running"), None) or next((item for item in items if item["status"] == "waiting"), None) or next((item for item in items if item["status"] == "queued"), None)
    current_item_payload = dict(current_item.get("input_json", {})) if current_item else {}
    current_source_url = str(
        run["summary_json"].get("current_source_url")
        or current_item_payload.get("source_url")
        or current_item_payload.get("profile_url")
        or current_item_payload.get("url")
        or ""
    ).strip()
    current_source_title = str(
        run["summary_json"].get("current_source_title")
        or current_item_payload.get("source_title")
        or current_item_payload.get("page_title")
        or current_item_payload.get("title")
        or (current_item.get("title") if current_item else "")
        or ""
    ).strip()
    current_entity_name = str(
        run["summary_json"].get("current_entity_name")
        or current_item_payload.get("name")
        or current_item_payload.get("candidate_name")
        or current_item_payload.get("page_title")
        or current_item_payload.get("office_title")
        or current_item_payload.get("ministry_name")
        or (current_item.get("title") if current_item else "")
        or ""
    ).strip()
    current_entity_id = str(
        run["summary_json"].get("current_entity_id")
        or (current_item.get("entity_id") if current_item else "")
        or current_item_payload.get("entity_id")
        or current_item_payload.get("subject_id")
        or ""
    ).strip()
    current_relation_name = str(
        run["summary_json"].get("current_relation_name")
        or current_item_payload.get("relation_type")
        or current_item_payload.get("office_title")
        or current_item_payload.get("ministry_name")
        or current_item_payload.get("target_name")
        or ""
    ).strip()
    current_claim_item = extracted_claim_items[-1] if extracted_claim_items else {}
    current_extracted_quote = str(
        run["summary_json"].get("current_extracted_quote")
        or current_claim_item.get("evidence_quote")
        or current_claim_item.get("quote")
        or ""
    ).strip()
    current_extracted_claim = str(
        run["summary_json"].get("current_extracted_claim")
        or current_claim_item.get("statement")
        or current_claim_item.get("claim")
        or ""
    ).strip()
    current_source_status = str(run["summary_json"].get("current_source_status") or current_item_payload.get("source_status") or current_item.get("status") if current_item else "").strip() if (current_item or run["summary_json"].get("current_source_status")) else ""
    if not current_source_status:
        current_source_status = "searching"
    def _node_source_url(node: dict[str, Any]) -> str:
        links = node.get("links")
        if isinstance(links, dict):
            for key in ("official_profile", "official", "source", "profile", "homepage"):
                value = links.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            for value in links.values():
                if isinstance(value, str) and value.strip():
                    return value.strip()
        profile = node.get("profile")
        if isinstance(profile, dict):
            for link in profile.get("source_links", []) or []:
                if isinstance(link, dict) and str(link.get("url") or "").strip():
                    return str(link.get("url")).strip()
        return ""
    def _named_node(node_id: str) -> dict[str, Any]:
        node = node_map.get(str(node_id or "").strip(), {})
        return {
            "id": str(node.get("id") or node_id or "").strip(),
            "name": str(node.get("name") or node.get("label") or node_id or "").strip(),
            "type": str(node.get("category") or node.get("kind") or "").strip(),
            "status": str(node.get("change_type") or "unchanged").strip(),
            "source_url": _node_source_url(node),
        }
    def _named_edge(edge_id: str) -> dict[str, Any]:
        edge = edge_map.get(str(edge_id or "").strip(), {})
        source_id = str(edge.get("from") or edge.get("source") or "").strip()
        target_id = str(edge.get("to") or edge.get("target") or "").strip()
        source_node = node_map.get(source_id, {})
        target_node = node_map.get(target_id, {})
        return {
            "id": str(edge.get("id") or edge_id or "").strip(),
            "source_name": str(source_node.get("name") or source_node.get("label") or source_id or "").strip(),
            "target_name": str(target_node.get("name") or target_node.get("label") or target_id or "").strip(),
            "relation_type": str(edge.get("relation_type") or edge.get("type") or "").strip(),
            "status": str(edge.get("status") or edge.get("change_type") or "unchanged").strip(),
            "evidence_quote": str(edge.get("evidence_quote") or "").strip(),
        }
    processed_entities = [_named_node(node_id) for node_id in list(diff.get("new_node_ids", [])) + list(diff.get("updated_node_ids", []))]
    processed_relations = [_named_edge(edge_id) for edge_id in list(diff.get("new_edge_ids", [])) + list(diff.get("updated_edge_ids", []))]
    rejected_nodes = [item for item in diff.get("rejected", []) if str(item.get("type") or "") == "vertex"]
    rejected_edges = [item for item in diff.get("rejected", []) if str(item.get("type") or "") == "edge"]
    source_titles_by_url: dict[str, str] = {}
    for artifact in artifacts:
        payload = artifact["payload_json"] if isinstance(artifact["payload_json"], dict) else {}
        url = str(payload.get("url") or payload.get("final_url") or "").strip()
        title = str(payload.get("title") or payload.get("page_title") or payload.get("source_title") or "").strip()
        if url and title and url not in source_titles_by_url:
            source_titles_by_url[url] = title
    visited_sources = []
    seen_visit_urls: set[str] = set()
    for row in visited_urls:
        url = str(row.get("url") or row.get("final_url") or "").strip()
        if not url or url in seen_visit_urls:
            continue
        seen_visit_urls.add(url)
        visited_sources.append(
            {
                "title": str(row.get("title") or row.get("source_title") or source_titles_by_url.get(url) or url).strip(),
                "url": url,
                "domain": str(row.get("host") or row.get("domain") or "").strip(),
                "status": str(row.get("status") or "").strip(),
                "reason": str(row.get("reason") or row.get("error") or "").strip(),
            }
        )
    run_payload = {
        "run_id": run_id,
        "status": run["status"],
        "run_type": run["run_type"],
        "current_stage": run["current_stage"],
        "last_active_stage": run["summary_json"].get("last_active_stage", ""),
        "query": run["user_query"],
        "target_entity": target_entity,
        "target_type": run["summary_json"].get("target_type", run["run_type"]),
        "target_role": target_role,
        "context_person": context_person,
        "date_from": date_from,
        "date_to": date_to,
        "requested_entities": requested_entities,
        "coverage": coverage,
        "years_checked": coverage.get("years_checked", run["summary_json"].get("years_checked", [])),
        "roles_checked": coverage.get("roles_checked", run["summary_json"].get("roles_checked", [])),
        "sources_checked": coverage.get("sources_checked", run["summary_json"].get("sources_checked", [])),
        "confirmed_claims": coverage.get("confirmed_claims", run["summary_json"].get("claims_extracted", 0)),
        "claims_logged": run["summary_json"].get("claims_logged", 0),
        "role_history_office_holder_claims": run["summary_json"].get("role_history_office_holder_claims", coverage.get("confirmed_claims", 0)),
        "rejected_claims": coverage.get("rejected_claims", len(rejected_changes)),
        "unresolved_candidates": coverage.get("unresolved_candidates", 0),
        "current_work_item_type": str(current_item.get("item_type") or "") if current_item else "",
        "current_entity_name": current_entity_name,
        "current_entity_id": current_entity_id,
        "current_relation_name": current_relation_name,
        "current_source_title": current_source_title,
        "current_source_url": current_source_url,
        "current_source_status": current_source_status,
        "current_extracted_quote": current_extracted_quote,
        "current_extracted_claim": current_extracted_claim,
        "counters": counts,
        "budget_pages": run["budget_json"].get("budget_pages"),
        "max_depth": run["budget_json"].get("max_depth"),
        "search_queries": len(search_calls),
        "search_hits": search_hits,
        "model_calls": len(model_calls),
        "search_provider": run["summary_json"].get("search_provider", "unknown"),
        "internet_search_available": bool(run["summary_json"].get("internet_search_available", True)),
        "limited_search_mode": limited_search_mode,
        "limited_search_message": "Limited mode: external web search unavailable; using official seed URLs only." if limited_search_mode else "",
        "temporal_granularity": temporal_granularity,
        "events": event_rows,
        "event_count": len(events),
        "viewed_links": visited_urls,
        "visited_sources": visited_sources,
        "accepted_sources": accepted_sources,
        "rejected_sources": rejected_sources,
        "extracted_claims": [
            item.get("statement") or item.get("evidence_quote") or item
            for item in extracted_claims
        ],
        "extracted_claim_items": extracted_claim_items,
        "processed_entities": event_entities or processed_entities,
        "processed_relations": event_relations or processed_relations,
        "accepted_graph_changes": accepted_graph_changes,
        "accepted_change_artifacts": len(accepted_changes),
        "rejected_graph_changes": len(rejected_changes),
        "graph_diff": {
            "new_node_ids": diff.get("new_node_ids", []),
            "updated_node_ids": diff.get("updated_node_ids", []),
            "new_edge_ids": diff.get("new_edge_ids", []),
            "updated_edge_ids": diff.get("updated_edge_ids", []),
            "rejected_updates": diff.get("rejected", []),
        },
        "graph_diff_named": {
            "new_nodes": [_named_node(node_id) for node_id in diff.get("new_node_ids", [])],
            "updated_nodes": [_named_node(node_id) for node_id in diff.get("updated_node_ids", [])],
            "new_edges": [_named_edge(edge_id) for edge_id in diff.get("new_edge_ids", [])],
            "updated_edges": [_named_edge(edge_id) for edge_id in diff.get("updated_edge_ids", [])],
            "rejected_nodes": rejected_nodes,
            "rejected_edges": rejected_edges,
        },
        "edge_payload_count": len(diff.get("new_edge_ids", [])) + len(diff.get("updated_edge_ids", [])),
        "failure_explanation": " ; ".join(run["summary_json"].get("failure_reasons", [])) if run["summary_json"].get("failure_reasons") else "",
        "failure_reasons": run["summary_json"].get("failure_reasons", []),
        "planner_status": run["summary_json"].get("planner_status", "deterministic"),
        "selected_model": selected_model,
        "resolved_model": resolved_model,
        "model_used": resolved_model or selected_model,
        "fallback_used": bool(run["summary_json"].get("source_mode") == "fallback") or fallback_used,
    }
    return {
        "ok": True,
        "contract": "ResearchRunContract.v1",
        "run_id": run_id,
        "status": run["status"],
        "current_stage": run["current_stage"],
        "query": run["user_query"],
        "run_type": run["run_type"],
        "budget": run["budget_json"],
        "summary": run["summary_json"],
        "counts": counts,
        "work_items": items,
        "tool_calls": tool_calls,
        "trace": {
            "query": run["user_query"],
            "seed_queries": run["summary_json"].get("seed_queries", []),
            "frontier": run["summary_json"].get("frontier", []),
            "search_queries": [call.get("input_json", {}) for call in search_calls],
            "search_hits": search_hits,
            "events": event_rows,
            "event_count": len(events),
            "model_calls": model_calls,
            "visited_urls": visited_urls,
            "visited_sources": visited_sources,
            "accepted_sources": accepted_sources,
            "rejected_sources": rejected_sources,
            "coverage": coverage,
            "role_history_office_holder_claims": run["summary_json"].get("role_history_office_holder_claims", coverage.get("confirmed_claims", 0)),
            "extracted_claims": extracted_claims,
            "extracted_claim_items": extracted_claim_items,
            "processed_entities": event_entities or processed_entities,
            "processed_relations": event_relations or processed_relations,
            "proposed_nodes": run["summary_json"].get("proposed_nodes", []),
            "proposed_edges": run["summary_json"].get("proposed_edges", []),
            "accepted_changes": accepted_changes,
            "accepted_change_artifacts": len(accepted_changes),
            "rejected_changes": rejected_changes,
            "graph_diff": {
                "new_nodes": diff.get("new_node_ids", []),
                "updated_nodes": diff.get("updated_node_ids", []),
                "new_edges": diff.get("new_edge_ids", []),
                "updated_edges": diff.get("updated_edge_ids", []),
                "rejected": diff.get("rejected", []),
            },
            "selected_model": selected_model,
            "resolved_model": resolved_model,
            "target_role": target_role,
            "context_person": context_person,
            "date_from": date_from,
            "date_to": date_to,
            "requested_entities": requested_entities,
            "limited_search_mode": limited_search_mode,
            "temporal_granularity": temporal_granularity,
            "current_work_item_type": run_payload["current_work_item_type"],
            "current_entity_name": current_entity_name,
            "current_entity_id": current_entity_id,
            "current_relation_name": current_relation_name,
            "current_source_title": current_source_title,
            "current_source_url": current_source_url,
            "current_source_status": current_source_status,
            "current_extracted_quote": current_extracted_quote,
            "current_extracted_claim": current_extracted_claim,
            "graph_diff_named": run_payload["graph_diff_named"],
        },
        "failed_items": [item for item in items if item["status"] == "failed"],
        "updated_at": run["updated_at"],
        "run": run_payload,
    }
