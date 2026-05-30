#!/usr/bin/env python3
"""Audit and repair the claim-first graph contract."""

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

from graph_domain import canonical_admission, sync_compatibility_views
from pipeline_common import CANONICAL_GRAPH, iso_now, load_graph, stable_hash, write_json


def _index_by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("id") or "").strip(): row for row in rows if isinstance(row, dict) and str(row.get("id") or "").strip()}


def _claim_from_edge(edge: dict[str, Any], sources_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    edge_id = str(edge.get("id") or "").strip()
    source_ids = [str(value).strip() for value in edge.get("source_ids", []) if str(value).strip()]
    evidence_ids = [str(value).strip() for value in edge.get("evidence_ids", []) if str(value).strip()]
    source_reliability = max(
        [float((sources_by_id.get(source_id) or {}).get("reliability", 0.0) or 0.0) for source_id in source_ids] or [0.0]
    )
    source_classes = {str((sources_by_id.get(source_id) or {}).get("source_class") or "").strip() for source_id in source_ids}
    has_official = "official" in source_classes
    claim_id = f"claim-{stable_hash('edge-backfill', edge_id, edge.get('from', ''), edge.get('to', ''), edge.get('type', ''))}"
    relation_type = str(edge.get("relation_type") or edge.get("type") or "").strip()
    statement = str(edge.get("natural_language_summary") or edge.get("human_text") or edge.get("summary") or "").strip()
    if not statement:
        statement = f"{edge.get('from', '')} {relation_type} {edge.get('to', '')}".strip()
    return {
        "id": claim_id,
        "claim_hash": stable_hash(claim_id, statement, ",".join(evidence_ids), ",".join(source_ids)),
        "claim_type": relation_type,
        "claim_class": "factual",
        "subject_vertex_id": str(edge.get("from") or "").strip(),
        "object_vertex_id": str(edge.get("to") or "").strip(),
        "statement": statement,
        "evidence_ids": evidence_ids,
        "source_ids": source_ids,
        "source_reliability": round(source_reliability or float(edge.get("confidence", 0.0) or 0.0), 3),
        "cross_source_confirmation": 1.0 if has_official or len(source_ids) > 1 else (0.4 if source_ids else 0.0),
        "interpretive_degree": 0.1 if relation_type in {"part_of", "holds_office_in", "member_of"} else 0.25,
        "extraction_confidence": round(float(edge.get("confidence", 0.0) or 0.0), 3),
        "publication_risk": 0.15,
        "status": str(edge.get("status") or "observed").strip() or "observed",
        "observed_at": edge.get("observed_at") or edge.get("updated_at") or iso_now(),
        "valid_from": edge.get("valid_from"),
        "valid_to": edge.get("valid_to"),
        "updated_at": iso_now(),
        "backfilled_from_edge_id": edge_id,
    }


def audit_graph(graph: dict[str, Any]) -> dict[str, Any]:
    vertices = _index_by_id(list(graph.get("vertices", [])))
    graph_nodes = {**vertices, **_index_by_id(list(graph.get("events", [])))}
    claims = _index_by_id(list(graph.get("claims", [])))
    sources = _index_by_id(list(graph.get("sources", [])))
    evidence = _index_by_id(list(graph.get("evidence", [])))
    issues: list[dict[str, Any]] = []

    for edge in graph.get("edges", []):
        if not isinstance(edge, dict):
            continue
        edge_id = str(edge.get("id") or "").strip()
        source = str(edge.get("from") or "").strip()
        target = str(edge.get("to") or "").strip()
        if source not in graph_nodes or target not in graph_nodes:
            issues.append({"severity": "error", "type": "edge_endpoint_missing", "id": edge_id, "from": source, "to": target})
        claim_ids = [str(value).strip() for value in edge.get("claim_ids", []) if str(value).strip()]
        if not claim_ids:
            issues.append({"severity": "error", "type": "edge_without_claim", "id": edge_id})
        for claim_id in claim_ids:
            if claim_id not in claims:
                issues.append({"severity": "error", "type": "edge_claim_missing", "id": edge_id, "claim_id": claim_id})
        if not edge.get("evidence_ids") and not edge.get("evidence"):
            issues.append({"severity": "warning", "type": "edge_without_evidence", "id": edge_id})

    for claim in graph.get("claims", []):
        if not isinstance(claim, dict):
            continue
        claim_id = str(claim.get("id") or "").strip()
        subject = str(claim.get("subject_vertex_id") or "").strip()
        obj = str(claim.get("object_vertex_id") or "").strip()
        if subject not in graph_nodes or (obj and obj not in graph_nodes):
            issues.append({"severity": "error", "type": "claim_endpoint_missing", "id": claim_id, "subject": subject, "object": obj})
        for evidence_id in claim.get("evidence_ids", []) or []:
            if str(evidence_id) not in evidence:
                issues.append({"severity": "error", "type": "claim_evidence_missing", "id": claim_id, "evidence_id": str(evidence_id)})
        for source_id in claim.get("source_ids", []) or []:
            if str(source_id) not in sources:
                issues.append({"severity": "error", "type": "claim_source_missing", "id": claim_id, "source_id": str(source_id)})

    for item in graph.get("evidence", []):
        if not isinstance(item, dict):
            continue
        supported = [str(value).strip() for value in item.get("supports_claim_ids", []) if str(value).strip()]
        if not supported:
            issues.append({"severity": "warning", "type": "evidence_without_claim", "id": str(item.get("id") or "")})

    admitted_claims = 0
    for claim in graph.get("claims", []):
        if isinstance(claim, dict) and canonical_admission(claim, sources).get("admit"):
            admitted_claims += 1

    return {
        "ok": not any(issue["severity"] == "error" for issue in issues),
        "updated_at": iso_now(),
        "counts": {
            "vertices": len(graph.get("vertices", [])),
            "edges": len(graph.get("edges", [])),
            "claims": len(graph.get("claims", [])),
            "admitted_claims": admitted_claims,
            "sources": len(graph.get("sources", [])),
            "evidence": len(graph.get("evidence", [])),
        },
        "claim_first": {
            "claims_gte_edges": len(graph.get("claims", [])) >= len(graph.get("edges", [])),
            "edges_without_claims": sum(1 for edge in graph.get("edges", []) if isinstance(edge, dict) and not edge.get("claim_ids")),
            "edges_without_evidence": sum(1 for edge in graph.get("edges", []) if isinstance(edge, dict) and not edge.get("evidence_ids") and not edge.get("evidence")),
            "evidence_without_claims": sum(1 for item in graph.get("evidence", []) if isinstance(item, dict) and not item.get("supports_claim_ids")),
        },
        "issues": issues,
    }


def repair_graph(graph: dict[str, Any]) -> dict[str, Any]:
    graph = sync_compatibility_views(graph)
    claims = graph.setdefault("claims", [])
    claims_by_id = _index_by_id(claims)
    sources_by_id = _index_by_id(list(graph.get("sources", [])))
    evidence_by_id = _index_by_id(list(graph.get("evidence", [])))
    created = 0
    linked_edges = 0
    linked_evidence = 0

    for edge in graph.get("edges", []):
        if not isinstance(edge, dict):
            continue
        claim_ids = [str(value).strip() for value in edge.get("claim_ids", []) if str(value).strip()]
        if not claim_ids:
            claim = _claim_from_edge(edge, sources_by_id)
            if claim["id"] not in claims_by_id:
                claims.append(claim)
                claims_by_id[claim["id"]] = claim
                created += 1
            edge["claim_ids"] = [claim["id"]]
            linked_edges += 1
        for claim_id in edge.get("claim_ids", []) or []:
            for evidence_id in edge.get("evidence_ids", []) or []:
                evidence = evidence_by_id.get(str(evidence_id))
                if not evidence:
                    continue
                bucket = evidence.setdefault("supports_claim_ids", [])
                if claim_id not in bucket:
                    bucket.append(claim_id)
                    linked_evidence += 1

    graph.setdefault("runtime", {})["claim_contract_repair"] = {
        "updated_at": iso_now(),
        "created_claims": created,
        "linked_edges": linked_edges,
        "linked_evidence": linked_evidence,
    }
    graph["updated_at"] = iso_now()
    return sync_compatibility_views(graph)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit or repair Thiezer's claim-first graph contract.")
    parser.add_argument("--graph", type=Path, default=CANONICAL_GRAPH)
    parser.add_argument("--repair", action="store_true", help="Backfill claims for existing canonical edges and write the graph.")
    parser.add_argument("--report", type=Path, default=ROOT / "content" / "graph" / "claim-contract-report.json")
    args = parser.parse_args(argv)

    graph = load_graph() if args.graph == CANONICAL_GRAPH else json.loads(args.graph.read_text(encoding="utf-8"))
    if args.repair:
        graph = repair_graph(graph)
        write_json(args.graph, graph)
    report = audit_graph(graph)
    write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
