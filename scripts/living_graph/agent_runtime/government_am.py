"""Deterministic helpers for gov.am minister roster and profile pages."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urlparse

GOV_MEMBERS_URL = "https://www.gov.am/en/gov-members/"
GOV_STAFF_STRUCTURE_URL = "https://www.gov.am/en/staff-structure/"


def _absolute_url(base_url: str, href: str) -> str:
    value = str(href or "").strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    parsed = urlparse(base_url or GOV_MEMBERS_URL)
    if not parsed.scheme or not parsed.netloc:
        parsed = urlparse(GOV_MEMBERS_URL)
    return f"{parsed.scheme}://{parsed.netloc}/{value.lstrip('/')}"


def _clean_text(value: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", value))
    return re.sub(r"\s+", " ", text).strip()


def _html_to_lines(body: str) -> list[str]:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", body, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"</(p|div|li|h1|h2|h3|h4|tr|section|article)>", "\n", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return [line for line in lines if line]


def _ministry_from_title(title: str) -> str:
    value = str(title or "").strip()
    match = re.match(r"^Minister of (.+)$", value, flags=re.I)
    if match:
        return f"Ministry of {match.group(1).strip()}"
    if value.lower() == "prime minister":
        return "Government of Armenia"
    return value


def parse_government_members_page(body: str, base_url: str = GOV_MEMBERS_URL) -> dict[str, Any]:
    people: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    pattern = re.compile(
        r'<div[^>]+id="min-bl1"[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>\s*(.*?)\s*</a>\s*<p>\s*([^<]+?)\s*</p>',
        flags=re.I | re.S,
    )
    for href, raw_name, raw_title in pattern.findall(body):
        name = _clean_text(raw_name).replace(" ,", ",")
        title = _clean_text(raw_title)
        if not name or not title:
            continue
        ministry_name = _ministry_from_title(title)
        key = (name.lower(), title.lower())
        if key in seen:
            continue
        seen.add(key)
        people.append(
            {
                "name": name,
                "aliases": [],
                "profile_url": _absolute_url(base_url, href),
                "title": title,
                "position": title,
                "ministry_name": ministry_name,
                "source_url": base_url,
                "source_type": "official_web",
                "fetched_at": "",
            }
        )
    return {"people": people}


def parse_minister_profile_page(body: str, profile_url: str, seed: dict[str, Any] | None = None) -> dict[str, Any]:
    seed = seed or {}
    lines = _html_to_lines(body)
    text = " ".join(lines)
    biography: list[str] = []
    for line in lines:
        lowered = line.lower()
        if len(line.split()) < 8:
            continue
        if any(
            token in lowered
            for token in (
                "home",
                "search",
                "official news",
                "government decrees",
                "session agenda",
                "the government of the republic of armenia",
            )
        ):
            continue
        biography.append(line)
        if len(biography) >= 4:
            break
    birth_date = ""
    birth_match = re.search(r"\b(\d{1,2}\s+[A-Z][a-z]+\s+\d{4})\b", text)
    if birth_match:
        birth_date = birth_match.group(1)
    current_roles = [value for value in [seed.get("title", ""), seed.get("ministry_name", "")] if str(value or "").strip()]
    timeline = [{"date": "current", "title": str(seed.get("title") or "").strip()}] if seed.get("title") else []
    return {
        "name": str(seed.get("name") or "").strip(),
        "title": str(seed.get("title") or "").strip(),
        "ministry_name": str(seed.get("ministry_name") or "").strip(),
        "birth_date": birth_date,
        "biography": biography,
        "current_roles": current_roles,
        "timeline": timeline,
        "profile_url": profile_url,
    }


def parse_prime_minister_staff_structure_page(body: str, base_url: str = GOV_STAFF_STRUCTURE_URL) -> dict[str, Any]:
    people: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    cleaned = re.sub(r"<script\b[^>]*>.*?</script>", " ", body, flags=re.I | re.S)
    cleaned = re.sub(r"<style\b[^>]*>.*?</style>", " ", cleaned, flags=re.I | re.S)
    section_pattern = re.compile(r"<h3[^>]*>(.*?)</h3>", flags=re.I | re.S)
    section_matches = list(section_pattern.finditer(cleaned))

    def emit_person(*, name: str, href: str, title: str, section_title: str, **extra: Any) -> None:
        candidate_name = _clean_text(name).rstrip(".")
        role_title = _clean_text(title)
        if not candidate_name or not role_title:
            return
        if not re.match(r"^[A-ZԱ-Ֆ][A-Za-zԱ-Ֆա-ֆև'’.-]+(?: [A-ZԱ-Ֆ][A-Za-zԱ-Ֆա-ֆև'’.-]+){1,3}$", candidate_name):
            return
        key = (candidate_name.lower(), role_title.lower())
        if key in seen:
            return
        seen.add(key)
        row = {
            "name": candidate_name,
            "aliases": [],
            "profile_url": _absolute_url(base_url, href),
            "title": role_title,
            "position": role_title,
            "section_title": section_title,
            "source_url": base_url,
            "source_type": "official_web",
            "fetched_at": "",
        }
        if extra:
            row.update(extra)
        people.append(row)

    for index, match in enumerate(section_matches):
        raw_section_title = match.group(1)
        start = match.end()
        end = section_matches[index + 1].start() if index + 1 < len(section_matches) else len(cleaned)
        block = cleaned[start:end]
        section_title = _clean_text(raw_section_title)
        if not section_title:
            continue
        if section_title.lower() == "staff departments":
            department_blocks = re.findall(r'<div[^>]+class="staff-structure"[^>]*>(.*?)</div>', block, flags=re.I | re.S)
            for subblock in department_blocks:
                department_match = re.search(r'<p[^>]*class="staff-name"[^>]*>(.*?)</p>', subblock, flags=re.I | re.S)
                department_name = _clean_text(department_match.group(1)) if department_match else ""
                head_match = re.search(r'Head:\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', subblock, flags=re.I | re.S)
                if head_match:
                    head_href = head_match.group(1)
                    head_name = _clean_text(head_match.group(2))
                    role_title = f"Head of {department_name}" if department_name else "Head of Department"
                    emit_person(
                        name=head_name,
                        href=head_href,
                        title=role_title,
                        section_title=section_title,
                        department_name=department_name,
                    )
                else:
                    # Fallback: if the department block has a single person anchor, still expose it.
                    anchor_match = re.search(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', subblock, flags=re.I | re.S)
                    if anchor_match and department_name:
                        emit_person(
                            name=_clean_text(anchor_match.group(2)),
                            href=anchor_match.group(1),
                            title=f"Head of {department_name}",
                            section_title=section_title,
                            department_name=department_name,
                        )
            continue

        anchor_pattern = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', flags=re.I | re.S)
        anchors = anchor_pattern.findall(block)
        if not anchors:
            continue
        for href, raw_name in anchors:
            name = _clean_text(raw_name)
            if not name:
                continue
            emit_person(name=name, href=href, title=section_title, section_title=section_title)

    return {"people": people, "source_url": base_url}
