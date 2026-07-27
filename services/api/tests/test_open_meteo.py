from datetime import UTC, datetime

import httpx
import pytest

from thiezer.domain.contracts import GeoPoint
from thiezer.providers.weather.open_meteo import OpenMeteoWeatherProvider


@pytest.mark.asyncio
async def test_open_meteo_adapter_normalizes_fixture() -> None:
    payload = {
        "latitude": 40.2,
        "longitude": 44.5,
        "model": "fixture-model",
        "hourly": {
            "time": ["2026-07-27T20:00", "2026-07-27T21:00"],
            "cloud_cover": [10, 20],
            "cloud_cover_low": [5, 10],
            "cloud_cover_mid": [3, 4],
            "cloud_cover_high": [2, 6],
            "temperature_2m": [18.0, 17.0],
            "relative_humidity_2m": [40, 45],
            "dew_point_2m": [4.0, 5.0],
            "precipitation": [0.0, 0.1],
            "visibility": [30000, 25000],
            "wind_speed_10m": [2.0, 3.0],
            "wind_gusts_10m": [4.0, 5.0],
            "surface_pressure": [850.0, 849.0],
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["timezone"] == "UTC"
        return httpx.Response(200, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenMeteoWeatherProvider(base_url="https://weather.test/v1", client=client)
    point = GeoPoint(latitude_deg=40.18, longitude_deg=44.51)
    result = await provider.get_hourly_forecast(
        point=point,
        start_utc=datetime(2026, 7, 27, 20, tzinfo=UTC),
        end_utc=datetime(2026, 7, 27, 21, tzinfo=UTC),
    )
    await client.aclose()

    assert len(result) == 2
    assert result[0].total_cloud_fraction == 0.1
    assert result[0].wind_speed_mps == 2.0
    assert result[0].provider == "open_meteo"
    assert result[0].returned_grid_point.latitude_deg == 40.2
