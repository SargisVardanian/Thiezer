from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from thiezer.domain.contracts import GeoPoint, HourlySkyCondition


class OpenMeteoWeatherProvider:
    """Normalize Open-Meteo hourly forecast responses into Thiezer contracts."""

    _HOURLY_FIELDS = (
        "cloud_cover",
        "cloud_cover_low",
        "cloud_cover_mid",
        "cloud_cover_high",
        "temperature_2m",
        "relative_humidity_2m",
        "dew_point_2m",
        "precipitation",
        "visibility",
        "wind_speed_10m",
        "wind_gusts_10m",
        "surface_pressure",
    )

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def __aenter__(self) -> OpenMeteoWeatherProvider:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_hourly_forecast(
        self,
        *,
        point: GeoPoint,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[HourlySkyCondition]:
        if start_utc.tzinfo is None or end_utc.tzinfo is None:
            raise ValueError("forecast bounds must be timezone-aware")
        if end_utc <= start_utc:
            raise ValueError("end_utc must be after start_utc")

        params: dict[str, str | float] = {
            "latitude": point.latitude_deg,
            "longitude": point.longitude_deg,
            "hourly": ",".join(self._HOURLY_FIELDS),
            "timezone": "UTC",
            "wind_speed_unit": "ms",
            "start_date": start_utc.astimezone(UTC).date().isoformat(),
            "end_date": end_utc.astimezone(UTC).date().isoformat(),
        }
        if self._api_key:
            params["apikey"] = self._api_key

        response = await self._client.get(f"{self._base_url}/forecast", params=params)
        response.raise_for_status()
        if len(response.content) > 5_000_000:
            raise ValueError("provider response exceeds safety limit")
        payload: dict[str, Any] = response.json()
        return self._normalize(
            payload=payload,
            requested_point=point,
            start_utc=start_utc,
            end_utc=end_utc,
        )

    @staticmethod
    def _fraction(percent: float | int) -> float:
        return min(1.0, max(0.0, float(percent) / 100.0))

    def _normalize(
        self,
        *,
        payload: dict[str, Any],
        requested_point: GeoPoint,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[HourlySkyCondition]:
        hourly = payload.get("hourly")
        if not isinstance(hourly, dict):
            raise ValueError("missing hourly provider payload")
        times = hourly.get("time")
        if not isinstance(times, list):
            raise ValueError("missing hourly time array")

        returned_point = GeoPoint(
            latitude_deg=float(payload["latitude"]),
            longitude_deg=float(payload["longitude"]),
        )
        model_name = payload.get("model")
        conditions: list[HourlySkyCondition] = []
        for index, raw_time in enumerate(times):
            timestamp = datetime.fromisoformat(str(raw_time)).replace(tzinfo=UTC)
            if timestamp < start_utc.astimezone(UTC) or timestamp > end_utc.astimezone(UTC):
                continue
            conditions.append(
                HourlySkyCondition(
                    timestamp_utc=timestamp,
                    total_cloud_fraction=self._fraction(hourly["cloud_cover"][index]),
                    low_cloud_fraction=self._fraction(hourly["cloud_cover_low"][index]),
                    mid_cloud_fraction=self._fraction(hourly["cloud_cover_mid"][index]),
                    high_cloud_fraction=self._fraction(hourly["cloud_cover_high"][index]),
                    temperature_c=float(hourly["temperature_2m"][index]),
                    relative_humidity_fraction=self._fraction(
                        hourly["relative_humidity_2m"][index]
                    ),
                    dew_point_c=float(hourly["dew_point_2m"][index]),
                    precipitation_mm=max(0.0, float(hourly["precipitation"][index])),
                    visibility_m=max(0.0, float(hourly["visibility"][index])),
                    wind_speed_mps=max(0.0, float(hourly["wind_speed_10m"][index])),
                    wind_gust_mps=max(0.0, float(hourly["wind_gusts_10m"][index])),
                    pressure_hpa=max(0.01, float(hourly["surface_pressure"][index])),
                    provider="open_meteo",
                    model_name=str(model_name) if model_name else None,
                    run_timestamp_utc=None,
                    requested_point=requested_point,
                    returned_grid_point=returned_point,
                    attribution="Weather data by Open-Meteo",
                )
            )
        return conditions
