from __future__ import annotations

import math
from collections.abc import Iterable

import h3

from thiezer.domain.contracts import (
    CandidatePlace,
    DiscoveryMetrics,
    GeoPoint,
    PlaceKind,
    SearchScope,
    SurfaceCell,
    VerificationStatus,
    WarningCode,
)
from thiezer.domain.geospatial import haversine_distance_km
from thiezer.providers.access.base import AccessPoint, AccessPointProvider
from thiezer.providers.country import CountryResolver
from thiezer.providers.static_layers.base import StaticLayerProvider
from thiezer.repositories.base import PlaceRepository, PlaceSearchBatch


class SurfacePlaceRepository:
    """Global radius-first, surface-first observation-site discovery."""

    def __init__(
        self,
        *,
        seed_repository: PlaceRepository,
        static_provider: StaticLayerProvider,
        access_provider: AccessPointProvider | None,
        country_resolver: CountryResolver | None,
        coarse_parent_budget: int = 24,
        static_shortlist_budget: int = 60,
        local_access_radius_km: float = 6.0,
    ) -> None:
        self._seed = seed_repository
        self._static = static_provider
        self._access = access_provider
        self._countries = country_resolver
        self._coarse_parent_budget = max(4, coarse_parent_budget)
        self._static_shortlist_budget = max(10, static_shortlist_budget)
        self._local_access_radius_km = min(10.0, max(1.0, local_access_radius_km))

    async def search(
        self,
        *,
        user_location: GeoPoint,
        scope: SearchScope,
        country_code: str | None,
        max_distance_km: float,
        limit: int,
        include_unverified: bool = True,
    ) -> PlaceSearchBatch:
        seed_batch = await self._seed.search(
            user_location=user_location,
            scope=scope,
            country_code=country_code,
            max_distance_km=max_distance_km,
            limit=max(limit, 20),
            include_unverified=include_unverified,
        )
        warnings = list(seed_batch.warnings)
        sources = list(seed_batch.discovery_sources)
        attributions = list(seed_batch.attributions)

        coarse_resolution, refined_resolution = _resolutions_for_radius(max_distance_km)
        coarse_ids, coarse_centers = _cells_for_radius(
            origin=user_location,
            radius_km=max_distance_km,
            resolution=coarse_resolution,
        )
        coarse_cells = await self._static.evaluate_cells(
            cell_ids=coarse_ids,
            centers=coarse_centers,
            resolutions=[coarse_resolution] * len(coarse_ids),
        )
        coarse_cells = self._apply_country_policy(
            coarse_cells,
            scope=scope,
            country_code=country_code,
            warnings=warnings,
        )
        coarse_cells = [cell for cell in coarse_cells if _surface_allowed(cell)]
        parent_shortlist = _spatial_nms(
            sorted(coarse_cells, key=_surface_sort_key),
            minimum_separation_km=_coarse_separation_km(coarse_resolution),
            limit=self._coarse_parent_budget,
        )

        refined_ids = sorted(
            {
                child
                for parent in parent_shortlist
                for child in h3.cell_to_children(parent.h3_index, refined_resolution)
            }
        )
        refined_centers = [_cell_center(cell_id) for cell_id in refined_ids]
        refined_cells = await self._static.evaluate_cells(
            cell_ids=refined_ids,
            centers=refined_centers,
            resolutions=[refined_resolution] * len(refined_ids),
        )
        refined_cells = self._apply_country_policy(
            refined_cells,
            scope=scope,
            country_code=country_code,
            warnings=warnings,
        )
        refined_cells = [
            cell
            for cell in refined_cells
            if haversine_distance_km(user_location, cell.center) <= max_distance_km
            and _surface_allowed(cell)
        ]
        static_shortlist = _spatial_nms(
            sorted(refined_cells, key=_surface_sort_key),
            minimum_separation_km=_refined_separation_km(refined_resolution),
            limit=self._static_shortlist_budget,
        )

        access_cells = static_shortlist[: min(40, max(10, limit * 3))]
        access_by_cell: dict[str, list[AccessPoint]] = {}
        if self._access is not None and access_cells:
            try:
                access_by_cell = await self._access.discover_access_points(
                    cells=access_cells,
                    radius_km=self._local_access_radius_km,
                    limit_per_cell=3,
                )
                sources.append(self._access.source_name)
                attributions.append(self._access.attribution)
            except Exception:
                warnings.append(WarningCode.DISCOVERY_PROVIDER_UNAVAILABLE)

        dynamic_matches: list[tuple[CandidatePlace, float]] = []
        for cell in access_cells:
            points = access_by_cell.get(cell.h3_index, [])
            representative = _choose_access_point(cell, points)
            if representative is None:
                continue
            place = _materialize_place(cell, representative)
            if not include_unverified:
                continue
            if scope == SearchScope.COUNTRY and country_code is not None:
                if place.country_code != country_code:
                    continue
            distance = haversine_distance_km(user_location, place.point)
            if distance <= max_distance_km:
                dynamic_matches.append((place, distance))

        sources.append(self._static.source_name)
        attributions.append(self._static.attribution)
        if any(cell.uncertainty >= 0.8 for cell in static_shortlist):
            warnings.append(WarningCode.STATIC_LAYERS_FALLBACK)
        if not dynamic_matches and access_cells:
            warnings.append(WarningCode.ACCESS_POINT_UNAVAILABLE)

        merged = _merge_matches([*seed_batch.matches, *dynamic_matches])
        merged.sort(
            key=lambda item: (
                -item[0].darkness_score,
                item[0].static_uncertainty,
                item[1],
                item[0].id,
            )
        )
        coverage = sorted(
            {place.country_code for place, _ in merged if place.country_code is not None}
        )
        metrics = DiscoveryMetrics(
            coarse_cells_evaluated=len(coarse_cells),
            refined_cells_evaluated=len(refined_cells),
            static_shortlist_count=len(static_shortlist),
            access_cells_requested=len(access_cells),
            materialized_candidates=len(merged),
        )
        return PlaceSearchBatch(
            matches=merged[:limit],
            coverage_country_codes=coverage,
            discovery_sources=sorted(set(sources)),
            attributions=sorted(set(attributions)),
            warnings=list(dict.fromkeys(warnings)),
            metrics=metrics,
        )

    def _apply_country_policy(
        self,
        cells: list[SurfaceCell],
        *,
        scope: SearchScope,
        country_code: str | None,
        warnings: list[WarningCode],
    ) -> list[SurfaceCell]:
        if scope != SearchScope.COUNTRY:
            return cells
        if self._countries is None or country_code is None:
            warnings.append(WarningCode.COUNTRY_FILTER_APPROXIMATE)
            return [cell for cell in cells if cell.country_code in {None, country_code}]
        resolved = self._countries.resolve([cell.center for cell in cells])
        warnings.append(WarningCode.COUNTRY_FILTER_APPROXIMATE)
        return [
            cell.model_copy(update={"country_code": code})
            for cell, code in zip(cells, resolved, strict=True)
            if code == country_code
        ]


