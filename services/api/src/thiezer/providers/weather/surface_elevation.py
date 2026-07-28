from __future__ import annotations

from datetime import datetime

from thiezer.domain.contracts import GeoPoint, HourlySkyCondition
from thiezer.providers.static_layers.base import StaticLayerProvider
from thiezer.providers.weather.base import (
    WeatherPointKey,
    weather_point_key,
)
from thiezer.providers.weather.open_meteo import OpenMeteoWeatherProvider


class SurfaceElevationWeatherProvider:
    """Inject surface elevation into batched Open-Meteo requests."""

    def __init__(
        self,
        *,
        delegate: OpenMeteoWeatherProvider,
        static_layers: StaticLayerProvider,
    ) -> None:
        self._delegate = delegate
        self._static = static_layers

    async def get_hourly_forecast(
        self,
        *,
        point: GeoPoint,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[HourlySkyCondition]:
        result = await self.get_hourly_forecasts(
            points=[point],
            start_utc=start_utc,
            end_utc=end_utc,
        )
        return result[weather_point_key(point)]

    async def get_hourly_forecasts(
        self,
        *,
        points: list[GeoPoint],
        start_utc: datetime,
        end_utc: datetime,
        elevations_m: list[float] | None = None,
    ) -> dict[WeatherPointKey, list[HourlySkyCondition]]:
        elevations = elevations_m
        if elevations is None:
            raw = await self._static.evaluate_points(
                points=points,
                resolution=7,
            )
            elevations = [item.elevation_m for item in raw]
        return await self._delegate.get_hourly_forecasts(
            points=points,
            start_utc=start_utc,
            end_utc=end_utc,
            elevations_m=elevations,
        )

    async def aclose(self) -> None:
        return None
