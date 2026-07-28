from __future__ import annotations

from typing import Protocol

from thiezer.domain.contracts import CandidatePlace, EquipmentStore, GeoPoint


class PlaceDiscoveryProvider(Protocol):
    @property
    def attribution(self) -> str: ...

    @property
    def source_name(self) -> str: ...

    async def discover_places(
        self,
        *,
        user_location: GeoPoint,
        radius_km: float,
        limit: int,
    ) -> list[CandidatePlace]: ...

    async def discover_stores(
        self,
        *,
        user_location: GeoPoint,
        radius_km: float,
        limit: int,
    ) -> list[EquipmentStore]: ...

    async def aclose(self) -> None: ...
