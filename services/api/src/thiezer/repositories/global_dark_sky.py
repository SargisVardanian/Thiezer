from __future__ import annotations

from dataclasses import dataclass

from thiezer.domain.contracts import CandidatePlace, GeoPoint, PlaceKind, VerificationStatus
from thiezer.domain.geospatial import haversine_distance_km
from thiezer.repositories.base import PlaceSearchBatch

_DARKSKY_PLACES_URL = "https://darksky.org/what-we-do/international-dark-sky-places/all-places/"
_OSM_ATTRIBUTION = "Coordinates resolved from OpenStreetMap geocoding; see place source links"


@dataclass(frozen=True, slots=True)
class GlobalDarkSkyPlace:
    """A real, curated global destination used when global raster data is unavailable.

    The darkness value is a catalog prior, not a satellite measurement. Keeping this
    separate from the H3 surface provider prevents an Armenia-only proxy from being
    extrapolated over the rest of the planet.
    """

    id: str
    name: str
    country_code: str
    region: str
    point: GeoPoint
    catalog_url: str = _DARKSKY_PLACES_URL
    darkness_prior: float = 0.86


# DarkSky International's public place finder is the authoritative seed catalog.
# These are representative destinations, not a claim that this small fixture is
# exhaustive. A global calibrated VIIRS/DEM provider can replace this catalog later.
GLOBAL_DARK_SKY_PLACES: tuple[GlobalDarkSkyPlace, ...] = (
    GlobalDarkSkyPlace(
        "darksky:namibrand",
        "NamibRand Nature Reserve",
        "NA",
        "Hardap",
        GeoPoint(latitude_deg=-25.2108013, longitude_deg=15.9830678),
        darkness_prior=0.95,
    ),
    GlobalDarkSkyPlace(
        "darksky:teide",
        "Teide National Park",
        "ES",
        "Canary Islands",
        GeoPoint(latitude_deg=28.2687962, longitude_deg=-16.6374029),
        darkness_prior=0.90,
    ),
    GlobalDarkSkyPlace(
        "darksky:anza-borrego",
        "Anza-Borrego Desert State Park",
        "US",
        "California",
        GeoPoint(latitude_deg=33.0955355, longitude_deg=-116.3018977),
        darkness_prior=0.91,
    ),
    GlobalDarkSkyPlace(
        "darksky:big-bend",
        "Big Bend National Park",
        "US",
        "Texas",
        GeoPoint(latitude_deg=29.3332484, longitude_deg=-103.1943284),
        darkness_prior=0.94,
    ),
    GlobalDarkSkyPlace(
        "darksky:natural-bridges",
        "Natural Bridges National Monument",
        "US",
        "Utah",
        GeoPoint(latitude_deg=37.6025953, longitude_deg=-110.0111751),
        darkness_prior=0.94,
    ),
    GlobalDarkSkyPlace(
        "darksky:aotea",
        "Aotea / Great Barrier Island",
        "NZ",
        "Auckland",
        GeoPoint(latitude_deg=-36.1994214, longitude_deg=175.4172916),
        darkness_prior=0.89,
    ),
    GlobalDarkSkyPlace(
        "darksky:warrumbungle",
        "Warrumbungle National Park",
        "AU",
        "New South Wales",
        GeoPoint(latitude_deg=-31.2490573, longitude_deg=148.9702761),
        darkness_prior=0.92,
    ),
    GlobalDarkSkyPlace(
        "darksky:alula",
        "AlUla Dark Sky Parks",
        "SA",
        "Al Madinah",
        GeoPoint(latitude_deg=26.5588965, longitude_deg=37.9596519),
        darkness_prior=0.92,
    ),
)


def search_global_dark_sky_places(*, user_location: GeoPoint, limit: int) -> PlaceSearchBatch:
    matches: list[tuple[CandidatePlace, float]] = []
    for item in GLOBAL_DARK_SKY_PLACES:
        distance = haversine_distance_km(user_location, item.point)
        matches.append(
            (
                CandidatePlace(
                    id=item.id,
                    name=item.name,
                    country_code=item.country_code,
                    region=item.region,
                    point=item.point,
                    elevation_m=0.0,
                    kind=PlaceKind.OBSERVATION_SITE,
                    verification_status=VerificationStatus.VERIFIED,
                    darkness_score=item.darkness_prior,
                    horizon_openness_score=0.82,
                    accessibility_score=0.55,
                    risk_score=0.20,
                    road_access="Road access must be checked for the selected destination",
                    notes=(
                        "DarkSky International catalog destination. Darkness is a catalog "
                        "prior, not a calibrated VIIRS measurement; local access, elevation, "
                        "horizon and safety still require verification."
                    ),
                    source_url=item.catalog_url,
                    source_provider="darksky_catalog_v1",
                    darkness_model="darksky_catalog_prior_v1",
                ),
                distance,
            )
        )
    matches.sort(key=lambda item: (-item[0].darkness_score, item[1], item[0].id))
    return PlaceSearchBatch(
        matches=matches[:limit],
        coverage_country_codes=sorted(
            {item[0].country_code for item in matches if item[0].country_code}
        ),
        discovery_sources=["darksky_catalog_v1"],
        attributions=[_DARKSKY_PLACES_URL, _OSM_ATTRIBUTION],
        warnings=[],
    )
