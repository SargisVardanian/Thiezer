#!/usr/bin/env python3
"""Export Thiezer's canonical graph into a static knowledge_graph.json contract."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import deque
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from graph_memory import dossier_bundle, entity_kind, strip_boilerplate
from pipeline_common import CANONICAL_GRAPH, iso_now, load_graph, normalize_text, write_json


OUTPUT_PATH = ROOT / "web" / "graph-viewer" / "knowledge_graph.json"
LAYOUT_CACHE_PATH = ROOT / "web" / "graph-viewer" / "knowledge_graph.layout.json"

DURABLE_EXPORT_REL_TYPES = {
    "holds_office_in",
    "member_of",
    "aligned_with",
    "leads",
    "board_member_of",
    "owns_or_controls",
    "licensed_by",
    "funded_by",
    "contracted_with_state",
    "implemented_by",
    "affects",
    "announced_by",
    "subject_of_legal_case",
    "investigated_by",
    "publicly_supported",
    "publicly_opposed",
}


def _edge_targets(graph: dict[str, Any], entity_ids: set[str]) -> dict[str, list[str]]:
    outgoing: dict[str, list[str]] = {entity_id: [] for entity_id in entity_ids}
    for relation in graph.get("relations", []):
        source = str(relation.get("from") or "").strip()
        target = str(relation.get("to") or "").strip()
        relation_type = str(relation.get("relation_type") or "").strip()
        if source not in entity_ids or target not in entity_ids:
            continue
        if relation_type not in DURABLE_EXPORT_REL_TYPES:
            continue
        if target == source:
            continue
        bucket = outgoing.setdefault(source, [])
        if target not in bucket:
            bucket.append(target)
    for source, targets in outgoing.items():
        targets.sort()
    return outgoing


def _inverse_targets(outgoing: dict[str, list[str]]) -> dict[str, list[str]]:
    incoming: dict[str, list[str]] = {node_id: [] for node_id in outgoing}
    for source, targets in outgoing.items():
        for target in targets:
            bucket = incoming.setdefault(target, [])
            if source not in bucket:
                bucket.append(source)
    for target, sources in incoming.items():
        sources.sort()
    return incoming


def _descendants(start: str, outgoing: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    stack = list(outgoing.get(start, []))
    while stack:
        current = stack.pop()
        if current in seen or current == start:
            continue
        seen.add(current)
        stack.extend(outgoing.get(current, []))
    return seen


def _ancestors(start: str, incoming: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    stack = list(incoming.get(start, []))
    while stack:
        current = stack.pop()
        if current in seen or current == start:
            continue
        seen.add(current)
        stack.extend(incoming.get(current, []))
    return seen


def _depths(outgoing: dict[str, list[str]], incoming: dict[str, list[str]]) -> dict[str, int]:
    indegree = {node_id: len(incoming.get(node_id, [])) for node_id in outgoing}
    roots = [node_id for node_id, degree in indegree.items() if degree == 0]
    depth = {node_id: 0 for node_id in outgoing}
    queue = deque(roots or list(outgoing.keys()))
    visits = 0
    max_visits = max(1, len(outgoing) * 4)
    while queue and visits < max_visits:
        node_id = queue.popleft()
        visits += 1
        current_depth = depth.get(node_id, 0)
        for target in outgoing.get(node_id, []):
            if depth.get(target, 0) < current_depth + 1:
                depth[target] = current_depth + 1
            indegree[target] = max(0, indegree.get(target, 0) - 1)
            if indegree[target] == 0:
                queue.append(target)
    return depth


def _pagerank(outgoing: dict[str, list[str]], *, alpha: float = 0.85, max_iter: int = 80, tol: float = 1e-7) -> dict[str, float]:
    nodes = list(outgoing)
    n = len(nodes)
    if not n:
        return {}
    base = 1.0 / n
    scores = {node_id: base for node_id in nodes}
    incoming = _inverse_targets(outgoing)
    dangling = [node_id for node_id, targets in outgoing.items() if not targets]
    for _ in range(max_iter):
        prev = scores.copy()
        dangling_mass = alpha * sum(prev[node_id] for node_id in dangling) / n
        delta = 0.0
        for node_id in nodes:
            rank = (1.0 - alpha) / n + dangling_mass
            for source in incoming.get(node_id, []):
                out_degree = max(1, len(outgoing.get(source, [])))
                rank += alpha * prev[source] / out_degree
            scores[node_id] = rank
            delta += abs(rank - prev[node_id])
        if delta < tol:
            break
    return scores


def _degree_centrality(outgoing: dict[str, list[str]], incoming: dict[str, list[str]]) -> dict[str, float]:
    size = max(1, len(outgoing) - 1)
    return {
        node_id: (len(outgoing.get(node_id, [])) + len(incoming.get(node_id, []))) / size
        for node_id in outgoing
    }


def _betweenness_centrality(outgoing: dict[str, list[str]]) -> dict[str, float]:
    nodes = list(outgoing)
    score = {node_id: 0.0 for node_id in nodes}
    for source in nodes:
        stack: list[str] = []
        predecessors = {node_id: [] for node_id in nodes}
        sigma = dict.fromkeys(nodes, 0.0)
        sigma[source] = 1.0
        distance = dict.fromkeys(nodes, -1)
        distance[source] = 0
        queue = deque([source])
        while queue:
            vertex = queue.popleft()
            stack.append(vertex)
            for neighbor in outgoing.get(vertex, []):
                if distance[neighbor] < 0:
                    queue.append(neighbor)
                    distance[neighbor] = distance[vertex] + 1
                if distance[neighbor] == distance[vertex] + 1:
                    sigma[neighbor] += sigma[vertex]
                    predecessors[neighbor].append(vertex)
        dependency = dict.fromkeys(nodes, 0.0)
        while stack:
            vertex = stack.pop()
            for predecessor in predecessors[vertex]:
                if sigma[vertex]:
                    dependency[predecessor] += (sigma[predecessor] / sigma[vertex]) * (1.0 + dependency[vertex])
            if vertex != source:
                score[vertex] += dependency[vertex]
    scale = 1.0 / ((len(nodes) - 1) * (len(nodes) - 2)) if len(nodes) > 2 else 1.0
    return {node_id: round(value * scale, 9) for node_id, value in score.items()}


def _definition_from_bundle(bundle: dict[str, Any]) -> str:
    return strip_boilerplate(bundle.get("overview") or "")


def _long_description_from_bundle(bundle: dict[str, Any]) -> str:
    kind = str(bundle.get("kind") or "entity")
    blocks: list[str] = []
    overview = _definition_from_bundle(bundle)
    if overview:
        blocks.append(overview)
    if kind == "person":
        biography = [str(item).strip() for item in bundle.get("biography", []) if str(item).strip()]
        roles = [str(item).strip() for item in bundle.get("current_roles", []) if str(item).strip()]
        if biography:
            blocks.append("## Biography\n" + "\n".join(f"- {item}" for item in biography[:6]))
        if roles:
            blocks.append("## Current Roles\n" + "\n".join(f"- {item}" for item in roles[:6]))
    else:
        history = [str(item).strip() for item in bundle.get("history", []) if str(item).strip()]
        mission = [str(item).strip() for item in bundle.get("mission_or_functions", []) if str(item).strip()]
        powers = [str(item).strip() for item in bundle.get("responsibilities_or_powers", []) if str(item).strip()]
        if history:
            blocks.append("## History\n" + "\n".join(f"- {item}" for item in history[:6]))
        if mission:
            blocks.append("## Mission / Functions\n" + "\n".join(f"- {item}" for item in mission[:6]))
        if powers:
            blocks.append("## Responsibilities / Powers\n" + "\n".join(f"- {item}" for item in powers[:6]))
    timeline = bundle.get("timeline", []) if isinstance(bundle.get("timeline", []), list) else []
    if timeline:
        rows = []
        for item in timeline[:6]:
            if isinstance(item, dict):
                title = str(item.get("title") or item.get("summary") or "").strip()
                date = str(item.get("date") or "").strip()
                if title:
                    rows.append(f"- {date}: {title}" if date else f"- {title}")
            elif str(item).strip():
                rows.append(f"- {str(item).strip()}")
        if rows:
            blocks.append("## Timeline\n" + "\n".join(rows))
    return "\n\n".join(blocks).strip()


def export_knowledge_graph(graph: dict[str, Any]) -> list[dict[str, Any]]:
    entities = [entity for entity in graph.get("entities", []) if isinstance(entity, dict) and str(entity.get("id") or "").strip()]
    entity_ids = {str(entity.get("id")) for entity in entities}
    outgoing = _edge_targets(graph, entity_ids)
    incoming = _inverse_targets(outgoing)
    pagerank = _pagerank(outgoing)
    degree = _degree_centrality(outgoing, incoming)
    betweenness = _betweenness_centrality(outgoing)
    depth = _depths(outgoing, incoming)
    total = max(1, len(entity_ids) - 1)
    rows: list[dict[str, Any]] = []
    for entity in entities:
        entity_id = str(entity.get("id"))
        bundle = dossier_bundle(graph, entity_id)
        profile = entity.get("profile", {}) if isinstance(entity.get("profile", {}), dict) else {}
        perspectives = [
            item
            for item in graph.get("perspectives", [])
            if isinstance(item, dict) and str(item.get("vertex_id") or "") == entity_id
        ]
        descendants = _descendants(entity_id, outgoing)
        ancestors = _ancestors(entity_id, incoming)
        category = entity_kind(entity) or str(entity.get("category") or "entity")
        rows.append(
            {
                "id": entity_id,
                "label": str(entity.get("name") or entity_id),
                "category": category,
                "definition": _definition_from_bundle(bundle),
                "long_description": _long_description_from_bundle(bundle),
                "to": outgoing.get(entity_id, []),
                "from": incoming.get(entity_id, []),
                "depth": int(depth.get(entity_id, 0)),
                "dispute_flags": profile.get("dispute_flags", []),
                "neutral_analytic_summary": str(profile.get("neutral_analytic_summary") or bundle.get("overview") or entity.get("summary") or "").strip(),
                "perspective_count": len(perspectives),
                "_pagerank": float(round(pagerank.get(entity_id, 0.0), 12)),
                "_degree_centrality": float(round(degree.get(entity_id, 0.0), 12)),
                "_betweenness_centrality": float(round(betweenness.get(entity_id, 0.0), 12)),
                "_descendant_ratio": float(round(len(descendants) / total, 12)),
                "_prerequisite_ratio": float(round(len(ancestors) / total, 12)),
                "_reachability_ratio": float(round(len(descendants) / total, 12)),
            }
        )
    rows.sort(key=lambda item: (normalize_text(item.get("category", "")), normalize_text(item.get("label", ""))))
    return rows


def write_knowledge_graph(graph: dict[str, Any], *, output_path: Path = OUTPUT_PATH) -> list[dict[str, Any]]:
    payload = export_knowledge_graph(graph)
    write_json(output_path, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Thiezer canonical graph into a static knowledge_graph.json file.")
    parser.add_argument("--input", type=Path, default=CANONICAL_GRAPH, help="Canonical graph JSON file.")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="Output knowledge_graph.json path.")
    parser.add_argument("--layout-cache", type=Path, default=LAYOUT_CACHE_PATH, help="Optional layout cache path to keep present.")
    args = parser.parse_args()

    graph = load_graph() if args.input == CANONICAL_GRAPH else json.loads(args.input.read_text(encoding="utf-8"))
    payload = write_knowledge_graph(graph, output_path=args.output)
    if not args.layout_cache.exists():
        write_json(args.layout_cache, {"positions": {}, "updated_at": iso_now()})
    print(json.dumps({"ok": True, "nodes": len(payload), "output": str(args.output), "layout_cache": str(args.layout_cache)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
