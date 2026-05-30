#!/usr/bin/env python3
"""Restore Thiezer's canonical graph from local snapshots and evidence logs."""

from __future__ import annotations

import json
import re
import difflib
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from export_knowledge_graph import write_knowledge_graph  # noqa: E402
from graph_domain import build_claim_from_relation, build_edge_from_claim, normalize_vertex, relation_class  # noqa: E402
from pipeline_common import CANONICAL_GRAPH, fetch_url, iso_now, load_graph, normalize_text, slugify, stable_hash, write_json, canonical_name_key, canonical_person_key  # noqa: E402
from living_graph.agent_runtime.government_am import GOV_MEMBERS_URL, parse_government_members_page  # noqa: E402


KNOWLEDGE_GRAPH_PATH = ROOT / "web" / "graph-viewer" / "knowledge_graph.json"
EVIDENCE_LOG_PATH = ROOT / "content" / "graph" / "evidence-log.jsonl"
REPAIR_REPORT_PATH = ROOT / "content" / "graph" / "repairs" / "latest.json"
REPAIR_RUN_ID = "graph-repair-restore-old-links"

KNOWN_PARTY_IDS = {
    "civil contract": "party-civil-contract",
    "republican party of armenia": "party-republican-party-of-armenia",
    "armenia alliance": "party-armenia-alliance",
    "with honor": "party-with-honor",
}

KNOWN_INSTITUTION_IDS = {
    "national assembly": "institution-parliament",
    "national assembly of armenia": "institution-parliament",
    "parliament": "institution-parliament",
    "government of armenia": "institution-government-of-armenia",
    "government": "institution-government-of-armenia",
}

