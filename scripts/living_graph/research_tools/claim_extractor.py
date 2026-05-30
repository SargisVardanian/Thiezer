"""Strict claim extraction with model + deterministic fallback."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

try:
    from ..store import normalize_text
except ImportError:  # pragma: no cover
    from living_graph.store import normalize_text

try:
    from ...model_runtime import call_parser_model
except ImportError:  # pragma: no cover
    from model_runtime import call_parser_model


@dataclass
class ClaimExtractionResult:
    claims: list[dict[str, Any]] = field(default_factory=list)
    profile_updates: list[dict[str, Any]] = field(default_factory=list)
    model_meta: dict[str, Any] = field(default_factory=dict)
    raw_model_output: str = ""
    fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "claims": self.claims,
            "profile_updates": self.profile_updates,
            "model_meta": self.model_meta,
            "raw_model_output": self.raw_model_output,
            "fallback_used": self.fallback_used,
        }


def _first_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


_PERSON_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"introduced newly appointed Chief of Staff ([A-Z][A-Za-z'’.-]+(?: [A-Z][A-Za-z'’.-]+)+)", flags=re.I),
    re.compile(r"newly appointed Chief of Staff ([A-Z][A-Za-z'’.-]+(?: [A-Z][A-Za-z'’.-]+)+)", flags=re.I),
    re.compile(r"appointed Chief of Staff ([A-Z][A-Za-z'’.-]+(?: [A-Z][A-Za-z'’.-]+)+)", flags=re.I),
    re.compile(r"thanking ([A-Z][A-Za-z'’.-]+(?: [A-Z][A-Za-z'’.-]+)+) for the work done throughout his tenure as chief of staff", flags=re.I),
    re.compile(r"Mr\.?\s+([A-Z][A-Za-z'’.-]+(?: [A-Z][A-Za-z'’.-]+)+)\s+took office", flags=re.I),
    re.compile(r"Chief of Staff\s+([A-Z][A-Za-z'’.-]+(?: [A-Z][A-Za-z'’.-]+)+)", flags=re.I),
)

_GENERIC_LABEL_HINTS: tuple[str, ...] = (
    "government team members",
    "government of the republic of armenia",
    "the government of the republic of armenia",
    "office of the prime minister",
    "prime minister's office",
    "office holders",
    "team members",
    "members",
    "roster",
    "directory",
    "official website",
    "historical overview",
    "former prime",
    "the prime",
    "prime minister",
    "press release",
    "press releases",
    "updates",
    "government",
    "office",
    "staff",
    "overview",
    "history",
    "fra prime",
    "eng",
    "հայ",
    "рус",
)

_ROLE_HINTS: tuple[str, ...] = (
    "minister",
    "ministry",
    "parliament",
    "deput",
    "faction",
    "party",
    "government",
    "chief of staff",
    "head of staff",
    "speaker",
    "chair",
    "president",
    "vice president",
    "director",
    "secretary",
    "advisor",
    "assistant",
    "աշխատակազմի ղեկավար",
    "վարչապետի աշխատակազմի ղեկավար",
    "руководитель аппарата",
    "глава аппарата",
)

_OFFICE_NAME_HINTS: tuple[str, ...] = (
    "prime minister",
    "chief of staff",
    "head of staff",
    "government",
    "office of",
    "staff of",
    "apparatus",
    "secretariat",
    "руководитель аппарата",
    "глава аппарата",
    "վարչապետի աշխատակազմի ղեկավար",
    "աշխատակազմի ղեկավար",
)

_EXPLICIT_ROLE_HISTORY_OFFICE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bChief of Staff of the Prime Minister\b", flags=re.I),
    re.compile(r"\bHead of the Prime Minister['’]s Staff\b", flags=re.I),
    re.compile(r"\bPrime Minister['’]s Chief of Staff\b", flags=re.I),
    re.compile(r"\bprime minister(?:['’]s)? staff\b", flags=re.I),
    re.compile(r"\boffice of the prime minister\b", flags=re.I),
    re.compile(r"\bhead of staff\b", flags=re.I),
    re.compile(r"\bchief of staff\b", flags=re.I),
    re.compile(r"\bруководитель аппарата премьер-министра\b", flags=re.I),
    re.compile(r"\bглава аппарата премьер-министра\b", flags=re.I),
    re.compile(r"\bվարչապետի աշխատակազմի ղեկավար\b", flags=re.I),
    re.compile(r"\bաշխատակազմի ղեկավար\b", flags=re.I),
)


def _name_extraction_segments(page_text: str, title: str = "") -> list[str]:
    segments: list[str] = []
    for source in (title, page_text):
        for raw_line in str(source or "").splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip(" \t\r\n-•|:")
            if not line:
                continue
            lower = normalize_text(line)
            if lower in {"eng", "հայ", "рус", "fra", "english", "french"}:
                continue
            if len(line.split()) == 1 and lower in {"home", "search", "share", "print", "webmaster", "links", "site map"}:
                continue
            if any(token in lower for token in ("home", "search", "share", "print", "webmaster", "links", "site map")) and len(line.split()) <= 3:
                continue
            segments.append(line)
    return segments


def _is_generic_person_label(label: str) -> bool:
    blob = re.sub(r"\s+", " ", str(label or "").strip().lower())
    if not blob:
        return True
    return any(token in blob for token in _GENERIC_LABEL_HINTS)


def _is_human_name_candidate(label: str) -> bool:
    blob = re.sub(r"\s+", " ", str(label or "").strip())
    lowered = blob.lower()
    if not blob or _is_generic_person_label(blob):
        return False
    if any(token in lowered for token in ("historical overview", "former prime", "the prime", "press release", "press releases", "updates", "fra prime")):
        return False
    if any(token in lowered for token in _OFFICE_NAME_HINTS):
        return False
    if any(token in lowered for token in _ROLE_HINTS):
        return False
    if len(blob.split()) > 4:
        return False
    if not re.match(r"^[A-ZԱ-Ֆ]", blob):
        return False
    return bool(re.match(r"^[A-ZԱ-Ֆ][A-Za-zԱ-Ֆա-ֆև'’.-]+(?: [A-ZԱ-Ֆ][A-Za-zԱ-Ֆա-ֆև'’.-]+){1,3}$", blob))


def _extract_person_names(page_text: str, title: str = "") -> list[str]:
    names: list[str] = []
    for segment in _name_extraction_segments(page_text, title):
        for pattern in _PERSON_PATTERNS:
            for match in pattern.finditer(segment):
                name = re.sub(r"\s+", " ", match.group(1)).strip(" ,.;:—-")
                if name and name not in names and _is_human_name_candidate(name):
                    names.append(name)
    if not names:
        name_then_role_patterns = (
            re.compile(
                r"(?P<name>[A-ZԱ-Ֆ][A-Za-zԱ-Ֆա-ֆև'’.-]+(?:\s+[A-ZԱ-Ֆ][A-Za-zԱ-Ֆա-ֆև'’.-]+){1,3})\s+(?P<role>Minister(?: of [A-Z][A-Za-z -]+)?|Deputy Prime Minister|Chief of Staff(?: of the Prime Minister)?|Head of [A-Z][A-Za-z -]+|Chief Adviser|Adviser|Assistant|Press Secretary|Chief Protocol Officer)",
                flags=re.I,
            ),
            re.compile(
                r"(?P<name>[A-ZԱ-Ֆ][A-Za-zԱ-Ֆա-ֆև'’.-]+(?:\s+[A-ZԱ-Ֆ][A-Za-zԱ-Ֆա-ֆև'’.-]+){1,3})\s+(?P<role>Minister|Chief|Head|Advisor|Adviser|Assistant|Secretary|Director)\b",
                flags=re.I,
            ),
        )
        for segment in _name_extraction_segments(page_text, title):
            for pattern in name_then_role_patterns:
                for match in pattern.finditer(segment):
                    name = re.sub(r"\s+", " ", match.group("name")).strip(" ,.;:—-")
                    if name and name not in names and _is_human_name_candidate(name):
                        names.append(name)
    if not names:
        for raw_line in _name_extraction_segments(page_text, title):
            line = re.sub(r"\s+", " ", raw_line).strip(" \t\r\n-•|:")
            if not line:
                continue
            if _is_human_name_candidate(line) and line not in names:
                names.append(line)
                if len(names) >= 4:
                    break
                continue
            lower = line.lower()
            if not any(token in lower for token in _ROLE_HINTS):
                continue
            match = re.match(r"^([A-ZԱ-Ֆ][A-Za-zԱ-Ֆա-ֆև'’.-]+(?: [A-ZԱ-Ֆ][A-Za-zԱ-Ֆա-ֆև'’.-]+){1,3})\b", line)
            if not match:
                continue
            name = re.sub(r"\s+", " ", match.group(1)).strip(" ,.;:—-")
            if name and name not in names and _is_human_name_candidate(name):
                names.append(name)
    return names[:4]


def _extract_explicit_role_office_title(text_blob: str) -> str | None:
    blob = re.sub(r"\s+", " ", str(text_blob or "").strip())
    if not blob:
        return None
    for pattern in _EXPLICIT_ROLE_HISTORY_OFFICE_PATTERNS:
        if pattern.search(blob):
            return "Chief of Staff of the Prime Minister"
    return None


def _normalize_role_history_display_label(payload: dict[str, Any], office_title: str) -> str:
    candidates = [
        str(payload.get("candidate_name") or "").strip(),
        str(payload.get("source_title") or "").strip(),
        str(payload.get("page_title") or "").strip(),
        str(payload.get("source_snippet") or "").strip(),
    ]
    for candidate in candidates:
        if _is_human_name_candidate(candidate):
            return candidate
    return office_title or "role history candidate"


def _claim_candidate_is_person(claim: dict[str, Any]) -> bool:
    subject_name = str(claim.get("subject_name") or "").strip()
    subject_type = str(claim.get("subject_type") or "").strip().lower()
    relation_type = str(claim.get("relation_type") or claim.get("claim_type") or "").strip().lower()
    if not subject_name:
        return False
    if subject_type and subject_type not in {"person", "official"}:
        return False
    if relation_type in {"role", "membership", "biography", "contact", "date", "other", "holds_office_in", "member_of", "part_of", "leads"}:
        return _is_human_name_candidate(subject_name)
    return _is_human_name_candidate(subject_name)




def _fast_role_history_extraction(*, query: str, target_name: str, source_url: str, page_text: str, page_title: str = "") -> ClaimExtractionResult | None:
    text_blob = f"{page_title}\n{page_text}"
    office_title = _extract_explicit_role_office_title(text_blob) or ""
    specific_names: list[str] = []
    intro_match = re.search(r"introduced newly appointed Chief of Staff ([A-ZԱ-Ֆ][A-Za-zԱ-Ֆա-ֆև'’.-]+(?: [A-ZԱ-Ֆ][A-Za-zԱ-Ֆա-ֆև'’.-]+){1,3})(?: to the|,|\.|$)", text_blob, flags=re.I)
    if intro_match:
        specific_names.append(re.sub(r"\s+", " ", intro_match.group(1)).strip(" ,.;:—-"))
        office_title = "Chief of Staff of the Prime Minister"
    thank_match = re.search(r"Thanking ([A-ZԱ-Ֆ][A-Za-zԱ-Ֆա-ֆև'’.-]+(?: [A-ZԱ-Ֆ][A-Za-zԱ-Ֆա-ֆև'’.-]+){1,3}) for the work done throughout his tenure as chief of staff", text_blob, flags=re.I)
    if thank_match:
        name = re.sub(r"\s+", " ", thank_match.group(1)).strip(" ,.;:—-")
        if name and name not in specific_names:
            specific_names.append(name)
        office_title = office_title or "Chief of Staff of the Prime Minister"
    names = specific_names or _extract_person_names(page_text, page_title)
    if not names:
        return None
    if not office_title:
        return None
    claims: list[dict[str, Any]] = []
    evidence = page_text[:360].strip()
    for person_name in names[:4]:
        claims.append({
            "claim_type": "role",
            "subject_id_hint": "",
            "subject_name": person_name,
            "object_id_hint": "",
            "object_name": office_title,
            "relation_type": "holds_office_in",
            "statement": f"{person_name} holds {office_title} according to {page_title or source_url}.",
            "date_from": "",
            "date_to": "",
            "confidence": 0.88,
            "evidence_quote": evidence,
            "source_url": source_url,
        })
    if not claims:
        return None
    profile_updates = [{
        "entity_name": names[0],
        "overview": f"Official role-history candidate for {office_title}.",
        "biography_or_history": [page_title] if page_title else [],
        "current_roles_or_functions": [office_title],
        "timeline_items": [{"date": "current", "title": office_title}],
    }]
    return ClaimExtractionResult(claims=claims, profile_updates=profile_updates, model_meta={"provider": "deterministic", "model": "role_history_fast_path"}, raw_model_output="", fallback_used=True)

def _deterministic_fallback(query: str, target_name: str, source_url: str, page_text: str, *, title: str = "") -> ClaimExtractionResult:
    claims: list[dict[str, Any]] = []
    if source_url and page_text:
        person_names = _extract_person_names(page_text, title)
        if target_name and not person_names and _is_human_name_candidate(target_name):
            person_names = [target_name]
        lower = page_text.lower()
        if person_names and any(token in lower for token in ("minister", "ministry", "parliament", "deput", "faction", "party", "government", "chief of staff", "head of staff", "աշխատակազմի ղեկավար", "վարչապետի աշխատակազմի ղեկավար", "руководитель аппарата", "глава аппарата")):
            evidence = page_text[:360].strip()
            for person_name in person_names:
                claims.append(
                    {
                        "claim_type": "role",
                        "subject_id_hint": "",
                        "subject_name": person_name,
                        "object_id_hint": "",
                        "object_name": "",
                        "relation_type": "holds_office_in",
                        "statement": f"{person_name} is mentioned in the official source for {title or source_url}.",
                        "date_from": "",
                        "date_to": "",
                        "confidence": 0.72,
                        "evidence_quote": evidence,
                        "source_url": source_url,
                    }
                )
        elif target_name and any(token in lower for token in ("minister", "ministry", "parliament", "deput", "faction", "party", "government", "chief of staff", "head of staff", "աշխատակազմի ղեկավար", "վարչապետի աշխատակազմի ղեկավար", "руководитель аппарата", "глава аппарата")):
            claims.append(
                {
                    "claim_type": "role",
                    "subject_id_hint": "",
                    "subject_name": target_name,
                    "object_id_hint": "",
                    "object_name": "",
                    "relation_type": "holds_office_in",
                    "statement": f"{target_name} appears in the official source for {title or source_url}.",
                    "date_from": "",
                    "date_to": "",
                    "confidence": 0.66,
                    "evidence_quote": page_text[:240].strip(),
                    "source_url": source_url,
                }
            )
    return ClaimExtractionResult(claims=claims, profile_updates=[], model_meta={"provider": "deterministic", "model": "rules"}, raw_model_output="", fallback_used=True)


def _fast_biography_extraction(*, query: str, target_name: str, source_url: str, page_text: str, page_title: str = "", context: dict[str, Any] | None = None) -> ClaimExtractionResult | None:
    ctx = context or {}
    expected = {str(item).lower() for item in ctx.get("expected_claim_types", []) or []}
    question_type = str(ctx.get("question_type") or "").lower()
    blob = normalize_text(f"{query} {page_title} {page_text[:2000]}")
    if "biography_fact" not in expected and "biography" not in question_type and "biography" not in blob and "биограф" not in blob and "կենսագր" not in blob:
        return None
    candidate = target_name if _is_human_name_candidate(target_name) else ""
    if not candidate:
        names = _extract_person_names(page_text, page_title)
        candidate = names[0] if names else ""
    if not candidate or not _is_human_name_candidate(candidate):
        return None
    candidate_blob = normalize_text(candidate)
    if candidate_blob and candidate_blob not in normalize_text(f"{page_title} {page_text[:6000]}"):
        return None
    evidence = page_text[:420].strip()
    if not evidence:
        return None
    claim = {
        "claim_type": "biography",
        "subject_id_hint": "",
        "subject_name": candidate,
        "object_id_hint": "",
        "object_name": "",
        "relation_type": "other",
        "statement": f"{candidate} has source-backed biographical information in {page_title or source_url}.",
        "date_from": "",
        "date_to": "",
        "confidence": 0.58,
        "evidence_quote": evidence,
        "source_url": source_url,
    }
    profile_update = {
        "entity_name": candidate,
        "overview": f"Biographical source candidate from {page_title or source_url}.",
        "biography_or_history": [evidence],
        "current_roles_or_functions": [],
        "timeline_items": [],
    }
    return ClaimExtractionResult(claims=[claim], profile_updates=[profile_update], model_meta={"provider": "deterministic", "model": "biography_fast_path"}, raw_model_output="", fallback_used=True)


def extract_claims_from_page(*, query: str, target_name: str, source_url: str, page_text: str, page_title: str = "", source_type: str = "official", context: dict[str, Any] | None = None, timeout: int = 12) -> ClaimExtractionResult:
    normalized_target_name = target_name if _is_human_name_candidate(target_name) else ""
    prompt = f"""
