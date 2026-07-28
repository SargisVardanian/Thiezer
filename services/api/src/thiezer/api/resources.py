from __future__ import annotations

from dataclasses import dataclass

import httpx

from thiezer.config import Settings
from thiezer.domain.celestial_objects import (
    CatalogSource,
    CelestialCoordinates,
    CelestialObject,
    CelestialObjectClass,
    CelestialObjectId,
)
from thiezer.domain.ephemeris import SkyfieldAstronomyProvider
from thiezer.providers.access.base import AccessPointProvider
from thiezer.providers.access.overpass import LocalOverpassAccessPointProvider
from thiezer.providers.access.procedural import ProceduralAccessPointProvider
from thiezer.providers.catalogs.exoplanet_archive import ExoplanetArchiveProvider
from thiezer.providers.catalogs.gaia import GaiaCatalogProvider
from thiezer.providers.catalogs.ned import NedCatalogProvider
from thiezer.providers.catalogs.simbad import simbad_fixture
from thiezer.providers.catalogs.skyfield import SkyfieldPresetCatalogProvider
from thiezer.providers.catalogs.vizier import VizierCatalogProvider
from thiezer.providers.places.overpass import OverpassDiscoveryProvider
from thiezer.providers.static_layers.base import StaticLayerProvider
from thiezer.providers.static_layers.cog import CogLayerConfig, CogSurfaceLayerProvider
from thiezer.providers.static_layers.procedural import ProceduralSurfaceLayerProvider
from thiezer.providers.weather.open_meteo import OpenMeteoWeatherProvider
from thiezer.providers.weather.surface_elevation import SurfaceElevationWeatherProvider
from thiezer.repositories.adaptive import AdaptiveStoreRepository
from thiezer.repositories.seed import SeedStoreRepository
from thiezer.repositories.surface import SurfacePlaceRepository
from thiezer.services.celestial_resolution import CelestialResolutionService
from thiezer.services.celestial_visibility import CelestialVisibilityService
from thiezer.services.query_jobs import EphemeralQueryJobs
from thiezer.services.recommendations import RecommendationService
from thiezer.services.stores import StoreSearchService
from thiezer.services.surface_search import SurfaceSearchService
from thiezer.services.visibility import VisibilityService


@dataclass(slots=True)
class AppResources:
    client: httpx.AsyncClient
    static_layers: StaticLayerProvider
    access_provider: AccessPointProvider
    weather: OpenMeteoWeatherProvider
    recommendation_service: RecommendationService
    store_service: StoreSearchService
    visibility_service: VisibilityService
    celestial_resolution: CelestialResolutionService
    celestial_visibility: CelestialVisibilityService
    query_jobs: EphemeralQueryJobs
    store_overpass: OverpassDiscoveryProvider | None

    async def aclose(self) -> None:
        await self.weather.aclose()
        if self.store_overpass is not None:
            await self.store_overpass.aclose()
        await self.access_provider.aclose()
        await self.static_layers.aclose()
        await self.client.aclose()


def build_resources(settings: Settings) -> AppResources:
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=5.0,
            read=max(30.0, settings.overpass_timeout_seconds),
            write=10.0,
            pool=5.0,
        ),
        limits=httpx.Limits(max_connections=24, max_keepalive_connections=12),
        follow_redirects=False,
        headers={"User-Agent": "Thiezer/0.4 (+https://github.com/SargisVardanian/Thiezer)"},
    )
    static_layers = _build_static_layers(settings)
    if settings.overpass_enabled:
        access_provider: AccessPointProvider = LocalOverpassAccessPointProvider(
            base_url=str(settings.overpass_base_url),
            static_layers=static_layers,
            client=client,
            local_radius_km=settings.overpass_local_radius_km,
        )
        store_overpass = OverpassDiscoveryProvider(
            base_url=str(settings.overpass_base_url),
            client=client,
            timeout_seconds=settings.overpass_timeout_seconds,
        )
    else:
        access_provider = ProceduralAccessPointProvider(static_layers)
        store_overpass = None

    surface_search = SurfaceSearchService(
        static_layers=static_layers,
        access_provider=access_provider,
    )
    weather = OpenMeteoWeatherProvider(
        base_url=str(settings.open_meteo_base_url),
        api_key=settings.open_meteo_api_key,
        client=client,
    )
    elevation_weather = SurfaceElevationWeatherProvider(
        delegate=weather,
        static_layers=static_layers,
    )
    astronomy = SkyfieldAstronomyProvider()
    recommendation_service = RecommendationService(
        place_repository=SurfacePlaceRepository(surface_search),
        weather_provider=elevation_weather,
        astronomy_provider=astronomy,
    )
    store_repository = AdaptiveStoreRepository(
        seed_repository=SeedStoreRepository(),
        discovery_provider=store_overpass,
    )
    celestial_resolution = _build_celestial_resolution()
    return AppResources(
        client=client,
        static_layers=static_layers,
        access_provider=access_provider,
        weather=weather,
        recommendation_service=recommendation_service,
        store_service=StoreSearchService(store_repository),
        visibility_service=VisibilityService(astronomy),
        celestial_resolution=celestial_resolution,
        celestial_visibility=CelestialVisibilityService(celestial_resolution),
        query_jobs=EphemeralQueryJobs(
            recommendation_service, ttl_seconds=settings.query_ttl_seconds
        ),
        store_overpass=store_overpass,
    )


