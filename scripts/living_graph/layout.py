"""Persistent deterministic graph layout."""

from __future__ import annotations

import math
from typing import Any

try:
    from .store import LAYOUT_PATH, iso_now, stable_hash, write_json
except ImportError:  # pragma: no cover - top-level import from run_graph_web.py
    from living_graph.store import LAYOUT_PATH, iso_now, stable_hash, write_json

CLUSTER_CENTERS = {
    "institution": (0.0, 0.0),
    "office": (220.0, 0.0),
    "person": (440.0, 0.0),
    "party": (120.0, 300.0),
    "media": (-340.0, 260.0),
    "business": (-300.0, -260.0),
    "case": (280.0, -300.0),
    "event": (0.0, -380.0),
    "organization": (0.0, 300.0),
}


def load_layout() -> dict[str, Any]:
    if not LAYOUT_PATH.exists():
        return {"positions": {}, "updated_at": iso_now()}
    try:
        payload = __import__("json").loads(LAYOUT_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload.setdefault("positions", {})
            return payload
    except Exception:
        pass
    return {"positions": {}, "updated_at": iso_now()}


def save_layout(positions: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, dict[str, Any]] = {}
    for node_id, pos in positions.items():
        if not isinstance(pos, dict):
            continue
        try:
            clean[str(node_id)] = {
                "x": float(pos.get("x", 0.0)),
                "y": float(pos.get("y", 0.0)),
                "z": float(pos.get("z", 0.0)),
                "locked": bool(pos.get("locked", False)),
                "updated_at": str(pos.get("updated_at") or iso_now()),
            }
        except Exception:
            continue
    payload = {"positions": clean, "updated_at": iso_now()}
    write_json(LAYOUT_PATH, payload)
    return payload


def deterministic_position(node: dict[str, Any], index: int = 0) -> dict[str, float]:
    node_id = str(node.get("id") or node.get("vertex_id") or index)
    category = str(node.get("category") or node.get("subtype") or node.get("kind") or "organization").strip()
    center = CLUSTER_CENTERS.get(category) or CLUSTER_CENTERS.get(str(node.get("subtype") or "")) or (0.0, 0.0)
    digest = int(stable_hash(node_id, category), 16)
    angle = (digest % 3600) / 3600.0 * math.tau
    radius = 50.0 + float(digest % 260)
    z_center = (digest % 7 - 3) * 36.0
    return {
        "x": round(center[0] + math.cos(angle) * radius, 3),
        "y": round(center[1] + math.sin(angle) * radius, 3),
        "z": round(z_center, 3),
        "locked": False,
        "updated_at": iso_now(),
    }


def positions_for_nodes(nodes: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    payload = load_layout()
    positions = payload.get("positions", {}) if isinstance(payload.get("positions"), dict) else {}
    changed = False
    for index, node in enumerate(nodes):
        node_id = str(node.get("id") or node.get("vertex_id") or "").strip()
        if not node_id:
            continue
        if node_id not in positions:
            positions[node_id] = deterministic_position(node, index)
            changed = True
    if changed:
        save_layout(positions)
    return positions
