from __future__ import annotations

from typing import Protocol

from thiezer.domain.contracts import GeoPoint
from thiezer.domain.static_scoring import RawSurfaceFeatures


class StaticLayerProvider(Protocol):
    @property
    def source_name(self) -> str: ...

    @property
    def attributions(self) -> tuple[str, ...]: ...

    @property
    def darkness_is_proxy(self) -> bool: ...

    async def evaluate_cells(self, cell_ids: list[str]) -> list[RawSurfaceFeatures]: ...

    async def evaluate_points(
        self,
        *,
        points: list[GeoPoint],
        resolution: int,
    ) -> list[RawSurfaceFeatures]: ...

    async def aclose(self) -> None: ...
