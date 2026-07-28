from __future__ import annotations

from typing import Protocol

from thiezer.domain.contracts import GeoPoint, SurfaceCell


class StaticLayerProvider(Protocol):
    @property
    def source_name(self) -> str: ...

    @property
    def attribution(self) -> str: ...

    async def evaluate_cells(
        self,
        *,
        cell_ids: list[str],
        centers: list[GeoPoint],
        resolutions: list[int],
    ) -> list[SurfaceCell]: ...

    async def aclose(self) -> None: ...
