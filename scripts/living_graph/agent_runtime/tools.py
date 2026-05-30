"""Logged tool wrappers for runtime workers."""

from __future__ import annotations

import sys
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from ..profiles import card_for_node
    from ..store import graph_write_path, load_graph, normalize_text, short_host, stable_hash, write_json
    from ..research_tools import PageFetcher, build_search_provider, emit_event, extract_page_text, extract_claims_from_page
    from .task_db import save_artifact, save_graph_diff, save_tool_call
except ImportError:  # pragma: no cover
    from living_graph.profiles import card_for_node
    from living_graph.store import graph_write_path, load_graph, normalize_text, short_host, stable_hash, write_json
    from living_graph.research_tools import PageFetcher, build_search_provider, emit_event, extract_page_text, extract_claims_from_page
    from living_graph.agent_runtime.task_db import save_artifact, save_graph_diff, save_tool_call

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from graph_domain import build_claim_from_relation, build_edge_from_claim, normalize_vertex  # noqa: E402
from pipeline_common import canonical_name_key, canonical_person_key, load_entity_alias_index, resolve_entity  # noqa: E402

_PAGE_FETCHER = PageFetcher()
_HASHISH_LABEL_RE = re.compile(r"^(?:[a-fA-F0-9]{8,}|[A-Z]?[a-fA-F0-9]{8,}[A-Za-z0-9]*|E[0-9A-Fa-f]{12,}[A-Za-z0-9]*)$")
_OFFICE_TITLE_HINTS = (
    "chief of staff",
    "head of staff",
    "head of the prime minister",
    "prime minister's staff",
    "prime minister staff",
    "office of",
    "staff of",
    "apparatus",
    "secretariat",
    "руководитель аппарата",
    "глава аппарата",
    "վարչապետի աշխատակազմի ղեկավար",
    "աշխատակազմի ղեկավար",
)
_PERSON_COLLECTION_HINTS = (
    "government team members",
    "team members",
    "office holders",
    "members",
    "directory",
    "roster",
    "staff report",
    "staff list",
    "staff directory",
    "official website",
    "government of the republic of armenia",
    "office of the prime minister",
    "prime minister's office",
    "government staff",
    "historical overview",
    "former prime",
    "the prime",
    "prime minister",
    "press release",
    "press releases",
    "updates",
    "overview",
    "fra prime",
    "eng",
    "հայ",
    "рус",
)


def is_office_title_like(label: str) -> bool:
    blob = normalize_text(label)
    if not blob:
        return False
    return any(token in blob for token in _OFFICE_TITLE_HINTS)


def _vertex_admission_reason(entity: dict[str, Any]) -> tuple[bool, str]:
    entity_id = str(entity.get("id") or "").strip()
    label = str(entity.get("label") or entity.get("name") or "").strip()
    category = str(entity.get("category") or "").strip()
    if not label:
        return False, "missing_label"
    if _HASHISH_LABEL_RE.fullmatch(label) or _HASHISH_LABEL_RE.fullmatch(entity_id):
        return False, "hash_like_label"
    lowered = normalize_text(label)
    if category == "person":
        if is_office_title_like(label):
            return False, "office_title_person_label"
        if any(token in lowered for token in _PERSON_COLLECTION_HINTS):
            return False, "missing_human_readable_name"
        if any(token in lowered for token in ("historical overview", "former prime", "the prime", "press release", "press releases", "updates", "fra prime")):
            return False, "missing_human_readable_name"
        if len(label.split()) < 2 or len(label.split()) > 5:
            return False, "missing_human_readable_name"
    return True, "accepted"


