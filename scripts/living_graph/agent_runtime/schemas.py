"""Typed runtime records for durable work-item execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RunRecord:
    run_id: str
    user_query: str
    run_type: str
    status: str
    created_at: str
    updated_at: str
    current_stage: str = ""
    budget_json: dict[str, Any] = field(default_factory=dict)
    summary_json: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkItem:
    item_id: str
    run_id: str
    item_type: str
    title: str
    status: str
    input_json: dict[str, Any] = field(default_factory=dict)
    output_json: dict[str, Any] = field(default_factory=dict)
    parent_item_id: str = ""
    entity_id: str = ""
    priority: int = 100
    attempts: int = 0
    max_attempts: int = 3
    error: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ToolCallRecord:
    tool_call_id: str
    run_id: str
    item_id: str
    tool_name: str
    input_json: dict[str, Any]
    output_json: dict[str, Any] = field(default_factory=dict)
    status: str = "completed"
    error: str = ""
    created_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GraphDiff:
    new_node_ids: list[str] = field(default_factory=list)
    updated_node_ids: list[str] = field(default_factory=list)
    new_edge_ids: list[str] = field(default_factory=list)
    updated_edge_ids: list[str] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProposedEntity:
    id: str
    name: str
    category: str
    subtype: str = ""
    aliases: list[str] = field(default_factory=list)
    links: dict[str, str] = field(default_factory=dict)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProposedClaim:
    subject_id: str
    predicate: str
    object_id: str
    source_url: str
    evidence_quote: str
    confidence: float
    status: str = "confirmed"
    valid_from: str = ""
    valid_to: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProposedEdge:
    from_id: str
    to_id: str
    relation_type: str
    confidence: float
    status: str = "confirmed"
    canonical_or_derived: str = "canonical"
    source_url: str = ""
    evidence_quote: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EntityProfileUpdate:
    entity_id: str
    overview: str = ""
    biography_or_history: list[str] = field(default_factory=list)
    current_roles_or_functions: list[str] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    source_links: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkItemResult:
    ok: bool
    status: str
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    child_items: list[dict[str, Any]] = field(default_factory=list)
    graph_diff: GraphDiff = field(default_factory=GraphDiff)
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    current_stage: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["graph_diff"] = self.graph_diff.to_dict()
        return payload

