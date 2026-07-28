from __future__ import annotations

import pytest

from thiezer.domain.contracts import GeoPoint, SearchScope
from thiezer.repositories.seed import SeedPlaceRepository
from thiezer.repositories.surface import (
    SurfacePlaceRepository,
    _cells_for_radius,
    _refined_separation_km,
    _spatial_nms,
    _surface_allowed,
    _surface_sort_key,
)
from test_surface_repository import RecordingAccessProvider, SyntheticStaticProvider


@pytest.mark.asyncio
async def test_armenia_radius_coarse_to_fine_matches_exhaustive_static_oracle() -> None:
    origin = GeoPoint(latitude_deg=40.1772, longitude_deg=44.5035)
    radius_km = 250.0
    static = SyntheticStaticProvider()
    access = RecordingAccessProvider()
    repository = SurfacePlaceRepository(
        seed_repository=SeedPlaceRepository([]),
        static_provider=static,
        access_provider=access,
        country_resolver=None,
        coarse_parent_budget=24,
        static_shortlist_budget=60,
    )
    production = await repository.search(
        user_location=origin,
        scope=SearchScope.ADAPTIVE,
        country_code=None,
        max_distance_km=radius_km,
        limit=10,
        include_unverified=True,
    )

    oracle_ids, oracle_centers = _cells_for_radius(
        origin=origin,
        radius_km=radius_km,
        resolution=7,
    )
    oracle_cells = await static.evaluate_cells(
        cell_ids=oracle_ids,
        centers=oracle_centers,
        resolutions=[7] * len(oracle_ids),
    )
    oracle = _spatial_nms(
        sorted((cell for cell in oracle_cells if _surface_allowed(cell)), key=_surface_sort_key),
        minimum_separation_km=_refined_separation_km(7),
        limit=10,
    )
    expected = {cell.h3_index for cell in oracle}
    actual = {
        place.surface_cell_id
        for place, _ in production.matches
        if place.surface_cell_id is not None
    }
    recall = len(expected & actual) / max(1, len(expected))
    best_regret = oracle[0].static_score - production.matches[0][0].darkness_score

    assert recall >= 0.95
    assert best_regret <= 0.02
    assert access.radii and max(access.radii) <= 10.0
    assert production.metrics.access_cells_requested <= 40
    assert len(actual) == len(production.matches)
