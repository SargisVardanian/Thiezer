import httpx
import pytest

from thiezer.domain.contracts import GeoPoint, RoadRouteRequest
from thiezer.providers.routing.osrm import OsrmRoadRoutingProvider


@pytest.mark.asyncio
async def test_osrm_provider_returns_drivable_geojson_route() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/driving/44.503500,40.177200;44.700000,40.300000")
        assert request.url.params["geometries"] == "geojson"
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "routes": [
                    {
                        "distance": 25_400.0,
                        "duration": 2_040.0,
                        "geometry": {
                            "coordinates": [
                                [44.5035, 40.1772],
                                [44.61, 40.22],
                                [44.7, 40.3],
                            ]
                        },
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OsrmRoadRoutingProvider(
            base_url="https://routing.example/route/v1",
            client=client,
            timeout_seconds=5.0,
        )
        route = await provider.route(
            RoadRouteRequest(
                origin=GeoPoint(latitude_deg=40.1772, longitude_deg=44.5035),
                destination=GeoPoint(latitude_deg=40.3, longitude_deg=44.7),
            )
        )

    assert route.distance_m == 25_400.0
    assert route.duration_s == 2_040.0
    assert route.geometry[-1] == GeoPoint(latitude_deg=40.3, longitude_deg=44.7)
