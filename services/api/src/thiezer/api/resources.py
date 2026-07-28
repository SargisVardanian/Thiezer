from __future__ import annotations

from dataclasses import dataclass

import httpx

from thiezer.config import Settings
from thiezer.domain.ephemeris import SkyfieldAstronomyProvider
from thiezer.providers.access.base import AccessPointProvider
from thiezer.providers.access.overpass import LocalOverpassAccessPointProvider
from thiezer.providers.access.procedural import ProceduralAccessPointProvider
from thiezer.providers.places.overpass import OverpassDiscoveryProvider
from thiezer.providers.static_layers.base import StaticLayerProvider
from thiezer.providers.static_layers.cog import CogLayerConfig, CogSurfaceLayerProvider
from thiezer.providers.static_layers.procedural import ProceduralSurfaceLayerProvider
from thiezer.providers.weather.open_meteo import OpenMeteoWeatherProvider
from thiezer.providers.weather.surface_elevation import SurfaceElevationWeatherProvider
from thiezer.repositories.adaptive import AdaptiveStoreRepository
from thiezer.repositories.seed import SeedStoreRepository
from thiezer.repositories.surface import SurfacePlaceRepository
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
    return AppResources(
        client=client,
        static_layers=static_layers,
        access_provider=access_provider,
        weather=weather,
        recommendation_service=recommendation_service,
        store_service=StoreSearchService(store_repository),
        visibility_service=VisibilityService(astronomy),
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
