from __future__ import annotations

import httpx
import pytest

from thiezer.domain.contracts import GeoPoint, PlaceKind, VerificationStatus
from thiezer.providers.places.overpass import OverpassDiscoveryProvider


@pytest.mark.asyncio
async def test_overpass_provider_parses_viewpoint_and_darkness_proxy() -> None:
    payload = {
        "elements": [
            {
                "type": "node",
                "id": 1,
                "lat": 41.0,
                "lon": 44.0,
                "tags": {
                    "tourism": "viewpoint",
                    "name": "Mountain View",
                    "addr:country": "GE",
                    "ele": "1800 m",
                },
            },
            {
                "type": "node",
                "id": 2,
                "lat": 41.1,
                "lon": 44.1,
                "tags": {
                    "place": "town",
                    "name": "Nearby Town",
                    "population": "12000",
                },
            },
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        body = request.content.decode()
        assert "around%3A250000" in body or "around:250000" in body
        return httpx.Response(200, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OverpassDiscoveryProvider(
        base_url="https://overpass.test/api",
        client=client,
    )
    places = await provider.discover_places(
        user_location=GeoPoint(latitude_deg=40.2, longitude_deg=44.5),
        radius_km=250,
        limit=5,
    )
    await client.aclose()

    assert len(places) == 1
    assert places[0].kind == PlaceKind.VIEWPOINT
    assert places[0].country_code == "GE"
    assert places[0].elevation_m == 1800
    assert places[0].verification_status == VerificationStatus.UNVERIFIED_DISCOVERED
    assert 0.0 <= places[0].darkness_score <= 1.0


@pytest.mark.asyncio
async def test_overpass_provider_parses_candidate_equipment_store() -> None:
    payload = {
        "elements": [
            {
                "type": "node",
                "id": 7,
                "lat": 40.18,
                "lon": 44.51,
                "tags": {
                    "shop": "camera",
                    "name": "Camera Lab",
                    "website": "https://example.com",
                    "addr:country": "AM",
                },
            }
        ]
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OverpassDiscoveryProvider(
        base_url="https://overpass.test/api",
        client=client,
    )
    stores = await provider.discover_stores(
        user_location=GeoPoint(latitude_deg=40.17, longitude_deg=44.50),
        radius_km=25,
        limit=5,
    )
    await client.aclose()

    assert stores[0].name == "Camera Lab"
    assert "cameras" in stores[0].categories
    assert stores[0].country_code == "AM"
