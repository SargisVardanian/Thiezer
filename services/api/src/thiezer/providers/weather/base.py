from __future__ import annotations

from datetime import datetime
from typing import Protocol

from thiezer.domain.contracts import GeoPoint, HourlySkyCondition

WeatherPointKey = tuple[float, float]


class WeatherProvider(Protocol):
    async def get_hourly_forecast(
        self,
        *,
        point: GeoPoint,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[HourlySkyCondition]: ...

    async def get_hourly_forecasts(
        self,
        *,
        points: list[GeoPoint],
        start_utc: datetime,
        end_utc: datetime,
    ) -> dict[WeatherPointKey, list[HourlySkyCondition]]: ...

    async def aclose(self) -> None: ...


def weather_point_key(point: GeoPoint) -> WeatherPointKey:
    return (round(point.latitude_deg, 6), round(point.longitude_deg, 6))
