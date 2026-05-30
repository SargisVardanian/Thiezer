"""Bounded worker implementations for durable task execution."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

try:
    from pipeline_common import append_claim_records, canonical_person_key, load_entity_alias_index, resolve_entity, write_entity_registry
    from ..store import iso_now, load_graph, normalize_text
    from .context_builder import build_work_item_context
    from .government_am import GOV_MEMBERS_URL, GOV_STAFF_STRUCTURE_URL, parse_government_members_page, parse_minister_profile_page, parse_prime_minister_staff_structure_page
    from .parliament_am import FALLBACK_PEOPLE, FACTIONS_URL, ROSTER_URL, parse_factions_page, parse_profile_page, parse_roster_page
    from ..research_tools import build_role_queries, emit_event, extract_year_range, day_windows, month_windows, should_zoom_window, year_windows
    from ..research_tools.claim_extractor import _extract_person_names as extract_person_names_from_text
    from .tools import extract_claims_logged, extract_page_logged, fetch_url_logged, get_entity_card, is_office_title_like, propose_graph_update, resolve_entity_logged, search_web_logged
    from .schemas import GraphDiff, WorkItemResult
    from .task_db import enqueue_item, increment_run_summary, latest_graph_diff, save_artifact, update_run_status
    from .validators import (
        validate_claim_has_evidence,
        validate_edge_has_claim,
        validate_no_generic_relation,
        validate_no_person_clique,
        validate_source_quality,
    )
except ImportError:  # pragma: no cover
    from pipeline_common import append_claim_records, canonical_person_key, load_entity_alias_index, resolve_entity, write_entity_registry
    from living_graph.store import iso_now, load_graph, normalize_text
    from living_graph.agent_runtime.context_builder import build_work_item_context
    from living_graph.agent_runtime.government_am import GOV_MEMBERS_URL, GOV_STAFF_STRUCTURE_URL, parse_government_members_page, parse_minister_profile_page, parse_prime_minister_staff_structure_page
    from living_graph.agent_runtime.parliament_am import FALLBACK_PEOPLE, FACTIONS_URL, ROSTER_URL, parse_factions_page, parse_profile_page, parse_roster_page
    from living_graph.research_tools import build_role_queries, emit_event, extract_year_range, day_windows, month_windows, should_zoom_window, year_windows
    from living_graph.research_tools.claim_extractor import _extract_person_names as extract_person_names_from_text
    from living_graph.agent_runtime.tools import extract_claims_logged, extract_page_logged, fetch_url_logged, get_entity_card, is_office_title_like, propose_graph_update, resolve_entity_logged, search_web_logged
    from living_graph.agent_runtime.schemas import GraphDiff, WorkItemResult
    from living_graph.agent_runtime.task_db import enqueue_item, increment_run_summary, latest_graph_diff, save_artifact, update_run_status
    from living_graph.agent_runtime.validators import (
        validate_claim_has_evidence,
        validate_edge_has_claim,
        validate_no_generic_relation,
        validate_no_person_clique,
        validate_source_quality,
    )


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "item"


def _person_id(name: str) -> str:
    canonical = canonical_person_key(name) if str(name or "").strip() else ""
    return f"person-{_slug(canonical or name)}"


def _canonical_person_display_name(graph: dict[str, Any], name: str) -> str:
    candidate = str(name or "").strip()
    if not candidate:
        return ""
    alias_index = load_entity_alias_index(graph)
    matched_id = resolve_entity(candidate, alias_index, bucket="people")
    if matched_id:
        matched = next((entity for entity in graph.get("entities", []) or [] if str(entity.get("id") or "") == str(matched_id)), None)
        if matched:
            resolved_name = str(matched.get("name") or matched.get("label") or "").strip()
            if resolved_name:
                return resolved_name
    return candidate


def _office_id(title: str) -> str:
    return f"office-{_slug(title)}"


def _org_id(prefix: str, title: str) -> str:
    return f"{prefix}-{_slug(title)}"


def _government_id() -> str:
    return _org_id("institution", "Government of Armenia")


def _record_claim_memory(run_id: str, item_id: str, claims: list[dict[str, Any]], *, stage: str, source_url: str = "") -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        enriched.append(
            {
                **claim,
                "run_id": run_id,
                "item_id": item_id,
                "stage": stage,
                "source_url": str(claim.get("source_url") or source_url or "").strip(),
                "recorded_at": iso_now(),
            }
        )
    return append_claim_records(enriched) if enriched else []


def _refresh_entity_registry_after_graph_write() -> None:
    try:
        write_entity_registry(load_graph())
    except Exception:
        pass


ROLE_HISTORY_OFFICE_ALIASES = (
    "Chief of Staff of the Prime Minister",
    "Head of the Prime Minister's Staff",
    "Prime Minister's Chief of Staff",
    "Վարչապետի աշխատակազմի ղեկավար",
    "руководитель аппарата премьер-министра",
    "глава аппарата премьер-министра",
)

ROLE_HISTORY_DOMAINS = ["primeminister.am", "gov.am", "arlis.am"]
ROLE_HISTORY_ROLE_GROUPS = (
    "Chief of Staff",
    "Deputy Chief of Staff",
    "Chief Adviser",
    "Adviser",
    "Assistant",
    "Press Secretary",
    "Chief Protocol Officer",
    "Head of Department",
    "Head of Division",
)
_ROLE_PERSON_REJECT_HINTS = (
    "minister",
    "ministry",
    "deput",
    "chief of staff",
    "head of staff",
    "speaker",
    "chair",
    "advisor",
    "assistant",
    "government",
    "office of",
    "staff of",
    "apparatus",
    "secretariat",
    "руководитель аппарата",
    "глава аппарата",
    "վարչապետի աշխատակազմի ղեկավար",
    "աշխատակազմի ղեկավար",
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


def _role_history_candidate_allowed(url: str, title: str, office_title: str) -> bool:
    parsed = urlparse(url or "")
    host = parsed.netloc.lower().lstrip("www.")
    path = parsed.path.lower()
    if not host:
        return False
    if host.endswith("primeminister.am"):
        if "login" in path or "search" in path or "sitemap" in path:
            return False
        return any(token in path for token in ("", "/en/", "/am/", "/ru/", "/press-release/", "/staff-", "/official/", "/government")) or path in {"/", "/en", "/am", "/ru"}
    if host.endswith("gov.am"):
        if "login" in path or "search" in path or "sitemap" in path:
            return False
        if "/gov-members/" in path:
            return False
        return any(token in path for token in ("/staff-structure/", "/bodies-under-prime-minister/", "/bodies-under-government/", "/deputy-pms-staff-structure/", "/official/", "/press-release/")) or path in {"/", "/en/", "/am/", "/ru/"}
    if host.endswith("arlis.am"):
        return True
    return False


def _role_history_followup_link_allowed(url: str) -> bool:
    parsed = urlparse(url or "")
    host = parsed.netloc.lower().lstrip("www.")
    path = parsed.path.lower()
    if not host:
        return False
    if host.endswith("primeminister.am"):
        return any(token in path for token in ("/press-release/item/", "/staff-", "/official/", "/prime-minister", "/government"))
    if host.endswith("gov.am"):
        return any(token in path for token in ("/gov-members/", "/staff-", "/bodies-under-prime-minister/", "/bodies-under-government/", "/deputy-pms-staff-structure/"))
    if host.endswith("arlis.am"):
        return True
    return False


def _role_history_staff_structure_url(url: str) -> bool:
    parsed = urlparse(url or "")
    host = parsed.netloc.lower().lstrip("www.")
    path = parsed.path.lower()
    return host.endswith("gov.am") and "/staff-structure/" in path


def _resolve_role_history_office(query: str) -> str:
    blob = normalize_text(query)
    if any(token in blob for token in ("chief of staff", "head of staff", "աշխատակազմի ղեկավար", "վարչապետի աշխատակազմի ղեկավար")):
        return "Chief of Staff of the Prime Minister"
    if "премьер" in blob or "prime minister" in blob:
        return "Chief of Staff of the Prime Minister"
    return "Chief of Staff of the Prime Minister"


def _role_history_search_roles(office_title: str, context: dict[str, Any]) -> list[str]:
    roles = [office_title, *ROLE_HISTORY_ROLE_GROUPS]
    for role in context.get("requested_roles", []) or []:
        value = str(role or "").strip()
        if value and value not in roles:
            roles.append(value)
    return roles


def _role_history_query_variants(query: str, office_title: str) -> list[str]:
    start_year, end_year = extract_year_range(query)
    windows = year_windows(start_year, end_year)
    variants: list[str] = []
    if query.strip():
        variants.append(query.strip())
    for window in windows:
        variants.extend(build_role_queries(target_person="Nikol Pashinyan", office_family=office_title, window=window))
    deduped: list[str] = []
    seen: set[str] = set()
    for item in variants:
        normalized = normalize_text(item)
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(item)
    return deduped[:18]


def _role_history_entity_category(name: str, relation_type: str = "") -> tuple[str, str]:
    blob = normalize_text(name)
    if any(token in blob for token in ("company", "llc", "ltd", "inc", "holding", "bank", "corp", "group", "co.", "c.j.s.c", "ojsc", "cjsc")):
        return "organization", "company"
    if relation_type == "holds_office_in" and any(token in blob for token in ("office", "staff", "apparatus", "secretariat", "office of", "staff of", "head of", "chief of")):
        return "office", "state_office"
    if any(token in blob for token in ("ministry", "government", "office", "staff", "administration", "apparatus", "committee", "agency", "service", "board", "council", "department", "secretariat", "unit", "body", "structure")):
        return "organization", "institution"
    if relation_type in {"holds_office_in", "member_of", "leads", "appointed_by"}:
        return "organization", "institution"
    return "person", "official"


def _role_history_object_allowed(name: str, relation_type: str) -> bool:
    blob = normalize_text(name)
    if not blob:
        return False
    if any(token in blob for token in _ROLE_PERSON_REJECT_HINTS):
        return False
    if is_office_title_like(name):
        return True
    allowed_object_terms = (
        "ministry",
        "government",
        "office",
        "staff",
        "administration",
        "committee",
        "agency",
        "service",
        "board",
        "council",
        "department",
        "secretariat",
        "unit",
        "body",
        "structure",
        "party",
        "company",
        "llc",
        "ltd",
        "inc",
        "group",
        "institution",
        "foundation",
        "association",
        "center",
        "media",
        "press",
        "parliament",
        "assembly",
    )
    if any(token in blob for token in allowed_object_terms):
        return True
    if _is_role_person_candidate(name):
        return True
    return False


def _discover_government_ministers(run_id: str, item: dict[str, Any]) -> WorkItemResult:
    query = str(item.get("input_json", {}).get("query") or "current government ministers Armenia official roster")
    search_results = search_web_logged(run_id, item["item_id"], query, domains=["gov.am", "primeminister.am"], max_results=5)
    roster_candidate = next((row for row in search_results if str(row.get("url") or "").startswith("https://www.gov.am/")), None)
    roster_url = str(roster_candidate.get("url") if roster_candidate else GOV_MEMBERS_URL)
    increment_run_summary(run_id, search_queries=1)
    fetch = fetch_url_logged(run_id, item["item_id"], roster_url)
    roster = parse_government_members_page(fetch["body"], fetch["final_url"])
    people = roster.get("people", [])
    source = {"url": fetch["final_url"], "source_type": "official_web", "status": "accepted_as_source", "reason": "official government team members roster"}
    ok, reason = validate_source_quality(source)
    if ok:
        save_artifact(run_id, item["item_id"], "accepted_source", source, ref=fetch["final_url"])
    else:
        save_artifact(run_id, item["item_id"], "rejected_source", {**source, "reason": reason}, ref=fetch["final_url"])
    if not people:
        update_run_status(
            run_id,
            "failed_retryable",
            current_stage="discover_government_ministers",
            summary_json={"roster_record_count": 0, "failure_reasons": ["minister roster parser returned 0 records"]},
        )
        return WorkItemResult(
            ok=False,
            status="failed_retryable",
            error="parser_returned_zero_minister_records",
            current_stage="discover_government_ministers",
        )
    for person in people:
        entity_id = _person_id(person["name"])
        enqueue_item(
            run_id,
            "fetch_minister_profile",
            f"Fetch profile for {person['name']}",
            person,
            priority=50,
            parent_item_id=item["item_id"],
            entity_id=entity_id,
        )
    enqueue_item(run_id, "build_government_relations", "Build government relations", {"source_url": fetch["final_url"]}, priority=300, parent_item_id=item["item_id"])
    enqueue_item(run_id, "rebuild_profiles", "Rebuild updated profiles", {"source_url": fetch["final_url"]}, priority=400, parent_item_id=item["item_id"])
    save_artifact(run_id, item["item_id"], "roster_records", {"count": len(people), "people": people[:12], "source_mode": "live"}, ref=fetch["final_url"])
    update_run_status(
        run_id,
        "running",
        current_stage="fetch_minister_profile",
        summary_json={"roster_record_count": len(people), "source_mode": "live", "accepted_source_hosts": ["gov.am"]},
    )
    return WorkItemResult(
        ok=True,
        status="done",
        current_stage="fetch_minister_profile",
        output={"roster_count": len(people), "source_url": fetch["final_url"]},
        graph_diff=GraphDiff(),
    )


def _discover_parliament_roster(run_id: str, item: dict[str, Any]) -> WorkItemResult:
    people: list[dict[str, Any]] = []
    source_mode = "live"
    faction_map: dict[str, dict[str, str]] = {}
    try:
        query = str(item.get("input_json", {}).get("query") or "current parliament deputies Armenia official roster")
        search_results = search_web_logged(run_id, item["item_id"], query, domains=["parliament.am"], max_results=5)
        roster_url = str(next((row.get("url") for row in search_results if str(row.get("url") or "").startswith("https://www.parliament.am/")), ROSTER_URL))
        increment_run_summary(run_id, search_queries=1)
        roster_fetch = fetch_url_logged(run_id, item["item_id"], roster_url)
        roster = parse_roster_page(roster_fetch["body"], roster_fetch["final_url"])
        people = roster.get("people", [])
        source = {"url": roster_fetch["final_url"], "source_type": "official_web", "status": "accepted_as_source", "reason": "official parliament roster"}
        ok, reason = validate_source_quality(source)
        if ok:
            save_artifact(run_id, item["item_id"], "accepted_source", source, ref=roster_fetch["final_url"])
        else:
            save_artifact(run_id, item["item_id"], "rejected_source", {**source, "reason": reason}, ref=roster_fetch["final_url"])
        try:
            faction_fetch = fetch_url_logged(run_id, item["item_id"], FACTIONS_URL)
            faction_map = parse_factions_page(faction_fetch["body"])
            save_artifact(run_id, item["item_id"], "accepted_source", {"url": faction_fetch["final_url"], "source_type": "official_web", "status": "accepted_as_source", "reason": "official faction roster"}, ref=faction_fetch["final_url"])
        except Exception as exc:
            save_artifact(run_id, item["item_id"], "rejected_source", {"url": FACTIONS_URL, "status": "failed_fetch", "reason": str(exc)}, ref=FACTIONS_URL)
    except Exception as exc:
        people = list(FALLBACK_PEOPLE)
        source_mode = "fallback"
        save_artifact(run_id, item["item_id"], "rejected_source", {"url": ROSTER_URL, "status": "failed_fetch", "reason": str(exc)}, ref=ROSTER_URL)
        save_artifact(run_id, item["item_id"], "accepted_source", {"url": ROSTER_URL, "source_type": "official_web_cached_snapshot", "status": "accepted_as_source", "reason": "fallback cached official snapshot"}, ref=ROSTER_URL)
    if not people:
        update_run_status(run_id, "failed_retryable", current_stage="discover_roster", summary_json={"roster_record_count": 0, "failure_reasons": ["roster parser returned 0 records"]})
        return WorkItemResult(ok=False, status="failed_retryable", error="roster parser returned 0 records", current_stage="discover_roster")
    for person in people:
        extras = faction_map.get(normalize_text(person.get("name", "")), {})
        if extras:
            person["faction"] = person.get("faction") or extras.get("faction", "")
            person["party"] = person.get("party") or extras.get("party", "")
        entity_id = _person_id(person["name"])
        if str(person.get("profile_url") or "").strip():
            enqueue_item(
                run_id,
                "fetch_deputy_profile",
                f"Fetch profile for {person['name']}",
                person,
                priority=50,
                parent_item_id=item["item_id"],
                entity_id=entity_id,
            )
        else:
            save_artifact(
                run_id,
                item["item_id"],
                "accepted_source",
                {
                    "url": str(person.get("source_url") or ROSTER_URL),
                    "source_type": str(person.get("source_type") or "official_web"),
                    "status": "accepted_as_source",
                    "reason": "roster record without profile URL; using roster record as profile stub",
                },
                ref=str(person.get("source_url") or ROSTER_URL),
            )
            enqueue_item(
                run_id,
                "extract_deputy_claims",
                f"Extract claims for {person['name']}",
                {**person, "profile_url": "", "profile_text": "", "page_title": str(person.get("role") or ""), "query": item.get("input_json", {}).get("query") or "deputy roster stub extraction"},
                priority=45,
                parent_item_id=item["item_id"],
                entity_id=entity_id,
            )
    enqueue_item(run_id, "build_deputy_relations", "Build derived deputy relations", {"source_mode": source_mode}, priority=300, parent_item_id=item["item_id"])
    enqueue_item(run_id, "rebuild_profiles", "Rebuild updated profiles", {"source_mode": source_mode}, priority=400, parent_item_id=item["item_id"])
    save_artifact(run_id, item["item_id"], "roster_records", {"count": len(people), "people": people[:10], "source_mode": source_mode}, ref=ROSTER_URL)
    update_run_status(run_id, "running", current_stage="create_deputy_items", summary_json={"roster_record_count": len(people), "source_mode": source_mode})
    return WorkItemResult(
        ok=True,
        status="done",
        current_stage="create_deputy_items",
        output={"roster_count": len(people), "source_mode": source_mode},
        artifacts=[],
        graph_diff=GraphDiff(),
    )


def _discover_role_history(run_id: str, item: dict[str, Any]) -> WorkItemResult:
    payload = dict(item.get("input_json", {}))
    query = str(payload.get("query") or "role history Armenia official sources")
    office_title = _resolve_role_history_office(query)
    start_year, end_year = extract_year_range(query)
    start_year = int(payload.get("start_year") or start_year or 2018)
    end_year = int(payload.get("end_year") or end_year or start_year)
    years_per_item = max(1, int(payload.get("years_per_item") or 2))
    window_start_year = max(start_year, int(payload.get("window_start_year") or start_year))
    window_end_year = min(end_year, window_start_year + years_per_item - 1)
    year_plan = year_windows(window_start_year, window_end_year)
    role_plan = _role_history_search_roles(office_title, payload)
    queries = _role_history_query_variants(query, office_title)
    target_person = str(payload.get("context_person") or "Nikol Pashinyan").strip()
    max_candidates = int(payload.get("max_candidates") or 8)
    fetch_threshold = max(1, int(payload.get("fetch_threshold") or 3))
    emit_event(
        run_id,
        "temporal_plan_built",
        {
            "start_year": start_year,
            "end_year": end_year,
            "windows": [window.label() for window in year_plan],
            "office_title": office_title,
            "roles": role_plan,
        },
        stage="search",
        item_id=item["item_id"],
    )
    save_artifact(
        run_id,
        item["item_id"],
        "temporal_plan",
        {
            "start_year": start_year,
            "end_year": end_year,
            "windows": [window.label() for window in year_plan],
            "office_title": office_title,
            "roles": role_plan,
        },
        ref=office_title,
    )
    remaining_start_year = window_end_year + 1
    candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    zoomed_windows: set[str] = set()
    checked_years: list[int] = []
    checked_roles: list[str] = []
    checked_hosts: list[str] = []
    for window in year_plan:
        checked_years.append(window.start.year)
        window_candidates_before = len(candidates)
        for role in role_plan:
            checked_roles.append(role)
            role_queries = build_role_queries(target_person=target_person, office_family=role, window=window)
            if len(candidates) < 4:
                role_queries.extend(
                    [
                        f'site:primeminister.am "{role}" "{target_person}" {window.start.year}',
                        f'site:gov.am "{role}" "{target_person}" {window.start.year}',
                        f'site:arlis.am "{role}" "{target_person}" {window.start.year}',
                    ]
                )
            for search_query in role_queries[:6]:
                results = search_web_logged(run_id, item["item_id"], search_query, domains=ROLE_HISTORY_DOMAINS, max_results=10)
                increment_run_summary(run_id, search_queries=1)
                emit_event(
                    run_id,
                    "search_results_received",
                    {"query": search_query, "window": window.label(), "role": role, "result_count": len(results)},
                    stage="search",
                    item_id=item["item_id"],
                )
                for result in results:
                    url = str(result.get("url") or "").strip()
                    title = str(result.get("title") or "").strip()
                    host = urlparse(url or "").netloc.lower().lstrip("www.")
                    if not url or url in seen_urls:
                        continue
                    if not _role_history_candidate_allowed(url, title, office_title):
                        continue
                    seen_urls.add(url)
                    if host:
                        checked_hosts.append(host)
                    candidates.append(
                        {
                            "url": url,
                            "title": title,
                            "snippet": str(result.get("snippet") or "").strip(),
                            "source": str(result.get("source") or "deterministic_official").strip(),
                            "window": window.label(),
                            "role": role,
                        }
                    )
                    emit_event(
                        run_id,
                        "candidate_entity_found",
                        {"url": url, "title": title, "window": window.label(), "role": role, "source": str(result.get("source") or "deterministic_official").strip()},
                        stage="search",
                        item_id=item["item_id"],
                    )
                    if len(candidates) >= max_candidates or len(candidates) >= fetch_threshold:
                        break
                if len(candidates) >= max_candidates or len(candidates) >= fetch_threshold:
                    break
            if len(candidates) >= max_candidates or len(candidates) >= fetch_threshold:
                break
        if len(candidates) > window_candidates_before and should_zoom_window(window, source_count=len(candidates), claim_count=0):
            zoomed_windows.add(window.label())
            for month_window in month_windows(window.start.year):
                month_queries = build_role_queries(target_person=target_person, office_family=office_title, window=month_window)
                for search_query in month_queries[:4]:
                    results = search_web_logged(run_id, item["item_id"], search_query, domains=ROLE_HISTORY_DOMAINS, max_results=8)
                    increment_run_summary(run_id, search_queries=1)
                    for result in results:
                        url = str(result.get("url") or "").strip()
                        title = str(result.get("title") or "").strip()
                        host = urlparse(url or "").netloc.lower().lstrip("www.")
                        if not url or url in seen_urls:
                            continue
                        if not _role_history_candidate_allowed(url, title, office_title):
                            continue
                        seen_urls.add(url)
                        if host:
                            checked_hosts.append(host)
                        candidates.append(
                            {
                                "url": url,
                                "title": title,
                                "snippet": str(result.get("snippet") or "").strip(),
                                "source": str(result.get("source") or "deterministic_official").strip(),
                                "window": month_window.label(),
                                "role": role,
                            }
                        )
                        emit_event(
                            run_id,
                            "followup_search_scheduled",
                            {"url": url, "title": title, "window": month_window.label(), "role": role, "reason": "zoom_month"},
                            stage="search",
                            item_id=item["item_id"],
                        )
                        if len(candidates) >= max_candidates or len(candidates) >= fetch_threshold:
                            break
                    if len(candidates) >= max_candidates or len(candidates) >= fetch_threshold:
                        break
                if len(candidates) >= max_candidates or len(candidates) >= fetch_threshold:
                    break
            if len(candidates) >= max_candidates or len(candidates) >= fetch_threshold:
                break
        if len(candidates) >= max_candidates:
            break
        if len(candidates) > 0 and window.start.year >= window_end_year:
            break
    if not candidates:
        update_run_status(
            run_id,
            "failed_retryable",
            current_stage="resolve_target_office",
            summary_json={"role_history_record_count": 0, "failure_reasons": ["role history search returned 0 candidates"]},
        )
        return WorkItemResult(ok=False, status="failed_retryable", error="role_history_search_returned_zero_candidates", current_stage="resolve_target_office")
    coverage_report = {
        "years_checked": sorted(set(checked_years)),
        "roles_checked": sorted(set(checked_roles)),
        "sources_checked": sorted(set(checked_hosts)),
        "confirmed_claims": 0,
        "rejected_claims": 0,
        "unresolved_candidates": len(candidates),
    }
    save_artifact(run_id, item["item_id"], "search_plan", {"office_title": office_title, "queries": queries, "candidate_count": len(candidates), "coverage": coverage_report}, ref=office_title)
    save_artifact(run_id, item["item_id"], "search_results", {"office_title": office_title, "candidates": candidates[:24], "zoomed_windows": sorted(zoomed_windows), "coverage": coverage_report}, ref=office_title)
    save_artifact(run_id, item["item_id"], "coverage_report", coverage_report, ref=office_title)
    for candidate in candidates[:12]:
        enqueue_item(
            run_id,
            "fetch_role_history_profile",
            candidate["title"] or candidate["url"],
            {
                "query": query,
                "office_title": office_title,
                "source_url": candidate["url"],
                "source_title": candidate["title"],
                "source_snippet": candidate["snippet"],
                "candidate_name": candidate.get("title") or "",
                "coverage": coverage_report,
            },
            priority=45,
            parent_item_id=item["item_id"],
            entity_id="",
        )
    if remaining_start_year <= end_year:
        enqueue_item(
            run_id,
            "discover_role_history",
            f"Continue role history discovery from {remaining_start_year}",
            {
                "query": query,
                "start_year": remaining_start_year,
                "end_year": end_year,
                "years_per_item": years_per_item,
                "max_candidates": max_candidates,
                "context_person": target_person,
            },
            priority=120,
            parent_item_id=item["item_id"],
        )
    enqueue_item(run_id, "extract_associations", f"Extract associations for {office_title}", {"office_title": office_title, "coverage": coverage_report}, priority=350, parent_item_id=item["item_id"])
    enqueue_item(run_id, "rebuild_profiles", "Rebuild updated profiles", {"source_mode": "role_history", "coverage": coverage_report}, priority=400, parent_item_id=item["item_id"])
    update_run_status(run_id, "running", current_stage="fetch_candidate_pages", summary_json={"role_history_record_count": len(candidates), "resolved_office": office_title, "source_mode": "live", "temporal_windows": [window.label() for window in year_plan], "zoomed_windows": sorted(zoomed_windows), "coverage": coverage_report, "years_checked": coverage_report["years_checked"], "roles_checked": coverage_report["roles_checked"], "sources_checked": coverage_report["sources_checked"]})
    return WorkItemResult(ok=True, status="done", current_stage="fetch_candidate_pages", output={"candidate_count": len(candidates), "office_title": office_title}, graph_diff=GraphDiff())


def _fetch_role_history_profile(run_id: str, item: dict[str, Any]) -> WorkItemResult:
    payload = dict(item.get("input_json", {}))
    profile_url = str(payload.get("source_url") or "").strip()
    office_title = str(payload.get("office_title") or _resolve_role_history_office(str(payload.get("query") or ""))).strip()
    query = str(payload.get("query") or "role history extraction")
    if not profile_url:
        save_artifact(run_id, item["item_id"], "rejected_source", {"url": "", "status": "missing_profile_url", "reason": "role history candidate has no source URL"}, ref=item.get("title") or "role_history")
        return WorkItemResult(ok=False, status="failed_retryable", error="missing_profile_url", current_stage="fetch_candidate_pages")
    fetch = fetch_url_logged(run_id, item["item_id"], profile_url)
    coverage = dict(payload.get("coverage") or {})
    source_record = {
        "title": str(payload.get("source_title") or item.get("title") or office_title or fetch["final_url"]).strip(),
        "url": fetch["final_url"],
        "source_type": "official_web",
        "status": "accepted_as_source",
        "reason": "official role-history candidate source",
    }
    ok, reason = validate_source_quality(source_record)
    if ok:
        save_artifact(run_id, item["item_id"], "accepted_source", source_record, ref=fetch["final_url"])
    else:
        save_artifact(run_id, item["item_id"], "rejected_source", {**source_record, "reason": reason}, ref=fetch["final_url"])
    increment_run_summary(run_id, profile_pages_fetched=1)
    page = extract_page_logged(run_id, item["item_id"], fetch["body"], fetch["final_url"], content_type=str(fetch.get("content_type") or ""))
    save_artifact(run_id, item["item_id"], "profile_page_raw", {"url": fetch["final_url"], "title": page.get("title", ""), "text": page.get("text", "")[:24000], "office_title": office_title}, ref=fetch["final_url"])
    if _role_history_staff_structure_url(fetch["final_url"]):
        structure = parse_prime_minister_staff_structure_page(fetch["body"], fetch["final_url"])
        staff_people = structure.get("people", []) or []
        if staff_people:
            save_artifact(run_id, item["item_id"], "staff_structure_roster", {"url": fetch["final_url"], "people": staff_people[:30]}, ref=fetch["final_url"])
            roster_claim_count = 0
            for person in staff_people[:20]:
                name = str(person.get("name") or "").strip()
                role_title = str(person.get("title") or person.get("position") or office_title or "").strip()
                department_name = str(person.get("department_name") or "").strip()
                object_name = department_name or (office_title if role_title.lower() == "chief of staff" and office_title else role_title)
                if not name or not object_name or not _is_role_person_candidate(name):
                    continue
                resolved_name = _canonical_person_display_name(load_graph(), name)
                subject_name = resolved_name or name
                subject_id = _person_id(subject_name)
                object_category, object_subtype = _role_history_entity_category(object_name, "holds_office_in")
                if object_category == "office":
                    object_id = _office_id(object_name)
                else:
                    object_id = _org_id(object_subtype if object_subtype != "official" else "organization", object_name)
                evidence_quote = f"{department_name}. Head: {name}" if department_name else f"{name} — {role_title}"
                claim = {
                    "subject_id": subject_id,
                    "predicate": "holds_office_in",
                    "object_id": object_id,
                    "source_url": fetch["final_url"],
                    "evidence_quote": evidence_quote,
                    "confidence": 0.96,
                    "status": "confirmed",
                    "valid_from": "",
                    "valid_to": "",
                }
                emit_event(
                    run_id,
                    "candidate_claim_accepted",
                    {"subject_name": subject_name, "object_name": object_name, "relation_type": "holds_office_in", "source_url": fetch["final_url"]},
                    stage="admit",
                    item_id=item["item_id"],
                )
                role_entity = {
                    "id": object_id,
                    "label": object_name,
                    "name": object_name,
                    "category": object_category,
                    "subtype": object_subtype,
                    "summary": f"Official role or structure listed on the Prime Minister's staff page.",
                }
                role_vertex_diff = propose_graph_update(
                    run_id,
                    item["item_id"],
                    {
                        "entity": role_entity,
                        "claims": [],
                        "profile_update": {},
                        "source_url": fetch["final_url"],
                        "evidence_quote": evidence_quote,
                        "updated_at": iso_now(),
                    },
                )
                person_entity = {
                    "id": subject_id,
                    "label": subject_name,
                    "name": subject_name,
                    "category": "person",
                    "subtype": "official",
                    "summary": f"Official staff member of the Prime Minister's office.",
                    "links": {"official_profile": str(person.get("profile_url") or fetch["final_url"])},
                }
                role_entity = {
                    "id": object_id,
                    "label": object_name,
                    "name": object_name,
                    "category": object_category,
                    "subtype": object_subtype,
                    "summary": f"Official role or structure listed on the Prime Minister's staff page.",
                }
                proposal_diff = propose_graph_update(
                    run_id,
                    item["item_id"],
                    {
                        "entity": person_entity,
                        "claims": [claim],
                        "profile_update": {
                            "overview": f"{subject_name} serves in the Prime Minister's office.",
                            "current_roles_or_functions": [object_name],
                            "timeline": [{"date": "current", "title": object_name}],
                            "source_links": [{"title": str(person.get("section_title") or role_title or "Prime Minister staff page"), "url": str(person.get("profile_url") or fetch["final_url"]), "source_type": "official"}],
                        },
                        "source_url": fetch["final_url"],
                        "evidence_quote": evidence_quote,
                        "updated_at": iso_now(),
                    },
                )
                recorded_claims = _record_claim_memory(run_id, item["item_id"], [claim], stage="staff_structure_roster", source_url=fetch["final_url"])
                _refresh_entity_registry_after_graph_write()
                roster_claim_count += 1
                increment_run_summary(run_id, role_history_office_holder_claims=1, claims_logged=len(recorded_claims))
                save_artifact(
                    run_id,
                    item["item_id"],
                    "accepted_change",
                    {
                        "entity_name": subject_name,
                        "role_name": object_name,
                        "role_graph_diff": role_vertex_diff,
                        "graph_diff": proposal_diff,
                        "source_url": fetch["final_url"],
                    },
                    ref=subject_id,
                )
                update_run_status(
                    run_id,
                    "running",
                    current_stage="fetch_candidate_pages",
                    summary_json={
                        "current_entity_name": subject_name,
                        "current_entity_id": subject_id,
                        "current_source_title": str(person.get("section_title") or role_title or "Prime Minister staff page").strip(),
                        "current_source_url": fetch["final_url"],
                        "role_history_office_holder_claims": roster_claim_count + 1,
                    },
                )
                profile_url = str(person.get("profile_url") or "").strip()
                if not profile_url:
                    continue
                enqueue_item(
                    run_id,
                    "fetch_role_history_profile",
                    f"Follow staff page {person.get('name')}",
                    {
                        "query": query,
                        "office_title": str(person.get("title") or office_title or "").strip(),
                        "source_url": profile_url,
                        "source_title": str(person.get("name") or person.get("title") or "").strip(),
                        "source_snippet": str(person.get("section_title") or "Prime Minister staff structure").strip(),
                        "candidate_name": str(person.get("name") or "").strip(),
                        "coverage": coverage,
                    },
                    priority=50,
                    parent_item_id=item["item_id"],
                    entity_id="",
                )
            if roster_claim_count:
                increment_run_summary(run_id, claims_extracted=roster_claim_count, graph_updates=roster_claim_count)
                update_run_status(
                    run_id,
                    "running",
                    current_stage="fetch_candidate_pages",
                    summary_json={
                        "current_entity_name": str(staff_people[0].get("name") or office_title or "role history candidate").strip(),
                        "current_source_title": str(page.get("title") or fetch["final_url"]).strip(),
                        "current_source_url": fetch["final_url"],
                        "role_history_office_holder_claims": roster_claim_count,
                    },
                )
            return WorkItemResult(ok=True, status="done", current_stage="fetch_candidate_pages", output={"profile_url": fetch["final_url"], "staff_count": len(staff_people)}, graph_diff=GraphDiff())
    seen_followups: set[str] = set()
    for link in (page.get("links", []) or [])[:24]:
        link_url = str(link or "").strip()
        if not link_url or not _role_history_followup_link_allowed(link_url):
            continue
        normalized_link = link_url.rstrip("/")
        normalized_current = profile_url.rstrip("/")
        if normalized_link == normalized_current or normalized_link in seen_followups:
            continue
        seen_followups.add(normalized_link)
        enqueue_item(
            run_id,
            "fetch_role_history_profile",
            f"Follow role-history link {link_url}",
            {
                "query": query,
                "office_title": office_title,
                "source_url": link_url,
                "source_title": str(page.get("title") or item.get("title") or office_title or "").strip(),
                "source_snippet": "linked from official office page",
                "candidate_name": str(page.get("title") or office_title or "").strip(),
                "coverage": coverage,
            },
            priority=55,
            parent_item_id=item["item_id"],
            entity_id="",
        )
    enqueue_item(
        run_id,
        "extract_role_history_claims",
        f"Extract claims for {candidate_label(payload, office_title)}",
        {
            **payload,
            "candidate_name": candidate_label(payload, office_title),
            "profile_url": fetch["final_url"],
            "profile_text": page.get("text", "")[:24000],
            "page_title": page.get("title", ""),
            "office_title": office_title,
        },
        priority=40,
        parent_item_id=item["item_id"],
        entity_id="",
    )
    update_run_status(run_id, "running", current_stage=f"extract_role_tenure_claims: {candidate_label(payload, office_title)}")
    return WorkItemResult(ok=True, status="done", current_stage="extract_role_tenure_claims", output={"profile_url": fetch["final_url"]}, graph_diff=GraphDiff())


def candidate_label(payload: dict[str, Any], office_title: str) -> str:
    candidate_name = str(payload.get("candidate_name") or "").strip()
    if candidate_name and _is_role_person_candidate(candidate_name):
        return candidate_name
    source_title = str(payload.get("source_title") or "").strip()
    if source_title and _is_role_person_candidate(source_title):
        return source_title
    source_snippet = str(payload.get("source_snippet") or "").strip()
    if source_snippet and _is_role_person_candidate(source_snippet):
        return source_snippet
    return "role history candidate"


def _is_role_person_candidate(label: str) -> bool:
    blob = normalize_text(label)
    if not blob:
        return False
    if is_office_title_like(blob):
        return False
    if any(token in blob for token in ("historical overview", "former prime", "the prime", "press release", "press releases", "updates", "prime minister", "fra prime")):
        return False
    if any(token in blob for token in _ROLE_PERSON_REJECT_HINTS):
        return False
    if len(blob.split()) > 4:
        return False
    if any(token in blob for token in ("government team members", "team members", "office holders", "staff report", "staff list", "directory", "roster", "official website")):
        return False
    return bool(re.search(r"[A-Za-zԱ-Ֆա-ֆև]", blob))


def _normalize_role_history_relation(relation_type: str, object_category: str) -> str:
    relation = str(relation_type or "").strip()
    if relation in {"holds_office_in", "member_of", "part_of", "leads", "board_member_of", "appointed_by", "removed_from", "licensed_by", "implemented_by"}:
        return relation
    if object_category in {"organization", "institution", "company"}:
        return "member_of"
    return "holds_office_in"


def _extract_role_history_claims(run_id: str, item: dict[str, Any]) -> WorkItemResult:
    graph = load_graph()
    payload = dict(item.get("input_json", {}))
    profile_url = str(payload.get("profile_url") or "").strip()
    office_title = str(payload.get("office_title") or _resolve_role_history_office(str(payload.get("query") or ""))).strip()
    profile_text = str(payload.get("profile_text") or "")
    coverage = dict(payload.get("coverage") or {})
    context = build_work_item_context(graph, item, [{"url": profile_url, "text": profile_text[:8000]}] if profile_text else [])
    get_entity_card(run_id, item["item_id"], graph, item.get("entity_id") or "")
    extract_entity_name = candidate_label(payload, office_title)
    source_person_candidates = {
        canonical_person_key(name)
        for name in extract_person_names_from_text(profile_text, str(payload.get("page_title") or ""))
        if canonical_person_key(name)
    }
    emit_event(
        run_id,
        "candidate_claim_extraction_started",
        {"entity_name": extract_entity_name, "source_url": profile_url, "source_title": str(payload.get("source_title") or "")},
        stage="extract",
        item_id=item["item_id"],
    )
    model_result = extract_claims_logged(
        run_id,
        item["item_id"],
        query=str(payload.get("query") or "role history extraction"),
        target_name=extract_entity_name,
        source_url=profile_url or payload.get("source_url", ""),
        page_text=profile_text or "",
        page_title=str(payload.get("page_title") or ""),
        source_type="official_web",
        context=context,
    )
    claims: list[dict[str, Any]] = []
    entity_nodes: dict[str, dict[str, Any]] = {}
    profile_update = {
        "overview": f"Official role-history candidate tied to {office_title}.",
        "biography_or_history": [],
        "current_roles_or_functions": [office_title] if office_title else [],
        "timeline": [{"date": "current", "title": office_title}] if office_title else [],
        "source_links": [{"title": str(payload.get("source_title") or office_title or "Official source"), "url": profile_url, "source_type": "official"}] if profile_url else [],
    }
    for model_profile in model_result.get("profile_updates", []) or []:
        if not isinstance(model_profile, dict):
            continue
        if str(model_profile.get("overview") or "").strip():
            profile_update["overview"] = str(model_profile.get("overview")).strip()
        if isinstance(model_profile.get("biography_or_history"), list) and model_profile.get("biography_or_history"):
            profile_update["biography_or_history"] = [str(item).strip() for item in model_profile.get("biography_or_history", []) if str(item).strip()][:6]
        if isinstance(model_profile.get("current_roles_or_functions"), list) and model_profile.get("current_roles_or_functions"):
            profile_update["current_roles_or_functions"] = [str(item).strip() for item in model_profile.get("current_roles_or_functions", []) if str(item).strip()][:6]
        if isinstance(model_profile.get("timeline_items"), list) and model_profile.get("timeline_items"):
            profile_update["timeline"] = list(model_profile.get("timeline_items", []))[:6]

    valid_claim_count = 0
    for claim in model_result.get("claims", []) or []:
        if not isinstance(claim, dict):
            continue
        subject_name = str(claim.get("subject_name") or payload.get("candidate_name") or payload.get("page_title") or "").strip()
        object_name = str(claim.get("object_name") or claim.get("object_id_hint") or payload.get("office_title") or "").strip()
        relation_type = _normalize_role_history_relation(str(claim.get("relation_type") or claim.get("claim_type") or "holds_office_in"), _role_history_entity_category(object_name, str(claim.get("relation_type") or ""))[0])
        if not subject_name or is_office_title_like(subject_name) or not _is_role_person_candidate(subject_name):
            emit_event(
                run_id,
                "candidate_claim_rejected",
                {"reason": "office_title_as_person", "claim": claim, "source_url": profile_url},
                stage="admit",
                item_id=item["item_id"],
            )
            continue
        subject_key = canonical_person_key(subject_name)
        if source_person_candidates and subject_key not in source_person_candidates:
            emit_event(
                run_id,
                "candidate_claim_rejected",
                {"reason": "subject_not_supported_by_page_text", "claim": claim, "source_url": profile_url},
                stage="admit",
                item_id=item["item_id"],
            )
            continue
        resolved_subject_name = _canonical_person_display_name(graph, subject_name)
        if resolved_subject_name:
            subject_name = resolved_subject_name
        subject_id = _person_id(subject_name)
        if not _role_history_object_allowed(object_name or office_title, relation_type):
            emit_event(
                run_id,
                "candidate_claim_rejected",
                {"reason": "object_not_supported_by_page_text", "claim": claim, "source_url": profile_url},
                stage="admit",
                item_id=item["item_id"],
            )
            continue
        object_category, object_subtype = _role_history_entity_category(object_name, relation_type)
        if object_name:
            if object_category == "office":
                object_id = _office_id(object_name)
            else:
                object_id = _org_id(object_subtype if object_subtype != "official" else "organization", object_name)
        else:
            object_id = _office_id(office_title)
        if not subject_name or not object_name:
            emit_event(
                run_id,
                "candidate_claim_rejected",
                {"reason": "missing_subject_or_object", "claim": claim, "source_url": profile_url},
                stage="admit",
                item_id=item["item_id"],
            )
            continue
        normalized_claim = {
            "subject_id": subject_id,
            "predicate": relation_type,
            "object_id": object_id,
            "source_url": str(claim.get("source_url") or profile_url or payload.get("source_url") or "").strip(),
            "evidence_quote": str(claim.get("evidence_quote") or profile_text[:240] or "").strip(),
            "confidence": float(claim.get("confidence", 0.75) or 0.75),
            "status": str(claim.get("status") or "confirmed").strip() or "confirmed",
            "valid_from": str(claim.get("date_from") or payload.get("date_from") or "").strip(),
            "valid_to": str(claim.get("date_to") or payload.get("date_to") or "").strip(),
        }
        claims.append(normalized_claim)
        valid_claim_count += 1
        coverage["confirmed_claims"] = int(coverage.get("confirmed_claims", 0) or 0) + 1
        entity_nodes[subject_id] = {
            "id": subject_id,
            "label": subject_name,
            "name": subject_name,
            "category": "person",
            "subtype": "official",
            "summary": profile_update["overview"] or f"Public official associated with {office_title}.",
            "links": {"official_profile": profile_url} if profile_url else {},
        }
        entity_nodes[object_id] = {
            "id": object_id,
            "label": object_name,
            "name": object_name,
            "category": object_category,
            "subtype": object_subtype,
            "summary": f"Official structure related to {office_title}.",
        }
        emit_event(
            run_id,
            "candidate_claim_accepted",
            {"subject_name": subject_name, "object_name": object_name, "relation_type": relation_type, "source_url": normalized_claim["source_url"]},
            stage="admit",
            item_id=item["item_id"],
        )

    if not claims:
        save_artifact(run_id, item["item_id"], "rejected_change", {"type": "claims", "reason": "no_role_history_claims", "source_url": profile_url}, ref=profile_url)
        increment_run_summary(run_id, rejected_sources=1)
        update_run_status(
            run_id,
            "running",
            current_stage=f"extract_role_tenure_claims: {office_title or extract_entity_name}",
            summary_json={
                "last_active_stage": "extract_role_tenure_claims",
                "current_entity_name": extract_entity_name,
                "current_source_title": str(payload.get('source_title') or office_title or 'role history candidate').strip(),
                "current_source_url": profile_url,
                "failure_reasons": ["no_role_history_claims"],
                "coverage": dict(payload.get("coverage") or {}),
            },
        )
        return WorkItemResult(ok=True, status="done", current_stage="extract_role_tenure_claims", output={"claims_extracted": 0, "warning": "no_role_history_claims", "source_url": profile_url}, graph_diff=GraphDiff())

    for claim in claims:
        ok, reason = validate_claim_has_evidence(claim)
        if not ok:
            save_artifact(run_id, item["item_id"], "rejected_change", {"type": "claim", "reason": reason, "claim": claim}, ref=claim["predicate"])
            return WorkItemResult(ok=False, status="failed", error=reason, current_stage="extract_role_tenure_claims")

    recorded_claims = _record_claim_memory(run_id, item["item_id"], claims, stage="extract_role_tenure_claims", source_url=profile_url)
    for claim in claims:
        save_artifact(run_id, item["item_id"], "extracted_claim", claim, ref=claim["predicate"])

    diff = GraphDiff()
    base_source_url = profile_url or payload.get("source_url", "")
    base_evidence = str(profile_text[:240] or office_title).strip()
    person_id = claims[0]["subject_id"]
    person_proposal = {
        "entity": entity_nodes[person_id],
        "claims": claims,
        "profile_update": profile_update,
        "source_url": base_source_url,
        "evidence_quote": base_evidence,
        "updated_at": iso_now(),
    }
    proposal_diff = propose_graph_update(run_id, item["item_id"], person_proposal)
    diff.new_node_ids.extend(proposal_diff.get("new_node_ids", []))
    diff.updated_node_ids.extend(proposal_diff.get("updated_node_ids", []))
    diff.new_edge_ids.extend(proposal_diff.get("new_edge_ids", []))
    diff.updated_edge_ids.extend(proposal_diff.get("updated_edge_ids", []))
    if valid_claim_count and (proposal_diff.get("new_node_ids") or proposal_diff.get("updated_node_ids") or proposal_diff.get("new_edge_ids") or proposal_diff.get("updated_edge_ids")):
        increment_run_summary(run_id, role_history_office_holder_claims=valid_claim_count)
    for node_id, entity in entity_nodes.items():
        if node_id == person_id:
            continue
        entity_diff = propose_graph_update(
            run_id,
            item["item_id"],
            {
                "entity": entity,
                "claims": [],
                "profile_update": {},
                "source_url": base_source_url,
                "evidence_quote": base_evidence,
                "updated_at": iso_now(),
            },
        )
        diff.new_node_ids.extend(entity_diff.get("new_node_ids", []))
        diff.updated_node_ids.extend(entity_diff.get("updated_node_ids", []))

    _refresh_entity_registry_after_graph_write()
    coverage = dict(payload.get("coverage") or {})
    coverage["confirmed_claims"] = int(coverage.get("confirmed_claims", 0) or 0)
    increment_run_summary(run_id, claims_extracted=len(claims), claims_logged=len(recorded_claims), graph_updates=len(diff.new_node_ids) + len(diff.updated_node_ids) + len(diff.new_edge_ids) + len(diff.updated_edge_ids), coverage=coverage)
    save_artifact(run_id, item["item_id"], "accepted_change", {"entity_id": person_id, "entity_name": entity_nodes[person_id]["name"], "graph_diff": diff.to_dict(), "coverage": coverage}, ref=person_id)
    update_run_status(
        run_id,
        "running",
        current_stage=f"resolve_person_entities: {entity_nodes[person_id]['name']}",
        summary_json={
            "current_entity_name": entity_nodes[person_id]["name"],
            "current_entity_id": person_id,
            "current_source_title": str(payload.get("source_title") or office_title or "role history candidate").strip(),
            "current_source_url": profile_url,
            "current_extracted_quote": claims[0].get("evidence_quote", "") if claims else "",
            "current_extracted_claim": claims[0].get("statement", "") if claims else "",
            "coverage": coverage,
            "last_active_stage": "resolve_person_entities",
        },
    )
    return WorkItemResult(ok=True, status="done", current_stage="resolve_person_entities", output={"entity_id": person_id, "entity_name": entity_nodes[person_id]["name"], "claims_extracted": len(claims), "coverage": coverage}, graph_diff=diff)


def _extract_associations(run_id: str, item: dict[str, Any]) -> WorkItemResult:
    graph = load_graph()
    group_members: dict[str, list[str]] = {}
    for relation in graph.get("relations", []) or []:
        if not isinstance(relation, dict):
            continue
        relation_type = str(relation.get("relation_type") or relation.get("type") or "")
        if relation_type not in {"holds_office_in", "member_of", "board_member_of", "part_of"}:
            continue
        source = str(relation.get("from") or "")
        target = str(relation.get("to") or "")
        if source.startswith("person-") and target:
            group_members.setdefault(target, []).append(source)
    derived: list[dict[str, Any]] = []
    for target_id, members in group_members.items():
        members = sorted(set(members))
        for index, left in enumerate(members):
            for right in members[index + 1 :]:
                derived.append(
                    {
                        "id": f"derived-{_slug(left)}-{_slug(right)}-{_slug(target_id)}",
                        "from": left,
                        "to": right,
                        "relation_type": "aligned_with",
                        "relation_class": "political_alignment",
                        "semantic_summary": "Derived relation: shared office, structure, or affiliation in the role-history graph.",
                        "basis_paths": [[left, target_id, right]],
                        "basis_edge_ids": [],
                        "confidence": 0.66,
                        "canonical": False,
                        "edge_kind": "derived",
                        "status": "derived",
                        "last_changed_run_id": run_id,
                        "change_type": "updated",
                    }
                )
    graph["derived_relations"] = [*list(graph.get("derived_relations", []) or []), *derived][:800]
    from pipeline_common import canonical_graph_path, write_json
    write_json(canonical_graph_path(), graph)
    save_artifact(run_id, item["item_id"], "accepted_change", {"derived_relations": len(derived)}, ref="role_history_associations")
    update_run_status(run_id, "running", current_stage="extract_associations", summary_json={"derived_relations": len(derived)})
    return WorkItemResult(ok=True, status="done", current_stage="extract_associations", output={"derived_relation_count": len(derived)}, graph_diff=GraphDiff())


def _fetch_deputy_profile(run_id: str, item: dict[str, Any]) -> WorkItemResult:
    payload = dict(item.get("input_json", {}))
    profile_url = str(payload.get("profile_url") or "").strip()
    if profile_url:
        fetch = fetch_url_logged(run_id, item["item_id"], profile_url)
        save_artifact(run_id, item["item_id"], "accepted_source", {"url": fetch["final_url"], "source_type": "official_web", "status": "accepted_as_source", "reason": "official deputy profile"}, ref=fetch["final_url"])
        increment_run_summary(run_id, profile_pages_fetched=1)
        page = extract_page_logged(run_id, item["item_id"], fetch["body"], fetch["final_url"], content_type=str(fetch.get("content_type") or ""))
        save_artifact(run_id, item["item_id"], "profile_page_raw", {"url": fetch["final_url"], "title": page.get("title", ""), "text": page.get("text", "")[:24000], "name": payload.get("name", "")}, ref=fetch["final_url"])
        enqueue_item(
            run_id,
            "extract_deputy_claims",
            f"Extract claims for {payload.get('name', item['entity_id'])}",
            {**payload, "profile_url": fetch["final_url"], "profile_text": page.get("text", "")[:24000], "page_title": page.get("title", "")},
            priority=45,
            parent_item_id=item["item_id"],
            entity_id=item["entity_id"],
        )
        update_run_status(run_id, "running", current_stage="fetch_deputy_profile")
        return WorkItemResult(ok=True, status="done", current_stage="fetch_deputy_profile", output={"profile_url": fetch["final_url"]}, graph_diff=GraphDiff())
    else:
        roster_source_url = str(payload.get("source_url") or ROSTER_URL)
        save_artifact(
            run_id,
            item["item_id"],
            "accepted_source",
            {
                "url": roster_source_url,
                "source_type": str(payload.get("source_type") or "official_web_cached_snapshot"),
                "status": "accepted_as_source",
                "reason": "missing deputy profile URL; using roster stub for downstream extraction",
            },
            ref=roster_source_url,
        )
        stub_text = " ".join(
            value for value in [
                str(payload.get("name") or "").strip(),
                str(payload.get("role") or "").strip(),
                str(payload.get("period") or "").strip(),
                str(payload.get("party") or "").strip(),
                str(payload.get("faction") or "").strip(),
            ] if value
        ).strip()
        enqueue_item(
            run_id,
            "extract_deputy_claims",
            f"Extract claims for {payload.get('name', item['entity_id'])}",
            {
                **payload,
                "profile_url": "",
                "profile_text": stub_text,
                "page_title": str(payload.get("role") or payload.get("name") or "Deputy roster stub"),
                "source_url": roster_source_url,
            },
            priority=45,
            parent_item_id=item["item_id"],
            entity_id=item["entity_id"],
        )
        update_run_status(run_id, "running", current_stage="fetch_deputy_profile")
        return WorkItemResult(ok=True, status="done", current_stage="fetch_deputy_profile", output={"profile_url": "", "stubbed_from_roster": True}, graph_diff=GraphDiff())


def _extract_deputy_claims(run_id: str, item: dict[str, Any]) -> WorkItemResult:
    graph = load_graph()
    payload = dict(item.get("input_json", {}))
    profile_url = str(payload.get("profile_url") or "").strip()
    profile = {
        "name": payload.get("name", ""),
        "birth_date": "",
        "party": payload.get("party", ""),
        "faction": payload.get("faction", ""),
        "email": "",
        "biography": [],
        "profile_url": profile_url,
        "period": payload.get("period", ""),
    }
    profile_text = str(payload.get("profile_text") or "")
    source_texts: list[dict[str, Any]] = [{"url": profile_url, "text": profile_text[:8000]}] if profile_text else []
    if profile_text:
        parsed = parse_profile_page(profile_text, profile_url)
        for key, value in parsed.items():
            if value:
                profile[key] = value
    context = build_work_item_context(graph, item, source_texts)
    get_entity_card(run_id, item["item_id"], graph, item["entity_id"])
    resolve_entity_logged(run_id, item["item_id"], graph, profile.get("name", payload.get("name", "")))
    model_result = extract_claims_logged(
        run_id,
        item["item_id"],
        query=str(payload.get("query") or "deputy profile extraction"),
        target_name=profile.get("name", payload.get("name", "")),
        source_url=profile_url or payload.get("source_url", ""),
        page_text=profile_text or "",
        page_title=str(payload.get("page_title") or ""),
        source_type="official_web",
        context=context,
    )
    if model_result.get("claims"):
        increment_run_summary(run_id, claims_extracted=len([claim for claim in model_result.get("claims", []) if isinstance(claim, dict)]))
    resolved_person_name = _canonical_person_display_name(graph, profile["name"] or payload["name"])
    entity = {
        "id": item["entity_id"] or _person_id(resolved_person_name or profile["name"] or payload["name"]),
        "label": resolved_person_name or profile["name"] or payload["name"],
        "name": resolved_person_name or profile["name"] or payload["name"],
        "category": "person",
        "subtype": "mp",
        "aliases": [alias for alias in payload.get("aliases", []) or [] if alias],
        "links": {"official_profile": profile_url} if profile_url else {},
        "summary": " ".join(profile.get("biography", [])[:1]).strip() or f"Deputy of the National Assembly of Armenia. {profile.get('role', payload.get('role', '')).strip()}".strip(),
    }
    claims: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    office_id = _office_id("Member of the National Assembly of Armenia")
    office_entity = {
        "id": office_id,
        "label": "Member of the National Assembly of Armenia",
        "name": "Member of the National Assembly of Armenia",
        "category": "office",
        "subtype": "mp_office",
        "summary": "Parliamentary office in the National Assembly of Armenia.",
    }
    assembly_id = _org_id("institution", "National Assembly of Armenia")
    assembly_entity = {
        "id": assembly_id,
        "label": "National Assembly of Armenia",
        "name": "National Assembly of Armenia",
        "category": "institution",
        "subtype": "parliament",
        "summary": "The parliament of Armenia.",
    }
    evidence_quote = profile.get("role") or payload.get("role") or "Listed on the official parliament roster as a deputy of the National Assembly."
    claims.append(
        {
            "subject_id": entity["id"],
            "predicate": "holds_office_in",
            "object_id": office_id,
            "source_url": profile_url or payload.get("source_url", ""),
            "evidence_quote": evidence_quote,
            "confidence": 0.9,
            "status": "confirmed",
            "valid_from": "2021",
        }
    )
    edges.append({"from_id": entity["id"], "to_id": office_id, "relation_type": "holds_office_in", "canonical_or_derived": "canonical", "claim_ref": "holds_office_in"})
    claims.append(
        {
            "subject_id": office_id,
            "predicate": "part_of",
            "object_id": assembly_id,
            "source_url": payload.get("source_url", ""),
            "evidence_quote": "Members of the National Assembly belong to the parliament of Armenia.",
            "confidence": 0.85,
            "status": "confirmed",
            "valid_from": "2021",
        }
    )
    edges.append({"from_id": office_id, "to_id": assembly_id, "relation_type": "part_of", "canonical_or_derived": "canonical", "claim_ref": "part_of"})
    if profile.get("faction") or profile.get("party"):
        target_name = profile.get("faction") or profile.get("party")
        relation_type = "member_of"
        target_id = _org_id("faction" if profile.get("faction") else "party", target_name)
        claims.append(
            {
                "subject_id": entity["id"],
                "predicate": relation_type,
                "object_id": target_id,
                "source_url": profile_url or payload.get("source_url", ""),
                "evidence_quote": f'{profile.get("name") or payload.get("name")} is listed under {target_name}.',
                "confidence": 0.78 if profile.get("faction") else 0.72,
                "status": "confirmed" if profile.get("faction") else "probable",
                "valid_from": "2021",
            }
        )
        edges.append({"from_id": entity["id"], "to_id": target_id, "relation_type": relation_type, "canonical_or_derived": "canonical", "claim_ref": relation_type})
    profile_update = {
        "overview": entity["summary"],
        "biography_or_history": profile.get("biography", [])[:4],
        "current_roles_or_functions": [value for value in [payload.get("role", ""), "Deputy of the National Assembly of Armenia"] if value],
        "timeline": [{"date": profile.get("period") or "2021-present", "title": "Serves in the 8th convocation of the National Assembly"}],
        "source_links": [{"title": "Official profile", "url": profile_url, "source_type": "official"}] if profile_url else [],
    }
    for model_profile in model_result.get("profile_updates", []) or []:
        if not isinstance(model_profile, dict):
            continue
        if str(model_profile.get("overview") or "").strip():
            profile_update["overview"] = str(model_profile.get("overview"))
        if isinstance(model_profile.get("biography_or_history"), list) and model_profile.get("biography_or_history"):
            profile_update["biography_or_history"] = [str(item) for item in model_profile.get("biography_or_history", []) if str(item).strip()][:6]
        if isinstance(model_profile.get("current_roles_or_functions"), list) and model_profile.get("current_roles_or_functions"):
            profile_update["current_roles_or_functions"] = [str(item) for item in model_profile.get("current_roles_or_functions", []) if str(item).strip()][:6]
        if isinstance(model_profile.get("timeline_items"), list) and model_profile.get("timeline_items"):
            profile_update["timeline"] = list(model_profile.get("timeline_items", []))[:6]
    entity_nodes = {entity["id"]: entity, office_id: office_entity, assembly_id: assembly_entity}
    if profile.get("faction"):
        entity_nodes[_org_id("faction", profile["faction"])] = {"id": _org_id("faction", profile["faction"]), "label": profile["faction"], "name": profile["faction"], "category": "organization", "subtype": "faction", "summary": "Parliamentary faction."}
    elif profile.get("party"):
        entity_nodes[_org_id("party", profile["party"])] = {"id": _org_id("party", profile["party"]), "label": profile["party"], "name": profile["party"], "category": "organization", "subtype": "party", "summary": "Political party."}
    for claim in claims:
        ok, reason = validate_claim_has_evidence(claim)
        if not ok:
            save_artifact(run_id, item["item_id"], "rejected_change", {"type": "claim", "reason": reason, "claim": claim}, ref=claim["predicate"])
            return WorkItemResult(ok=False, status="failed", error=reason, current_stage="extract_deputy_claims")
    for edge in edges:
        for validator in (
            lambda current: validate_edge_has_claim(current),
            lambda current: validate_no_generic_relation(current),
            lambda current: validate_no_person_clique(current, entity_nodes),
        ):
            ok, reason = validator(edge)
            if not ok:
                save_artifact(run_id, item["item_id"], "rejected_change", {"type": "edge", "reason": reason, "edge": edge}, ref=edge["relation_type"])
                return WorkItemResult(ok=False, status="failed", error=reason, current_stage="extract_deputy_claims")
    recorded_claims = _record_claim_memory(run_id, item["item_id"], claims, stage="extract_deputy_claims", source_url=profile_url)
    diff = GraphDiff()
    base_source_url = profile_url or payload.get("source_url", "")
    base_evidence = evidence_quote
    for extra_entity in entity_nodes.values():
        entity_proposal = {
            "entity": extra_entity,
            "claims": [],
            "profile_update": {},
            "source_url": base_source_url,
            "evidence_quote": base_evidence,
            "updated_at": iso_now(),
        }
        entity_diff = propose_graph_update(run_id, item["item_id"], entity_proposal)
        diff.new_node_ids.extend(entity_diff.get("new_node_ids", []))
        diff.updated_node_ids.extend(entity_diff.get("updated_node_ids", []))
    person_proposal = {
        "entity": entity,
        "claims": claims,
        "profile_update": profile_update,
        "source_url": base_source_url,
        "evidence_quote": base_evidence,
        "updated_at": iso_now(),
    }
    proposal_diff = propose_graph_update(run_id, item["item_id"], person_proposal)
    diff.new_node_ids.extend(proposal_diff.get("new_node_ids", []))
    diff.updated_node_ids.extend(proposal_diff.get("updated_node_ids", []))
    diff.new_edge_ids.extend(proposal_diff.get("new_edge_ids", []))
    diff.updated_edge_ids.extend(proposal_diff.get("updated_edge_ids", []))
    _refresh_entity_registry_after_graph_write()
    for claim in claims:
        save_artifact(run_id, item["item_id"], "extracted_claim", claim, ref=claim["predicate"])
    save_artifact(run_id, item["item_id"], "accepted_change", {"entity_id": entity["id"], "graph_diff": diff.to_dict()}, ref=entity["id"])
    increment_run_summary(
        run_id,
        claims_extracted=len(claims),
        claims_logged=len(recorded_claims),
        graph_updates=len(diff.new_node_ids) + len(diff.updated_node_ids) + len(diff.new_edge_ids) + len(diff.updated_edge_ids),
    )
    update_run_status(run_id, "running", current_stage="extract_deputy_claims")
    return WorkItemResult(
        ok=True,
        status="done",
        current_stage="extract_deputy_claims",
        output={"entity_id": entity["id"], "context": context, "profile_url": profile_url},
        graph_diff=diff,
    )


def _fetch_minister_profile(run_id: str, item: dict[str, Any]) -> WorkItemResult:
    payload = dict(item.get("input_json", {}))
    profile_url = str(payload.get("profile_url") or "").strip()
    if not profile_url:
        save_artifact(run_id, item["item_id"], "rejected_source", {"url": "", "status": "missing_profile_url", "reason": "minister roster item has no profile URL"}, ref=item["entity_id"])
        return WorkItemResult(ok=False, status="failed_retryable", error="missing_profile_url", current_stage="fetch_minister_profile")
    fetch = fetch_url_logged(run_id, item["item_id"], profile_url)
    save_artifact(run_id, item["item_id"], "accepted_source", {"url": fetch["final_url"], "source_type": "official_web", "status": "accepted_as_source", "reason": "official minister profile"}, ref=fetch["final_url"])
    increment_run_summary(run_id, profile_pages_fetched=1)
    page = extract_page_logged(run_id, item["item_id"], fetch["body"], fetch["final_url"], content_type=str(fetch.get("content_type") or ""))
    save_artifact(run_id, item["item_id"], "profile_page_raw", {"url": fetch["final_url"], "title": page.get("title", ""), "text": page.get("text", "")[:24000], "name": payload.get("name", "")}, ref=fetch["final_url"])
    enqueue_item(
        run_id,
        "extract_minister_claims",
        f"Extract claims for {payload.get('name', item['entity_id'])}",
        {**payload, "profile_url": fetch["final_url"], "profile_text": page.get("text", "")[:24000], "page_title": page.get("title", "")},
        priority=45,
        parent_item_id=item["item_id"],
        entity_id=item["entity_id"],
    )
    update_run_status(run_id, "running", current_stage="fetch_minister_profile")
    return WorkItemResult(ok=True, status="done", current_stage="fetch_minister_profile", output={"profile_url": fetch["final_url"]}, graph_diff=GraphDiff())


def _extract_minister_claims(run_id: str, item: dict[str, Any]) -> WorkItemResult:
    graph = load_graph()
    payload = dict(item.get("input_json", {}))
    profile_url = str(payload.get("profile_url") or "").strip()
    profile_text = str(payload.get("profile_text") or "")
    parsed = parse_minister_profile_page(profile_text, profile_url, payload)
    context = build_work_item_context(graph, item, [{"url": profile_url, "text": profile_text[:8000]}] if profile_text else [])
    get_entity_card(run_id, item["item_id"], graph, item["entity_id"])
    resolve_entity_logged(run_id, item["item_id"], graph, parsed.get("name", payload.get("name", "")))
    model_result = extract_claims_logged(
        run_id,
        item["item_id"],
        query=str(payload.get("query") or "minister profile extraction"),
        target_name=parsed.get("name", payload.get("name", "")),
        source_url=profile_url or payload.get("source_url", GOV_MEMBERS_URL),
        page_text=profile_text or "",
        page_title=str(payload.get("page_title") or ""),
        source_type="official_web",
        context=context,
    )
    if model_result.get("claims"):
        increment_run_summary(run_id, claims_extracted=len([claim for claim in model_result.get("claims", []) if isinstance(claim, dict)]))

    resolved_person_name = _canonical_person_display_name(graph, parsed.get("name") or payload.get("name", ""))
    person_id = item["entity_id"] or _person_id(resolved_person_name or parsed.get("name") or payload.get("name", ""))
    ministry_name = parsed.get("ministry_name") or payload.get("ministry_name") or payload.get("title") or "Government of Armenia"
    ministry_id = _org_id("organization", ministry_name)
    office_title = parsed.get("title") or payload.get("title") or "Minister"
    office_id = _office_id(office_title)
    government_id = _government_id()
    evidence_quote = parsed.get("title") or payload.get("title") or f"{payload.get('name', '')} is listed on the official government members roster."
    source_url = profile_url or payload.get("source_url", GOV_MEMBERS_URL)

    person_entity = {
        "id": person_id,
        "label": resolved_person_name or parsed.get("name") or payload.get("name"),
        "name": resolved_person_name or parsed.get("name") or payload.get("name"),
        "category": "person",
        "subtype": "minister",
        "aliases": [alias for alias in payload.get("aliases", []) or [] if alias],
        "links": {"official_profile": profile_url} if profile_url else {},
        "summary": " ".join(parsed.get("biography", [])[:1]).strip() or f"{office_title} in the Government of Armenia.",
    }
    office_entity = {
        "id": office_id,
        "label": office_title,
        "name": office_title,
        "category": "office",
        "subtype": "ministerial_office",
        "summary": f"Cabinet office: {office_title}.",
    }
    ministry_entity = {
        "id": ministry_id,
        "label": ministry_name,
        "name": ministry_name,
        "category": "organization",
        "subtype": "ministry",
        "summary": "Government ministry of Armenia.",
    }
    government_entity = {
        "id": government_id,
        "label": "Government of Armenia",
        "name": "Government of Armenia",
        "category": "institution",
        "subtype": "government",
        "summary": "Executive branch of the Republic of Armenia.",
    }
    claims = [
        {
            "subject_id": person_id,
            "predicate": "holds_office_in",
            "object_id": office_id,
            "source_url": source_url,
            "evidence_quote": evidence_quote,
            "confidence": 0.94,
            "status": "confirmed",
            "valid_from": "current",
        },
        {
            "subject_id": person_id,
            "predicate": "leads",
            "object_id": ministry_id,
            "source_url": source_url,
            "evidence_quote": f"{parsed.get('name') or payload.get('name')} serves as {office_title}.",
            "confidence": 0.93,
            "status": "confirmed",
            "valid_from": "current",
        },
        {
            "subject_id": office_id,
            "predicate": "part_of",
            "object_id": ministry_id,
            "source_url": source_url,
            "evidence_quote": f"{office_title} belongs to {ministry_name}.",
            "confidence": 0.9,
            "status": "confirmed",
            "valid_from": "current",
        },
        {
            "subject_id": ministry_id,
            "predicate": "part_of",
            "object_id": government_id,
            "source_url": payload.get("source_url", GOV_MEMBERS_URL),
            "evidence_quote": f"{ministry_name} is listed among Government Team Members.",
            "confidence": 0.9,
            "status": "confirmed",
            "valid_from": "current",
        },
    ]
    package = {
        "person_entity": person_entity,
        "office_entity": office_entity,
        "ministry_entity": ministry_entity,
        "government_entity": government_entity,
        "claims": claims,
        "profile_update": {
            "overview": person_entity["summary"],
            "biography_or_history": parsed.get("biography", [])[:4],
            "current_roles_or_functions": parsed.get("current_roles", []) or [office_title, ministry_name],
            "timeline": parsed.get("timeline", []) or [{"date": "current", "title": office_title}],
            "source_links": [{"title": "Official profile", "url": profile_url, "source_type": "official"}] if profile_url else [{"title": "Government team members", "url": payload.get("source_url", GOV_MEMBERS_URL), "source_type": "official"}],
        },
        "source_url": source_url,
        "evidence_quote": evidence_quote,
    }
    for model_profile in model_result.get("profile_updates", []) or []:
        if not isinstance(model_profile, dict):
            continue
        if str(model_profile.get("overview") or "").strip():
            package["profile_update"]["overview"] = str(model_profile.get("overview"))
        if isinstance(model_profile.get("biography_or_history"), list) and model_profile.get("biography_or_history"):
            package["profile_update"]["biography_or_history"] = [str(item) for item in model_profile.get("biography_or_history", []) if str(item).strip()][:6]
        if isinstance(model_profile.get("current_roles_or_functions"), list) and model_profile.get("current_roles_or_functions"):
            package["profile_update"]["current_roles_or_functions"] = [str(item) for item in model_profile.get("current_roles_or_functions", []) if str(item).strip()][:6]
        if isinstance(model_profile.get("timeline_items"), list) and model_profile.get("timeline_items"):
            package["profile_update"]["timeline"] = list(model_profile.get("timeline_items", []))[:6]
    for claim in claims:
        ok, reason = validate_claim_has_evidence(claim)
        if not ok:
            save_artifact(run_id, item["item_id"], "rejected_change", {"type": "claim", "reason": reason, "claim": claim}, ref=claim["predicate"])
            return WorkItemResult(ok=False, status="failed", error=reason, current_stage="extract_minister_claims")
        save_artifact(run_id, item["item_id"], "extracted_claim", claim, ref=claim["predicate"])
    recorded_claims = _record_claim_memory(run_id, item["item_id"], claims, stage="extract_minister_claims", source_url=source_url)
    increment_run_summary(run_id, claims_extracted=len(claims), claims_logged=len(recorded_claims))
    enqueue_item(
        run_id,
        "link_minister_to_ministry",
        f"Link {parsed.get('name') or payload.get('name')} to {ministry_name}",
        {**payload, "proposal_package": package, "context": context},
        priority=40,
        parent_item_id=item["item_id"],
        entity_id=person_id,
    )
    update_run_status(run_id, "running", current_stage="extract_minister_claims")
    return WorkItemResult(ok=True, status="done", current_stage="extract_minister_claims", output={"entity_id": person_id, "profile_url": profile_url}, graph_diff=GraphDiff())


def _link_minister_to_ministry(run_id: str, item: dict[str, Any]) -> WorkItemResult:
    payload = dict(item.get("input_json", {}))
    package = dict(payload.get("proposal_package", {}))
    claims = list(package.get("claims", []))
    entity_nodes = {
        package["person_entity"]["id"]: package["person_entity"],
        package["office_entity"]["id"]: package["office_entity"],
        package["ministry_entity"]["id"]: package["ministry_entity"],
        package["government_entity"]["id"]: package["government_entity"],
    }
    edges = [
        {"from_id": package["person_entity"]["id"], "to_id": package["office_entity"]["id"], "relation_type": "holds_office_in", "claim_ref": "holds_office_in"},
        {"from_id": package["person_entity"]["id"], "to_id": package["ministry_entity"]["id"], "relation_type": "leads", "claim_ref": "leads"},
        {"from_id": package["office_entity"]["id"], "to_id": package["ministry_entity"]["id"], "relation_type": "part_of", "claim_ref": "part_of"},
        {"from_id": package["ministry_entity"]["id"], "to_id": package["government_entity"]["id"], "relation_type": "part_of", "claim_ref": "part_of"},
    ]
    for edge in edges:
        for validator in (
            lambda current: validate_edge_has_claim(current),
            lambda current: validate_no_generic_relation(current),
            lambda current: validate_no_person_clique(current, entity_nodes),
        ):
            ok, reason = validator(edge)
            if not ok:
                save_artifact(run_id, item["item_id"], "rejected_change", {"type": "edge", "reason": reason, "edge": edge}, ref=edge["relation_type"])
                return WorkItemResult(ok=False, status="failed", error=reason, current_stage="link_minister_to_ministry")
    diff = GraphDiff()
    for extra_entity in (package["office_entity"], package["ministry_entity"], package["government_entity"]):
        entity_diff = propose_graph_update(
            run_id,
            item["item_id"],
            {
                "entity": extra_entity,
                "claims": [],
                "profile_update": {},
                "source_url": package.get("source_url", ""),
                "evidence_quote": package.get("evidence_quote", ""),
                "updated_at": iso_now(),
            },
        )
        diff.new_node_ids.extend(entity_diff.get("new_node_ids", []))
        diff.updated_node_ids.extend(entity_diff.get("updated_node_ids", []))
    person_diff = propose_graph_update(
        run_id,
        item["item_id"],
        {
            "entity": package["person_entity"],
            "claims": claims,
            "profile_update": package.get("profile_update", {}),
            "source_url": package.get("source_url", ""),
            "evidence_quote": package.get("evidence_quote", ""),
            "updated_at": iso_now(),
        },
    )
    diff.new_node_ids.extend(person_diff.get("new_node_ids", []))
    diff.updated_node_ids.extend(person_diff.get("updated_node_ids", []))
    diff.new_edge_ids.extend(person_diff.get("new_edge_ids", []))
    diff.updated_edge_ids.extend(person_diff.get("updated_edge_ids", []))
    _refresh_entity_registry_after_graph_write()
    save_artifact(run_id, item["item_id"], "accepted_change", {"entity_id": package["person_entity"]["id"], "graph_diff": diff.to_dict()}, ref=package["person_entity"]["id"])
    increment_run_summary(
        run_id,
        graph_updates=len(diff.new_node_ids) + len(diff.updated_node_ids) + len(diff.new_edge_ids) + len(diff.updated_edge_ids),
    )
    update_run_status(run_id, "running", current_stage="link_minister_to_ministry")
    return WorkItemResult(ok=True, status="done", current_stage="link_minister_to_ministry", output={"entity_id": package["person_entity"]["id"]}, graph_diff=diff)


def _build_deputy_relations(run_id: str, item: dict[str, Any]) -> WorkItemResult:
    graph = load_graph()
    faction_members: dict[str, list[str]] = {}
    for relation in graph.get("relations", []) or []:
        if not isinstance(relation, dict):
            continue
        if str(relation.get("relation_type") or relation.get("type") or "") != "member_of":
            continue
        source = str(relation.get("from") or "")
        target = str(relation.get("to") or "")
        if source.startswith("person-") and (target.startswith("faction-") or target.startswith("party-")):
            faction_members.setdefault(target, []).append(source)
    derived: list[dict[str, Any]] = []
    for target_id, members in faction_members.items():
        members = sorted(set(members))
        for index, left in enumerate(members):
            for right in members[index + 1 :]:
                derived.append(
                    {
                        "id": f"derived-{_slug(left)}-{_slug(right)}-{_slug(target_id)}",
                        "from": left,
                        "to": right,
                        "relation_type": "aligned_with",
                        "relation_class": "political_alignment",
                        "semantic_summary": "Derived relation: shared parliamentary faction or party membership.",
                        "basis_paths": [[left, target_id, right]],
                        "basis_edge_ids": [],
                        "confidence": 0.72,
                        "canonical": False,
                        "edge_kind": "derived",
                        "status": "derived",
                    }
                )
    graph["derived_relations"] = derived[:500]
    from graph_memory import entity_profile_card  # local import
    from pipeline_common import write_json
    from pipeline_common import canonical_graph_path
    write_json(canonical_graph_path(), graph)
    derived_ids = [row["id"] for row in derived[:500] if row.get("id")]
    save_artifact(run_id, item["item_id"], "accepted_change", {"derived_relations": len(derived_ids)}, ref="derived_relations")
    update_run_status(run_id, "running", current_stage="build_relations", summary_json={"derived_relations": len(graph["derived_relations"]), "graph_updates": len(derived_ids)})
    return WorkItemResult(ok=True, status="done", current_stage="build_relations", output={"derived_relation_count": len(graph["derived_relations"])}, graph_diff=GraphDiff(new_edge_ids=derived_ids))


def _build_government_relations(run_id: str, item: dict[str, Any]) -> WorkItemResult:
    graph = load_graph()
    members: list[str] = []
    government_id = _government_id()
    for relation in graph.get("relations", []) or []:
        if not isinstance(relation, dict):
            continue
        relation_type = str(relation.get("relation_type") or relation.get("type") or "")
        if relation_type == "leads" and str(relation.get("from") or "").startswith("person-") and str(relation.get("to") or "").startswith("organization-"):
            members.append(str(relation.get("from") or ""))
        if relation_type == "part_of" and str(relation.get("to") or "") == government_id and str(relation.get("from") or "").startswith("organization-"):
            continue
    members = sorted(set(members))
    derived = list(graph.get("derived_relations", []) or [])
    for index, left in enumerate(members):
        for right in members[index + 1 :]:
            derived.append(
                {
                    "id": f"derived-{_slug(left)}-{_slug(right)}-government",
                    "from": left,
                    "to": right,
                    "relation_type": "aligned_with",
                    "relation_class": "political_alignment",
                    "semantic_summary": "Derived relation: both serve in the current Government of Armenia cabinet.",
                    "basis_paths": [[left, government_id, right]],
                    "basis_edge_ids": [],
                    "confidence": 0.69,
                    "canonical": False,
                    "edge_kind": "derived",
                    "status": "derived",
                    "last_changed_run_id": run_id,
                    "change_type": "updated",
                }
            )
    graph["derived_relations"] = derived[:800]
    derived_ids = [row["id"] for row in derived if row.get("id")]
    from pipeline_common import canonical_graph_path, write_json
    write_json(canonical_graph_path(), graph)
    save_artifact(run_id, item["item_id"], "accepted_change", {"derived_relations": len(derived_ids)}, ref="derived_government_relations")
    update_run_status(run_id, "running", current_stage="build_government_relations", summary_json={"derived_relations": len(graph["derived_relations"]), "graph_updates": len(derived_ids)})
    return WorkItemResult(ok=True, status="done", current_stage="build_government_relations", output={"derived_relation_count": len(graph["derived_relations"])}, graph_diff=GraphDiff(new_edge_ids=derived_ids))


def _rebuild_profiles(run_id: str, item: dict[str, Any]) -> WorkItemResult:
    graph = load_graph()
    refreshed = 0
    warnings: list[dict[str, Any]] = []
    diff = latest_graph_diff(run_id)
    candidate_ids = [
        str(entity_id)
        for entity_id in (
            list(diff.get("new_node_ids", []) or [])
            + list(diff.get("updated_node_ids", []) or [])
        )
        if str(entity_id).startswith("person-")
    ]
    if not candidate_ids:
        candidate_ids = [
            str(entity.get("id") or "")
            for entity in (graph.get("entities", []) or [])
            if isinstance(entity, dict) and str(entity.get("id") or "").startswith("person-")
        ][:25]
    for entity_id in candidate_ids:
        entity = next((row for row in graph.get("entities", []) or [] if isinstance(row, dict) and str(row.get("id") or "") == entity_id), None)
        if not entity:
            warnings.append({"entity_id": entity_id, "reason": "missing_entity"})
            continue
        if not isinstance(entity, dict):
            continue
        try:
            card = get_entity_card(run_id, item["item_id"], graph, entity_id)
            if card:
                refreshed += 1
            else:
                warnings.append({"entity_id": entity_id, "reason": "missing_card"})
        except Exception as exc:
            warnings.append({"entity_id": entity_id, "reason": str(exc)})
            continue
    save_artifact(run_id, item["item_id"], "profile_refresh", {"profiles_rebuilt": refreshed, "warnings": warnings[:20]}, ref="profiles")
    update_run_status(run_id, "running", current_stage="rebuild_profiles", summary_json={"profiles_rebuilt": refreshed, "profile_refresh_warnings": len(warnings), "last_active_stage": "rebuild_profiles"})
    return WorkItemResult(ok=True, status="done", current_stage="rebuild_profiles", output={"profiles_rebuilt": refreshed, "warnings": warnings[:20]}, graph_diff=GraphDiff())


def _generic_topic_research(run_id: str, item: dict[str, Any]) -> WorkItemResult:
    payload = dict(item.get("input_json", {}))
    query = str(payload.get("query") or payload.get("prompt") or item.get("title") or "").strip()
    if not query:
        save_artifact(run_id, item["item_id"], "rejected_change", {"reason": "empty_generic_query"}, ref="generic")
        return WorkItemResult(ok=False, status="failed_retryable", error="empty_generic_query", current_stage="generic_topic_research")
    seed_queries = [str(row).strip() for row in payload.get("seed_queries", []) or [] if str(row).strip()]
    expected_claim_types = [str(row).strip() for row in payload.get("expected_claim_types", []) or [] if str(row).strip()]
    suggested_source_types = [str(row).strip() for row in payload.get("suggested_source_types", []) or [] if str(row).strip()]
    query_plan: list[str] = []
    for candidate in [query, *seed_queries]:
        normalized = normalize_text(candidate)
        if normalized and normalized not in {normalize_text(row) for row in query_plan}:
            query_plan.append(candidate)
    budget_pages = max(1, min(25, int(payload.get("budget_pages") or payload.get("budget") or 5)))
    per_query_results = max(3, min(8, budget_pages))
    search_results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    search_count = 0
    for planned_query in query_plan[:6]:
        results = search_web_logged(run_id, item["item_id"], planned_query, max_results=per_query_results)
        search_count += 1
        for result in results:
            url = str(result.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            search_results.append({**result, "planned_query": planned_query})
            if len(search_results) >= budget_pages:
                break
        if len(search_results) >= budget_pages:
            break
    target_name = str(payload.get("target_name") or "").strip()
    if not target_name:
        for pattern in (
            r"\bfor\s+([A-ZԱ-Ֆ][A-Za-zԱ-Ֆա-ֆև'’.-]+(?:\s+[A-ZԱ-Ֆ][A-Za-zԱ-Ֆա-ֆև'’.-]+){1,3})\b",
            r"\babout\s+([A-ZԱ-Ֆ][A-Za-zԱ-Ֆա-ֆև'’.-]+(?:\s+[A-ZԱ-Ֆ][A-Za-zԱ-Ֆա-ֆև'’.-]+){1,3})\b",
        ):
            match = re.search(pattern, query)
            if match:
                target_name = re.sub(r"\s+", " ", match.group(1)).strip(" .,:;")
                break
    target_name = target_name or query
    increment_run_summary(run_id, search_queries=search_count)
    save_artifact(
        run_id,
        item["item_id"],
        "research_question_plan",
        {
            "question_id": payload.get("question_id", ""),
            "question_type": payload.get("question_type", ""),
            "target_entities": payload.get("target_entities", []),
            "expected_claim_types": expected_claim_types,
            "suggested_source_types": suggested_source_types,
            "query_plan": query_plan,
            "budget_pages": budget_pages,
            "search_results": len(search_results),
        },
        ref=str(payload.get("question_id") or query),
    )
    if not search_results:
        save_artifact(run_id, item["item_id"], "rejected_change", {"reason": "no_search_results", "query": query, "query_plan": query_plan}, ref=query)
        return WorkItemResult(ok=False, status="failed_retryable", error="no_search_results", current_stage="generic_topic_research")
    extracted_claims: list[dict[str, Any]] = []
    accepted_sources = 0
    attempted_sources: list[dict[str, str]] = []
    for result in search_results[:budget_pages]:
        url = str(result.get("url") or "").strip()
        if not url:
            continue
        attempted_sources.append({"url": url, "title": str(result.get("title") or "").strip(), "planned_query": str(result.get("planned_query") or "").strip()})
        try:
            fetch = fetch_url_logged(run_id, item["item_id"], url)
        except Exception:
            continue
        page = extract_page_logged(run_id, item["item_id"], fetch["body"], fetch["final_url"], content_type=str(fetch.get("content_type") or ""))
        if not page.get("text", "").strip():
            continue
        accepted_sources += 1
        extraction = extract_claims_logged(
            run_id,
            item["item_id"],
            query=query,
            target_name=target_name,
            source_url=page.get("url") or fetch["final_url"],
            page_text=page.get("text", "")[:16000],
            page_title=page.get("title", ""),
            source_type="web",
            context={
                "search_result": result,
                "query": query,
                "planned_query": result.get("planned_query", ""),
                "question_id": payload.get("question_id", ""),
                "question_type": payload.get("question_type", ""),
                "expected_claim_types": expected_claim_types,
                "suggested_source_types": suggested_source_types,
                "target_entities": payload.get("target_entities", []),
            },
        )
        extracted_claims.extend(extraction.get("claims", []) or [])
    if not extracted_claims:
        save_artifact(run_id, item["item_id"], "rejected_change", {"reason": "no_extractable_claims", "query": query, "query_plan": query_plan, "accepted_sources": accepted_sources, "attempted_sources": attempted_sources[:10]}, ref=query)
        increment_run_summary(run_id, rejected_sources=1, accepted_sources=accepted_sources)
        if accepted_sources > 0:
            return WorkItemResult(ok=True, status="done", current_stage="generic_topic_research", output={"query": query, "query_plan": query_plan, "accepted_sources": accepted_sources, "claims_extracted": 0, "no_changes_reason": "no_extractable_claims"}, graph_diff=GraphDiff())
        return WorkItemResult(ok=False, status="failed_retryable", error="no_extractable_claims", current_stage="generic_topic_research")
    increment_run_summary(run_id, accepted_sources=accepted_sources, claims_extracted=len(extracted_claims))
    save_artifact(run_id, item["item_id"], "accepted_change", {"query": query, "query_plan": query_plan, "accepted_sources": accepted_sources, "claims": extracted_claims[:10]}, ref=query)
    return WorkItemResult(ok=True, status="done", current_stage="generic_topic_research", output={"query": query, "query_plan": query_plan, "accepted_sources": accepted_sources, "claims_extracted": len(extracted_claims)}, graph_diff=GraphDiff())


def execute_item(run_id: str, item: dict[str, Any]) -> WorkItemResult:
    item_type = str(item.get("item_type") or "")
    if item_type == "discover_role_history":
        return _discover_role_history(run_id, item)
    if item_type == "discover_government_ministers":
        return _discover_government_ministers(run_id, item)
    if item_type == "discover_parliament_roster":
        return _discover_parliament_roster(run_id, item)
    if item_type == "fetch_role_history_profile":
        return _fetch_role_history_profile(run_id, item)
    if item_type == "extract_role_history_claims":
        return _extract_role_history_claims(run_id, item)
    if item_type == "fetch_minister_profile":
        return _fetch_minister_profile(run_id, item)
    if item_type == "fetch_deputy_profile":
        return _fetch_deputy_profile(run_id, item)
    if item_type == "extract_associations":
        return _extract_associations(run_id, item)
    if item_type == "extract_minister_claims":
        return _extract_minister_claims(run_id, item)
    if item_type == "extract_deputy_claims":
        return _extract_deputy_claims(run_id, item)
    if item_type == "link_minister_to_ministry":
        return _link_minister_to_ministry(run_id, item)
    if item_type == "build_government_relations":
        return _build_government_relations(run_id, item)
    if item_type == "build_deputy_relations":
        return _build_deputy_relations(run_id, item)
    if item_type == "rebuild_profiles":
        return _rebuild_profiles(run_id, item)
    return _generic_topic_research(run_id, item)
