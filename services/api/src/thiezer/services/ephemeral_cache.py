from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(slots=True)
class _Entry[T]:
    value: T
    expires_at: datetime


class EphemeralTtlCache[T]:
    """Process-local TTL storage; keys must never contain user coordinates or signed URLs."""

    def __init__(self, *, now: Callable[[], datetime] | None = None) -> None:
        self._entries: dict[str, _Entry[T]] = {}
        self._now = now or (lambda: datetime.now(UTC))

    def get(self, key: str) -> T | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at <= self._now():
            self._entries.pop(key, None)
            return None
        return entry.value

    def put(self, key: str, value: T, *, ttl: timedelta) -> None:
        if (
            "latitude" in key.casefold()
            or "longitude" in key.casefold()
            or "token=" in key.casefold()
        ):
            raise ValueError("ephemeral cache keys must not contain coordinates or tokens")
        self._entries[key] = _Entry(value=value, expires_at=self._now() + ttl)

    def clear(self) -> None:
        self._entries.clear()
