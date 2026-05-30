"""Deterministic helpers for parliament.am roster and deputy pages."""

from __future__ import annotations

import html
import re
from typing import Any

try:
    from ..store import normalize_text
except ImportError:  # pragma: no cover
    from living_graph.store import normalize_text


ROSTER_URL = "https://www.parliament.am/deputies.php?lang=eng"
FACTIONS_URL = "https://www.parliament.am/deputies.php?lang=eng&sel=factions"

FALLBACK_PEOPLE = [
    {
        "name": "Alen Simonyan",
        "name_hy": "Ալեն Սիմոնյան",
        "aliases": ["Simonyan Alen"],
        "profile_url": "",
        "faction": "",
        "party": "",
        "role": "President of the National Assembly",
        "period": "2021-present",
        "source_url": ROSTER_URL,
        "source_type": "official_web_cached_snapshot",
    },
    {
        "name": "Hakob Arshakyan",
        "name_hy": "Հակոբ Արշակյան",
        "aliases": ["Arshakyan Hakob"],
        "profile_url": "",
        "faction": "",
        "party": "",
        "role": "Vice President of the National Assembly",
        "period": "2021-present",
        "source_url": ROSTER_URL,
        "source_type": "official_web_cached_snapshot",
    },
]


def _clean_text(value: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", value))
    return re.sub(r"\s+", " ", text).strip()


def parse_roster_page(body: str, base_url: str = ROSTER_URL) -> dict[str, Any]:
    people: list[dict[str, Any]] = []
    seen: set[str] = set()
    for href, name_blob in re.findall(r'href="([^"]*deputies\.php\?ID=\d+[^"]*)"[^>]*>\s*([^<]+?)\s*</a>', body, flags=re.I):
        if "sel=details" not in href:
            href = href + ("&" if "?" in href else "?") + "sel=details"
        profile_url = href if href.startswith("http") else f"https://www.parliament.am/{href.lstrip('/')}"
        name_text = _clean_text(name_blob)
        if not name_text:
            continue
        role = ""
        if "(" in name_text and name_text.endswith(")"):
            name_text, role = name_text.rsplit("(", 1)
            role = role.rstrip(")").strip()
        normalized = normalize_text(name_text)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if "," in name_text:
            last_name, first_name = [part.strip() for part in name_text.split(",", 1)]
            display_name = f"{first_name} {last_name}".strip()
            aliases = [name_text.strip()]
        else:
            display_name = name_text.strip()
            aliases = []
        people.append(
            {
                "name": display_name,
                "name_hy": "",
                "aliases": aliases,
                "profile_url": profile_url,
                "faction": "",
                "party": "",
                "role": role,
                "period": "2021-present",
                "source_url": base_url,
                "source_type": "official_web",
            }
        )
    return {"people": people}


def parse_factions_page(body: str) -> dict[str, dict[str, str]]:
    mapping: dict[str, dict[str, str]] = {}
    current_faction = ""
    current_party = ""
    cleaned = _clean_text(body)
    lines = [line.strip() for line in re.split(r"\s{2,}|\n+", cleaned) if line.strip()]
    for line in lines:
        faction_match = re.match(r'^"([^"]+)" Faction$', line)
        if faction_match:
            current_faction = faction_match.group(1).strip()
            current_party = ""
            continue
        if current_faction and line.startswith("Contains "):
            continue
        if current_faction and "/" in line and "\"" in line:
            party_match = re.search(r'"([^"]+)"', line)
            if party_match:
                current_party = party_match.group(1).strip()
        if current_faction and re.match(r"^[A-Z][a-z]+(?: [A-Z][a-z-]+)+$", line):
            mapping[normalize_text(line)] = {"faction": current_faction, "party": current_party}
    return mapping


def parse_profile_page(body: str, profile_url: str) -> dict[str, Any]:
    text = _clean_text(body)
    lines = [line.strip() for line in re.split(r"\n+|\s{2,}", text) if line.strip()]
    title_match = re.search(r"\|\s+([A-Z][A-Za-z' -]+(?: [A-Z][A-Za-z' -]+)+)\s+(Birth date|Party|Faction|E-mail)", text)
    name = title_match.group(1).title().strip() if title_match else ""
    birth_date = ""
    party = ""
    faction = ""
    email = ""
    biography: list[str] = []
    current_period = ""
    for index, line in enumerate(lines):
        if line == "Birth date" and index + 1 < len(lines):
            birth_date = lines[index + 1]
        elif line == "Party" and index + 1 < len(lines):
            party = lines[index + 1].strip('" ')
        elif line == "Faction" and index + 1 < len(lines):
            faction = lines[index + 1].strip('" ')
        elif line == "E-mail" and index + 1 < len(lines):
            email = lines[index + 1]
        elif re.match(r"^\d{2}\.\d{2}\.\d{4}$", line):
            current_period = line
        elif len(line.split()) > 7 and not biography:
            biography.append(line)
        elif biography and len(biography) < 4 and len(line.split()) > 7:
            biography.append(line)
    return {
        "name": name,
        "birth_date": birth_date,
        "party": party,
        "faction": faction,
        "email": email if email.endswith("@parliament.am") else "",
        "biography": biography[:4],
        "profile_url": profile_url,
        "period": current_period,
    }

