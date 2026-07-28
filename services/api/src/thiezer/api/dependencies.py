from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from thiezer.config import get_settings
from thiezer.domain.ephemeris import SkyfieldAstronomyProvider
from thiezer.providers.places.overpass import OverpassDiscoveryProvider
from thiezer.providers.weather.open_meteo import OpenMeteoWeatherProvider
from thiezer.repositories.adaptive import AdaptivePlaceRepository, AdaptiveStoreRepository
from thiezer.repositories.seed import SeedPlaceRepository, SeedStoreRepository
from thiezer.services.recommendations import RecommendationService
from thiezer.services.stores import StoreSearchService
from thiezer.services.visibility import VisibilityService


@lru_cache(maxsize=1)
def get_seed_place_repository() -> SeedPlaceRepository:
    return SeedPlaceRepository()


@lru_cache(maxsize=1)
def get_seed_store_repository() -> SeedStoreRepository:
    return SeedStoreRepository()


@lru_cache(maxsize=1)
def get_astronomy_provider() -> SkyfieldAstronomyProvider:
    return SkyfieldAstronomyProvider()


async def get_recommendation_service() -> AsyncIterator[RecommendationService]:
    settings = get_settings()
    weather = OpenMeteoWeatherProvider(
        base_url=str(settings.open_meteo_base_url),
        api_key=settings.open_meteo_api_key,
    )
    overpass = (
        OverpassDiscoveryProvider(
            base_url=str(settings.overpass_base_url),
            timeout_seconds=settings.overpass_timeout_seconds,
        )
        if settings.overpass_enabled
        else None
    )
    repository = AdaptivePlaceRepository(
        seed_repository=get_seed_place_repository(),
        discovery_provider=overpass,
    )
    try:
        yield RecommendationService(
            place_repository=repository,
            weather_provider=weather,
            astronomy_provider=get_astronomy_provider(),
        )
    finally:
        await weather.aclose()
        if overpass is not None:
            await overpass.aclose()


async def get_store_service() -> AsyncIterator[StoreSearchService]:
    settings = get_settings()
    overpass = (
        OverpassDiscoveryProvider(
            base_url=str(settings.overpass_base_url),
            timeout_seconds=settings.overpass_timeout_seconds,
        )
        if settings.overpass_enabled
        else None
    )
    repository = AdaptiveStoreRepository(
        seed_repository=get_seed_store_repository(),
        discovery_provider=overpass,
    )
    try:
        yield StoreSearchService(repository)
    finally:
        if overpass is not None:
            await overpass.aclose()


def get_visibility_service() -> VisibilityService:
    return VisibilityService(get_astronomy_provider())
