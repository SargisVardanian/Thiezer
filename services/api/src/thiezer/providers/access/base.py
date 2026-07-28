from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from thiezer.domain.contracts import EquipmentStore, GeoPoint, PlaceKind, SurfaceCell


@dataclass(frozen=True, slots=True)
class AccessPoint:
    id: str
    name: str
    point: GeoPoint
    kind: PlaceKind
    country_code: str | None
    road_access: str
    source_url: str | None = None


class AccessPointProvider(Protocol):
    @property
    def source_name(self) -> str: ...

    @property
    def attribution(self) -> str: ...

    async def discover_access_points(
        self,
        *,
        cells: list[SurfaceCell],
        radius_km: float,
        limit_per_cell: int,
    ) -> dict[str, list[AccessPoint]]: ...

    async def discover_stores(
        self,
        *,
        user_location: GeoPoint,
        radius_km: float,
        limit: int,
    ) -> list[EquipmentStore]: ...

    async def aclose(self) -> None: ...