def fetch_url_logged(run_id: str, item_id: str, url: str) -> dict[str, Any]:
    emit_event(run_id, "source_opened", {"url": url}, stage="fetch", item_id=item_id)
    try:
        result = _PAGE_FETCHER.fetch(url)
        if result.error:
            raise RuntimeError(result.error)
    except Exception as exc:
        payload = {"url": url, "status": "failed_fetch", "error": str(exc)}
        save_tool_call(run_id, item_id, "fetch_url", {"url": url}, payload, status="failed", error=str(exc))
        save_artifact(run_id, item_id, "visited_url", payload, ref=url)
        emit_event(run_id, "source_failed", {"url": url, "error": str(exc)}, stage="fetch", item_id=item_id)
        raise RuntimeError(f"failed_fetch:{url}")
    payload = {
        "url": result.url,
        "final_url": result.final_url,
        "status_code": result.status_code,
        "content_type": result.content_type,
        "status": "visited" if result.status_code < 400 else "failed_fetch",
        "host": short_host(result.final_url),
        "body_length": len(result.body),
    }
    save_tool_call(run_id, item_id, "fetch_url", {"url": url}, payload, status="completed" if result.status_code < 400 else "failed", error=result.error)
    save_artifact(run_id, item_id, "visited_url", payload, ref=result.final_url)
    emit_event(
        run_id,
        "source_scraped",
        {
            "url": result.final_url,
            "status_code": result.status_code,
            "content_type": result.content_type,
            "body_length": len(result.body),
        },
        stage="fetch",
        item_id=item_id,
    )
    return {"body": result.body, "final_url": result.final_url, "status_code": result.status_code, "content_type": result.content_type}


def search_web_logged(run_id: str, item_id: str, query: str, *, domains: list[str] | None = None, max_results: int = 10) -> list[dict[str, Any]]:
    provider, meta = build_search_provider()
    emit_event(run_id, "search_query_started", {"query": query, "domains": domains or [], "provider": meta["provider"]}, stage="search", item_id=item_id)
    results = provider.search(query, domains=domains, max_results=max_results)
    payload = {
        "query": query,
        "provider": meta["provider"],
        "available": bool(meta["available"]),
        "domains": domains or [],
        "max_results": max_results,
        "results": [result.to_dict() for result in results],
    }
    save_tool_call(run_id, item_id, "search_web", {"query": query, "domains": domains or [], "max_results": max_results}, payload)
    save_artifact(run_id, item_id, "search_query", {"query": query, "provider": meta["provider"], "available": bool(meta["available"]), "result_count": len(results)}, ref=query)
    emit_event(
        run_id,
        "search_results_received",
        {
            "query": query,
            "provider": meta["provider"],
            "available": bool(meta["available"]),
            "result_count": len(results),
            "results": payload["results"][:10],
        },
        stage="search",
        item_id=item_id,
    )
    return [result.to_dict() for result in results]


def extract_page_logged(run_id: str, item_id: str, body: str, url: str, *, content_type: str = "") -> dict[str, Any]:
    extracted = extract_page_text(body, url, content_type=content_type)
    payload = extracted.to_dict()
    save_tool_call(run_id, item_id, "extract_page_text", {"url": url}, payload)
    emit_event(
        run_id,
        "source_text_extracted",
        {
            "url": url,
            "title": payload.get("title", ""),
            "text_chars": len(payload.get("text", "") or ""),
            "link_count": len(payload.get("links", []) or []),
        },
        stage="scrape",
        item_id=item_id,
    )
    return payload


def extract_claims_logged(run_id: str, item_id: str, *, query: str, target_name: str, source_url: str, page_text: str, page_title: str = "", source_type: str = "official", context: dict[str, Any] | None = None) -> dict[str, Any]:
    emit_event(
        run_id,
        "candidate_claim_extraction_started",
        {"query": query, "target_name": target_name, "source_url": source_url, "source_title": page_title},
        stage="extract",
        item_id=item_id,
    )
    result = extract_claims_from_page(
        query=query,
        target_name=target_name,
        source_url=source_url,
        page_text=page_text,
        page_title=page_title,
        source_type=source_type,
        context=context,
    )
    payload = result.to_dict()
    save_tool_call(run_id, item_id, "extract_claims", {"query": query, "target_name": target_name, "source_url": source_url}, payload, status="completed" if result.claims else "completed", error="")
    if result.model_meta:
        save_tool_call(run_id, item_id, "model_call", {"role": "parser", "source_url": source_url}, result.model_meta, status="completed" if result.model_meta.get("ok") else "failed", error=str(result.model_meta.get("error") or ""))
    for claim in result.claims:
        save_artifact(run_id, item_id, "extracted_claim", claim, ref=str(claim.get("relation_type") or claim.get("claim_type") or source_url))
    emit_event(
        run_id,
        "candidate_claims_extracted",
        {"source_url": source_url, "target_name": target_name, "claim_count": len(result.claims), "profile_update_count": len(result.profile_updates)},
        stage="extract",
        item_id=item_id,
    )
    return payload


