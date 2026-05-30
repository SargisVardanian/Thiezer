"""Entity profile contracts for the Living Graph UI."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from graph_memory import entity_profile_card, graph_profile_quality, profile_quality  # noqa: E402,F401


def card_for_node(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    return entity_profile_card(graph, node_id)

