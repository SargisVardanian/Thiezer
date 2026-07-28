from datetime import UTC, datetime

import httpx
import pytest

from thiezer.domain.contracts import GeoPoint
from thiezer.providers.weather.base import weather_point_key
from thiezer.providers.weather.open_meteo import OpenMeteoWeatherProvider


def _payload(latitude: float, longitude: float) -> dict[str, object]:
    return {
        "latitude": latitude,
        "longitude": longitude,
        "model": "fixture-model",
        "hourly": {
            "time": ["2026-07-29T20:00"],
            "cloud_cover": [10],
            "cloud_cover_low": [5],
            "cloud_cover_mid": [3],
            "cloud_cover_high": [2],
            "temperature_2m": [18.0],
            "relative_humidity_2m": [40],
            "dew_point_2m": [4.0],
            "precipitation": [0.0],
            "visibility": [30000],
            "wind_speed_10m": [2.0],
            "wind_gusts_10m": [4.0],
            "surface_pressure": [850.0],
        },
    }


@pytest.mark.asyncio
async def test_open_meteo_batches_multiple_coordinates_in_one_request() -> None:
    points = [
        GeoPoint(latitude_deg=40.2, longitude_deg=44.5),
        GeoPoint(latitude_deg=40.4, longitude_deg=44.3),
    ]
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.params["latitude"] == "40.200000,40.400000"
        assert request.url.params["longitude"] == "44.500000,44.300000"
        return httpx.Response(200, json=[_payload(40.2, 44.5), _payload(40.4, 44.3)])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenMeteoWeatherProvider(base_url="https://weather.test/v1", client=client)
    result = await provider.get_hourly_forecasts(
        points=points,
        start_utc=datetime(2026, 7, 29, 20, tzinfo=UTC),
        end_utc=datetime(2026, 7, 29, 21, tzinfo=UTC),
    )
    await client.aclose()

    assert calls == 1
    assert set(result) == {weather_point_key(point) for point in points}
    assert result[weather_point_key(points[0])][0].total_cloud_fraction == 0.1
