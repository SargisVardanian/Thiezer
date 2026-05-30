#!/usr/bin/env python3
"""User-facing task runtime over the deterministic Thiezer core."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from explorer import (
    _is_cabinet_query,
    _is_institutional_roster_query,
    build_queue as build_exploration_queue,
    process_queue as process_exploration_queue,
)
from graph_domain import graph_safety_report
from pipeline_common import (
    EVIDENCE_LOG,
    TASK_RUNS_FILE,
    TASK_RUNTIME_FILE,
    append_jsonl,
    compact_summary,
    ensure_layout,
    iso_now,
    load_graph,
    load_json,
    stable_hash,
    translate_to_russian,
    write_json,
)


ROOT = Path(__file__).resolve().parents[1]
STAGE_COMMANDS = {
    "ingest": ["python3", "scripts/ingest.py"],
    "retrieve": ["python3", "scripts/retrieve.py"],
    "graph": ["python3", "scripts/graph.py"],
    "publish": ["python3", "scripts/publish.py"],
    "party_crawl": ["python3", "scripts/party_crawler.py", "--once", "--quiet"],
}
PHASE_TIMEOUTS = {
    "plan": 2,
    "party_crawl": 120,
    "ingest/search": 45,
    "fetch/normalize": 2,
    "retrieve/cluster": 45,
    "graph_propose": 45,
    "graph_verify": 2,
    "critic": 2,
    "publish_prepare": 20,
    "publish_send": 2,
    "final_report": 2,
}

PHASE_SEQUENCE = [
    "plan",
    "ingest/search",
    "fetch/normalize",
    "retrieve/cluster",
    "graph_propose",
    "graph_verify",
    "critic",
    "publish_prepare",
    "publish_send",
    "final_report",
]


def default_progress() -> dict[str, Any]:
    return {
        "current_phase": "plan",
        "sources_checked": 0,
        "fetched_links": 0,
        "story_candidates": 0,
        "verified_stories": 0,
        "rejected_stories": 0,
        "graph_proposals": 0,
        "graph_updates_applied": 0,
        "graph_updates_rejected": 0,
        "publish_status": "dry_run_only",
    }


def new_task_receipt(
    *,
    run_id: str,
    mode: str,
    task_type: str,
    query: str,
    topic: str,
    budget: int,
    max_runtime_per_phase: int,
    max_total_runtime: int,
    resume_from_phase: str = "",
    checkpoint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = iso_now()
    return {
        "run_id": run_id,
        "mode": mode,
        "task_type": task_type,
        "query": query,
        "topic": topic,
        "budget": budget,
        "status": "running",
        "failure_class": "",
        "partial": False,
        "started_at": now,
        "finished_at": None,
        "resumed_from": resume_from_phase or "",
        "budgets": {
            "max_runtime_per_phase": max_runtime_per_phase,
            "max_total_runtime": max_total_runtime,
            "max_sources": min(12, max(3, budget)),
            "max_links_per_source": 3,
            "max_depth": 1,
            "max_new_entities": min(32, max(8, budget * 4)),
        },
        "progress": default_progress(),
        "phase_receipts": [],
        "transport_receipts": [],
        "checkpoint": checkpoint or {},
        "operator_trace": {
            "links_viewed": [],
            "sources_checked": [],
            "story_ids_verified": [],
            "story_ids_rejected": [],
            "graph_updates": [],
        },
    }


def start_phase(receipt: dict[str, Any], phase: str, *, note: str = "") -> dict[str, Any]:
    row = {
        "phase": phase,
        "status": "running",
        "started_at": iso_now(),
        "finished_at": None,
        "failure_class": "",
        "partial": False,
        "note": note,
        "details": {},
    }
    receipt.setdefault("phase_receipts", []).append(row)
    receipt.setdefault("progress", default_progress())["current_phase"] = phase
    return row


def finish_phase(
    receipt: dict[str, Any],
    phase: str,
    *,
    status: str,
    details: dict[str, Any] | None = None,
    failure_class: str = "",
    partial: bool = False,
) -> dict[str, Any]:
    rows = receipt.setdefault("phase_receipts", [])
    row = next((item for item in reversed(rows) if item.get("phase") == phase and item.get("finished_at") is None), None)
    if row is None:
        row = start_phase(receipt, phase)
    row["status"] = status
    row["finished_at"] = iso_now()
    row["failure_class"] = failure_class
    row["partial"] = partial
    row["details"] = details or {}
    if failure_class:
        receipt["failure_class"] = failure_class
    return row


def mark_partial(receipt: dict[str, Any], failure_class: str, *, phase: str = "") -> None:
    receipt["partial"] = True
    receipt["status"] = "partial_success"
    receipt["failure_class"] = failure_class or "partial_success"
    if phase:
        receipt.setdefault("progress", default_progress())["current_phase"] = phase


def update_progress(receipt: dict[str, Any], **counts: int | str) -> None:
    progress = receipt.setdefault("progress", default_progress())
    for key, value in counts.items():
        if value is not None:
            progress[key] = value


def set_checkpoint(receipt: dict[str, Any], phase: str, artifacts: dict[str, Any] | None = None) -> None:
    receipt["checkpoint"] = {
        "phase": phase,
        "updated_at": iso_now(),
        "artifacts": artifacts or {},
    }


def build_operator_trace_summary(receipt: dict[str, Any]) -> str:
    progress = receipt.get("progress", {})
    trace = receipt.get("operator_trace", {})
    phase_rows = receipt.get("phase_receipts", [])
    lines = [
        f"run_id: {receipt.get('run_id')}",
        f"task_type: {receipt.get('task_type')}",
        f"query: {receipt.get('query') or '-'}",
        f"current_phase: {progress.get('current_phase')}",
        f"sources_checked: {progress.get('sources_checked', 0)}",
        f"fetched_links: {progress.get('fetched_links', 0)}",
        f"story_candidates: {progress.get('story_candidates', 0)}",
        f"verified_stories: {progress.get('verified_stories', 0)}",
        f"rejected_stories: {progress.get('rejected_stories', 0)}",
        f"graph_proposals: {progress.get('graph_proposals', 0)}",
        f"graph_updates_applied: {progress.get('graph_updates_applied', 0)}",
        f"graph_updates_rejected: {progress.get('graph_updates_rejected', 0)}",
        f"publish_status: {progress.get('publish_status', 'dry_run_only')}",
        f"status: {receipt.get('status')}",
    ]
    if receipt.get("failure_class"):
        lines.append(f"failure_class: {receipt.get('failure_class')}")
    if receipt.get("checkpoint"):
        checkpoint = receipt["checkpoint"]
        lines.append(f"checkpoint: {checkpoint.get('phase')} @ {checkpoint.get('updated_at')}")
    if phase_rows:
        lines.append("phases:")
        for row in phase_rows:
            details = row.get("details") or {}
            detail_bits = []
            for key in ("sources_checked", "fetched_links", "story_candidates", "verified_stories", "rejected_stories", "graph_proposals", "graph_updates_applied", "graph_updates_rejected", "publish_status"):
                if key in details:
                    detail_bits.append(f"{key}={details.get(key)}")
            suffix = f" {' '.join(detail_bits)}" if detail_bits else ""
            lines.append(
                f"- {row.get('phase')}: {row.get('status')}"
                f"{' [' + row.get('failure_class') + ']' if row.get('failure_class') else ''}"
                f"{suffix}"
            )
    links = list(trace.get("links_viewed", []))[:8]
    if links:
        lines.append("links_viewed:")
        lines.extend(f"- {link}" for link in links)
    return "\n".join(lines)


def classify_task(query: str, explicit_task: str = "") -> str:
    if explicit_task:
        return explicit_task
    text = query.lower()
    if any(token in text for token in ["генштаб", "главный штаб", "general staff", "chief of the general staff", "chief of general staff", "գլխավոր շտաբ"]):
        return "graph_improve"
    if any(token in text for token in ["minister", "ministers", "cabinet", "government of armenia", "министр", "министры", "кабинет", "правительство", "նախարար", "նախարարներ", "կառավարություն"]):
        return "graph_improve"
    if any(token in text for token in ["выбор", "election", "parliament", "парламент", "депутат", "politic", "полит", "party", "парт"]):
        return "topic_deep_research"
    if any(token in text for token in ["сегодня", "today", "news", "новост"]):
        return "news_today"
    if any(token in text for token in ["проверь граф", "graph check", "graph_audit", "graph"]):
        return "graph_check"
    if any(token in text for token in ["улучши граф", "graph improve", "исслед", "deep research", "докоп"]):
        return "graph_improve"
    if any(token in text for token in ["статья", "article", "write", "draft"]):
        return "write_article"
    if any(token in text for token in ["соц", "telegram", "x ", "twitter", "post"]):
        return "social_publish_prepare"
    return "topic_deep_research"


def infer_topic_from_query(query: str) -> str:
    text = query.lower()
    if any(token in text for token in ["генштаб", "главный штаб", "general staff", "chief of the general staff", "chief of general staff", "գլխավոր շտաբ"]):
        return "internal_politics"
    if any(token in text for token in ["выбор", "election", "parliament", "парламент", "депутат", "politic", "полит", "party", "парт"]):
        return "internal_politics"
    if any(token in text for token in ["econom", "budget", "tax", "finance", "долг", "бюджет", "налог", "эконом"]):
        return "economy"
    if any(token in text for token in ["court", "суд", "law", "прав", "human rights", "rights", "арест", "задерж", "justice"]):
        return "legal_human_rights"
    if any(token in text for token in ["foreign", "russia", "iran", "turkey", "azerbaijan", "israel", "ukraine", "диплом", "внеш"]):
        return "foreign_policy"
    if any(token in text for token in ["community", "municip", "mayor", "region", "district", "marz", "համայնք", "մարզ", "քաղաքապետ"]):
        return "local_governance"
    return ""


def is_election_theme_query(query: str) -> bool:
    text = query.lower()
    return any(
        token in text
        for token in [
            "выбор",
            "election",
            "parliament",
            "парламент",
            "депутат",
            "politic",
            "полит",
            "party",
            "парт",
            "кампан",
            "affiliat",
            "аффили",
            "coalition",
            "bloc",
        ]
    )


def write_task_runtime(payload: dict[str, Any]) -> None:
    write_json(TASK_RUNTIME_FILE, payload)
    append_jsonl(TASK_RUNS_FILE, [payload])


def graph_check_report() -> dict[str, Any]:
    graph = load_graph()
    safety = graph_safety_report(graph)
    return {
        "updated_at": iso_now(),
        "task_type": "graph_check",
        "graph_safety": safety,
        "graph_summary": {
            "entities": len(graph.get("entities", [])),
            "relations": len(graph.get("relations", [])),
            "event_nodes": len(graph.get("event_nodes", [])),
        },
    }


def make_article_pack(graph: dict[str, Any]) -> dict[str, Any]:
    publication = graph.get("runtime", {}).get("publication", {})
    items = list(publication.get("items", []))
    verified = list(graph.get("runtime", {}).get("graph", {}).get("verified_story_pack", []))
    selected = verified[:4] if verified else []
    return {
        "updated_at": iso_now(),
        "task_type": "write_article",
        "article_candidates": [
            {
                "story_id": story.get("story_id"),
                "title": translate_to_russian(story.get("title", "")) or story.get("title", ""),
                "summary": compact_summary(story.get("summary", "")) or story.get("public_impact", ""),
                "topic": story.get("topic", ""),
                "source_links": [source.get("url", "") for source in story.get("sources", []) if source.get("url")][:4],
                "graph_context": story.get("story_context_pack", {}),
            }
            for story in selected
        ],
        "published_items": items[:4],
    }


def make_social_pack(graph: dict[str, Any]) -> dict[str, Any]:
    publication = graph.get("runtime", {}).get("publication", {})
    return {
        "updated_at": iso_now(),
        "task_type": "social_publish_prepare",
        "social_outputs": publication.get("social_outputs", []),
    }


def run_stage(command: list[str], timeout_seconds: int) -> tuple[dict[str, Any], str, str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, cwd=str(ROOT), timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        return (
            {
                "error": "timeout",
                "command": " ".join(command),
                "stdout": (exc.stdout or "").strip(),
                "stderr": (exc.stderr or "").strip(),
            },
            "timed_out",
            "tool_timeout",
        )
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if completed.returncode != 0:
        failure_class = "source_fetch_failure" if any(token in command[-1] for token in {"ingest.py", "retrieve.py"}) else "orchestration_failure"
        return (
            {
                "error": stderr or stdout or f"failed: {' '.join(command)}",
                "stdout": stdout,
                "stderr": stderr,
                "returncode": completed.returncode,
            },
            "failed",
            failure_class,
        )
    try:
        return (json.loads(stdout) if stdout else {}, "ok", "")
    except json.JSONDecodeError:
        return ({"raw": stdout}, "ok", "")


def summarize_graph_runtime(graph: dict[str, Any]) -> dict[str, Any]:
    runtime = graph.get("runtime", {})
    ingest_runtime = runtime.get("ingest", {}) if isinstance(runtime.get("ingest", {}), dict) else {}
    retrieval_runtime = runtime.get("retrieval", {}) if isinstance(runtime.get("retrieval", {}), dict) else {}
    graph_runtime = runtime.get("graph", {}) if isinstance(runtime.get("graph", {}), dict) else {}
    publication = runtime.get("publication", {}) if isinstance(runtime.get("publication", {}), dict) else {}
    exploration = runtime.get("exploration", {}) if isinstance(runtime.get("exploration", {}), dict) else {}
    publication_count = int(publication.get("count", 0) or 0)
    skipped_story_ids = list(publication.get("skipped_story_ids", [])) if isinstance(publication.get("skipped_story_ids", []), list) else []
    graph_updates_applied = (
        int(graph_runtime.get("relation_updates", 0) or 0)
        + int(graph_runtime.get("event_node_updates", 0) or 0)
        + int(graph_runtime.get("story_mention_updates", 0) or 0)
    )
    return {
        "sources_checked": int(ingest_runtime.get("source_count", 0) or 0),
        "fetched_links": len(list(ingest_runtime.get("candidates", []))),
        "story_candidates": int(retrieval_runtime.get("story_count", 0) or retrieval_runtime.get("stories", 0) or 0),
        "verified_stories": int(graph_runtime.get("accepted_story_count", 0) or 0),
        "rejected_stories": int(graph_runtime.get("rejected_story_count", 0) or 0),
        "graph_proposals": len(list(graph_runtime.get("proposal_receipts", []))),
        "graph_updates_applied": graph_updates_applied,
        "graph_updates_rejected": int(graph_runtime.get("rejected_story_count", 0) or 0),
        "publish_status": "prepared" if publication_count > 0 else ("skipped_duplicate" if skipped_story_ids else "dry_run_only"),
        "publication_count": publication_count,
        "exploration_candidates": int(exploration.get("candidate_count", 0) or 0),
        "exploration_processed": int(exploration.get("processed_count", 0) or 0),
    }


def collect_trace_links(graph: dict[str, Any], receipt: dict[str, Any]) -> list[str]:
    links: list[str] = []
    runtime = graph.get("runtime", {})
    ingest_runtime = runtime.get("ingest", {}) if isinstance(runtime.get("ingest", {}), dict) else {}
    graph_runtime = runtime.get("graph", {}) if isinstance(runtime.get("graph", {}), dict) else {}
    exploration = runtime.get("exploration", {}) if isinstance(runtime.get("exploration", {}), dict) else {}
    for candidate in ingest_runtime.get("candidates", [])[:16]:
        url = str(candidate.get("url") or "").strip()
        if url and url not in links:
            links.append(url)
    for story in graph_runtime.get("verified_story_pack", [])[:6]:
        for source in story.get("sources", [])[:3]:
            url = str(source.get("url") or "").strip()
            if url and url not in links:
                links.append(url)
    for item in exploration.get("queue", [])[:12]:
        url = str(item.get("target_url") or "").strip()
        if url and url not in links:
            links.append(url)
    for url in links[:24]:
        if url not in receipt.setdefault("operator_trace", {}).setdefault("links_viewed", []):
            receipt["operator_trace"]["links_viewed"].append(url)
    return links[:24]


def complete_phase_receipt(receipt: dict[str, Any], phase: str, status: str, details: dict[str, Any], failure_class: str = "", partial: bool = False) -> None:
    finish_phase(receipt, phase, status=status, details=details, failure_class=failure_class, partial=partial)
    if failure_class:
        mark_partial(receipt, failure_class, phase=phase)


def update_runtime_from_graph(receipt: dict[str, Any], graph: dict[str, Any], *, phase: str) -> None:
    summary = summarize_graph_runtime(graph)
    update_progress(receipt, **summary)
    collect_trace_links(graph, receipt)
    graph_runtime = graph.get("runtime", {}).get("graph", {}) if isinstance(graph.get("runtime", {}).get("graph", {}), dict) else {}
    for story in list(graph_runtime.get("verified_story_pack", []))[:6]:
        story_id = str(story.get("story_id") or "")
        if story_id:
            bucket = receipt.setdefault("operator_trace", {}).setdefault("story_ids_verified", [])
            if story_id not in bucket:
                bucket.append(story_id)
    for story in list(graph_runtime.get("rejected_story_pack", []))[:6]:
        story_id = str(story.get("story_id") or "")
        if story_id:
            bucket = receipt.setdefault("operator_trace", {}).setdefault("story_ids_rejected", [])
            if story_id not in bucket:
                bucket.append(story_id)
    publication_runtime = graph.get("runtime", {}).get("publication", {}) if isinstance(graph.get("runtime", {}).get("publication", {}), dict) else {}
    for story_id in list(publication_runtime.get("skipped_story_ids", []))[:6]:
        story_id = str(story_id or "")
        if story_id:
            bucket = receipt.setdefault("operator_trace", {}).setdefault("skipped_story_ids", [])
            if story_id not in bucket:
                bucket.append(story_id)
    set_checkpoint(
        receipt,
        phase,
        {
            "graph_updated_at": graph.get("updated_at"),
            "publication_count": summary.get("publication_count", 0),
            "verified_story_count": summary.get("verified_stories", 0),
            "rejected_story_count": summary.get("rejected_stories", 0),
            "graph_updates_applied": summary.get("graph_updates_applied", 0),
        },
    )


def finalize_runtime(receipt: dict[str, Any], graph: dict[str, Any], *, transport_receipt: dict[str, Any] | None = None) -> dict[str, Any]:
    if transport_receipt:
        receipt.setdefault("transport_receipts", []).append(transport_receipt)
        status = str(transport_receipt.get("status") or "failed")
        if status == "sent":
            update_progress(receipt, publish_status="sent")
        elif status == "dry_run_only":
            update_progress(receipt, publish_status="dry_run_only")
        else:
            update_progress(receipt, publish_status="failed")
    if receipt.get("status") == "running":
        receipt["status"] = "ok" if not receipt.get("partial") else "partial_success"
    if not any(row.get("phase") == "final_report" for row in receipt.get("phase_receipts", [])):
        start_phase(receipt, "final_report", note="compile final operator report")
        complete_phase_receipt(
            receipt,
            "final_report",
            "ok" if receipt.get("status") == "ok" else "partial",
            {
                "status": receipt.get("status"),
                "failure_class": receipt.get("failure_class", ""),
                "publish_status": receipt.get("progress", {}).get("publish_status"),
                "transport_receipts": len(receipt.get("transport_receipts", [])),
                "phase_count": len(receipt.get("phase_receipts", [])),
            },
        )
    receipt["finished_at"] = iso_now()
    receipt["operator_trace_summary"] = build_operator_trace_summary(receipt)
    receipt["result"] = {
        "status": receipt.get("status"),
        "failure_class": receipt.get("failure_class", ""),
        "partial": receipt.get("partial", False),
        "task_type": receipt.get("task_type"),
        "query": receipt.get("query"),
        "topic": receipt.get("topic"),
        "graph_summary": {
            "entities": len(graph.get("entities", [])),
            "relations": len(graph.get("relations", [])),
            "event_nodes": len(graph.get("event_nodes", [])),
        },
        "publication": graph.get("runtime", {}).get("publication", {}),
        "verified_story_pack": list(graph.get("runtime", {}).get("graph", {}).get("verified_story_pack", []))[:6],
        "rejected_story_pack": list(graph.get("runtime", {}).get("graph", {}).get("rejected_story_pack", []))[:6],
        "exploration": graph.get("runtime", {}).get("exploration", {}),
        "operator_trace_summary": receipt.get("operator_trace_summary", ""),
        "phase_receipts": receipt.get("phase_receipts", []),
        "transport_receipts": receipt.get("transport_receipts", []),
    }
    if receipt.get("work_result"):
        receipt["result"]["work_result"] = receipt.get("work_result")
    write_task_runtime(receipt)
    append_jsonl(
        EVIDENCE_LOG,
        [
            {
                "recorded_at": iso_now(),
                "action": "task_runner",
                "task_type": receipt.get("task_type"),
                "query": receipt.get("query"),
                "topic": receipt.get("topic"),
                "budget": receipt.get("budget"),
                "status": receipt.get("status"),
                "failure_class": receipt.get("failure_class"),
            }
        ],
    )
    return receipt


def run_news_like_task(receipt: dict[str, Any], *, topic: str, budget: int, phase_deadline: float, task_type: str) -> dict[str, Any]:
    phase = "ingest/search"
    inferred_topic = topic or infer_topic_from_query(str(receipt.get("query") or ""))
    start_phase(receipt, "plan", note="bounded execution initialized")
    complete_phase_receipt(
        receipt,
        "plan",
        "ok",
        {
            "budgets": receipt.get("budgets", {}),
            "resumed_from": receipt.get("resumed_from", ""),
            "max_total_runtime": receipt.get("budgets", {}).get("max_total_runtime"),
            "inferred_topic": inferred_topic,
        },
    )

    if inferred_topic == "internal_politics" and is_election_theme_query(str(receipt.get("query") or "")):
        phase = "party_roster"
        start_phase(receipt, phase, note="seed party roster and affiliation graph")
        try:
            from run_graph_web import run_party_roster_workflow

            roster_plan = {
                "query": str(receipt.get("query") or ""),
                "seed_queries": [str(receipt.get("query") or "")],
                "workflow": "graph_improve",
                "topic": "internal_politics",
                "tool_plan": ["internet_roster_extract", "graph_upsert"],
                "model_selection": {},
            }
            roster_payload = run_party_roster_workflow(str(receipt.get("query") or ""), roster_plan)
            complete_phase_receipt(
                receipt,
                phase,
                "ok",
                {
                    "records_found": roster_payload.get("workflow_summary", {}).get("candidate_count", 0) if isinstance(roster_payload.get("workflow_summary", {}), dict) else 0,
                    "graph_updates_applied": roster_payload.get("workflow_summary", {}).get("graph_updates_applied", 0) if isinstance(roster_payload.get("workflow_summary", {}), dict) else 0,
                },
            )
            graph = load_graph()
            update_runtime_from_graph(receipt, graph, phase=phase)
            update_progress(receipt, publish_status="dry_run_only")
        except Exception as exc:
            complete_phase_receipt(receipt, phase, "partial", {"error": str(exc)}, "party_roster_failure", partial=True)
            mark_partial(receipt, "party_roster_failure", phase=phase)
        phase = "ingest/search"

    if time.monotonic() >= phase_deadline:
        mark_partial(receipt, "partial_success", phase="plan")
        return receipt

    start_phase(receipt, phase, note="ingest source registry and fetch candidates")
    ingest_payload, ingest_status, ingest_failure = run_stage(STAGE_COMMANDS["ingest"], PHASE_TIMEOUTS[phase])
    if ingest_status != "ok":
        complete_phase_receipt(receipt, phase, ingest_status, ingest_payload, ingest_failure, partial=True)
        mark_partial(receipt, ingest_failure, phase=phase)
        return receipt
    complete_phase_receipt(receipt, phase, "ok", {"source_count": ingest_payload.get("sources", 0), "candidate_count": ingest_payload.get("candidates", 0), "source_health_summary": ingest_payload.get("source_health_summary", {})})
    graph = load_graph()
    update_runtime_from_graph(receipt, graph, phase=phase)
    if task_type == "graph_improve":
        update_progress(receipt, publish_status="dry_run_only", publication_count=0)
    update_progress(receipt, publish_status="dry_run_only")

    phase = "fetch/normalize"
    start_phase(receipt, phase, note="normalize fetched links and source candidates")
    complete_phase_receipt(
        receipt,
        phase,
        "ok",
        {
            "fetched_links": receipt.get("progress", {}).get("fetched_links", 0),
            "sources_checked": receipt.get("progress", {}).get("sources_checked", 0),
        },
    )

    if time.monotonic() >= phase_deadline:
        mark_partial(receipt, "partial_success", phase=phase)
        return receipt

    phase = "retrieve/cluster"
    start_phase(receipt, phase, note="cluster stories and verify source trust")
    retrieve_payload, retrieve_status, retrieve_failure = run_stage(STAGE_COMMANDS["retrieve"], PHASE_TIMEOUTS[phase])
    if retrieve_status != "ok":
        complete_phase_receipt(receipt, phase, retrieve_status, retrieve_payload, retrieve_failure, partial=True)
        mark_partial(receipt, retrieve_failure, phase=phase)
        return receipt
    complete_phase_receipt(
        receipt,
        phase,
        "ok",
        {
            "story_count": retrieve_payload.get("story_count", retrieve_payload.get("stories", 0)),
            "graph_worthy_stories": retrieve_payload.get("graph_worthy_stories", 0),
        },
    )
    graph = load_graph()
    update_runtime_from_graph(receipt, graph, phase=phase)
    update_progress(receipt, publish_status="dry_run_only")

    phase = "graph_propose"
    start_phase(receipt, phase, note="build graph proposal and verified story pack")
    graph_payload, graph_status, graph_failure = run_stage(STAGE_COMMANDS["graph"], PHASE_TIMEOUTS[phase])
    if graph_status != "ok":
        complete_phase_receipt(receipt, phase, graph_status, graph_payload, graph_failure, partial=True)
        mark_partial(receipt, graph_failure, phase=phase)
        return receipt
    complete_phase_receipt(
        receipt,
        phase,
        "ok",
        {
            "accepted_story_count": graph_payload.get("accepted_story_count", 0),
            "rejected_story_count": graph_payload.get("rejected_story_count", 0),
            "relation_updates": graph_payload.get("relation_updates", 0),
        },
    )
    graph = load_graph()
    update_runtime_from_graph(receipt, graph, phase=phase)

    phase = "graph_verify"
    start_phase(receipt, phase, note="verify graph safety and proposal receipts")
    graph_runtime = graph.get("runtime", {}).get("graph", {}) if isinstance(graph.get("runtime", {}).get("graph", {}), dict) else {}
    safety = graph_runtime.get("graph_safety_report", {}) if isinstance(graph_runtime.get("graph_safety_report", {}), dict) else {}
    verify_payload = {
        "issue_count": safety.get("issue_count", 0),
        "accepted_story_count": graph_runtime.get("accepted_story_count", 0),
        "rejected_story_count": graph_runtime.get("rejected_story_count", 0),
    }
    verify_status = "ok" if int(verify_payload["issue_count"] or 0) == 0 else "partial"
    verify_failure = "graph_verify_reject" if int(verify_payload["issue_count"] or 0) > 0 else ""
    complete_phase_receipt(receipt, phase, verify_status, verify_payload, verify_failure, partial=bool(verify_failure))
    if verify_failure:
        mark_partial(receipt, verify_failure, phase=phase)

    phase = "critic"
    start_phase(receipt, phase, note="critic inspect graph receipts")
    proposal_receipts = list(graph_runtime.get("proposal_receipts", []))
    critic_issues = sum(1 for row in proposal_receipts if str(row.get("critic_status") or "") not in {"pass", "ok", "warn"})
    critic_payload = {
        "proposal_receipts": len(proposal_receipts),
        "critic_issues": critic_issues,
    }
    critic_status = "ok" if critic_issues == 0 else "partial"
    critic_failure = "critic_reject" if critic_issues > 0 else ""
    complete_phase_receipt(receipt, phase, critic_status, critic_payload, critic_failure, partial=bool(critic_failure))
    if critic_failure:
        mark_partial(receipt, critic_failure, phase=phase)

    phase = "publish_prepare"
    start_phase(receipt, phase, note="prepare publication candidate")
    publish_payload, publish_status, publish_failure = run_stage(STAGE_COMMANDS["publish"], PHASE_TIMEOUTS[phase])
    if publish_status != "ok":
        complete_phase_receipt(receipt, phase, publish_status, publish_payload, publish_failure, partial=True)
        mark_partial(receipt, publish_failure, phase=phase)
        return receipt
    complete_phase_receipt(
        receipt,
        phase,
        "ok",
        {
            "publication_count": publish_payload.get("publication", {}).get("count", 0),
            "social_outputs": len(publish_payload.get("publication", {}).get("social_outputs", [])),
        },
    )
    graph = load_graph()
    update_runtime_from_graph(receipt, graph, phase=phase)
    publication_count = int(publish_payload.get("publication", {}).get("count", 0) or 0)
    skipped_story_ids = list(publish_payload.get("publication", {}).get("skipped_story_ids", [])) if isinstance(publish_payload.get("publication", {}).get("skipped_story_ids", []), list) else []
    update_progress(receipt, publish_status="prepared" if publication_count > 0 else ("skipped_duplicate" if skipped_story_ids else "dry_run_only"))

    phase = "publish_send"
    start_phase(receipt, phase, note="transport send handled by orchestrator or gateway")
    complete_phase_receipt(
        receipt,
        phase,
        "dry_run_only",
        {
            "transport": "orchestrator_pending",
            "publish_status": "dry_run_only",
        },
    )

    if time.monotonic() >= phase_deadline:
        mark_partial(receipt, "partial_success", phase=phase)

    return receipt


def run_research_like_task(receipt: dict[str, Any], *, task_type: str, query: str, topic: str, budget: int, phase_deadline: float) -> dict[str, Any]:
    start_phase(receipt, "plan", note="bounded execution initialized")
    effective_topic = topic or (
        "local_governance"
        if task_type == "graph_improve"
        and any(token in query.lower() for token in ["район", "district", "community", "governor", "marz", "мэр", "глав"])
        else ""
    )
    complete_phase_receipt(
        receipt,
        "plan",
        "ok",
        {
            "budgets": receipt.get("budgets", {}),
            "resumed_from": receipt.get("resumed_from", ""),
            "effective_topic": effective_topic,
            "query": query,
        },
    )

    election_theme_query = task_type == "topic_deep_research" and is_election_theme_query(query)
    if election_theme_query:
        phase = "party_crawl"
        start_phase(receipt, phase, note="seed political parties and affiliations")
        party_budget = max(8, min(14, budget * 4))
        party_payload, party_status, party_failure = run_stage(
            [
                "python3",
                "scripts/party_crawler.py",
                "--once",
                "--quiet",
                "--budget",
                str(party_budget),
            ],
            PHASE_TIMEOUTS[phase],
        )
        if party_status != "ok":
            complete_phase_receipt(receipt, phase, party_status, party_payload, party_failure, partial=True)
            mark_partial(receipt, party_failure, phase=phase)
        else:
            complete_phase_receipt(
                receipt,
                phase,
                "ok",
                {
                    "round": party_payload.get("round", 0),
                    "targets": party_payload.get("targets", 0),
                    "visited": party_payload.get("visited", 0),
                    "entities_added": party_payload.get("stats", {}).get("entities_added", 0) if isinstance(party_payload.get("stats", {}), dict) else 0,
                    "relations_added": party_payload.get("stats", {}).get("relations_added", 0) if isinstance(party_payload.get("stats", {}), dict) else 0,
                    "cross_party_connections": len(party_payload.get("cross_party_connections", [])) if isinstance(party_payload.get("cross_party_connections", []), list) else 0,
                },
            )
            graph = load_graph()
            update_runtime_from_graph(receipt, graph, phase=phase)
            update_progress(receipt, publish_status="dry_run_only")

    phase = "retrieve/cluster"
    start_phase(receipt, phase, note="budgeted exploration queue")
    graph = load_graph()
    exploration_queue = build_exploration_queue(graph, topic=effective_topic, query=query, limit=max(1, budget))
    exploration_runtime = process_exploration_queue(graph, exploration_queue, limit=max(1, min(budget, 6)))
    graph = load_graph()
    payload = {
        "queue_count": exploration_runtime.get("queue_count", 0),
        "processed_count": exploration_runtime.get("processed_count", 0),
        "failed_count": exploration_runtime.get("failed_count", 0),
        "candidate_count": exploration_runtime.get("candidate_count", 0),
        "seed_targets": exploration_runtime.get("seed_targets", [])[:12],
    }
    complete_phase_receipt(receipt, phase, "ok", payload)
    update_progress(
        receipt,
        sources_checked=receipt.get("progress", {}).get("sources_checked", 0),
        fetched_links=receipt.get("progress", {}).get("fetched_links", 0),
        story_candidates=payload["candidate_count"],
        publish_status="dry_run_only",
    )
    update_runtime_from_graph(receipt, graph, phase=phase)

    if task_type == "graph_improve":
        if payload["queue_count"] == 0 and payload["candidate_count"] == 0:
            for skipped_phase in ["graph_propose", "graph_verify", "critic", "ingest/search", "fetch/normalize", "publish_prepare", "publish_send"]:
                start_phase(receipt, skipped_phase, note="no exploration candidates for this workflow")
                complete_phase_receipt(receipt, skipped_phase, "skipped", {"reason": "no_exploration_candidates"})
            update_progress(
                receipt,
                story_candidates=0,
                verified_stories=0,
                rejected_stories=0,
                graph_proposals=0,
                graph_updates_applied=0,
                graph_updates_rejected=0,
                publish_status="dry_run_only",
            )
            receipt["work_result"] = {
                "status": "noop",
                "reason": "no_exploration_candidates",
                "query": query,
                "topic": effective_topic,
            }
            return receipt

        direct_roster_graph = _is_cabinet_query(query) or _is_institutional_roster_query(query)
        if direct_roster_graph:
            phase = "graph_propose"
            start_phase(receipt, phase, note="promote official roster records into canonical graph")
            graph_payload, graph_status, graph_failure = run_stage(STAGE_COMMANDS["graph"], PHASE_TIMEOUTS[phase])
            if graph_status != "ok":
                complete_phase_receipt(receipt, phase, graph_status, graph_payload, graph_failure, partial=True)
                mark_partial(receipt, graph_failure, phase=phase)
                return receipt
            complete_phase_receipt(
                receipt,
                phase,
                "ok",
                {
                    "accepted_story_count": graph_payload.get("accepted_story_count", 0),
                    "rejected_story_count": graph_payload.get("rejected_story_count", 0),
                    "relation_updates": graph_payload.get("relation_updates", 0),
                },
            )
            graph = load_graph()
            update_runtime_from_graph(receipt, graph, phase=phase)

            phase = "graph_verify"
            start_phase(receipt, phase, note="verify graph safety and roster receipts")
            graph_runtime = graph.get("runtime", {}).get("graph", {}) if isinstance(graph.get("runtime", {}).get("graph", {}), dict) else {}
            safety = graph_runtime.get("graph_safety_report", {}) if isinstance(graph_runtime.get("graph_safety_report", {}), dict) else {}
            verify_payload = {
                "issue_count": safety.get("issue_count", 0),
                "accepted_story_count": graph_runtime.get("accepted_story_count", 0),
                "rejected_story_count": graph_runtime.get("rejected_story_count", 0),
            }
            verify_status = "ok" if int(verify_payload["issue_count"] or 0) == 0 else "partial"
            verify_failure = "graph_verify_reject" if int(verify_payload["issue_count"] or 0) > 0 else ""
            complete_phase_receipt(receipt, phase, verify_status, verify_payload, verify_failure, partial=bool(verify_failure))
            if verify_failure:
                mark_partial(receipt, verify_failure, phase=phase)

            phase = "critic"
            start_phase(receipt, phase, note="critic inspect graph receipts")
            proposal_receipts = list(graph_runtime.get("proposal_receipts", []))
            critic_issues = sum(1 for row in proposal_receipts if str(row.get("critic_status") or "") not in {"pass", "ok", "warn"})
            critic_payload = {
                "proposal_receipts": len(proposal_receipts),
                "critic_issues": critic_issues,
                "seed_targets": exploration_runtime.get("seed_targets", [])[:8],
            }
            critic_status = "ok" if critic_issues == 0 else "partial"
            critic_failure = "critic_reject" if critic_issues > 0 else ""
            complete_phase_receipt(receipt, phase, critic_status, critic_payload, critic_failure, partial=bool(critic_failure))
            if critic_failure:
                mark_partial(receipt, critic_failure, phase=phase)

            for skipped_phase in ["ingest/search", "fetch/normalize", "publish_prepare", "publish_send"]:
                start_phase(receipt, skipped_phase, note="not required for graph improve workflow")
                complete_phase_receipt(receipt, skipped_phase, "skipped", {"reason": "not_required_for_graph_improve"})
            return receipt

        phase = "graph_propose"
        start_phase(receipt, phase, note="retrieve exploration candidates into story clusters")
        retrieve_payload, retrieve_status, retrieve_failure = run_stage(STAGE_COMMANDS["retrieve"], PHASE_TIMEOUTS[phase])
        if retrieve_status != "ok":
            complete_phase_receipt(receipt, phase, retrieve_status, retrieve_payload, retrieve_failure, partial=True)
            mark_partial(receipt, retrieve_failure, phase=phase)
            return receipt
        complete_phase_receipt(
            receipt,
            phase,
            "ok",
            {
                "story_count": retrieve_payload.get("story_count", retrieve_payload.get("stories", 0)),
                "graph_worthy_stories": retrieve_payload.get("graph_worthy_stories", 0),
            },
        )
        graph = load_graph()
        update_runtime_from_graph(receipt, graph, phase=phase)
        update_progress(receipt, publish_status="dry_run_only", publication_count=0)

        phase = "graph_verify"
        start_phase(receipt, phase, note="apply graph proposals from exploration candidates")
        graph_payload, graph_status, graph_failure = run_stage(STAGE_COMMANDS["graph"], PHASE_TIMEOUTS[phase])
        if graph_status != "ok":
            complete_phase_receipt(receipt, phase, graph_status, graph_payload, graph_failure, partial=True)
            mark_partial(receipt, graph_failure, phase=phase)
            return receipt
        complete_phase_receipt(
            receipt,
            phase,
            "ok",
            {
                "accepted_story_count": graph_payload.get("accepted_story_count", 0),
                "rejected_story_count": graph_payload.get("rejected_story_count", 0),
                "relation_updates": graph_payload.get("relation_updates", 0),
            },
        )
        graph = load_graph()
        update_runtime_from_graph(receipt, graph, phase=phase)
        update_progress(receipt, publish_status="dry_run_only", publication_count=0)

        phase = "critic"
        start_phase(receipt, phase, note="critic inspect graph receipts")
        graph_runtime = graph.get("runtime", {}).get("graph", {}) if isinstance(graph.get("runtime", {}).get("graph", {}), dict) else {}
        proposal_receipts = list(graph_runtime.get("proposal_receipts", []))
        critic_issues = sum(1 for row in proposal_receipts if str(row.get("critic_status") or "") not in {"pass", "ok", "warn"})
        critic_payload = {
            "proposal_receipts": len(proposal_receipts),
            "critic_issues": critic_issues,
            "seed_targets": exploration_runtime.get("seed_targets", [])[:12],
        }
        critic_status = "ok" if critic_issues == 0 else "partial"
        critic_failure = "critic_reject" if critic_issues > 0 else ""
        complete_phase_receipt(receipt, phase, critic_status, critic_payload, critic_failure, partial=bool(critic_failure))
        if critic_failure:
            mark_partial(receipt, critic_failure, phase=phase)

        for skipped_phase in ["ingest/search", "fetch/normalize", "publish_prepare", "publish_send"]:
            start_phase(receipt, skipped_phase, note="not required for graph improve workflow")
            complete_phase_receipt(receipt, skipped_phase, "skipped", {"reason": "not_required_for_graph_improve"})
    else:
        for skipped_phase in ["ingest/search", "fetch/normalize", "graph_propose", "graph_verify", "critic", "publish_prepare", "publish_send"]:
            start_phase(receipt, skipped_phase, note="not required for this workflow")
            complete_phase_receipt(receipt, skipped_phase, "skipped", {"reason": "not_required_for_research_workflow"})

    if time.monotonic() >= phase_deadline:
        mark_partial(receipt, "partial_success", phase=phase)
    return receipt


def run_graph_check_task(receipt: dict[str, Any]) -> dict[str, Any]:
    start_phase(receipt, "plan", note="bounded execution initialized")
    complete_phase_receipt(receipt, "plan", "ok", {"budgets": receipt.get("budgets", {}), "resumed_from": receipt.get("resumed_from", "")})

    start_phase(receipt, "graph_verify", note="graph safety report")
    report = graph_check_report()
    safety = report.get("graph_safety", {})
    verify_payload = {
        "issue_count": safety.get("issue_count", 0),
        "graph_summary": report.get("graph_summary", {}),
    }
    status = "ok" if int(verify_payload["issue_count"] or 0) == 0 else "partial"
    failure_class = "graph_verify_reject" if int(verify_payload["issue_count"] or 0) > 0 else ""
    complete_phase_receipt(receipt, "graph_verify", status, verify_payload, failure_class, partial=bool(failure_class))
    if failure_class:
        mark_partial(receipt, failure_class, phase="graph_verify")

    start_phase(receipt, "critic", note="deterministic critic summary")
    critic_payload = {
        "graph_summary": report.get("graph_summary", {}),
        "critic_status": "pass" if int(verify_payload["issue_count"] or 0) == 0 else "warn",
    }
    complete_phase_receipt(receipt, "critic", "ok", critic_payload)

    for skipped_phase in ["ingest/search", "fetch/normalize", "retrieve/cluster", "graph_propose", "publish_prepare", "publish_send"]:
        start_phase(receipt, skipped_phase, note="not required for graph audit")
        complete_phase_receipt(receipt, skipped_phase, "skipped", {"reason": "not_required_for_graph_audit"})
    return receipt


def execute_task(task_type: str, query: str = "", topic: str = "", budget: int = 8) -> dict[str, Any]:
    ensure_layout()
    task_type = task_type or classify_task(query)
    started_at = iso_now()
    inferred_topic = topic or infer_topic_from_query(query)
    election_theme_query = is_election_theme_query(query)
    run_id = f"task-{task_type}-{stable_hash(task_type, query, inferred_topic, str(budget), started_at)[:12]}"
    previous = load_json(TASK_RUNTIME_FILE, {}) if TASK_RUNTIME_FILE.exists() else {}
    resume_from_phase = ""
    if isinstance(previous, dict) and previous.get("task_type") == task_type and previous.get("query") == query and previous.get("topic") == inferred_topic and previous.get("budget") == budget:
        if previous.get("status") in {"partial_success", "failed"}:
            checkpoint = previous.get("checkpoint", {}) if isinstance(previous.get("checkpoint", {}), dict) else {}
            resume_from_phase = str(checkpoint.get("phase") or "")
    max_runtime_per_phase = max(10, min(60, budget * (8 if election_theme_query else 6)))
    max_total_runtime = max(150 if election_theme_query else 45, min(240, budget * (45 if election_theme_query else 15)))
    receipt = new_task_receipt(
        run_id=run_id,
        mode="task",
        task_type=task_type,
        query=query,
        topic=inferred_topic,
        budget=budget,
        max_runtime_per_phase=max_runtime_per_phase,
        max_total_runtime=max_total_runtime,
        resume_from_phase=resume_from_phase,
    )
    write_task_runtime(receipt)
    phase_deadline = time.monotonic() + max_total_runtime

    try:
        if task_type in {"news_today", "background_sync"}:
            receipt = run_news_like_task(receipt, topic=inferred_topic, budget=budget, phase_deadline=phase_deadline, task_type=task_type)
        elif task_type in {"topic_deep_research", "graph_improve"}:
            receipt = run_research_like_task(receipt, task_type=task_type, query=query, topic=inferred_topic, budget=budget, phase_deadline=phase_deadline)
        elif task_type == "graph_check":
            receipt = run_graph_check_task(receipt)
        elif task_type == "write_article":
            start_phase(receipt, "plan", note="bounded execution initialized")
            complete_phase_receipt(receipt, "plan", "ok", {"budgets": receipt.get("budgets", {}), "resumed_from": receipt.get("resumed_from", "")})
            graph = load_graph()
            graph_runtime = graph.get("runtime", {}).get("graph", {}) if isinstance(graph.get("runtime", {}).get("graph", {}), dict) else {}
            retrieval_runtime = graph.get("runtime", {}).get("retrieval", {}) if isinstance(graph.get("runtime", {}).get("retrieval", {}), dict) else {}
            if not graph_runtime.get("verified_story_pack") or not retrieval_runtime.get("stories"):
                receipt = run_news_like_task(receipt, topic=inferred_topic, budget=budget, phase_deadline=phase_deadline, task_type="news_today")
                graph = load_graph()
            graph = load_graph()
            start_phase(receipt, "publish_prepare", note="article pack from verified story pack")
            result = make_article_pack(graph)
            complete_phase_receipt(receipt, "publish_prepare", "ok", {"article_candidates": len(result.get("article_candidates", [])), "published_items": len(result.get("published_items", []))})
            for skipped_phase in ["ingest/search", "fetch/normalize", "retrieve/cluster", "graph_propose", "graph_verify", "critic", "publish_send"]:
                start_phase(receipt, skipped_phase, note="not required for article pack")
                complete_phase_receipt(receipt, skipped_phase, "skipped", {"reason": "not_required_for_article_pack"})
            update_progress(receipt, publish_status="prepared")
            update_runtime_from_graph(receipt, graph, phase="publish_prepare")
            receipt["work_result"] = result
        elif task_type == "social_publish_prepare":
            start_phase(receipt, "plan", note="bounded execution initialized")
            complete_phase_receipt(receipt, "plan", "ok", {"budgets": receipt.get("budgets", {}), "resumed_from": receipt.get("resumed_from", "")})
            graph = load_graph()
            start_phase(receipt, "publish_prepare", note="social output packaging")
            result = make_social_pack(graph)
            complete_phase_receipt(receipt, "publish_prepare", "ok", {"social_outputs": len(result.get("social_outputs", []))})
            for skipped_phase in ["ingest/search", "fetch/normalize", "retrieve/cluster", "graph_propose", "graph_verify", "critic", "publish_send"]:
                start_phase(receipt, skipped_phase, note="not required for social packaging")
                complete_phase_receipt(receipt, skipped_phase, "skipped", {"reason": "not_required_for_social_pack"})
            update_progress(receipt, publish_status="prepared")
            update_runtime_from_graph(receipt, graph, phase="publish_prepare")
            receipt["work_result"] = result
        else:
            receipt = run_research_like_task(receipt, task_type=task_type, query=query, topic=inferred_topic, budget=budget, phase_deadline=phase_deadline)
    except Exception as exc:
        receipt["status"] = "failed"
        mark_partial(receipt, "orchestration_failure", phase=receipt.get("progress", {}).get("current_phase", "plan"))
        set_checkpoint(receipt, receipt.get("progress", {}).get("current_phase", "plan"), {"error": str(exc)})
        graph = load_graph()
        receipt["work_result"] = {"error": str(exc), "status": "failed"}
        return finalize_runtime(receipt, graph)

    graph = load_graph()
    if receipt.get("status") == "running":
        receipt["status"] = "ok" if not receipt.get("partial") else "partial_success"
    return finalize_runtime(receipt, graph)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default="", help="Optional explicit task type.")
    parser.add_argument("--query", default="", help="User query or instruction.")
    parser.add_argument("--topic", default="", help="Optional topic seed for deep research.")
    parser.add_argument("--budget", type=int, default=8, help="Exploration or execution budget.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    task_type = classify_task(args.query, args.task)
    payload = execute_task(task_type, query=args.query, topic=args.topic, budget=args.budget)
    print(json.dumps({"ok": payload.get("status") in {"ok", "partial_success"}, **payload}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
