from __future__ import annotations

from datetime import datetime
from typing import Protocol

from thiezer.domain.contracts import GeoPoint, HourlySkyCondition


class WeatherProvider(Protocol):
    async def get_hourly_forecast(
        self,
        *,
        point: GeoPoint,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[HourlySkyCondition]: ...
