from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from thiezer.domain.contracts import (
    CandidatePlace,
    DiscoveryMetrics,
    EquipmentStore,
    GeoPoint,
    SearchScope,
    WarningCode,
)


@dataclass(frozen=True, slots=True)
class PlaceSearchBatch:
    matches: list[tuple[CandidatePlace, float]]
    coverage_country_codes: list[str]
    discovery_sources: list[str]
    attributions: list[str]
    warnings: list[WarningCode]
    metrics: DiscoveryMetrics = field(default_factory=DiscoveryMetrics)


@dataclass(frozen=True, slots=True)
class StoreSearchBatch:
    matches: list[tuple[EquipmentStore, float | None]]
    coverage_country_codes: list[str]
    discovery_sources: list[str]
    attributions: list[str]
    warnings: list[WarningCode]


class PlaceRepository(Protocol):
    async def search(
        self,
        *,
        user_location: GeoPoint,
        scope: SearchScope,
        country_code: str | None,
        max_distance_km: float,
        limit: int,
        include_unverified: bool = True,
    ) -> PlaceSearchBatch: ...


class StoreRepository(Protocol):
    async def search(
        self,
        *,
        user_location: GeoPoint,
        scope: SearchScope,
        country_code: str | None,
        max_distance_km: float,
        limit: int,
    ) -> StoreSearchBatch: ...
