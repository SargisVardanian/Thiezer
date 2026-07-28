from __future__ import annotations

from thiezer.domain.contracts import (
    CandidatePlace,
    GeoPoint,
    PlaceKind,
    SearchScope,
    VerificationStatus,
    WarningCode,
)
from thiezer.domain.geospatial import haversine_distance_km
from thiezer.repositories.base import PlaceSearchBatch
from thiezer.services.surface_search import SurfaceSearchService


class SurfacePlaceRepository:
    def __init__(self, search_service: SurfaceSearchService) -> None:
        self._search = search_service

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
        if not include_unverified:
            return PlaceSearchBatch(
                matches=[],
                coverage_country_codes=[],
                discovery_sources=["h3_surface_search"],
                attributions=[],
                warnings=[WarningCode.NO_CANDIDATE_PLACES],
            )
        result = await self._search.search(
            user_location=user_location,
            scope=scope,
            country_code=country_code,
            max_distance_km=max_distance_km,
            limit=limit,
        )
        matches: list[tuple[CandidatePlace, float]] = []
        for site in result.sites:
            if (
                scope == SearchScope.COUNTRY
                and country_code
                and site.country_code not in {country_code, None}
            ):
                continue
            place = CandidatePlace(
                id=site.id,
                name=site.name,
                country_code=(
                    country_code
                    if scope == SearchScope.COUNTRY
                    else site.country_code
                ),
                region=site.region,
                point=site.point,
                elevation_m=site.elevation_m,
                kind=PlaceKind.OBSERVATION_SITE,
                verification_status=VerificationStatus.UNVERIFIED_DISCOVERED,
                darkness_score=site.cell.darkness_score,
                horizon_openness_score=site.horizon_openness_score,
                accessibility_score=site.accessibility_score,
                risk_score=site.risk_score,
                road_access=site.road_access,
                notes=(
                    f"H3 surface-first candidate. slope={site.slope_deg:.1f}°, "
                    f"roughness={site.cell.roughness_m:.0f} m, "
                    f"static_score={site.cell.static_score:.3f}. "
                    "Legal access, road condition, parking and nighttime safety "
                    "require validation."
                ),
                source_url=site.source_url,
                source_provider=site.source_provider,
                darkness_model=(
                    "viirs_multiscale_raster_v1"
                    if not result.darkness_is_proxy
                    else "surface_light_proxy_v1"
                ),
            )
            distance = haversine_distance_km(user_location, site.point)
            matches.append((place, distance))
        warnings = [WarningCode.DARKNESS_IS_PROXY] if result.darkness_is_proxy else []
        coverage = sorted(
            {place.country_code for place, _ in matches if place.country_code}
        )
        if scope == SearchScope.COUNTRY and country_code and matches:
            coverage = [country_code]
        return PlaceSearchBatch(
            matches=matches[:limit],
            coverage_country_codes=coverage,
            discovery_sources=["h3_surface_search", "local_access_materialization"],
            attributions=list(result.attributions),
            warnings=warnings,
        )
