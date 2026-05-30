#!/usr/bin/env python3
"""Single control plane for the minimal deterministic Thiezer pipeline."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from pipeline_common import (
    EXPLORATION_RUNTIME_FILE,
    EVALS_LATEST_DIR,
    PIPELINE_CONFIG,
    PUBLIC_POST_CHAT_HANDLE,
    TASK_RUNTIME_FILE,
    active_chain_snapshot,
    ensure_layout,
    find_publication_duplicate,
    load_graph,
    load_channel_mirror,
    load_json,
    load_structured,
    load_model_config,
    prompt_audit_payload,
    publication_fingerprint,
    record_publication_ledger_entry,
    load_source_registry,
    send_telegram_message_receipt,
    write_json,
)


ROOT = Path(__file__).resolve().parents[1]
STAGES = [
    ("ingest", ["python3", "scripts/ingest.py"]),
    ("retrieve", ["python3", "scripts/retrieve.py"]),
    ("graph", ["python3", "scripts/graph.py"]),
    ("publish", ["python3", "scripts/publish.py"]),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["daily-sync", "background-sync", "ask", "deep-research", "graph-audit", "claim-audit", "claim-repair", "semantic-edges", "graph-explore", "export-obsidian", "party-crawl", "health"])
    parser.add_argument("--task", default="", help="Explicit task type for ask/deep-research routing.")
    parser.add_argument("--query", default="", help="User query or freeform prompt for ask mode.")
    parser.add_argument("--topic", default="", help="Optional topic seed for exploration.")
    parser.add_argument("--budget", type=int, default=8, help="Exploration or task budget.")
    parser.add_argument("--output", default="", help="Output directory for export modes.")
    parser.add_argument("--interval", type=int, default=600, help="Party crawl interval in seconds.")
    parser.add_argument("--once", action="store_true", help="Run party crawl once then exit.")
    parser.add_argument("--deliver-public-telegram", default="", help="Telegram target for public outputs, for example @thiezerarm.")
    parser.add_argument("--deliver-ops-telegram", default="", help="Telegram target for operator trace output.")
    parser.add_argument("--deliver-thread-id", default="", help="Optional Telegram forum thread id for operator trace or delivery.")
    return parser


def pipeline_public_target() -> str:
    config = load_structured(PIPELINE_CONFIG, {})
    telegram = config.get("telegram", {}) if isinstance(config.get("telegram", {}), dict) else {}
    return str(telegram.get("default_chat") or PUBLIC_POST_CHAT_HANDLE).strip()


def build_operator_trace(payload: dict[str, object]) -> str:
    if isinstance(payload.get("operator_trace_summary"), str) and payload.get("operator_trace_summary"):
        return str(payload.get("operator_trace_summary"))
    result = payload.get("result", {}) if isinstance(payload.get("result"), dict) else {}
    publication = result.get("publication", {}) if isinstance(result.get("publication"), dict) else {}
    graph = load_graph()
    verified = list(result.get("verified_story_pack", [])) if isinstance(result.get("verified_story_pack"), list) else []
    exploration = result.get("exploration", {}) if isinstance(result.get("exploration"), dict) else {}
    graph_runtime = graph.get("runtime", {}).get("graph", {}) if isinstance(graph.get("runtime", {}), dict) else {}
    lines = [
        f"run_id: {payload.get('run_id') or '-'}",
        f"task_type: {payload.get('task_type') or payload.get('mode') or 'unknown'}",
        f"query: {payload.get('query') or '-'}",
        f"sources_checked: {payload.get('progress', {}).get('sources_checked', 0) if isinstance(payload.get('progress', {}), dict) else 0}",
        f"fetched_links: {payload.get('progress', {}).get('fetched_links', 0) if isinstance(payload.get('progress', {}), dict) else 0}",
        f"verified_stories: {payload.get('progress', {}).get('verified_stories', 0) if isinstance(payload.get('progress', {}), dict) else 0}",
        f"rejected_stories: {payload.get('progress', {}).get('rejected_stories', 0) if isinstance(payload.get('progress', {}), dict) else 0}",
        f"graph_updates_applied: {payload.get('progress', {}).get('graph_updates_applied', 0) if isinstance(payload.get('progress', {}), dict) else 0}",
        f"publish_status: {payload.get('progress', {}).get('publish_status', 'dry_run_only') if isinstance(payload.get('progress', {}), dict) else 'dry_run_only'}",
        f"published: {publication.get('count', 0)}",
        f"graph: entities={len(graph.get('entities', []))}, relations={len(graph.get('relations', []))}, events={len(graph.get('event_nodes', []))}",
        f"exploration: queue={exploration.get('queue_count', 0)}, processed={exploration.get('processed_count', 0)}, candidates={exploration.get('candidate_count', 0)}",
        f"safety_issues: {graph_runtime.get('graph_safety_report', {}).get('issue_count', 0)}",
        f"status: {payload.get('status') or 'unknown'}",
    ]
    if verified:
        lines.append("links:")
        focus_links = []
        for story in verified[:4]:
            for source in story.get("sources", [])[:2]:
                url = str(source.get("url") or "").strip()
                if url and url not in focus_links:
                    focus_links.append(url)
        lines.extend(f"- {url}" for url in focus_links[:8])
    return "\n".join(lines)


def deliver_runtime(payload: dict[str, object], public_target: str = "", ops_target: str = "", thread_id: str = "") -> dict[str, object]:
    public_target = public_target or pipeline_public_target()
    result = payload.get("result", {}) if isinstance(payload.get("result"), dict) else {}
    publication = result.get("publication", {}) if isinstance(result.get("publication"), dict) else {}
    social_outputs = list(publication.get("social_outputs", [])) if isinstance(publication.get("social_outputs"), list) else []
    delivery = {
        "public_target": public_target,
        "ops_target": ops_target,
        "public": [],
        "ops": None,
        "status": "dry_run_only",
    }
    transport_receipts: list[dict[str, object]] = []
    if public_target:
        public_count = 0
        duplicate_count = 0
        for item in social_outputs[:4]:
            message = str(item.get("telegram_post") or "").strip()
            if not message:
                continue
            story_id = str(item.get("story_id") or "").strip()
            source_links = []
            publication_items = list(publication.get("items", [])) if isinstance(publication.get("items"), list) else []
            for publication_item in publication_items:
                if isinstance(publication_item, dict) and str(publication_item.get("story_id") or "").strip() == story_id:
                    source_links = [
                        str(link).strip()
                        for link in publication_item.get("source_links", [])
                        if str(link).strip()
                    ][:4]
                    break
            duplicate = find_publication_duplicate(
                target=public_target,
                story_id=story_id,
                text=message,
                source_links=source_links,
            )
            if duplicate:
                duplicate_count += 1
                receipt = {
                    "status": "skipped_duplicate",
                    "transport": "publication_ledger",
                    "target": public_target,
                    "thread_id": thread_id or "",
                    "message_id": duplicate.get("message_id"),
                    "ok": False,
                    "error": "already_published_in_channel",
                    "raw": {
                        "duplicate_of": duplicate.get("message_id"),
                        "story_id": duplicate.get("story_id"),
                        "recorded_at": duplicate.get("recorded_at"),
                    },
                    "story_id": story_id,
                    "fingerprint": duplicate.get("fingerprint"),
                }
                transport_receipts.append(receipt)
                delivery["public"].append(receipt)
                continue
            receipt = send_telegram_message_receipt(message, public_target, thread_id=thread_id)
            receipt["story_id"] = story_id
            receipt["fingerprint"] = publication_fingerprint(
                story_id=story_id,
                target=public_target,
                text=message,
                source_links=source_links,
            )
            transport_receipts.append(receipt)
            delivery["public"].append(receipt)
            if receipt.get("ok"):
                public_count += 1
                record_publication_ledger_entry(
                    {
                        "recorded_at": payload.get("finished_at") or payload.get("started_at"),
                        "run_id": payload.get("run_id"),
                        "target": public_target,
                        "thread_id": thread_id or "",
                        "status": "sent",
                        "message_id": receipt.get("message_id"),
                        "story_id": story_id,
                        "fingerprint": receipt.get("fingerprint"),
                        "text": message,
                        "title": str(item.get("telegram_thread", [""])[0] if isinstance(item.get("telegram_thread"), list) else ""),
                        "summary": str(item.get("telegram_thread", ["", ""])[1] if isinstance(item.get("telegram_thread"), list) and len(item.get("telegram_thread")) > 1 else ""),
                        "source_links": source_links,
                    }
                )
        if public_count == 0 and social_outputs:
            delivery["status"] = "skipped_duplicate" if duplicate_count > 0 else "failed"
        elif public_count > 0:
            delivery["status"] = "sent"
    if ops_target:
        ops_receipt = send_telegram_message_receipt(build_operator_trace(payload), ops_target, thread_id=thread_id)
        transport_receipts.append(ops_receipt)
        delivery["ops"] = ops_receipt
        if ops_receipt.get("ok") and delivery["status"] == "dry_run_only":
            delivery["status"] = "sent"
        elif not ops_receipt.get("ok") and delivery["status"] == "sent":
            delivery["status"] = "partial_success"
    if transport_receipts:
        result["transport_receipts"] = transport_receipts
        result["channel_mirror"] = load_channel_mirror()
        task_runtime = load_json(TASK_RUNTIME_FILE, {}) if TASK_RUNTIME_FILE.exists() else {}
        if isinstance(task_runtime, dict) and task_runtime.get("run_id") == payload.get("run_id"):
            task_runtime["transport_receipts"] = transport_receipts
            progress = task_runtime.get("progress", {}) if isinstance(task_runtime.get("progress", {}), dict) else {}
            if delivery["status"] == "sent":
                progress["publish_status"] = "sent"
            elif delivery["status"] == "skipped_duplicate":
                progress["publish_status"] = "skipped_duplicate"
            elif delivery["status"] == "failed":
                progress["publish_status"] = "failed"
                task_runtime["partial"] = True
                task_runtime["failure_class"] = "transport_failure"
                task_runtime["status"] = "partial_success"
            elif delivery["status"] == "partial_success":
                progress["publish_status"] = "partial_success"
                task_runtime["partial"] = True
                task_runtime["failure_class"] = "transport_failure"
                task_runtime["status"] = "partial_success"
            task_runtime["progress"] = progress
            task_runtime["transport_receipts"] = transport_receipts
            task_runtime["channel_mirror"] = result.get("channel_mirror", {})
            task_runtime["finished_at"] = task_runtime.get("finished_at") or payload.get("finished_at")
            write_json(TASK_RUNTIME_FILE, task_runtime)
    return delivery


def run_stage(name: str, command: list[str]) -> dict[str, object]:
    completed = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or f"failed: {' '.join(command)}")
    output = completed.stdout.strip()
    try:
        payload = json.loads(output) if output else {}
    except json.JSONDecodeError:
        payload = {"raw": output}
    return {"stage": name, "command": " ".join(command), "result": payload, "returncode": completed.returncode}


def source_health_summary(registry: list[dict[str, object]]) -> dict[str, object]:
    summary = {"active": 0, "degraded": 0, "broken": 0, "dormant": 0}
    for source in registry:
        status = str(source.get("status") or "active")
        if status not in summary:
            summary[status] = 0
        summary[status] += 1
    return summary


def run_pipeline_steps() -> tuple[list[dict[str, object]], dict[str, object]]:
    steps = [run_stage(name, command) for name, command in STAGES]
    return steps, load_graph()


def health() -> int:
    ensure_layout()
    graph = load_graph()
    registry = load_source_registry()
    model_config = load_model_config()
    latest_eval_path = EVALS_LATEST_DIR / "summary.json"
    latest_eval = load_json(latest_eval_path, {}) if latest_eval_path.exists() else {}
    prompt_audit = load_json(EVALS_LATEST_DIR / "prompt-audit.json", {}) if (EVALS_LATEST_DIR / "prompt-audit.json").exists() else {}
    source_trust = load_json(EVALS_LATEST_DIR / "source-trust-report.json", {}) if (EVALS_LATEST_DIR / "source-trust-report.json").exists() else {}
    graph_safety = load_json(EVALS_LATEST_DIR / "graph-safety-report.json", {}) if (EVALS_LATEST_DIR / "graph-safety-report.json").exists() else {}
    openclaw_comparison = load_json(EVALS_LATEST_DIR / "openclaw-comparison.json", {}) if (EVALS_LATEST_DIR / "openclaw-comparison.json").exists() else {}
    task_runtime = load_json(TASK_RUNTIME_FILE, {}) if TASK_RUNTIME_FILE.exists() else {}
    exploration_runtime = load_json(EXPLORATION_RUNTIME_FILE, {}) if EXPLORATION_RUNTIME_FILE.exists() else {}
    payload = {
        "ok": True,
        "mode": "health",
        "active_model_chain": active_chain_snapshot(model_config),
        "source_counts_by_category": {},
        "source_health_summary": source_health_summary(registry),
        "number_of_entities": len(graph.get("entities", [])),
        "number_of_relations": len(graph.get("relations", [])),
        "number_of_event_nodes": len(graph.get("event_nodes", [])),
        "number_of_unresolved_sensitive_edges": sum(1 for relation in graph.get("relations", []) if relation.get("public_safe") is False),
        "last_graph_update": graph.get("updated_at"),
        "last_ingest": graph.get("runtime", {}).get("ingest", {}).get("updated_at"),
        "last_retrieve": graph.get("runtime", {}).get("retrieval", {}).get("updated_at"),
        "last_publish": graph.get("runtime", {}).get("publication", {}).get("updated_at"),
        "latest_eval": {
            "generated_at": latest_eval.get("generated_at"),
            "openclaw_available": latest_eval.get("openclaw_available"),
            "tested_modes": latest_eval.get("tested_modes", []),
            "task_count": latest_eval.get("task_count"),
            "result_count": latest_eval.get("result_count"),
        } if latest_eval else {},
        "prompt_audit": {
            "role_count": prompt_audit.get("role_count"),
            "tool_count": prompt_audit.get("tool_count"),
            "ok": prompt_audit.get("ok"),
        } if prompt_audit else {},
        "latest_source_trust_report": {
            "story_count": source_trust.get("story_count"),
        } if source_trust else {},
        "latest_graph_safety_report": {
            "issue_count": graph_safety.get("graph_safety", {}).get("issue_count"),
        } if graph_safety else {},
        "latest_openclaw_comparison": {
            "compared_tasks": openclaw_comparison.get("compared_tasks"),
        } if openclaw_comparison else {},
        "latest_task_runtime": {
            "task_type": task_runtime.get("task_type"),
            "status": task_runtime.get("status"),
            "failure_class": task_runtime.get("failure_class"),
            "current_phase": task_runtime.get("progress", {}).get("current_phase") if isinstance(task_runtime.get("progress", {}), dict) else None,
            "publish_status": task_runtime.get("progress", {}).get("publish_status") if isinstance(task_runtime.get("progress", {}), dict) else None,
            "finished_at": task_runtime.get("finished_at"),
        } if task_runtime else {},
        "latest_exploration_runtime": {
            "queue_count": exploration_runtime.get("queue_count"),
            "processed_count": exploration_runtime.get("processed_count"),
            "candidate_count": exploration_runtime.get("candidate_count"),
        } if exploration_runtime else {},
    }
    for source in registry:
        category = str(source.get("category") or "unknown")
        payload["source_counts_by_category"][category] = payload["source_counts_by_category"].get(category, 0) + 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def daily_sync(public_target: str = "", ops_target: str = "", thread_id: str = "") -> int:
    ensure_layout()
    steps, graph = run_pipeline_steps()
    model_config = load_model_config()
    write_json(EVALS_LATEST_DIR / "prompt-audit.json", prompt_audit_payload(model_config))
    comparison_path = EVALS_LATEST_DIR / "openclaw-comparison.json"
    if not comparison_path.exists():
        write_json(
            comparison_path,
            {
                "generated_at": None,
                "compared_tasks": 0,
                "openclaw_available": False,
                "note": "Run scripts/eval_models.py smoke or run to populate this comparison artifact.",
            },
        )
    payload = {
        "ok": True,
        "mode": "daily-sync",
        "steps": steps,
        "summary": {
            "entities": len(graph.get("entities", [])),
            "relations": len(graph.get("relations", [])),
            "events": len(graph.get("event_nodes", [])),
            "last_graph_update": graph.get("updated_at"),
            "last_publish": graph.get("runtime", {}).get("publication", {}).get("updated_at"),
        },
    }
    if public_target or ops_target:
        payload["delivery"] = deliver_runtime({"mode": "daily-sync", "result": {"graph": graph, "publication": graph.get("runtime", {}).get("publication", {})}}, public_target=public_target, ops_target=ops_target, thread_id=thread_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def background_sync(topic: str, budget: int, public_target: str = "", ops_target: str = "", thread_id: str = "") -> int:
    ensure_layout()
    steps, graph = run_pipeline_steps()
    graph = load_graph()
    model_config = load_model_config()
    write_json(EVALS_LATEST_DIR / "prompt-audit.json", prompt_audit_payload(model_config))
    comparison_path = EVALS_LATEST_DIR / "openclaw-comparison.json"
    if not comparison_path.exists():
        write_json(
            comparison_path,
            {
                "generated_at": None,
                "compared_tasks": 0,
                "openclaw_available": False,
                "note": "Run scripts/eval_models.py smoke or run to populate this comparison artifact.",
            },
        )
    explorer_command = ["python3", "scripts/explorer.py", "--limit", str(max(1, budget))]
    if topic:
        explorer_command.extend(["--topic", topic])
    explorer_result = run_stage("explorer", explorer_command)
    graph = load_graph()
    payload = {
        "ok": True,
        "mode": "background-sync",
        "steps": steps + [explorer_result],
        "summary": {
            "entities": len(graph.get("entities", [])),
            "relations": len(graph.get("relations", [])),
            "events": len(graph.get("event_nodes", [])),
            "last_graph_update": graph.get("updated_at"),
            "last_publish": graph.get("runtime", {}).get("publication", {}).get("updated_at"),
            "exploration": graph.get("runtime", {}).get("exploration", {}),
        },
    }
    if public_target or ops_target:
        payload["delivery"] = deliver_runtime({"mode": "background-sync", "topic": topic, "result": {"graph": graph, "publication": graph.get("runtime", {}).get("publication", {}), "exploration": graph.get("runtime", {}).get("exploration", {}), "verified_story_pack": graph.get("runtime", {}).get("graph", {}).get("verified_story_pack", [])}}, public_target=public_target, ops_target=ops_target, thread_id=thread_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def ask(query: str, task: str, topic: str, budget: int, public_target: str = "", ops_target: str = "", thread_id: str = "") -> int:
    ensure_layout()
    command = [
        "python3",
        "scripts/task_runner.py",
        "--query",
        query,
        "--budget",
        str(max(1, budget)),
    ]
    if task:
        command.extend(["--task", task])
    if topic:
        command.extend(["--topic", topic])
    completed = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "ask failed")
    payload = json.loads(completed.stdout.strip() or "{}")
    if public_target or ops_target:
        payload["delivery"] = deliver_runtime(payload, public_target=public_target, ops_target=ops_target, thread_id=thread_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def graph_audit() -> int:
    ensure_layout()
    command = ["python3", "scripts/task_runner.py", "--task", "graph_check"]
    completed = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "graph-audit failed")
    print(completed.stdout.strip())
    return 0


def claim_contract_audit(repair: bool = False) -> int:
    ensure_layout()
    command = ["python3", "scripts/graph_contract.py"]
    if repair:
        command.append("--repair")
    completed = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "claim contract audit failed")
    print(completed.stdout.strip())
    return 0


def export_obsidian(output: str = "") -> int:
    ensure_layout()
    command = ["python3", "scripts/export_obsidian.py"]
    if output:
        command.extend(["--output", output])
    completed = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "obsidian export failed")
    print(completed.stdout.strip())
    return 0


def semantic_edges() -> int:
    ensure_layout()
    completed = subprocess.run(["python3", "scripts/semantic_edge_builder.py", "--apply"], cwd=str(ROOT), text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "semantic edge enrichment failed")
    print(completed.stdout.strip())
    return 0


def graph_explore(topic: str, budget: int) -> int:
    ensure_layout()
    command = ["python3", "scripts/explorer.py", "--limit", str(max(1, budget))]
    if topic:
        command.extend(["--topic", topic])
    completed = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "graph-explore failed")
    print(completed.stdout.strip())
    return 0


def deep_research(query: str, topic: str, budget: int) -> int:
    ensure_layout()
    command = [
        "python3",
        "scripts/task_runner.py",
        "--task",
        "topic_deep_research",
        "--query",
        query,
        "--budget",
        str(max(1, budget)),
    ]
    if topic:
        command.extend(["--topic", topic])
    completed = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "deep-research failed")
    print(completed.stdout.strip())
    return 0


def party_crawl(budget: int, interval: int, once: bool) -> int:
    ensure_layout()
    command = ["python3", "scripts/party_crawler.py", "--budget", str(max(1, budget))]
    if once:
        command.append("--once")
    else:
        command.extend(["--interval", str(max(30, interval))])
    if once:
        completed = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "party-crawl failed")
        print(completed.stdout.strip())
    else:
        # For continuous mode, run as a live subprocess
        import signal
        try:
            proc = subprocess.Popen(command, cwd=str(ROOT))
            proc.wait()
        except KeyboardInterrupt:
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=5)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "health":
        return health()
    if args.mode == "party-crawl":
        return party_crawl(args.budget, args.interval, args.once)
    if args.mode == "background-sync":
        return background_sync(args.topic, args.budget, public_target=args.deliver_public_telegram, ops_target=args.deliver_ops_telegram, thread_id=args.deliver_thread_id)
    if args.mode == "ask":
        return ask(args.query, args.task, args.topic, args.budget, public_target=args.deliver_public_telegram, ops_target=args.deliver_ops_telegram, thread_id=args.deliver_thread_id)
    if args.mode == "graph-audit":
        return graph_audit()
    if args.mode == "claim-audit":
        return claim_contract_audit(repair=False)
    if args.mode == "claim-repair":
        return claim_contract_audit(repair=True)
    if args.mode == "semantic-edges":
        return semantic_edges()
    if args.mode == "graph-explore":
        return graph_explore(args.topic, args.budget)
    if args.mode == "export-obsidian":
        return export_obsidian(args.output)
    if args.mode == "deep-research":
        return deep_research(args.query, args.topic, args.budget)
    return daily_sync(public_target=args.deliver_public_telegram, ops_target=args.deliver_ops_telegram, thread_id=args.deliver_thread_id)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