def resolve_entity_logged(run_id: str, item_id: str, graph: dict[str, Any], name: str) -> dict[str, Any]:
    normalized = normalize_text(name)
    found = {}
    for entity in graph.get("entities", []) or []:
        aliases = [normalize_text(str(alias)) for alias in entity.get("aliases", []) or []]
        if normalized in {normalize_text(str(entity.get("name") or "")), *aliases}:
            found = entity
            break
    payload = {"query": name, "matched_id": found.get("id", ""), "matched_name": found.get("name", "")}
    save_tool_call(run_id, item_id, "resolve_entity", {"name": name}, payload)
    return payload


def get_entity_card(run_id: str, item_id: str, graph: dict[str, Any], entity_id: str) -> dict[str, Any]:
    card = card_for_node(graph, entity_id)
    save_tool_call(run_id, item_id, "get_entity_card", {"entity_id": entity_id}, {"found": bool(card)})
    return card


def _upsert_vertex(graph: dict[str, Any], proposed: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    vertex = normalize_vertex(proposed)
    vertices = graph.setdefault("vertices", [])
    alias_index = load_entity_alias_index(graph)
    bucket = "people" if str(vertex.get("category") or "").strip() == "person" else "orgs"
    candidate_names = [str(vertex.get("name") or ""), *[str(alias) for alias in vertex.get("aliases", []) or []]]
    existing_id = None
    for candidate in candidate_names:
        if not candidate:
            continue
        existing_id = resolve_entity(candidate, alias_index, bucket=bucket)
        if existing_id:
            break
    if existing_id:
        vertex["id"] = existing_id
    existing = next((row for row in vertices if str(row.get("id") or "") == vertex["id"]), None)
    if existing is None:
        vertices.append(vertex)
        return "added", vertex
    existing.update({k: v for k, v in vertex.items() if v not in ("", [], {}, None)})
    aliases = list(dict.fromkeys([*(existing.get("aliases", []) or []), *[alias for alias in vertex.get("aliases", []) or [] if alias], str(existing.get("name") or ""), str(vertex.get("name") or "")]))
    existing["aliases"] = [alias for alias in aliases if alias and alias != existing.get("name")]
    return "updated", existing


def _upsert_support_row(rows: list[dict[str, Any]], row: dict[str, Any]) -> dict[str, Any]:
    existing = next((item for item in rows if str(item.get("id") or "") == str(row.get("id") or "")), None)
    if existing is None:
        rows.append(row)
        return row
    existing.update(row)
    return existing


def _append_claim_and_edge(graph: dict[str, Any], claim: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], bool]:
    claims = graph.setdefault("claims", [])
    existing_claim = next((row for row in claims if str(row.get("id") or "") == claim["id"]), None)
    if existing_claim is None:
        claims.append(claim)
        claim_added = True
    else:
        existing_claim.update(claim)
        claim = existing_claim
        claim_added = False
    edge = build_edge_from_claim(claim, evidence_ids=claim.get("evidence_ids", []), source_ids=claim.get("source_ids", []))
    edges = graph.setdefault("edges", [])
    existing_edge = next((row for row in edges if str(row.get("id") or "") == edge["id"]), None)
    if existing_edge is None:
        edges.append(edge)
        edge_added = True
    else:
        existing_edge.update(edge)
        edge = existing_edge
        edge_added = False
    return claim, edge, claim_added or edge_added


