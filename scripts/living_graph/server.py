"""API assembly helpers for the Living Graph server."""

from __future__ import annotations

from typing import Any

try:
    from .agent_runtime.runtime import latest_trace, resume_run, run_steps, start_background_run, start_run
    from .agent_runtime.task_db import build_research_trace
    from .layout import positions_for_nodes, save_layout
    from .profiles import card_for_node, graph_profile_quality
    from .relations import dossier_for_pair, effective_status, relationship_dossier_for_id, semantic_edge_fields
    from .store import load_graph, node_rows
    from .updater import graph_audit
except ImportError:  # pragma: no cover - top-level import from run_graph_web.py
    from living_graph.agent_runtime.runtime import latest_trace, resume_run, run_steps, start_background_run, start_run
    from living_graph.agent_runtime.task_db import build_research_trace
    from living_graph.layout import positions_for_nodes, save_layout
    from living_graph.profiles import card_for_node, graph_profile_quality
    from living_graph.relations import dossier_for_pair, effective_status, relationship_dossier_for_id, semantic_edge_fields
    from living_graph.store import load_graph, node_rows
    from living_graph.updater import graph_audit


def visual_graph(graph: dict[str, Any], latest_diff: dict[str, Any] | None = None) -> dict[str, Any]:
    nodes = node_rows(graph)
    node_ids = {str(node.get("id") or node.get("vertex_id") or "").strip() for node in nodes}
    positions = positions_for_nodes(nodes)
    edge_payloads = []
    all_edges = [*(graph.get("edges", []) or []), *(graph.get("relations", []) or []), *(graph.get("derived_relations", []) or [])]
    for edge in all_edges:
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("from") or "").strip()
        target = str(edge.get("to") or "").strip()
        if source not in node_ids or target not in node_ids:
            continue
        fields = semantic_edge_fields(edge)
        edge_payloads.append(
            {
                "id": str(edge.get("id") or ""),
                "source": source,
                "target": target,
                "relation_type": edge.get("relation_type") or edge.get("type") or "",
                "relation_class": fields.get("relation_class"),
                "semantic_summary": fields.get("semantic_summary"),
                "confidence": edge.get("confidence", 0),
                "status": effective_status(edge),
                "canonical": bool(edge.get("canonical", True)),
                "last_changed_run_id": edge.get("last_changed_run_id"),
                "change_type": edge.get("change_type", "unchanged"),
                "basis_paths": edge.get("basis_paths", []),
            }
        )
    return {
        "nodes": [
            {
                "id": str(node.get("id") or node.get("vertex_id") or ""),
                "label": str(node.get("name") or node.get("label") or node.get("id") or ""),
                "category": str(node.get("category") or node.get("kind") or ""),
                "subtype": str(node.get("subtype") or ""),
                "summary": str(node.get("summary") or ""),
                "position": positions.get(str(node.get("id") or node.get("vertex_id") or ""), {}),
                "last_changed_run_id": node.get("last_changed_run_id"),
                "change_type": node.get("change_type", "unchanged"),
            }
            for node in nodes
        ],
        "edges": edge_payloads,
        "latest_diff": latest_diff or {},
        "layout": {"positions": positions},
        "audit": graph_audit(graph),
    }


__all__ = [
    "build_research_trace",
    "card_for_node",
    "dossier_for_pair",
    "graph_profile_quality",
    "latest_trace",
    "relationship_dossier_for_id",
    "resume_run",
    "save_layout",
    "run_steps",
    "start_background_run",
    "start_run",
    "visual_graph",
]
