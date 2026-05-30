"""Adaptive temporal planner for deep research windows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Iterable


@dataclass(frozen=True)
class TimeWindow:
    start: date
    end: date
    granularity: str  # year | month | week | day | datetime
    reason: str

    def label(self) -> str:
        return f"{self.start.isoformat()}..{self.end.isoformat()}:{self.granularity}"


def extract_year_range(text: str, *, default_start: int = 2018, default_end: int = 2026) -> tuple[int, int]:
    years = sorted({int(match) for match in re.findall(r"\b(19\d{2}|20\d{2})\b", str(text or ""))})
    if not years:
        return default_start, default_end
    if len(years) == 1:
        return years[0], years[0]
    return years[0], years[-1]


def year_windows(start_year: int, end_year: int) -> list[TimeWindow]:
    return [
        TimeWindow(start=date(year, 1, 1), end=date(year, 12, 31), granularity="year", reason="coarse_year_scan")
        for year in range(start_year, end_year + 1)
    ]


def month_windows(year: int) -> list[TimeWindow]:
    out: list[TimeWindow] = []
    for month in range(1, 13):
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        out.append(TimeWindow(start=start, end=end, granularity="month", reason="zoom_month"))
    return out


def day_windows(year: int, month: int) -> list[TimeWindow]:
    out: list[TimeWindow] = []
    start = date(year, month, 1)
    end_month = 1 if month == 12 else month + 1
    end_year = year + 1 if month == 12 else year
    end = date(end_year, end_month, 1)
    current = start
    while current < end:
        next_day = current.fromordinal(current.toordinal() + 1)
        out.append(TimeWindow(start=current, end=next_day, granularity="day", reason="zoom_day"))
        current = next_day
    return out


def should_zoom_window(window: TimeWindow, *, source_count: int, claim_count: int, conflicting_claims: int = 0) -> bool:
    if window.granularity == "year":
        return source_count >= 2 or claim_count >= 1 or conflicting_claims > 0
    if window.granularity == "month":
        return claim_count >= 1 or conflicting_claims > 0
    return False


def build_role_queries(*, target_person: str, office_family: str, window: TimeWindow, language: str = "multi") -> list[str]:
    year = window.start.year
    month = f"{window.start.month:02d}" if window.granularity in {"month", "day"} else ""
    window_label = f"{year}-{month}" if month else str(year)
    queries = [
        f'"{target_person}" "{office_family}" {window_label}'.strip(),
        f'"Prime Minister" "{office_family}" Armenia {window_label}'.strip(),
        f'"Office of the Prime Minister" Armenia "{office_family}" {window_label}'.strip(),
        f'"վարչապետի աշխատակազմի ղեկավար" Հայաստան {window_label}'.strip(),
        f'"руководитель аппарата премьер-министра" Армения {window_label}'.strip(),
        f'"Chief of Staff of the Prime Minister" Armenia {window_label}'.strip(),
    ]
    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        normalized = re.sub(r"\s+", " ", query).strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped[:6]

