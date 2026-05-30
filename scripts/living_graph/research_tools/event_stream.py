"""Append-only event journal for live research traces."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

try:
    from ..store import ROOT
except ImportError:  # pragma: no cover
    from living_graph.store import ROOT


EVENT_DIR = ROOT / "content" / "system" / "research-events"
EVENT_DIR.mkdir(parents=True, exist_ok=True)


def event_path(run_id: str) -> Path:
    safe = "".join(ch for ch in str(run_id or "") if ch.isalnum() or ch in "-_")
    return EVENT_DIR / f"{safe}.jsonl"


def emit_event(run_id: str, event_type: str, payload: dict[str, Any] | None = None, *, stage: str | None = None, item_id: str | None = None) -> dict[str, Any]:
    event = {
        "ts": time.time(),
        "run_id": str(run_id or ""),
        "event_type": str(event_type or ""),
        "stage": str(stage or ""),
        "item_id": str(item_id or ""),
        "payload": payload or {},
    }
    with event_path(run_id).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event


def read_events(run_id: str, after_ts: float | None = None, limit: int = 500) -> list[dict[str, Any]]:
    path = event_path(run_id)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except Exception:
                continue
            if after_ts is not None and float(event.get("ts") or 0.0) <= after_ts:
                continue
            events.append(event)
    return events[-max(1, int(limit)) :]