You extract structured factual claims from official source text for graph admission.
Return strict JSON only, no markdown, no commentary.

Query: {query}
Target entity: {normalized_target_name or target_name}
Source URL: {source_url}
Source type: {source_type}
Page title: {page_title}

Context:
{json.dumps(context or {}, ensure_ascii=False)[:2000]}

Source text:
{page_text[:12000]}

Schema:
{{
  "claims": [
    {{
      "claim_type": "role|membership|biography|contact|date|other",
      "subject_id_hint": "",
      "subject_name": "{normalized_target_name or target_name}",
      "object_id_hint": "",
      "object_name": "",
      "relation_type": "holds_office_in|member_of|part_of|leads|other",
      "statement": "",
      "date_from": "",
      "date_to": "",
      "confidence": 0.0,
      "evidence_quote": "",
      "source_url": "{source_url}"
    }}
  ],
  "profile_updates": [
    {{
      "entity_name": "{normalized_target_name or target_name}",
      "overview": "",
      "biography_or_history": [],
      "current_roles_or_functions": [],
      "timeline_items": []
    }}
  ]
}}
""".strip()
    fast_path = _fast_role_history_extraction(query=query, target_name=normalized_target_name or target_name, source_url=source_url, page_text=page_text, page_title=page_title)
    if fast_path is not None:
        return fast_path
    biography_fast_path = _fast_biography_extraction(query=query, target_name=normalized_target_name or target_name, source_url=source_url, page_text=page_text, page_title=page_title, context=context)
    if biography_fast_path is not None:
        return biography_fast_path
    parsed, meta = call_parser_model(page_text, prompt, timeout=timeout)
    raw_model_output = str(meta.get("raw") or "")
    if isinstance(parsed, dict):
        claims = []
        for claim in parsed.get("claims", []) if isinstance(parsed.get("claims", []), list) else []:
            if not isinstance(claim, dict):
                continue
            if not _claim_candidate_is_person(claim):
                continue
            claims.append(claim)
        profile_updates = [item for item in parsed.get("profile_updates", []) if isinstance(item, dict)]
        if claims or profile_updates:
            return ClaimExtractionResult(claims=claims, profile_updates=profile_updates, model_meta=meta, raw_model_output=raw_model_output, fallback_used=False)
    fallback = _deterministic_fallback(query, target_name, source_url, page_text, title=page_title)
    fallback.model_meta = meta or fallback.model_meta
    fallback.raw_model_output = raw_model_output
    return fallback
