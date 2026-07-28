from __future__ import annotations

from dataclasses import dataclass

import httpx
from fastapi import Request

from thiezer.config import Settings, get_settings
from thiezer.domain.ephemeris import SkyfieldAstronomyProvider
from thiezer.providers.access.overpass import OverpassAccessProvider
from thiezer.providers.country import CountryResolver
from thiezer.providers.static_layers.elevation import OpenMeteoElevationProvider
from thiezer.providers.static_layers.hybrid import HybridStaticLayerProvider
from thiezer.providers.weather.open_meteo import OpenMeteoWeatherProvider
from thiezer.repositories.adaptive import AdaptiveStoreRepository
from thiezer.repositories.seed import SeedPlaceRepository, SeedStoreRepository
from thiezer.repositories.surface import SurfacePlaceRepository
from thiezer.services.recommendations import RecommendationService
from thiezer.services.stores import StoreSearchService
from thiezer.services.visibility import VisibilityService


@dataclass(slots=True)
class RuntimeServices:
    client: httpx.AsyncClient
    weather: OpenMeteoWeatherProvider
    astronomy: SkyfieldAstronomyProvider
    place_repository: SurfacePlaceRepository
    store_repository: AdaptiveStoreRepository
    access_provider: OverpassAccessProvider | None
    static_provider: HybridStaticLayerProvider

    async def aclose(self) -> None:
        await self.weather.aclose()
        await self.static_provider.aclose()
        if self.access_provider is not None:
            await self.access_provider.aclose()
        await self.client.aclose()


async def build_runtime_services(settings: Settings | None = None) -> RuntimeServices:
    settings = settings or get_settings()
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=6.0, read=30.0, write=10.0, pool=6.0),
        limits=httpx.Limits(
            max_connections=settings.provider_max_connections,
            max_keepalive_connections=settings.provider_max_keepalive_connections,
        ),
        follow_redirects=False,
        headers={"user-agent": "Thiezer/0.3 (+https://github.com/SargisVardanian/Thiezer)"},
    )
    elevation = OpenMeteoElevationProvider(
        base_url=str(settings.open_meteo_base_url),
        client=client,
    )
    static_provider = HybridStaticLayerProvider(
        elevation_provider=elevation,
        surface_pack_path=settings.surface_pack_path,
    )
    access_provider = (
        OverpassAccessProvider(
            base_url=str(settings.overpass_base_url),
            client=client,
        )
        if settings.dynamic_discovery_enabled
        else None
    )
    seed_places = SeedPlaceRepository()
    seed_stores = SeedStoreRepository()
    place_repository = SurfacePlaceRepository(
        seed_repository=seed_places,
        static_provider=static_provider,
        access_provider=access_provider,
        country_resolver=CountryResolver(),
        coarse_parent_budget=settings.surface_coarse_parent_budget,
        static_shortlist_budget=settings.surface_static_shortlist_budget,
        local_access_radius_km=settings.local_access_radius_km,
    )
    store_repository = AdaptiveStoreRepository(
        seed_repository=seed_stores,
        discovery_provider=access_provider,
    )
    weather = OpenMeteoWeatherProvider(
        base_url=str(settings.open_meteo_base_url),
        api_key=settings.open_meteo_api_key,
        client=client,
    )
    return RuntimeServices(
        client=client,
        weather=weather,
        astronomy=SkyfieldAstronomyProvider(),
        place_repository=place_repository,
        store_repository=store_repository,
        access_provider=access_provider,
        static_provider=static_provider,
    )


def get_runtime_services(request: Request) -> RuntimeServices:
    runtime = getattr(request.app.state, "runtime_services", None)
    if not isinstance(runtime, RuntimeServices):
        raise RuntimeError("runtime services are not initialized")
    return runtime


def get_recommendation_service(request: Request) -> RecommendationService:
    runtime = get_runtime_services(request)
    return RecommendationService(
        place_repository=runtime.place_repository,
        weather_provider=runtime.weather,
        astronomy_provider=runtime.astronomy,
    )


def get_store_service(request: Request) -> StoreSearchService:
    return StoreSearchService(get_runtime_services(request).store_repository)


def get_visibility_service(request: Request) -> VisibilityService:
    return VisibilityService(get_runtime_services(request).astronomy)
