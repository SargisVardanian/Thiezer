"""Canonical graph store and shared deterministic helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pipeline_common import (  # noqa: E402
    CANONICAL_GRAPH,
    ROOT,
    fetch_url,
    iso_now,
    load_graph,
    normalize_text,
    short_host,
    stable_hash,
    write_json,
)

WEB_DIR = ROOT / "web" / "graph-viewer"
LAYOUT_PATH = WEB_DIR / "layout.json"
KNOWLEDGE_GRAPH_PATH = WEB_DIR / "knowledge_graph.json"
RESEARCH_RUNS_DIR = ROOT / "content" / "system" / "research-runs"
LATEST_RESEARCH_RUN_FILE = RESEARCH_RUNS_DIR / "latest.json"
RESEARCH_RUNS_LOG = RESEARCH_RUNS_DIR / "runs.jsonl"


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def node_rows(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in graph.get("entities", []) or graph.get("vertices", []) or [] if isinstance(row, dict)]


def edge_rows(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in graph.get("edges", []) or graph.get("relations", []) or [] if isinstance(row, dict)]