def _resolutions_for_radius(radius_km: float) -> tuple[int, int]:
    if radius_km <= 350.0:
        return 5, 7
    if radius_km <= 750.0:
        return 4, 6
    return 3, 5


def _cells_for_radius(
    *,
    origin: GeoPoint,
    radius_km: float,
    resolution: int,
) -> tuple[list[str], list[GeoPoint]]:
    origin_cell = h3.latlng_to_cell(origin.latitude_deg, origin.longitude_deg, resolution)
    edge_km = h3.average_hexagon_edge_length(resolution, unit="km")
    grid_radius = math.ceil(radius_km / max(0.5, 1.45 * edge_km)) + 2
    cells: list[str] = []
    centers: list[GeoPoint] = []
    tolerance = 2.0 * edge_km
    for cell_id in h3.grid_disk(origin_cell, grid_radius):
        center = _cell_center(cell_id)
        if haversine_distance_km(origin, center) <= radius_km + tolerance:
            cells.append(cell_id)
            centers.append(center)
    ordered = sorted(zip(cells, centers, strict=True), key=lambda item: item[0])
    return [item[0] for item in ordered], [item[1] for item in ordered]


def _cell_center(cell_id: str) -> GeoPoint:
    latitude, longitude = h3.cell_to_latlng(cell_id)
    return GeoPoint(latitude_deg=latitude, longitude_deg=longitude)


def _surface_allowed(cell: SurfaceCell) -> bool:
    return (
        cell.water_fraction <= 0.20
        and cell.urban_fraction <= 0.55
        and (cell.slope_deg is None or cell.slope_deg <= 15.0)
        and cell.restricted_fraction <= 0.10
        and cell.static_score >= 0.25
    )


