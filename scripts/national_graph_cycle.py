#!/usr/bin/env python3
"""Run the deterministic national graph maintenance cycle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pipeline_common import SYSTEM_DIR, iso_now, load_graph, write_json  # noqa: E402
from living_graph.question_generator import generate_research_questions, write_question_queue  # noqa: E402
from living_graph.store import edge_rows, node_rows  # noqa: E402
from living_graph.subgraph_builder import build_priority_subgraphs, write_subgraph_bundle  # noqa: E402


OPERATOR_REPORT_FILE = SYSTEM_DIR / "national-graph-operator-report.json"


def _count_status(rows: list[dict[str, Any]], status: str) -> int:
    return sum(1 for row in rows if str(row.get("status") or "").lower() == status)


def build_operator_report(
    graph: dict[str, Any],
    *,
    questions: list[dict[str, Any]],
    subgraphs: list[dict[str, Any]],
    dry_run: bool,
) -> dict[str, Any]:
    entities = node_rows(graph)
    edges = edge_rows(graph)
    claims = [row for row in graph.get("claims", []) or [] if isinstance(row, dict)]
    evidence = [row for row in graph.get("evidence", []) or [] if isinstance(row, dict)]
    sources = [row for row in graph.get("sources", []) or [] if isinstance(row, dict)]
    return {
        "contract": "NationalGraphOperatorReport.v1",
        "generated_at": iso_now(),
        "dry_run": dry_run,
        "sources_checked": len(sources),
        "urls_fetched": 0,
        "claims_extracted": len(claims),
        "claims_admitted": _count_status(claims, "admitted") + _count_status(claims, "confirmed"),
        "claims_rejected": _count_status(claims, "rejected"),
        "disputed_claims_stored": _count_status(claims, "disputed"),
        "vertices_created": len(entities),
        "vertices_merged": sum(len(row.get("merge_history", []) or []) for row in entities if isinstance(row.get("merge_history", []), list)),
        "edges_created_or_updated": len(edges),
        "stale_claims_detected": _count_status(claims, "stale"),
        "evidence_items": len(evidence),
        "questions_generated": len(questions),
        "subgraphs_updated": len([item for item in subgraphs if item.get("status") == "ready"]),
        "errors": [],
        "failures": [],
        "next_recommended_research_tasks": questions[:10],
    }


def run_cycle(args: argparse.Namespace) -> dict[str, Any]:
    graph = load_graph()
    questions = generate_research_questions(graph, limit=args.question_limit)
    subgraphs = build_priority_subgraphs(graph, questions, limit=args.subgraph_limit)
    report = build_operator_report(graph, questions=questions, subgraphs=subgraphs, dry_run=args.dry_run)
    if not args.dry_run:
        write_question_queue(questions)
        write_subgraph_bundle(subgraphs)
        write_json(OPERATOR_REPORT_FILE, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question-limit", type=int, default=50)
    parser.add_argument("--subgraph-limit", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_cycle(args)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"questions_generated: {report['questions_generated']}")
        print(f"subgraphs_updated: {report['subgraphs_updated']}")
        print(f"claims_extracted: {report['claims_extracted']}")
        print(f"claims_admitted: {report['claims_admitted']}")
        print(f"operator_report: {OPERATOR_REPORT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
