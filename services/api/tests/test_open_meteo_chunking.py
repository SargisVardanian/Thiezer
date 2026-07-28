from datetime import UTC, datetime

import httpx
import pytest

from thiezer.domain.contracts import GeoPoint
from thiezer.providers.weather.open_meteo import OpenMeteoWeatherProvider


def _payload(latitude: float, longitude: float) -> dict[str, object]:
    return {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": {
            "time": ["2026-07-28T20:00"],
            "cloud_cover": [10],
            "cloud_cover_low": [5],
            "cloud_cover_mid": [3],
            "cloud_cover_high": [2],
            "temperature_2m": [18],
            "relative_humidity_2m": [40],
            "dew_point_2m": [4],
            "precipitation": [0],
            "visibility": [30000],
            "wind_speed_10m": [2],
            "wind_gusts_10m": [4],
            "surface_pressure": [850],
        },
    }


@pytest.mark.asyncio
async def test_chunking_above_25_points_and_elevation_parameter() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        latitudes = [float(value) for value in request.url.params["latitude"].split(",")]
        longitudes = [float(value) for value in request.url.params["longitude"].split(",")]
        assert len(request.url.params["elevation"].split(",")) == len(latitudes)
        payloads = [
            _payload(latitude, longitude)
            for latitude, longitude in zip(latitudes, longitudes, strict=True)
        ]
        return httpx.Response(200, json=payloads)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenMeteoWeatherProvider(
        base_url="https://weather.test/v1",
        client=client,
    )
    points = [GeoPoint(latitude_deg=39.0 + index * 0.01, longitude_deg=44.0) for index in range(40)]
    result = await provider.get_hourly_forecasts(
        points=points,
        elevations_m=[1000.0 + index for index in range(40)],
        start_utc=datetime(2026, 7, 28, 20, tzinfo=UTC),
        end_utc=datetime(2026, 7, 28, 21, tzinfo=UTC),
    )
    await client.aclose()
    assert len(result) == 40
    assert len(requests) == 2
    assert provider.batch_calls == 2