def _surface_sort_key(cell: SurfaceCell) -> tuple[float, float, float, str]:
    # No user-distance term: this ranking is sky/surface quality only.
    return (-cell.upper_bound, -cell.static_score, cell.uncertainty, cell.h3_index)


def _spatial_nms(
    cells: Iterable[SurfaceCell],
    *,
    minimum_separation_km: float,
    limit: int,
) -> list[SurfaceCell]:
    selected: list[SurfaceCell] = []
    for cell in cells:
        if all(
            haversine_distance_km(cell.center, existing.center) >= minimum_separation_km
            for existing in selected
        ):
            selected.append(cell)
            if len(selected) >= limit:
                break
    return selected


def _coarse_separation_km(resolution: int) -> float:
    return max(12.0, h3.average_hexagon_edge_length(resolution, unit="km") * 2.0)


def _refined_separation_km(resolution: int) -> float:
    return max(3.0, h3.average_hexagon_edge_length(resolution, unit="km") * 3.0)


def _choose_access_point(
    cell: SurfaceCell,
    points: list[AccessPoint],
) -> AccessPoint | None:
    if not points:
        return None
    priorities = {
        PlaceKind.PARKING: 0,
        PlaceKind.VIEWPOINT: 1,
        PlaceKind.CAMPSITE: 2,
        PlaceKind.ROAD_ACCESS: 3,
        PlaceKind.OBSERVATORY: 4,
        PlaceKind.OBSERVATION_SITE: 5,
    }
    return min(
        points,
        key=lambda point: (
            priorities[point.kind],
            haversine_distance_km(cell.center, point.point),
            point.id,
        ),
    )


def _materialize_place(cell: SurfaceCell, access: AccessPoint) -> CandidatePlace:
    accessibility = {
        PlaceKind.PARKING: 0.90,
        PlaceKind.VIEWPOINT: 0.82,
        PlaceKind.CAMPSITE: 0.78,
        PlaceKind.ROAD_ACCESS: 0.62,
        PlaceKind.OBSERVATORY: 0.88,
        PlaceKind.OBSERVATION_SITE: 0.65,
    }[access.kind]
    terrain_risk = 0.0 if cell.slope_deg is None else min(1.0, cell.slope_deg / 25.0)
    roughness = cell.roughness_score or 0.0
    risk = min(
        1.0,
        0.40 * cell.restricted_fraction
        + 0.25 * terrain_risk
        + 0.25 * cell.uncertainty
        + 0.10 * roughness,
    )
    return CandidatePlace(
        id=f"surface-{cell.h3_index}-{access.id}",
        name=access.name,
        country_code=access.country_code or cell.country_code,
        region=None,
        point=access.point,
        elevation_m=float(cell.elevation_m or 0.0),
        kind=access.kind,
        verification_status=VerificationStatus.UNVERIFIED_DISCOVERED,
        darkness_score=cell.darkness_score,
        horizon_openness_score=cell.horizon_openness_score,
        accessibility_score=accessibility,
        risk_score=risk,
        road_access=access.road_access,
        notes="Surface-first candidate; legal access, parking and night safety are unverified.",
        source_url=access.source_url,
        source_provider=f"{cell.source}+local_access",
        darkness_model=(
            "viirs_surface_pack"
            if cell.viirs_radiance_nw_cm2_sr is not None
            else "uncertain_surface_fallback"
        ),
        surface_cell_id=cell.h3_index,
        static_uncertainty=cell.uncertainty,
    )


def _merge_matches(
    matches: list[tuple[CandidatePlace, float]],
) -> list[tuple[CandidatePlace, float]]:
    ordered = sorted(
        matches,
        key=lambda item: (
            _verification_rank(item[0].verification_status),
            item[0].static_uncertainty,
            -item[0].darkness_score,
            item[1],
        ),
    )
    selected: list[tuple[CandidatePlace, float]] = []
    for match in ordered:
        if all(
            haversine_distance_km(match[0].point, existing[0].point) >= 1.5
            for existing in selected
        ):
            selected.append(match)
    return selected


def _verification_rank(status: VerificationStatus) -> int:
    return {
        VerificationStatus.VERIFIED: 0,
        VerificationStatus.PARTNER_VERIFIED: 1,
        VerificationStatus.UNVERIFIED_SEED: 2,
        VerificationStatus.UNVERIFIED_DISCOVERED: 3,
    }[status]
