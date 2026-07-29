from __future__ import annotations

import asyncio

import httpx

from thiezer.domain.contracts import GeoPoint, RoadRoute, RoadRouteRequest


class OsrmRoadRoutingProvider:
    """OSRM driving routes with bounded retries and explicit OSM attribution."""

    attribution = "Road route: OSRM, based on OpenStreetMap data"

    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.AsyncClient,
        timeout_seconds: float,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def route(self, request: RoadRouteRequest) -> RoadRoute:
        coordinates = ";".join(
            (
                _coordinates(request.origin),
                _coordinates(request.destination),
            )
        )
        url = f"{self._base_url}/driving/{coordinates}"
        response: httpx.Response | None = None
        for attempt in range(2):
            try:
                response = await self._client.get(
                    url,
                    params={"overview": "full", "geometries": "geojson", "steps": "false"},
                    timeout=self._timeout_seconds,
                )
                if response.status_code < 500:
                    break
            except httpx.TransportError:
                if attempt == 1:
                    raise
            if attempt == 0:
                await asyncio.sleep(0.2)
        if response is None:
            raise RuntimeError("OSRM did not return a response")
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != "Ok" or not payload.get("routes"):
            raise ValueError(f"OSRM route unavailable: {payload.get('code', 'unknown')}")
        route = payload["routes"][0]
        coordinates_raw = route.get("geometry", {}).get("coordinates", [])
        geometry = [
            GeoPoint(latitude_deg=float(latitude), longitude_deg=float(longitude))
            for longitude, latitude in coordinates_raw
        ]
        if len(geometry) < 2:
            raise ValueError("OSRM returned an empty route geometry")
        return RoadRoute(
            provider="osrm",
            distance_m=float(route["distance"]),
            duration_s=float(route["duration"]),
            geometry=geometry,
            attribution=self.attribution,
        )


def _coordinates(point: GeoPoint) -> str:
    return f"{point.longitude_deg:.6f},{point.latitude_deg:.6f}"
