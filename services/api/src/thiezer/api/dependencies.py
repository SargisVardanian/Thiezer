from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from thiezer.config import get_settings
from thiezer.domain.ephemeris import SkyfieldAstronomyProvider
from thiezer.providers.weather.open_meteo import OpenMeteoWeatherProvider
from thiezer.repositories.seed import SeedPlaceRepository, SeedStoreRepository
from thiezer.services.recommendations import RecommendationService
from thiezer.services.stores import StoreSearchService
from thiezer.services.visibility import VisibilityService


@lru_cache(maxsize=1)
def get_place_repository() -> SeedPlaceRepository:
    return SeedPlaceRepository()


@lru_cache(maxsize=1)
def get_store_repository() -> SeedStoreRepository:
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
    try:
        yield RecommendationService(
            place_repository=get_place_repository(),
            weather_provider=weather,
            astronomy_provider=get_astronomy_provider(),
        )
    finally:
        await weather.aclose()


def get_store_service() -> StoreSearchService:
    return StoreSearchService(get_store_repository())


def get_visibility_service() -> VisibilityService:
    return VisibilityService(get_astronomy_provider())
