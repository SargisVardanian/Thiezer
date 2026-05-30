#!/usr/bin/env python3
"""Export the canonical graph as an Obsidian-compatible Markdown vault."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pipeline_common import CONTENT_DIR, load_graph, slugify


DEFAULT_OUTPUT = CONTENT_DIR / "exports" / "obsidian-vault"


def _index_by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("id") or "").strip(): row for row in rows if isinstance(row, dict) and str(row.get("id") or "").strip()}


def _safe_note_name(value: str, fallback: str) -> str:
    value = re.sub(r"[\[\]#^|]", " ", value or fallback)
    value = re.sub(r"[/:\\\\]+", " - ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:100].strip(" .") or fallback


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _frontmatter(payload: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in payload.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            if value:
                for item in value:
                    lines.append(f"  - {_yaml_scalar(item)}")
            else:
                lines.append("  []")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def _category_folder(vertex: dict[str, Any]) -> str:
    category = str(vertex.get("category") or vertex.get("kind") or "").strip().lower()
    if category == "person":
        return "People"
    if category in {"institution", "organization", "party", "media"}:
        return "Organizations"
    if category in {"event", "story"} or str(vertex.get("id") or "").startswith("event-"):
        return "Events"
    return "Entities"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _link(note_map: dict[str, str], item_id: str, fallback: str | None = None) -> str:
    note = note_map.get(item_id)
    if note:
        return f"[[{note}]]"
    return f"`{fallback or item_id}`"


def build_note_maps(graph: dict[str, Any]) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    vertex_notes: dict[str, str] = {}
    for vertex in graph.get("vertices", []):
        if not isinstance(vertex, dict):
            continue
        vertex_id = str(vertex.get("id") or "").strip()
        if not vertex_id:
            continue
        label = str(vertex.get("label") or vertex.get("name") or vertex_id).strip()
        folder = _category_folder(vertex)
        vertex_notes[vertex_id] = f"{folder}/{_safe_note_name(label, vertex_id)}"
    for event in graph.get("events", []):
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or event.get("vertex_id") or "").strip()
        if not event_id:
            continue
        label = str(event.get("label") or event.get("name") or event_id).strip()
        vertex_notes[event_id] = f"Events/{_safe_note_name(label, event_id)}"

    claim_notes = {
        str(claim.get("id")): f"Claims/{str(claim.get('id'))}"
        for claim in graph.get("claims", [])
        if isinstance(claim, dict) and str(claim.get("id") or "").strip()
    }
    source_notes = {}
    for source in graph.get("sources", []):
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("id") or "").strip()
        if not source_id:
            continue
        title = str(source.get("title") or source.get("publisher") or source_id).strip()
        source_notes[source_id] = f"Sources/{_safe_note_name(title, source_id)}"
    return vertex_notes, claim_notes, source_notes


def export_vertices(graph: dict[str, Any], output: Path, vertex_notes: dict[str, str], claim_notes: dict[str, str]) -> int:
    vertices = _index_by_id(list(graph.get("vertices", [])))
    for event in graph.get("events", []):
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or event.get("vertex_id") or "").strip()
        if event_id:
            vertices.setdefault(
                event_id,
                {
                    **event,
                    "id": event_id,
                    "category": "event",
                    "label": event.get("label") or event.get("name") or event_id,
                },
            )
    edges = [edge for edge in graph.get("edges", []) if isinstance(edge, dict)]
    written = 0
    for vertex_id, vertex in vertices.items():
        incoming = [edge for edge in edges if str(edge.get("to") or "").strip() == vertex_id]
        outgoing = [edge for edge in edges if str(edge.get("from") or "").strip() == vertex_id]
        label = str(vertex.get("label") or vertex.get("name") or vertex_id).strip()
        aliases = [str(value).strip() for value in vertex.get("aliases", []) if str(value).strip()]
        lines = [
            _frontmatter(
                {
                    "id": vertex_id,
                    "type": vertex.get("category") or vertex.get("kind") or "",
                    "subtype": vertex.get("subtype") or "",
                    "aliases": aliases,
                    "confidence": vertex.get("confidence"),
                }
            ),
            "",
            f"# {label}",
            "",
        ]
        profile = vertex.get("profile", {}) if isinstance(vertex.get("profile", {}), dict) else {}
        summary = str(vertex.get("summary") or profile.get("overview") or "").strip()
        if summary:
            lines.extend(["## Summary", summary, ""])

        if outgoing or incoming:
            lines.extend(["## Direct network", ""])
            for edge in outgoing:
                target = str(edge.get("to") or "").strip()
                relation = str(edge.get("relation_type") or edge.get("type") or "related_to").strip()
                confidence = edge.get("confidence", "")
                lines.append(f"- `{relation}` → {_link(vertex_notes, target)} (confidence: {confidence})")
                summary_text = str(edge.get("natural_language_summary") or edge.get("human_text") or "").strip()
                if summary_text:
                    lines.append(f"  - {summary_text}")
            for edge in incoming:
                source = str(edge.get("from") or "").strip()
                relation = str(edge.get("relation_type") or edge.get("type") or "related_to").strip()
                confidence = edge.get("confidence", "")
                lines.append(f"- {_link(vertex_notes, source)} → `{relation}` (confidence: {confidence})")
                summary_text = str(edge.get("natural_language_summary") or edge.get("human_text") or "").strip()
                if summary_text:
                    lines.append(f"  - {summary_text}")
            lines.append("")

        claim_ids: list[str] = []
        for edge in outgoing + incoming:
            for claim_id in edge.get("claim_ids", []) or []:
                claim_id = str(claim_id).strip()
                if claim_id and claim_id not in claim_ids:
                    claim_ids.append(claim_id)
        if claim_ids:
            lines.extend(["## Claims", ""])
            lines.extend(f"- {_link(claim_notes, claim_id)}" for claim_id in claim_ids)
            lines.append("")

        _write(output / f"{vertex_notes[vertex_id]}.md", "\n".join(lines))
        written += 1
    return written


def export_claims(
    graph: dict[str, Any],
    output: Path,
    vertex_notes: dict[str, str],
    claim_notes: dict[str, str],
    source_notes: dict[str, str],
) -> int:
    evidence_by_id = _index_by_id(list(graph.get("evidence", [])))
    written = 0
    for claim in graph.get("claims", []):
        if not isinstance(claim, dict):
            continue
        claim_id = str(claim.get("id") or "").strip()
        if not claim_id:
            continue
        subject = str(claim.get("subject_vertex_id") or "").strip()
        obj = str(claim.get("object_vertex_id") or "").strip()
        lines = [
            _frontmatter(
                {
                    "id": claim_id,
                    "type": claim.get("claim_type") or "",
                    "status": claim.get("status") or "",
                    "source_reliability": claim.get("source_reliability"),
                    "cross_source_confirmation": claim.get("cross_source_confirmation"),
                    "interpretive_degree": claim.get("interpretive_degree"),
                    "evidence_ids": claim.get("evidence_ids", []) or [],
                    "source_ids": claim.get("source_ids", []) or [],
                }
            ),
            "",
            f"# {claim_id}",
            "",
            "## Statement",
            str(claim.get("statement") or "").strip() or "_No statement recorded._",
            "",
            "## Typed link",
            f"{_link(vertex_notes, subject)} --`{claim.get('claim_type') or 'claim'}`--> {_link(vertex_notes, obj)}",
            "",
        ]
        evidence_ids = [str(value).strip() for value in claim.get("evidence_ids", []) if str(value).strip()]
        if evidence_ids:
            lines.extend(["## Evidence", ""])
            for evidence_id in evidence_ids:
                evidence = evidence_by_id.get(evidence_id, {})
                quote = str(evidence.get("quote") or evidence.get("snippet") or "").strip()
                url = str(evidence.get("url") or "").strip()
                source_id = str(evidence.get("source_id") or "").strip()
                link = f"[source]({url})" if url else _link(source_notes, source_id)
                lines.append(f"- {link}: {quote[:500]}")
            lines.append("")
        source_ids = [str(value).strip() for value in claim.get("source_ids", []) if str(value).strip()]
        if source_ids:
            lines.extend(["## Sources", ""])
            lines.extend(f"- {_link(source_notes, source_id)}" for source_id in source_ids)
            lines.append("")
        _write(output / f"{claim_notes[claim_id]}.md", "\n".join(lines))
        written += 1
    return written


def export_sources(graph: dict[str, Any], output: Path, source_notes: dict[str, str]) -> int:
    written = 0
    for source in graph.get("sources", []):
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("id") or "").strip()
        if not source_id:
            continue
        title = str(source.get("title") or source.get("publisher") or source_id).strip()
        url = str(source.get("url") or "").strip()
        lines = [
            _frontmatter(
                {
                    "id": source_id,
                    "source_class": source.get("source_class") or "",
                    "reliability": source.get("reliability"),
                    "language": source.get("language") or "",
                    "url": url,
                }
            ),
            "",
            f"# {title}",
            "",
        ]
        if url:
            lines.extend(["## URL", f"[{url}]({url})", ""])
        _write(output / f"{source_notes[source_id]}.md", "\n".join(lines))
        written += 1
    return written


def export_vault(graph: dict[str, Any], output: Path) -> dict[str, Any]:
    vertex_notes, claim_notes, source_notes = build_note_maps(graph)
    output.mkdir(parents=True, exist_ok=True)
    counts = {
        "vertices": export_vertices(graph, output, vertex_notes, claim_notes),
        "claims": export_claims(graph, output, vertex_notes, claim_notes, source_notes),
        "sources": export_sources(graph, output, source_notes),
    }
    readme = [
        "# Thiezer Graph Vault",
        "",
        "Generated from the canonical claim-first graph.",
        "",
        "## Sections",
        "- `People/`, `Organizations/`, `Events/`, `Entities/`: canonical vertices.",
        "- `Claims/`: claim notes used as evidence-first graph facts.",
        "- `Sources/`: source notes with URLs and reliability metadata.",
        "",
        "Typed relations are rendered as markdown bullets and claim notes.",
    ]
    _write(output / "README.md", "\n".join(readme))
    return {
        "ok": True,
        "output": str(output),
        "counts": counts,
        "total_markdown_files": sum(1 for _ in output.rglob("*.md")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export the canonical graph as an Obsidian-compatible Markdown vault.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    payload = export_vault(load_graph(), args.output)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
