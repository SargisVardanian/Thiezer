"""Living Graph contract helpers."""

from __future__ import annotations

from typing import Any


RESEARCH_TRACE_KEYS = (
    "seed_queries",
    "frontier",
    "visited_urls",
    "accepted_sources",
    "rejected_sources",
    "extracted_claims",
    "proposed_nodes",
    "proposed_edges",
    "accepted_changes",
    "rejected_changes",
)


def empty_graph_diff() -> dict[str, list[Any]]:
    return {"new_nodes": [], "updated_nodes": [], "new_edges": [], "updated_edges": []}


def research_run_contract(query: str, *, run_id: str, status: str = "created", **extra: Any) -> dict[str, Any]:
    trace = {key: list(extra.pop(key, []) or []) for key in RESEARCH_TRACE_KEYS}
    trace["query"] = query
    trace["graph_diff"] = extra.pop("graph_diff", empty_graph_diff())
    trace["status"] = status
    return {
        "contract": "ResearchRunContract.v1",
        "ok": status not in {"failed"},
        "run_id": run_id,
        "status": status,
        "query": query,
        "trace": trace,
        **extra,
    }

