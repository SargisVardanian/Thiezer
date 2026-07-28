from __future__ import annotations

from typing import Protocol

from thiezer.domain.surface import SurfaceCell, SurfaceSite


class AccessPointProvider(Protocol):
    source_name: str
    attribution: str
    large_radius_calls: int

    async def materialize_sites(
        self,
        *,
        cells: list[SurfaceCell],
        maximum_sites: int,
    ) -> list[SurfaceSite]: ...

    async def aclose(self) -> None: ...
