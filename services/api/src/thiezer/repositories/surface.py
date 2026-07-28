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
from thiezer.services.progress import ProgressCallback
from thiezer.services.surface_search import SurfaceSearchService

_RADIUS_TOLERANCE_KM = 0.5


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
        progress: ProgressCallback | None = None,
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
            progress=progress,
        )
        matches: list[tuple[CandidatePlace, float]] = []
        seen_ids: set[str] = set()
        seen_points: set[tuple[int, int]] = set()
        for site in result.sites:
            if (
                scope == SearchScope.COUNTRY
                and country_code
                and site.country_code not in {country_code, None}
            ):
                continue
            distance = haversine_distance_km(user_location, site.point)
            # H3 coverage includes cells intersecting the circle. Access materialization can move
            # the representative point outside it, so the final point must be checked again.
            if distance > max_distance_km + _RADIUS_TOLERANCE_KM:
                continue
            point_key = (
                round(site.point.latitude_deg * 100_000),
                round(site.point.longitude_deg * 100_000),
            )
            if site.id in seen_ids or point_key in seen_points:
                continue
            seen_ids.add(site.id)
            seen_points.add(point_key)
            place = CandidatePlace(
                id=site.id,
                name=site.name,
                country_code=(country_code if scope == SearchScope.COUNTRY else site.country_code),
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
            matches.append((place, distance))

        # Bright targets are often best observed without travelling. The origin is deliberately
        # assigned extremely poor/unknown darkness so deep-sky profiles will reject it while Moon,
        # planet and bright-star profiles can still recommend "stay here" when conditions permit.
        origin_key = (
            round(user_location.latitude_deg * 100_000),
            round(user_location.longitude_deg * 100_000),
        )
        if origin_key not in seen_points:
            matches.append(
                (
                    CandidatePlace(
                        id=(
                            "observer-location:"
                            f"{origin_key[0]:+d}:{origin_key[1]:+d}"
                        ),
                        name="Текущая позиция",
                        country_code=country_code if scope == SearchScope.COUNTRY else None,
                        region=None,
                        point=user_location,
                        elevation_m=0.0,
                        kind=PlaceKind.OBSERVATION_SITE,
                        verification_status=VerificationStatus.UNVERIFIED_DISCOVERED,
                        darkness_score=0.001,
                        horizon_openness_score=0.50,
                        accessibility_score=1.0,
                        risk_score=0.05,
                        road_access="Current observer location; local horizon is not measured",
                        notes=(
                            "No travel required. Darkness and local horizon are deliberately "
                            "unknown and must not be presented as calibrated values."
                        ),
                        source_provider="user_origin",
                        darkness_model="unknown_origin_proxy",
                    ),
                    0.0,
                )
            )

        matches.sort(key=lambda item: (item[1], -item[0].darkness_score, item[0].id))
        warnings = [WarningCode.DARKNESS_IS_PROXY] if result.darkness_is_proxy else []
        coverage = sorted({place.country_code for place, _ in matches if place.country_code})
        if scope == SearchScope.COUNTRY and country_code and matches:
            coverage = [country_code]
        return PlaceSearchBatch(
            matches=matches[:limit],
            coverage_country_codes=coverage,
            discovery_sources=["h3_surface_search", "local_access_materialization"],
            attributions=list(result.attributions),
            warnings=warnings,
        )
