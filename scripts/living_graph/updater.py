"""Graph audit and claim-first admission checks."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
import argparse
import json
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from graph_domain import normalize_status, relation_class  # noqa: E402
from graph_memory import graph_profile_quality  # noqa: E402
try:
    from .store import edge_rows, iso_now, node_rows  # noqa: E402
except ImportError:  # pragma: no cover - top-level import from run_graph_web.py
    from living_graph.store import edge_rows, iso_now, node_rows  # noqa: E402

GENERIC_RELATIONS = {"", "related_to", "relation", "associated_with", "connected_to"}


def has_edge_evidence(edge: dict[str, Any]) -> bool:
    return bool(
        edge.get("evidence_ids")
        or edge.get("source_ids")
        or str(edge.get("source_url") or edge.get("evidence_quote") or "").strip()
    )


def can_admit_edge(edge: dict[str, Any], node_ids: set[str], *, threshold: float = 0.55) -> tuple[bool, str]:
    relation_type = str(edge.get("relation_type") or edge.get("type") or "").strip()
    if relation_type in GENERIC_RELATIONS:
        return False, "generic_relation_type"
    if str(edge.get("from") or "").strip() not in node_ids or str(edge.get("to") or "").strip() not in node_ids:
        return False, "missing_endpoint"
    if not edge.get("claim_ids"):
        return False, "missing_claim"
    if not has_edge_evidence(edge):
        return False, "missing_evidence_or_source"
    if float(edge.get("confidence", 0.0) or 0.0) < threshold:
        return False, "confidence_below_threshold"
    normalize_status(str(edge.get("status") or "observed"))
    relation_class(relation_type)
    return True, "accepted"


def graph_audit(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = node_rows(graph)
    edges = edge_rows(graph)
    claims = [row for row in graph.get("claims", []) or [] if isinstance(row, dict)]
    node_ids = {str(row.get("id") or row.get("vertex_id") or "").strip() for row in nodes}
    admission = Counter()
    for edge in edges:
        ok, reason = can_admit_edge(edge, node_ids)
        admission["accepted" if ok else reason] += 1
    profile_report = graph_profile_quality(graph)
    return {
        "contract": "GraphAuditReport.v1",
        "updated_at": iso_now(),
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "total_claims": len(claims),
        "edges_without_claims": sum(1 for edge in edges if not edge.get("claim_ids")),
        "edges_without_evidence": sum(1 for edge in edges if not has_edge_evidence(edge)),
        "confirmed_edges_without_claims_or_evidence": sum(
            1
            for edge in edges
            if str(edge.get("status") or "").lower() == "confirmed" and not edge.get("claim_ids") and not has_edge_evidence(edge)
        ),
        "profile_counts": profile_report.get("counts", {}),
        "admission_reasons": dict(admission),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Living Graph claim/evidence/profile contract health.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()
    try:
        from .store import load_graph
    except ImportError:  # pragma: no cover - top-level import from run_graph_web.py
        from living_graph.store import load_graph

    report = graph_audit(load_graph())
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"nodes: {report['total_nodes']}")
        print(f"edges: {report['total_edges']}")
        print(f"claims: {report['total_claims']}")
        print(f"edges_without_claims: {report['edges_without_claims']}")
        print(f"edges_without_evidence: {report['edges_without_evidence']}")
        print(f"profile_counts: {report['profile_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