def _build_static_layers(settings: Settings) -> StaticLayerProvider:
    if settings.surface_provider == "cog":
        assert settings.dem_cog_url is not None
        assert settings.worldcover_cog_url is not None
        return CogSurfaceLayerProvider(
            CogLayerConfig(
                dem_url=settings.dem_cog_url,
                worldcover_url=settings.worldcover_cog_url,
                viirs_url=settings.viirs_cog_url,
            )
        )
    return ProceduralSurfaceLayerProvider()


def _build_celestial_resolution() -> CelestialResolutionService:
    """Offline fixtures make the default local runtime deterministic and network-free.

    Production deployments may replace these adapters with configured TAP clients; only the
    normalized object contract reaches API callers.
    """
    host = CelestialObject(
        identifier=CelestialObjectId(provider=CatalogSource.SIMBAD, object_id="51 Peg"),
        name="51 Pegasi",
        aliases=("51 Peg",),
        object_class=CelestialObjectClass.STAR,
        coordinates=CelestialCoordinates(right_ascension_deg=344.366, declination_deg=20.768),
        attribution="SIMBAD, CDS, Strasbourg",
    )
    planet = CelestialObject(
        identifier=CelestialObjectId(
            provider=CatalogSource.EXOPLANET_ARCHIVE, object_id="51 Peg b"
        ),
        name="51 Pegasi b",
        aliases=("Dimidium",),
        object_class=CelestialObjectClass.EXOPLANET,
        host_star=host.identifier,
        attribution="NASA Exoplanet Archive",
    )
    m31 = CelestialObject(
        identifier=CelestialObjectId(provider=CatalogSource.NED, object_id="M 31"),
        name="Andromeda Galaxy",
        aliases=("M31", "NGC 224"),
        object_class=CelestialObjectClass.GALAXY,
        coordinates=CelestialCoordinates(right_ascension_deg=10.684708, declination_deg=41.26875),
        attribution="NASA/IPAC Extragalactic Database (NED)",
    )
    m42 = CelestialObject(
        identifier=CelestialObjectId(provider=CatalogSource.VIZIER, object_id="M 42"),
        name="Orion Nebula",
        aliases=("M42", "NGC 1976"),
        object_class=CelestialObjectClass.NEBULA,
        coordinates=CelestialCoordinates(right_ascension_deg=83.822083, declination_deg=-5.391111),
        attribution="VizieR catalogue service, CDS, Strasbourg",
    )
    return CelestialResolutionService(
        {
            CatalogSource.SIMBAD: simbad_fixture(),
            CatalogSource.GAIA: GaiaCatalogProvider(),
            CatalogSource.VIZIER: VizierCatalogProvider(fixtures={"m 42": m42, "m42": m42}),
            CatalogSource.NED: NedCatalogProvider(fixtures={"m 31": m31, "m31": m31}),
            CatalogSource.EXOPLANET_ARCHIVE: ExoplanetArchiveProvider(
                fixtures={"51 peg b": planet, "dimidium": planet}
            ),
            CatalogSource.SKYFIELD: SkyfieldPresetCatalogProvider(),
        }
    )
