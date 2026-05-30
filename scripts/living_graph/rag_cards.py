"""Model-facing compact graph cards."""

from __future__ import annotations

from typing import Any

try:
    from .profiles import card_for_node
    from .relations import dossier_for_pair, relationship_dossier_for_id
except ImportError:  # pragma: no cover - top-level import from run_graph_web.py
    from living_graph.profiles import card_for_node
    from living_graph.relations import dossier_for_pair, relationship_dossier_for_id


def node_card(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    return card_for_node(graph, node_id)


def relation_card(graph: dict[str, Any], relation_id: str = "", *, from_id: str = "", to_id: str = "") -> dict[str, Any]:
    if relation_id:
        return relationship_dossier_for_id(graph, relation_id)
    return dossier_for_pair(graph, from_id, to_id)
