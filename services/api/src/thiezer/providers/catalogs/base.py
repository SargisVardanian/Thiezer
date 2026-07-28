from __future__ import annotations

from typing import Protocol

from thiezer.domain.celestial_objects import CatalogSource, CelestialObject


class CatalogProviderError(RuntimeError):
    """A provider failure suitable for partial-failure fallback and circuit breakers."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class CatalogProvider(Protocol):
    source: CatalogSource
    attribution: str

    async def search(self, query: str, *, limit: int) -> list[CelestialObject]: ...

    async def get(self, object_id: str) -> CelestialObject | None: ...
