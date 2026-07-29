from __future__ import annotations

from thiezer.domain.boundaries import CountryBoundaryProvider, StaticCountryBoundaryProvider
from thiezer.domain.contracts import GeoPoint, SearchScope
from thiezer.domain.geospatial import haversine_distance_km
from thiezer.domain.search_cells import choose_h3_search_plan, cover_circle, refine_cells
from thiezer.domain.spatial_diversity import spatial_nms
from thiezer.domain.static_scoring import (
    StaticFilterPolicy,
    passes_static_filters,
    score_raw_features,
)
from thiezer.domain.surface import (
    SurfaceCell,
    SurfaceSearchBudget,
    SurfaceSearchDiagnostics,
    SurfaceSearchResult,
)
from thiezer.providers.access.base import AccessPointProvider
from thiezer.providers.static_layers.base import StaticLayerProvider
from thiezer.services.progress import ProgressCallback, report_progress


class SurfaceSearchService:
    def __init__(
        self,
        *,
        static_layers: StaticLayerProvider,
        access_provider: AccessPointProvider,
        budget: SurfaceSearchBudget | None = None,
        filter_policy: StaticFilterPolicy | None = None,
        boundary_provider: CountryBoundaryProvider | None = None,
    ) -> None:
        self._static = static_layers
        self._access = access_provider
        self._budget = budget or SurfaceSearchBudget()
        self._filter_policy = filter_policy or StaticFilterPolicy()
        self._boundaries = boundary_provider or StaticCountryBoundaryProvider()

    async def search(
        self,
        *,
        user_location: GeoPoint,
        scope: SearchScope,
        country_code: str | None,
        max_distance_km: float,
        limit: int,
        progress: ProgressCallback | None = None,
    ) -> SurfaceSearchResult:
        if scope == SearchScope.COUNTRY and (
            country_code is None or not self._boundaries.supports(country_code)
        ):
            return self._empty_result(max_distance_km)

        await report_progress(progress, "generating_cells")
        plan = choose_h3_search_plan(max_distance_km)
        coarse_ids = cover_circle(
            user_location,
            max_distance_km,
            plan.coarse_resolution,
        )
        await report_progress(progress, "fetching_elevation")
        await report_progress(progress, "reading_surface_windows")
        coarse_raw = await self._static.evaluate_cells(coarse_ids)
        coarse = [score_raw_features(item) for item in coarse_raw]
        coarse = self._apply_boundary(coarse, scope, country_code)
        await report_progress(progress, "applying_static_filters")
        coarse_filtered = [
            cell for cell in coarse if passes_static_filters(cell, self._filter_policy)
        ]
        parents = spatial_nms(
            coarse_filtered,
            point=lambda cell: cell.center,
            score=lambda cell: cell.static_upper_bound,
            min_separation_km=self._budget.coarse_min_separation_km,
            limit=self._budget.coarse_parent_limit,
        )

        fine_ids = refine_cells(
            (cell.h3_index for cell in parents),
            plan.fine_resolution,
        )
        await report_progress(progress, "reading_surface_windows")
        fine_raw = await self._static.evaluate_cells(fine_ids)
        fine = [score_raw_features(item) for item in fine_raw]
        fine = self._apply_boundary(fine, scope, country_code)
        fine_filtered = [cell for cell in fine if passes_static_filters(cell, self._filter_policy)]
        selected_fine = spatial_nms(
            fine_filtered,
            point=lambda cell: cell.center,
            score=lambda cell: cell.static_score,
            min_separation_km=self._budget.fine_min_separation_km,
            limit=self._budget.fine_cell_limit,
        )

        await report_progress(progress, "checking_access")
        sites = await self._access.materialize_sites(
            cells=selected_fine,
            maximum_sites=self._budget.materialized_site_limit,
        )
        # Materialized access points are sampled inside H3 cells. Keep the hard radius
        # before ranking/truncating; otherwise a cross-border search can spend every
        # available slot on attractive but distant points and leave no local destination.
        sites = [
            site
            for site in sites
            if haversine_distance_km(user_location, site.point) <= max_distance_km
        ]
        # An H3 cell may straddle a border and a sampled access point can land on the
        # other side. Re-apply the requested country boundary before ranking or truncating.
        if scope == SearchScope.COUNTRY and country_code is not None:
            sites = [site for site in sites if self._boundaries.contains(country_code, site.point)]
        selected_sites = spatial_nms(
            sites,
            point=lambda site: site.point,
            score=lambda site: site.cell.static_score,
            min_separation_km=self._budget.site_min_separation_km,
            limit=min(self._budget.weather_candidate_limit, max(1, limit)),
        )
        diagnostics = SurfaceSearchDiagnostics(
            coarse_resolution=plan.coarse_resolution,
            fine_resolution=plan.fine_resolution,
            coarse_cells=len(coarse_ids),
            coarse_after_filters=len(coarse_filtered),
            selected_parents=len(parents),
            fine_cells=len(fine_ids),
            fine_after_filters=len(fine_filtered),
            selected_fine_cells=len(selected_fine),
            materialized_sites=len(sites),
            weather_candidates=len(selected_sites),
            static_evaluations=len(coarse_ids) + len(fine_ids),
            large_radius_overpass_calls=self._access.large_radius_calls,
        )
        attributions = tuple(dict.fromkeys([*self._static.attributions, self._access.attribution]))
        return SurfaceSearchResult(
            sites=selected_sites,
            diagnostics=diagnostics,
            attributions=attributions,
            darkness_is_proxy=self._static.darkness_is_proxy,
        )

    def _apply_boundary(
        self,
        cells: list[SurfaceCell],
        scope: SearchScope,
        country_code: str | None,
    ) -> list[SurfaceCell]:
        if scope != SearchScope.COUNTRY or country_code is None:
            return cells
        return [cell for cell in cells if self._boundaries.contains(country_code, cell.center)]

    def _empty_result(self, max_distance_km: float) -> SurfaceSearchResult:
        plan = choose_h3_search_plan(max_distance_km)
        return SurfaceSearchResult(
            sites=[],
            diagnostics=SurfaceSearchDiagnostics(
                coarse_resolution=plan.coarse_resolution,
                fine_resolution=plan.fine_resolution,
                coarse_cells=0,
                coarse_after_filters=0,
                selected_parents=0,
                fine_cells=0,
                fine_after_filters=0,
                selected_fine_cells=0,
                materialized_sites=0,
                weather_candidates=0,
                static_evaluations=0,
                large_radius_overpass_calls=0,
            ),
            attributions=tuple(self._static.attributions),
            darkness_is_proxy=self._static.darkness_is_proxy,
        )
