"""Source registry helpers for structured internet research."""

from __future__ import annotations

from typing import Any

try:
    from ...pipeline_common import load_source_registry
except ImportError:  # pragma: no cover
    from pipeline_common import load_source_registry


def load_source_registry_snapshot() -> list[dict[str, Any]]:
    sources = load_source_registry()
    return [dict(item) for item in sources if isinstance(item, dict)]