KNOWN_OFFICE_IDS = {
    "prime minister": "office-prime-minister-armenia",
}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _short_label(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _looks_like_sentence_label(label: str) -> bool:
    blob = _short_label(label)
    if not blob:
        return True
    if len(blob.split()) > 18:
        return True
    if len(blob) > 140:
        return True
    lowered = blob.lower()
    if re.search(r"\b(to|the|of|and|for|in)$", lowered):
        return True
    if any(marker in lowered for marker in ("introduced ", "introduced newly", "met with", "press release", "thanking ", "announced ", "appointed ", "official website", "government team members", "team members", "office holders", "government staff", "staff report", "staff directory")):
        return True
    if sum(1 for ch in blob if ch in ",;:") >= 2:
        return True
    return False


def _is_human_name_like(label: str) -> bool:
    blob = _short_label(label)
    if not blob or _looks_like_sentence_label(blob):
        return False
    if len(blob.split()) < 2:
        return False
    if any(ch.isdigit() for ch in blob):
        return False
    lowered = normalize_text(blob)
    if any(token in lowered for token in ("government team members", "team members", "office holders", "members", "directory", "roster", "staff report", "staff list", "staff directory", "official website", "office of the prime minister", "prime minister", "chief of staff", "head of staff", "minister of", "deputy minister", "chief adviser", "adviser", "assistant", "press secretary")):
        return False
    return True


def _coerce_vertex_category(vertex: dict[str, Any]) -> str:
    label = _short_label(str(vertex.get("label") or vertex.get("name") or ""))
    lowered = normalize_text(label)
    current = str(vertex.get("category") or vertex.get("kind") or "").strip().lower()
    if not label:
        return current or "organization"
    if _looks_like_sentence_label(label):
        return current or "organization"
    if _is_human_name_like(label):
        return "person"
    if any(token in lowered for token in ("chief of staff", "head of staff", "deputy chief", "chief adviser", "press secretary", "chief protocol", "adviser", "assistant", "head of department", "head of division", "minister of")):
        return "office"
    if any(token in lowered for token in ("government team members", "team members", "office holders", "members", "directory", "roster", "staff report", "staff list", "staff directory", "official website")):
        return "person" if current == "person" else "organization"
    return current or "organization"


def _should_keep_vertex(vertex: dict[str, Any]) -> tuple[bool, str]:
    vertex = deepcopy(vertex)
    vertex["category"] = _coerce_vertex_category(vertex)
    label = str(vertex.get("label") or vertex.get("name") or "").strip()
    category = str(vertex.get("category") or vertex.get("kind") or "").strip()
    entity_id = str(vertex.get("id") or "").strip()
    if not label:
        return False, "missing_label"
    if re.fullmatch(r"^(?:[a-fA-F0-9]{8,}|[A-Z]?[a-fA-F0-9]{8,}[A-Za-z0-9]*|E[0-9A-Fa-f]{12,}[A-Za-z0-9]*)$", label) or re.fullmatch(r"^(?:[a-fA-F0-9]{8,}|[A-Z]?[a-fA-F0-9]{8,}[A-Za-z0-9]*|E[0-9A-Fa-f]{12,}[A-Za-z0-9]*)$", entity_id):
        return False, "hash_like_label"
    if category == "person" and not _is_human_name_like(label):
        return False, "missing_human_readable_name"
    if category in {"office", "organization", "institution", "company", "party"} and _looks_like_sentence_label(label):
        return False, "internal_id_leak"
    return True, "accepted"


def _vertex_group_key(vertex: dict[str, Any]) -> tuple[str, str]:
    category = _coerce_vertex_category(vertex).lower()
    label = str(vertex.get("label") or vertex.get("name") or "").strip()
    if category == "person":
        return ("person", canonical_person_key(label) or canonical_name_key(label))
    return (category or "entity", canonical_name_key(label))


def _vertex_score(vertex: dict[str, Any]) -> tuple[int, int, int, int]:
    label = str(vertex.get("label") or vertex.get("name") or "").strip()
    profile = vertex.get("profile") if isinstance(vertex.get("profile"), dict) else {}
    links = vertex.get("links") if isinstance(vertex.get("links"), dict) else {}
    evidence = profile.get("evidence_summary") if isinstance(profile, dict) else []
    official_links = 1 if any("gov.am" in str(value or "") or "primeminister.am" in str(value or "") or "parliament.am" in str(value or "") or "arlis.am" in str(value or "") for value in links.values()) else 0
    return (
        official_links,
        len([value for value in links.values() if str(value or "").strip()]),
        len(evidence) if isinstance(evidence, list) else 0,
        -len(label.split()),
    )


def _merge_vertex_records(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = normalize_vertex({**base, **incoming})
    aliases = list(dict.fromkeys([*(base.get("aliases", []) or []), *(incoming.get("aliases", []) or []), str(base.get("label") or ""), str(incoming.get("label") or ""), str(base.get("name") or ""), str(incoming.get("name") or "")]))
    merged["aliases"] = [alias for alias in aliases if alias and alias != merged.get("name")]
    base_profile = base.get("profile") if isinstance(base.get("profile"), dict) else {}
    incoming_profile = incoming.get("profile") if isinstance(incoming.get("profile"), dict) else {}
    profile = deepcopy(base_profile)
    profile.update({k: v for k, v in incoming_profile.items() if v not in (None, "", [], {})})
    merged["profile"] = profile
    links = {}
    if isinstance(base.get("links"), dict):
        links.update(base.get("links"))
    if isinstance(incoming.get("links"), dict):
        links.update(incoming.get("links"))
    merged["links"] = links
    if not str(merged.get("label") or "").strip():
        merged["label"] = merged.get("name") or merged.get("id")
    return merged


def _numeric_confidence(value: Any, default: float = 0.6) -> float:
    if isinstance(value, dict):
        for key in ("confidence", "extraction_confidence", "source_reliability", "cross_source_confirmation", "publication_risk"):
            nested = value.get(key)
            if isinstance(nested, (int, float)):
                return float(nested)
        return default
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _write_json_replace(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _vertex_from_snapshot_row(row: dict[str, Any]) -> dict[str, Any]:
    profile = {
        "neutral_analytic_summary": str(row.get("neutral_analytic_summary") or row.get("definition") or row.get("label") or "").strip(),
        "overview": str(row.get("definition") or row.get("neutral_analytic_summary") or row.get("label") or "").strip(),
        "history_or_biography": [str(row.get("definition") or "").strip()] if row.get("definition") else [],
        "current_roles_or_functions": [],
        "timeline": [],
        "direct_network": list(row.get("to", []) or []),
        "indirect_network": list(row.get("from", []) or []),
        "evidence_summary": [str(row.get("definition") or "").strip()] if row.get("definition") else [],
        "dispute_flags": list(row.get("dispute_flags", []) or []),
    }
    return normalize_vertex(
        {
            "id": row.get("id"),
            "label": row.get("label") or row.get("id"),
            "name": row.get("label") or row.get("id"),
            "category": row.get("category") or "entity",
            "subtype": row.get("subtype") or "",
            "summary": str(row.get("neutral_analytic_summary") or row.get("definition") or row.get("label") or "").strip(),
            "profile": profile,
            "links": {},
            "aliases": [],
            "observed_at": iso_now(),
            "updated_at": iso_now(),
        }
    )


def _guess_vertex_category(node_id: str) -> tuple[str, str]:
    normalized = normalize_text(node_id)
    if normalized.startswith("person-"):
        return "person", "person"
    if normalized.startswith("party-"):
        return "party", "party"
    if normalized.startswith("institution-"):
        return "institution", "institution"
    if normalized.startswith("office-"):
        return "office", "office"
    if normalized.startswith("organization-"):
        return "organization", "organization"
    if normalized.startswith("media-"):
        return "media", "media"
    if normalized.startswith("company-"):
        return "company", "company"
    if normalized.startswith("administrative-unit-") or normalized.startswith("administrative_unit-") or normalized.startswith("region-") or normalized.startswith("district-"):
        return "administrative_unit", "administrative_unit"
    if normalized.startswith("country-"):
        return "country", "country"
    if normalized.startswith("community-"):
        return "community", "community"
    if normalized.startswith("case-"):
        return "case", "case"
    if normalized.startswith("law-"):
        return "law", "law"
    if normalized.startswith("event-story-") or normalized.startswith("event-"):
        return "event", "event"
    return "organization", "organization"


def _synthetic_vertex(node_id: str) -> dict[str, Any]:
    category, subtype = _guess_vertex_category(node_id)
    label = re.sub(r"^(person|party|institution|office|organization|media|company|administrative-unit|administrative_unit|region|district|country|community|case|law|event-story|event)-", "", node_id)
    label = label.replace("-", " ").strip() or node_id
    label = label.replace(" of ", " of ").strip()
    return normalize_vertex(
        {
            "id": node_id,
            "label": label.title() if label and label == label.lower() else label,
            "name": label.title() if label and label == label.lower() else label,
            "category": category,
            "subtype": subtype,
            "summary": label,
            "profile": {
                "neutral_analytic_summary": label,
                "overview": label,
                "history_or_biography": [],
                "current_roles_or_functions": [],
                "timeline": [],
                "direct_network": [],
                "indirect_network": [],
                "evidence_summary": [],
                "dispute_flags": [],
            },
            "links": {},
            "aliases": [],
            "observed_at": iso_now(),
            "updated_at": iso_now(),
        }
    )


def _infer_target(target_text: str) -> tuple[str, str]:
    cleaned = _short_label(target_text)
    normalized = normalize_text(cleaned)
    if not cleaned:
        return "", ""
    for needle, target_id in KNOWN_PARTY_IDS.items():
        if needle in normalized:
            return target_id, "party"
    for needle, target_id in KNOWN_INSTITUTION_IDS.items():
        if needle in normalized:
            return target_id, "institution"
    for needle, target_id in KNOWN_OFFICE_IDS.items():
        if needle in normalized:
            return target_id, "office"
    if normalized.startswith("minister of "):
        return f"office-{slugify(cleaned)}", "office"
    if "ministry of " in normalized:
        return f"organization-{slugify(cleaned)}", "organization"
    if "faction" in normalized or "bloc" in normalized:
        return f"party-{slugify(cleaned)}", "party"
    if "assembly" in normalized or "parliament" in normalized:
        return "institution-parliament", "institution"
    return f"organization-{slugify(cleaned)}", "organization"


def _relation_source_class(source_url: str, relation_type: str) -> str:
    url = str(source_url or "").lower()
    if url.startswith("snapshot://"):
        return "internal"
    if "gov.am" in url or "parliament.am" in url or "president.am" in url:
        return "official"
    if relation_type in {"holds_office_in", "part_of", "member_of"}:
        return "official"
    return "media"


def _relation_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("from") or "").strip(),
        str(row.get("to") or "").strip(),
        str(row.get("relation_type") or "").strip(),
        str(row.get("source_url") or "").strip(),
    )


def _build_relation_rows(snapshot_rows: list[dict[str, Any]], current_graph: dict[str, Any], evidence_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    def add(row: dict[str, Any]) -> None:
        key = _relation_key(row)
        if not key[0] or not key[1] or not key[2]:
            return
        if key in seen:
            return
        seen.add(key)
        rows.append(row)

    _ = current_graph  # preserve signature without re-ingesting the already-present current canonical edges.

    try:
        body, final_url = fetch_url(GOV_MEMBERS_URL)
        ministers = parse_government_members_page(body, final_url).get("people", [])
    except Exception:
        ministers = []
        final_url = GOV_MEMBERS_URL
    for minister in ministers:
        minister_name = str(minister.get("name") or "").strip()
        title = str(minister.get("title") or minister.get("position") or "").strip()
        ministry_name = str(minister.get("ministry_name") or "").strip()
        minister_id = f"person-{slugify(minister_name)}" if minister_name else ""
        if minister_id and title:
            office_target, _ = _infer_target(title)
            if office_target:
                add(
                    {
                        "id": f"gov-{stable_hash(minister_id, office_target, title)}",
                        "from": minister_id,
                        "to": office_target,
                        "relation_type": "holds_office_in",
                        "type": "holds_office_in",
                        "status": "probable",
                        "confidence": 0.92,
                        "source_url": final_url,
                        "source_type": "official",
                        "evidence_quote": f"{minister_name} is listed as {title}.",
                        "valid_from": "current",
                        "valid_to": None,
                        "collected_at": iso_now(),
                        "layer": "canonical",
                        "last_changed_run_id": REPAIR_RUN_ID,
                        "change_type": "updated",
                    }
                )
        if minister_id and ministry_name:
            ministry_id = f"organization-{slugify(ministry_name)}"
            add(
                {
                    "id": f"gov-{stable_hash(minister_id, ministry_id, ministry_name)}",
                    "from": minister_id,
                    "to": ministry_id,
                    "relation_type": "leads",
                    "type": "leads",
                    "status": "probable",
                    "confidence": 0.9,
                    "source_url": final_url,
                    "source_type": "official",
                    "evidence_quote": f"{minister_name} leads {ministry_name}.",
                    "valid_from": "current",
                    "valid_to": None,
                    "collected_at": iso_now(),
                    "layer": "canonical",
                    "last_changed_run_id": REPAIR_RUN_ID,
                    "change_type": "updated",
                }
            )
            add(
                {
                    "id": f"gov-{stable_hash(ministry_id, 'institution-government-of-armenia', ministry_name)}",
                    "from": ministry_id,
                    "to": "institution-government-of-armenia",
                    "relation_type": "part_of",
                    "type": "part_of",
                    "status": "probable",
                    "confidence": 0.88,
                    "source_url": final_url,
                    "source_type": "official",
                    "evidence_quote": f"{ministry_name} is part of the Government of Armenia.",
                    "valid_from": "current",
                    "valid_to": None,
                    "collected_at": iso_now(),
                    "layer": "canonical",
                    "last_changed_run_id": REPAIR_RUN_ID,
                    "change_type": "updated",
                }
            )

    for item in evidence_rows:
        relation_type = str(item.get("relation_type") or "").strip()
        source = str(item.get("source_url") or "").strip()
        from_id = str(item.get("entity_from") or "").strip()
        to_id = str(item.get("entity_to") or "").strip()
        if not relation_type or not from_id or not to_id:
            continue
        add(
            {
                "id": f"evidence-{stable_hash(from_id, to_id, relation_type, source, item.get('recorded_at', ''))}",
                "from": from_id,
                "to": to_id,
                "relation_type": relation_type,
                "type": relation_type,
                "status": "probable" if relation_type in {"aligned_with", "opposes", "publicly_opposed"} else "confirmed",
                "confidence": _numeric_confidence(item.get("confidence"), 0.6),
                "source_url": source,
                "source_type": str(item.get("source_type") or _relation_source_class(source, relation_type)),
                "evidence_quote": str(item.get("evidence_quote") or ""),
                "valid_from": item.get("valid_from"),
                "valid_to": item.get("valid_to"),
                "collected_at": str(item.get("recorded_at") or iso_now()),
                "layer": "canonical",
                "last_changed_run_id": str(item.get("run_id") or ""),
                "change_type": "updated" if str(item.get("action") or "") == "updated" else "new",
            }
        )

    for row in snapshot_rows:
        if str(row.get("category") or "") != "person":
            continue
        text = "\n".join(
            part
            for part in [
                str(row.get("long_description") or ""),
                str(row.get("neutral_analytic_summary") or ""),
                str(row.get("definition") or ""),
            ]
            if part.strip()
        )
        if not text:
            continue
        for match in re.finditer(r"(?im)^\-\s*(.+)$", text):
            line = _short_label(match.group(1))
            if not line:
                continue
            rel_type = ""
            target_text = ""
            if line.lower().startswith("member of "):
                rel_type = "member_of"
                target_text = line[10:]
            elif line.lower().startswith("holds office in "):
                rel_type = "holds_office_in"
                target_text = line[16:]
            elif "appointed minister of" in line.lower():
                rel_type = "holds_office_in"
                target_text = line.split("Appointed", 1)[-1].strip().removeprefix("Minister of ").strip()
                target_text = f"Minister of {target_text}"
            elif line.lower().startswith("minister of "):
                rel_type = "holds_office_in"
                target_text = line
            elif "prime minister" in line.lower():
                rel_type = "holds_office_in"
                target_text = "Prime Minister"
            if not rel_type:
                continue
            target_id, target_kind = _infer_target(target_text)
            if not target_id:
                continue
            add(
                {
                    "id": f"inferred-{stable_hash(row.get('id', ''), rel_type, target_id, line)}",
                    "from": str(row.get("id") or ""),
                    "to": target_id,
                    "relation_type": rel_type,
                    "type": rel_type,
                    "status": "probable",
                    "confidence": 0.64 if rel_type == "member_of" else 0.72,
                    "source_url": "snapshot://knowledge_graph",
                    "source_type": "internal",
                    "evidence_quote": line,
                    "valid_from": "current",
                    "valid_to": None,
                    "collected_at": iso_now(),
                    "layer": "derived",
                    "last_changed_run_id": REPAIR_RUN_ID,
                    "change_type": "updated",
                    "target_kind": target_kind,
                }
            )

    return rows


def repair_graph_bundle() -> dict[str, Any]:
    current_graph = load_graph()
    snapshot_rows = json.loads(KNOWLEDGE_GRAPH_PATH.read_text(encoding="utf-8")) if KNOWLEDGE_GRAPH_PATH.exists() else []
    evidence_rows = _load_jsonl(EVIDENCE_LOG_PATH)

    candidate_vertices: list[dict[str, Any]] = []
    rejected_vertices: list[dict[str, Any]] = []
    for existing in current_graph.get("vertices", []) or current_graph.get("entities", []) or []:
        if not isinstance(existing, dict):
            continue
        item = normalize_vertex(existing)
        item["category"] = _coerce_vertex_category(item)
        ok, reason = _should_keep_vertex(item)
        if not ok:
            rejected_vertices.append({"type": "vertex", "reason": reason, "vertex_id": item["id"], "label": item.get("label")})
            continue
        candidate_vertices.append(item)

    for row in snapshot_rows:
        if not isinstance(row, dict):
            continue
        vertex = _vertex_from_snapshot_row(row)
        vertex["category"] = _coerce_vertex_category(vertex)
        ok, reason = _should_keep_vertex(vertex)
        if not ok:
            rejected_vertices.append({"type": "vertex", "reason": reason, "vertex_id": vertex["id"], "label": vertex.get("label")})
            continue
        candidate_vertices.append(vertex)

    relation_rows = _build_relation_rows(snapshot_rows, current_graph, evidence_rows)
    grouped_vertices: dict[tuple[str, str], dict[str, Any]] = {}
    id_map: dict[str, str] = {}
    rejected_vertex_ids: set[str] = {str(item.get("vertex_id") or "").strip() for item in rejected_vertices if str(item.get("vertex_id") or "").strip()}
    for vertex in sorted(candidate_vertices, key=lambda row: (_vertex_score(row), str(row.get("id") or "")), reverse=True):
        group_key = _vertex_group_key(vertex)
        existing = grouped_vertices.get(group_key)
        if existing is None:
            initial = deepcopy(vertex)
            initial["category"] = group_key[0]
            grouped_vertices[group_key] = initial
            id_map[str(vertex.get("id") or "").strip()] = str(vertex.get("id") or "").strip()
            continue
        keep = deepcopy(existing)
        merged = _merge_vertex_records(keep, vertex)
        if _vertex_score(vertex) > _vertex_score(existing):
            merged["id"] = str(vertex.get("id") or "").strip()
        merged["category"] = group_key[0]
        grouped_vertices[group_key] = merged
        id_map[str(vertex.get("id") or "").strip()] = str(merged.get("id") or "").strip()
        id_map[str(existing.get("id") or "").strip()] = str(merged.get("id") or "").strip()

    person_groups = [key for key in grouped_vertices if key[0] == "person"]
    for index, left_key in enumerate(person_groups):
        left_vertex = grouped_vertices.get(left_key)
        if not left_vertex:
            continue
        for right_key in person_groups[index + 1 :]:
            right_vertex = grouped_vertices.get(right_key)
            if not right_vertex:
                continue
            score = difflib.SequenceMatcher(None, str(left_key[1] or ""), str(right_key[1] or "")).ratio()
            if score < 0.9:
                continue
            merged = _merge_vertex_records(left_vertex, right_vertex)
            if _vertex_score(right_vertex) > _vertex_score(left_vertex):
                merged["id"] = str(right_vertex.get("id") or "").strip()
            merged["category"] = "person"
            grouped_vertices[left_key] = merged
            id_map[str(right_vertex.get("id") or "").strip()] = str(merged.get("id") or "").strip()
            del grouped_vertices[right_key]
            left_vertex = merged

    vertices_by_id: dict[str, dict[str, Any]] = {str(vertex.get("id") or ""): vertex for vertex in grouped_vertices.values() if str(vertex.get("id") or "").strip()}
    person_index: dict[str, str] = {}
    for vertex in vertices_by_id.values():
        if str(vertex.get("category") or "").strip() != "person":
            continue
        label = str(vertex.get("label") or vertex.get("name") or "").strip()
        canonical = canonical_person_key(label) or canonical_name_key(label)
        if canonical:
            person_index[canonical] = str(vertex.get("id") or "").strip()
            person_index[canonical_name_key(label)] = str(vertex.get("id") or "").strip()

    for rejected in rejected_vertices:
        label = str(rejected.get("label") or "").strip()
        if not label:
            continue
        canonical = canonical_person_key(label) or canonical_name_key(label)
        for key, vertex_id in person_index.items():
            if key and key in canonical and vertex_id:
                id_map[str(rejected.get("vertex_id") or "").strip()] = vertex_id
                break

    endpoint_ids = set()
    for relation in relation_rows:
        endpoint_ids.add(str(relation.get("from") or "").strip())
        endpoint_ids.add(str(relation.get("to") or "").strip())
    for edge in current_graph.get("edges", []) or []:
        if not isinstance(edge, dict):
            continue
        endpoint_ids.add(str(edge.get("from") or "").strip())
        endpoint_ids.add(str(edge.get("to") or "").strip())
    for node_id in sorted(node_id for node_id in endpoint_ids if node_id):
        if node_id in rejected_vertex_ids:
            continue
        if node_id not in vertices_by_id:
            synthetic = _synthetic_vertex(node_id)
            synthetic["category"] = _coerce_vertex_category(synthetic)
            ok, reason = _should_keep_vertex(synthetic)
            if ok:
                vertices_by_id[node_id] = synthetic
            else:
                rejected_vertices.append({"type": "vertex", "reason": reason, "vertex_id": synthetic["id"], "label": synthetic.get("label")})

    sources_by_id: dict[str, dict[str, Any]] = {str(source.get("id") or ""): deepcopy(source) for source in current_graph.get("sources", []) or [] if isinstance(source, dict) and str(source.get("id") or "")}
    evidence_by_id: dict[str, dict[str, Any]] = {str(item.get("id") or ""): deepcopy(item) for item in current_graph.get("evidence", []) or [] if isinstance(item, dict) and str(item.get("id") or "")}
    claims_by_id: dict[str, dict[str, Any]] = {str(item.get("id") or ""): deepcopy(item) for item in current_graph.get("claims", []) or [] if isinstance(item, dict) and str(item.get("id") or "")}
    edges_by_id: dict[str, dict[str, Any]] = {str(item.get("id") or ""): deepcopy(item) for item in current_graph.get("edges", []) or [] if isinstance(item, dict) and str(item.get("id") or "")}

    def remap_vertex_id(value: str) -> str:
        raw = str(value or "").strip()
        return str(id_map.get(raw) or raw).strip()

    for claim in claims_by_id.values():
        claim["subject_vertex_id"] = remap_vertex_id(claim.get("subject_vertex_id") or claim.get("subject_id") or "")
        claim["object_vertex_id"] = remap_vertex_id(claim.get("object_vertex_id") or claim.get("object_id") or "")
    for edge in edges_by_id.values():
        edge["from"] = remap_vertex_id(edge.get("from") or edge.get("source") or "")
        edge["to"] = remap_vertex_id(edge.get("to") or edge.get("target") or "")

    for relation in relation_rows:
        source_url = str(relation.get("source_url") or "").strip()
        relation_type = str(relation.get("relation_type") or "").strip()
        relation["from"] = remap_vertex_id(relation.get("from") or relation.get("source_id") or "")
        relation["to"] = remap_vertex_id(relation.get("to") or relation.get("target_id") or "")
        source_type = str(relation.get("source_type") or "").strip() or _relation_source_class(source_url, relation_type)
        source_id = f"source-{stable_hash(source_url or relation.get('from', ''), relation_type, source_type)}"
        if source_id not in sources_by_id:
            sources_by_id[source_id] = {
                "id": source_id,
                "url": source_url,
                "title": str(relation.get("title") or relation.get("from") or relation_type or source_url).strip(),
                "publisher": str(relation.get("source_name") or "").strip() or ("snapshot" if source_type == "internal" else source_type),
                "source_class": source_type if source_type != "internal" else "unknown",
                "language": "eng",
                "reliability": _numeric_confidence(relation.get("confidence"), 0.6),
                "updated_at": iso_now(),
            }
        evidence_id = f"evidence-{stable_hash(source_id, relation.get('id', ''), relation.get('evidence_quote', ''), relation.get('from', ''), relation.get('to', ''))}"
        if evidence_id not in evidence_by_id:
            evidence_by_id[evidence_id] = {
                "id": evidence_id,
                "source_id": source_id,
                "url": source_url,
                "title": sources_by_id[source_id].get("title") or source_url,
                "publisher": sources_by_id[source_id].get("publisher") or "",
                "source_class": sources_by_id[source_id].get("source_class") or "",
                "language": "eng",
                "published_at": str(relation.get("valid_from") or "").strip(),
                "retrieved_at": str(relation.get("collected_at") or iso_now()).strip(),
                "snippet": str(relation.get("evidence_quote") or relation.get("notes") or "").strip(),
                "quote": str(relation.get("evidence_quote") or "").strip(),
                "stance": "supporting",
                "supports_claim_ids": [],
                "contradicts_claim_ids": [],
            }
        claim = build_claim_from_relation(relation, evidence_ids=[evidence_id], source_ids=[source_id])
        claim["created_by_run_id"] = REPAIR_RUN_ID
        claim["last_changed_run_id"] = REPAIR_RUN_ID
        claims_by_id[claim["id"]] = claim
        evidence_by_id[evidence_id]["supports_claim_ids"] = sorted(set(evidence_by_id[evidence_id].get("supports_claim_ids", [])) | {claim["id"]})
        edge = build_edge_from_claim(claim, evidence_ids=[evidence_id], source_ids=[source_id])
        edge["last_changed_run_id"] = relation.get("last_changed_run_id") or REPAIR_RUN_ID
        edge["change_type"] = relation.get("change_type") or ("new" if relation.get("action") == "created" else "updated")
        edges_by_id[edge["id"]] = edge

    valid_vertex_ids = set(vertices_by_id.keys())
    claims_by_id = {
        key: value
        for key, value in claims_by_id.items()
        if str(value.get("subject_vertex_id") or "").strip() in valid_vertex_ids and (not value.get("object_vertex_id") or str(value.get("object_vertex_id") or "").strip() in valid_vertex_ids)
    }
    edges_by_id = {
        key: value
        for key, value in edges_by_id.items()
        if str(value.get("from") or "").strip() in valid_vertex_ids and str(value.get("to") or "").strip() in valid_vertex_ids
    }

    graph = deepcopy(current_graph) if isinstance(current_graph, dict) else {}
    graph["vertices"] = list(vertices_by_id.values())
    graph["edges"] = list(edges_by_id.values())
    graph["claims"] = list(claims_by_id.values())
    graph["sources"] = list(sources_by_id.values())
    graph["evidence"] = list(evidence_by_id.values())
    graph.setdefault("derived_relations", current_graph.get("derived_relations", []) if isinstance(current_graph, dict) else [])
    graph["updated_at"] = iso_now()
    graph.setdefault("migration", {})
    graph["migration"].update(
        {
            "status": "restored_from_snapshot_and_evidence",
            "updated_at": iso_now(),
            "admission_policy_version": 2,
            "canonical_edges_admitted": len(graph["edges"]),
            "new_counts": {
                "vertices": len(graph["vertices"]),
                "edges": len(graph["edges"]),
                "claims": len(graph["claims"]),
                "sources": len(graph["sources"]),
                "evidence": len(graph["evidence"]),
            },
        }
    )
    graph.setdefault("runtime", {})["graph_repair"] = {
        "updated_at": iso_now(),
        "snapshot_rows": len(snapshot_rows),
        "evidence_rows": len(evidence_rows),
        "restored_vertices": len(graph["vertices"]),
        "restored_edges": len(graph["edges"]),
        "restored_claims": len(graph["claims"]),
    }
    _write_json_replace(CANONICAL_GRAPH, graph)
    repaired = load_graph()
    _write_json_replace(KNOWLEDGE_GRAPH_PATH, write_knowledge_graph(repaired, output_path=KNOWLEDGE_GRAPH_PATH))
    report = {
        "ok": True,
        "updated_at": iso_now(),
        "snapshot_rows": len(snapshot_rows),
        "evidence_rows": len(evidence_rows),
        "vertices": len(repaired.get("vertices", [])),
        "edges": len(repaired.get("edges", [])),
        "claims": len(repaired.get("claims", [])),
        "sources": len(repaired.get("sources", [])),
        "evidence": len(repaired.get("evidence", [])),
        "derived_relations": len(repaired.get("derived_relations", [])),
        "rejected_vertices": rejected_vertices[:100],
        "repair_run_id": REPAIR_RUN_ID,
    }
    REPAIR_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPAIR_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    report = repair_graph_bundle()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