def propose_graph_update(run_id: str, item_id: str, proposal: dict[str, Any]) -> dict[str, Any]:
    graph = load_graph()
    diff = {"new_node_ids": [], "updated_node_ids": [], "new_edge_ids": [], "updated_edge_ids": [], "rejected": []}
    entity_candidate = proposal.get("entity", {})
    ok, reason = _vertex_admission_reason(entity_candidate if isinstance(entity_candidate, dict) else {})
    if not ok:
        entity = entity_candidate if isinstance(entity_candidate, dict) else {}
        diff["rejected"].append({"type": "vertex", "reason": reason, "entity_id": str(entity.get("id") or ""), "label": str(entity.get("label") or entity.get("name") or "")})
        save_tool_call(run_id, item_id, "propose_graph_update", {"entity_id": str(entity.get("id") or "")}, diff)
        save_artifact(run_id, item_id, "rejected_change", {"type": "vertex", "reason": reason, "entity": entity}, ref=str(entity.get("id") or ""))
        emit_event(
            run_id,
            "graph_vertex_rejected",
            {"entity_id": str(entity.get("id") or ""), "label": str(entity.get("label") or entity.get("name") or ""), "reason": reason},
            stage="admit",
            item_id=item_id,
        )
        return diff
    source_url = str(proposal.get("source_url") or "").strip()
    evidence_quote = str(proposal.get("evidence_quote") or "").strip()
    source_id = f"source-{stable_hash(source_url or proposal['entity']['id'], proposal.get('relation_type', 'profile'))}"
    evidence_id = f"evidence-{stable_hash(source_url or proposal['entity']['id'], evidence_quote[:200])}"
    source = {
        "id": source_id,
        "url": source_url,
        "title": source_url or proposal["entity"]["name"],
        "publisher": short_host(source_url) or "official",
        "source_class": "official",
        "language": "eng",
        "reliability": 0.92,
        "updated_at": proposal["updated_at"],
    }
    evidence = {
        "id": evidence_id,
        "source_id": source_id,
        "url": source_url,
        "title": source_url or proposal["entity"]["name"],
        "publisher": short_host(source_url) or "official",
        "source_class": "official",
        "language": "eng",
        "published_at": proposal.get("valid_from") or "",
        "retrieved_at": proposal["updated_at"],
        "snippet": evidence_quote,
        "quote": evidence_quote,
        "stance": "supporting",
        "supports_claim_ids": [],
        "contradicts_claim_ids": [],
    }
    _upsert_support_row(graph.setdefault("sources", []), source)
    _upsert_support_row(graph.setdefault("evidence", []), evidence)
    action, entity = _upsert_vertex(graph, proposal["entity"])
    entity["last_changed_run_id"] = run_id
    entity["change_type"] = "new" if action == "added" else "updated"
    diff[f"{'new' if action == 'added' else 'updated'}_node_ids"].append(entity["id"])
    emit_event(
        run_id,
        "graph_vertex_created" if action == "added" else "graph_vertex_updated",
        {"entity_id": entity["id"], "name": entity.get("name") or entity.get("label") or "", "category": entity.get("category") or ""},
        stage="admit",
        item_id=item_id,
    )
    if proposal.get("profile_update"):
        entity.setdefault("profile", {}).update(proposal["profile_update"])
        entity["profile"]["last_changed_run_id"] = run_id
        entity["profile"]["change_type"] = entity["change_type"]
    for claim_input in proposal.get("claims", []):
        relation_row = {
            "id": f"rel-{stable_hash(claim_input['subject_id'], claim_input['object_id'], claim_input['predicate'], source_url)}",
            "from": claim_input["subject_id"],
            "to": claim_input["object_id"],
            "relation_type": claim_input["predicate"],
            "type": claim_input["predicate"],
            "status": claim_input.get("status", "confirmed"),
            "confidence": claim_input.get("confidence", 0.8),
            "source_url": claim_input.get("source_url", source_url),
            "source_type": "official",
            "evidence_quote": claim_input.get("evidence_quote", evidence_quote),
            "collected_at": proposal["updated_at"],
            "valid_from": claim_input.get("valid_from") or "",
            "valid_to": claim_input.get("valid_to") or "",
        }
        claim = build_claim_from_relation(relation_row, evidence_ids=[evidence_id], source_ids=[source_id])
        claim["created_by_run_id"] = run_id
        claim["last_changed_run_id"] = run_id
        evidence["supports_claim_ids"] = sorted(set(evidence.get("supports_claim_ids", [])) | {claim["id"]})
        claim, edge, added = _append_claim_and_edge(graph, claim)
        edge["last_changed_run_id"] = run_id
        edge["change_type"] = "new" if added else "updated"
        diff[f"{'new' if added else 'updated'}_edge_ids"].append(edge["id"])
        emit_event(
            run_id,
            "graph_edge_created" if added else "graph_edge_updated",
            {
                "edge_id": edge["id"],
                "source_id": edge["from"],
                "target_id": edge["to"],
                "relation_type": edge["relation_type"],
                "confidence": edge.get("confidence", 0),
            },
            stage="admit",
            item_id=item_id,
        )
    write_json(graph_write_path(), graph)
    save_graph_diff(run_id, diff)
    save_tool_call(run_id, item_id, "propose_graph_update", {"entity_id": proposal["entity"]["id"]}, diff)
    return diff
