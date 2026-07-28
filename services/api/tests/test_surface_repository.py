from __future__ import annotations

import h3
import pytest

from thiezer.domain.contracts import (
    GeoPoint,
    PlaceKind,
    SearchScope,
    SurfaceCell,
)
from thiezer.providers.access.base import AccessPoint
from thiezer.repositories.seed import SeedPlaceRepository
from thiezer.repositories.surface import SurfacePlaceRepository


class SyntheticStaticProvider:
    source_name = "synthetic_surface"
    attribution = "Synthetic test surface"

    async def evaluate_cells(
        self,
        *,
        cell_ids: list[str],
        centers: list[GeoPoint],
        resolutions: list[int],
    ) -> list[SurfaceCell]:
        result: list[SurfaceCell] = []
        for cell_id, center, resolution in zip(cell_ids, centers, resolutions, strict=True):
            parent = h3.cell_to_parent(cell_id, min(5, resolution))
            parent_signal = (int(parent[-5:], 16) % 700) / 1000.0
            child_signal = (int(cell_id[-4:], 16) % 30) / 3000.0
            score = min(0.95, 0.25 + parent_signal + child_signal)
            result.append(
                SurfaceCell(
                    h3_index=cell_id,
                    resolution=resolution,
                    center=center,
                    country_code=None,
                    elevation_m=1200.0,
                    slope_deg=3.0,
                    roughness_score=0.1,
                    viirs_radiance_nw_cm2_sr=0.2,
                    darkness_score=score,
                    water_fraction=0.0,
                    urban_fraction=0.05,
                    forest_fraction=0.2,
                    restricted_fraction=0.0,
                    distance_to_road_km=1.0,
                    distance_to_settlement_km=20.0,
                    horizon_openness_score=0.9,
                    static_score=score,
                    upper_bound=min(1.0, score + 0.02),
                    uncertainty=0.1,
                    source=self.source_name,
                )
            )
        return result

    async def aclose(self) -> None:
        return None


class RecordingAccessProvider:
    source_name = "synthetic_access"
    attribution = "Synthetic test access"

    def __init__(self) -> None:
        self.radii: list[float] = []
        self.cells_requested = 0

    async def discover_access_points(
        self,
        *,
        cells: list[SurfaceCell],
        radius_km: float,
        limit_per_cell: int,
    ) -> dict[str, list[AccessPoint]]:
        del limit_per_cell
        self.radii.append(radius_km)
        self.cells_requested += len(cells)
        return {
            cell.h3_index: [
                AccessPoint(
                    id=f"access-{cell.h3_index}",
                    name=f"Access {cell.h3_index[-5:]}",
                    point=cell.center,
                    kind=PlaceKind.PARKING,
                    country_code=None,
                    road_access="synthetic parking",
                )
            ]
            for cell in cells
        }

    async def discover_stores(self, **_: object) -> list[object]:
        return []

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_surface_search_is_radius_bounded_and_uses_only_local_access_queries() -> None:
    access = RecordingAccessProvider()
    repository = SurfacePlaceRepository(
        seed_repository=SeedPlaceRepository([]),
        static_provider=SyntheticStaticProvider(),
        access_provider=access,
        country_resolver=None,
    )
    origin = GeoPoint(latitude_deg=40.1772, longitude_deg=44.5035)
    batch = await repository.search(
        user_location=origin,
        scope=SearchScope.ADAPTIVE,
        country_code=None,
        max_distance_km=250.0,
        limit=10,
        include_unverified=True,
    )
    assert batch.matches
    assert all(distance <= 250.0 for _, distance in batch.matches)
    assert access.radii and max(access.radii) <= 10.0
    assert batch.metrics.coarse_cells_evaluated > 0
    assert batch.metrics.refined_cells_evaluated > batch.metrics.coarse_cells_evaluated
    assert batch.metrics.access_cells_requested <= 40
    assert len({place.surface_cell_id for place, _ in batch.matches}) == len(batch.matches)
