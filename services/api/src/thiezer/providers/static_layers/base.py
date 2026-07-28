from __future__ import annotations

from typing import Protocol

from thiezer.domain.contracts import GeoPoint
from thiezer.domain.static_scoring import RawSurfaceFeatures


class StaticLayerProvider(Protocol):
    source_name: str
    attributions: tuple[str, ...]
    darkness_is_proxy: bool

    async def evaluate_cells(self, cell_ids: list[str]) -> list[RawSurfaceFeatures]: ...

    async def evaluate_points(
        self,
        *,
        points: list[GeoPoint],
        resolution: int,
    ) -> list[RawSurfaceFeatures]: ...

    async def aclose(self) -> None: ...
