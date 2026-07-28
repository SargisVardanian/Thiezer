from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest

from thiezer.domain.contracts import GeoPoint, SurfaceCell
from thiezer.providers.access.overpass import OverpassAccessProvider


def _cell() -> SurfaceCell:
    return SurfaceCell(
        h3_index="872b5a375ffffff",
        resolution=7,
        center=GeoPoint(latitude_deg=40.2, longitude_deg=44.5),
        country_code="AM",
        elevation_m=1500.0,
        slope_deg=3.0,
        roughness_score=0.1,
        viirs_radiance_nw_cm2_sr=0.2,
        darkness_score=0.85,
        water_fraction=0.0,
        urban_fraction=0.05,
        forest_fraction=0.2,
        restricted_fraction=0.0,
        distance_to_road_km=1.0,
        distance_to_settlement_km=20.0,
        horizon_openness_score=0.9,
        static_score=0.85,
        upper_bound=0.9,
        uncertainty=0.1,
        source="fixture",
    )


@pytest.mark.asyncio
async def test_overpass_access_query_is_local_to_shortlisted_cell() -> None:
    queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = parse_qs(request.content.decode())
        query = payload["data"][0]
        queries.append(query)
        return httpx.Response(
            200,
            json={
                "elements": [
                    {
                        "type": "node",
                        "id": 1,
                        "lat": 40.201,
                        "lon": 44.501,
                        "tags": {"amenity": "parking", "name": "Night parking"},
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OverpassAccessProvider(base_url="https://overpass.test/api", client=client)
    result = await provider.discover_access_points(
        cells=[_cell()],
        radius_km=6.0,
        limit_per_cell=3,
    )
    await client.aclose()

    assert result[_cell().h3_index][0].name == "Night parking"
    assert queries
    assert "around:6000" in queries[0]
    assert "around:250000" not in queries[0]
