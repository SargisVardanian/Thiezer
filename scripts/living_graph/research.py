"""Bounded, trace-first research run scaffold."""

from __future__ import annotations

from typing import Any

try:
    from .contracts import research_run_contract
    from .store import LATEST_RESEARCH_RUN_FILE, RESEARCH_RUNS_LOG, append_jsonl, iso_now, stable_hash, write_json
except ImportError:  # pragma: no cover - top-level import from run_graph_web.py
    from living_graph.contracts import research_run_contract
    from living_graph.store import LATEST_RESEARCH_RUN_FILE, RESEARCH_RUNS_LOG, append_jsonl, iso_now, stable_hash, write_json


def source_status(url: str, status: str, reason: str = "") -> dict[str, str]:
    return {"url": url, "status": status, "reason": reason}


def run_research(payload: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query") or payload.get("prompt") or "").strip()
    run_id = f"run-{stable_hash(query, iso_now())}"
    budget = max(1, min(100, int(payload.get("budget_pages") or payload.get("budget") or 5)))
    source_priority = payload.get("source_priority") if isinstance(payload.get("source_priority"), list) else ["official", "reliable_media", "watchdog"]
    seed_queries = [query] if query else []
    lowered = query.lower()
    frontier: list[dict[str, Any]] = []
    accepted_sources: list[dict[str, Any]] = []
    rejected_sources: list[dict[str, Any]] = []
    if "minister" in lowered or "cabinet" in lowered or "gov-members" in lowered or "правительств" in lowered or "նախարար" in lowered:
        roster_url = "https://www.gov.am/en/gov-members/"
        frontier.append({"url": roster_url, "priority": "official_roster", "depth": 0})
        accepted_sources.append(source_status(roster_url, "accepted_as_source", "official government roster pages are authoritative for minister queries"))
    elif "parliament" in lowered or "депутат" in lowered or "պատգամավոր" in lowered or "national assembly" in lowered:
        roster_url = "https://www.parliament.am/deputies.php?lang=eng"
        frontier.append({"url": roster_url, "priority": "official_roster", "depth": 0})
        accepted_sources.append(source_status(roster_url, "accepted_as_source", "official parliament roster/profile pages are authoritative for roster queries"))
    status = "completed" if frontier else "no_results"
    run = research_run_contract(
        query,
        run_id=run_id,
        status=status,
        seed_queries=seed_queries,
        frontier=frontier[:budget],
        visited_urls=[{**item, "status": "visited"} for item in frontier[:budget]],
        accepted_sources=accepted_sources,
        rejected_sources=rejected_sources,
        budget_pages=budget,
        max_depth=max(1, min(3, int(payload.get("max_depth") or 1))),
        source_priority=source_priority,
        target_entities=payload.get("target_entities") if isinstance(payload.get("target_entities"), list) else [],
    )
    write_json(LATEST_RESEARCH_RUN_FILE, run)
    append_jsonl(RESEARCH_RUNS_LOG, run)
    return run
