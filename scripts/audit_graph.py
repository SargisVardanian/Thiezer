#!/usr/bin/env python3
"""Lightweight audit for the canonical Living Graph bundle."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from graph_memory import graph_profile_quality  # noqa: E402
from pipeline_common import load_graph  # noqa: E402


def main() -> int:
    _ = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
    graph = load_graph()
    vertices = graph.get("vertices", []) or []
    edges = graph.get("edges", []) or []
    claims = graph.get("claims", []) or []
    evidence = graph.get("evidence", []) or []
    sources = graph.get("sources", []) or []
    vertex_ids = {str(row.get("id") or "").strip() for row in vertices if isinstance(row, dict)}
    edges_without_claims = 0
    edges_without_evidence = 0
    broken_edge_endpoints = 0
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if not (edge.get("claim_ids") or []):
            edges_without_claims += 1
        if not ((edge.get("evidence_ids") or []) or (edge.get("source_ids") or []) or str(edge.get("source_url") or "").strip()):
            edges_without_evidence += 1
        if str(edge.get("from") or "").strip() not in vertex_ids or str(edge.get("to") or "").strip() not in vertex_ids:
            broken_edge_endpoints += 1
    quality = graph_profile_quality(graph)
    print(f"vertices: {len(vertices)}")
    print(f"edges: {len(edges)}")
    print(f"claims: {len(claims)}")
    print(f"evidence: {len(evidence)}")
    print(f"sources: {len(sources)}")
    print(f"edges_without_claims: {edges_without_claims}")
    print(f"edges_without_evidence: {edges_without_evidence}")
    print(f"broken_edge_endpoints: {broken_edge_endpoints}")
    print(f"thin_profiles: {int(quality.get('counts', {}).get('thin', 0))}")
    print(f"medium_profiles: {int(quality.get('counts', {}).get('medium', 0))}")
    print(f"rich_profiles: {int(quality.get('counts', {}).get('rich', 0))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
