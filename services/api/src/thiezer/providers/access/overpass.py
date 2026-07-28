from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from thiezer.domain.contracts import (
    EquipmentStore,
    GeoPoint,
    PlaceKind,
    StoreKind,
    SurfaceCell,
    VerificationStatus,
)
from thiezer.domain.geospatial import haversine_distance_km
from thiezer.providers.access.base import AccessPoint


class OverpassAccessProvider:
    """Local OSM materialization around shortlisted surface cells.

    It never performs a radius-wide observation-site query. Each query is restricted to the final
    surface shortlist and is used only to find a reachable representative point.
    """

    source_name = "openstreetmap_local_access"
    attribution = "© OpenStreetMap contributors"

    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.AsyncClient,
        max_concurrency: int = 2,
        cache_ttl_seconds: int = 900,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self._cache_ttl = max(0, cache_ttl_seconds)
        self._cache: dict[str, tuple[float, dict[str, list[AccessPoint]]]] = {}

    async def discover_access_points(
        self,
        *,
        cells: list[SurfaceCell],
        radius_km: float,
        limit_per_cell: int,
    ) -> dict[str, list[AccessPoint]]:
        if not cells:
            return {}
        local_radius_km = min(10.0, max(1.0, radius_km))
        cache_key = ":".join(
            [
                f"{cell.h3_index}:{local_radius_km:.1f}"
                for cell in sorted(cells, key=lambda item: item.h3_index)
            ]
        )
        cached = self._cache.get(cache_key)
        if cached is not None and time.monotonic() - cached[0] <= self._cache_ttl:
            return cached[1]

        chunks = [cells[index : index + 8] for index in range(0, len(cells), 8)]
        chunk_results = await asyncio.gather(
            *(self._fetch_access_chunk(chunk, local_radius_km) for chunk in chunks)
        )
        elements = [element for chunk in chunk_results for element in chunk]
        result: dict[str, list[AccessPoint]] = {cell.h3_index: [] for cell in cells}
        for element in elements:
            point = _element_point(element)
            if point is None:
                continue
            nearest = min(cells, key=lambda cell: haversine_distance_km(cell.center, point))
            distance = haversine_distance_km(nearest.center, point)
            if distance > local_radius_km:
                continue
            access = _parse_access_point(element, point)
            if access is not None:
                result[nearest.h3_index].append(access)

        for cell_id, points in result.items():
            points.sort(key=lambda item: (_access_priority(item.kind), item.name, item.id))
            result[cell_id] = points[: max(1, limit_per_cell)]
        self._cache[cache_key] = (time.monotonic(), result)
        return result

    async def discover_stores(
        self,
        *,
        user_location: GeoPoint,
        radius_km: float,
        limit: int,
    ) -> list[EquipmentStore]:
        # Public Overpass remains a fallback. A production deployment should use OSM PBF/PostGIS.
        query_radius_m = int(min(120.0, max(1.0, radius_km)) * 1000)
        query = f"""
[out:json][timeout:25];
(
  nwr(around:{query_radius_m},{user_location.latitude_deg:.6f},
      {user_location.longitude_deg:.6f})["shop"~"camera|electronics|optician|telescope"];
);
out center tags;
""".strip()
        payload = await self._request(query)
        elements = payload.get("elements", [])
        stores: list[EquipmentStore] = []
        if not isinstance(elements, list):
            return stores
        for element in elements:
            point = _element_point(element)
            tags = element.get("tags", {}) if isinstance(element, dict) else {}
            if point is None or not isinstance(tags, dict):
                continue
            name = str(tags.get("name") or tags.get("brand") or "Astronomy equipment store")
            website = str(
                tags.get("website")
                or tags.get("contact:website")
                or "https://www.openstreetmap.org"
            )
            stores.append(
                EquipmentStore(
                    id=f"osm-{element.get('type', 'element')}-{element.get('id')}",
                    name=name,
                    kind=StoreKind.PHYSICAL,
                    country_code=_country_code(tags),
                    point=point,
                    address=_address(tags),
                    website_url=website,
                    catalog_url=None,
                    phone=_optional_text(tags.get("phone") or tags.get("contact:phone")),
                    categories=["camera", "electronics", "optics"],
                    delivers_countrywide=False,
                    verification_status=VerificationStatus.UNVERIFIED_DISCOVERED,
                    source_checked_at_utc=datetime.now(UTC),
                    source_provider=self.source_name,
                )
            )
        stores.sort(
            key=lambda store: (
                haversine_distance_km(user_location, store.point)
                if store.point is not None
                else float("inf")
            )
        )
        return stores[:limit]

    async def _fetch_access_chunk(
        self,
        cells: list[SurfaceCell],
        radius_km: float,
    ) -> list[dict[str, Any]]:
        radius_m = int(radius_km * 1000)
        clauses: list[str] = []
        for cell in cells:
            lat = cell.center.latitude_deg
            lon = cell.center.longitude_deg
            around = f"around:{radius_m},{lat:.6f},{lon:.6f}"
            clauses.extend(
                [
                    f'nwr({around})["tourism"="viewpoint"];',
                    f'nwr({around})["tourism"="camp_site"];',
                    f'nwr({around})["amenity"="parking"];',
                    f'nwr({around})["leisure"="picnic_table"];',
                    f'nwr({around})["highway"="trailhead"];',
                    f'nwr({around})["highway"="turning_circle"];',
                ]
            )
        query = "[out:json][timeout:25];(\n" + "\n".join(clauses) + "\n);out center tags;"
        payload = await self._request(query)
        elements = payload.get("elements", [])
        if not isinstance(elements, list):
            return []
        return [element for element in elements if isinstance(element, dict)]

    async def _request(self, query: str) -> dict[str, Any]:
        async with self._semaphore:
            response = await self._client.post(
                self._base_url,
                content=f"data={quote(query)}",
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
        response.raise_for_status()
        payload: Any = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Overpass payload must be an object")
        return payload

    async def aclose(self) -> None:
        return None


def _parse_access_point(element: dict[str, Any], point: GeoPoint) -> AccessPoint | None:
    tags = element.get("tags", {})
    if not isinstance(tags, dict):
        return None
    kind = _place_kind(tags)
    if kind is None:
        return None
    element_type = str(element.get("type", "element"))
    element_id = str(element.get("id", "unknown"))
    name = str(tags.get("name") or _default_name(kind))
    return AccessPoint(
        id=f"osm-{element_type}-{element_id}",
        name=name,
        point=point,
        kind=kind,
        country_code=_country_code(tags),
        road_access=_road_access(tags, kind),
        source_url=f"https://www.openstreetmap.org/{element_type}/{element_id}",
    )


def _element_point(element: dict[str, Any]) -> GeoPoint | None:
    lat = element.get("lat")
    lon = element.get("lon")
    if lat is None or lon is None:
        center = element.get("center")
        if isinstance(center, dict):
            lat = center.get("lat")
            lon = center.get("lon")
    if lat is None or lon is None:
        return None
    return GeoPoint(latitude_deg=float(lat), longitude_deg=float(lon))


def _place_kind(tags: dict[str, Any]) -> PlaceKind | None:
    if tags.get("tourism") == "viewpoint":
        return PlaceKind.VIEWPOINT
    if tags.get("tourism") == "camp_site":
        return PlaceKind.CAMPSITE
    if tags.get("amenity") == "parking":
        return PlaceKind.PARKING
    if tags.get("highway") in {"trailhead", "turning_circle"}:
        return PlaceKind.ROAD_ACCESS
    if tags.get("leisure") == "picnic_table":
        return PlaceKind.ROAD_ACCESS
    return None


def _access_priority(kind: PlaceKind) -> int:
    return {
        PlaceKind.PARKING: 0,
        PlaceKind.VIEWPOINT: 1,
        PlaceKind.CAMPSITE: 2,
        PlaceKind.ROAD_ACCESS: 3,
        PlaceKind.OBSERVATORY: 4,
        PlaceKind.OBSERVATION_SITE: 5,
    }[kind]


def _default_name(kind: PlaceKind) -> str:
    return {
        PlaceKind.PARKING: "Parking near dark-sky surface",
        PlaceKind.VIEWPOINT: "Viewpoint near dark-sky surface",
        PlaceKind.CAMPSITE: "Campsite near dark-sky surface",
        PlaceKind.ROAD_ACCESS: "Road access near dark-sky surface",
        PlaceKind.OBSERVATORY: "Observatory",
        PlaceKind.OBSERVATION_SITE: "Observation site",
    }[kind]


def _road_access(tags: dict[str, Any], kind: PlaceKind) -> str:
    surface = _optional_text(tags.get("surface"))
    access = _optional_text(tags.get("access"))
    parts = [kind.value]
    if surface:
        parts.append(f"surface={surface}")
    if access:
        parts.append(f"access={access}")
    return "; ".join(parts)


def _country_code(tags: dict[str, Any]) -> str | None:
    value = tags.get("addr:country") or tags.get("is_in:country_code")
    text = _optional_text(value)
    return text.upper() if text and len(text) == 2 else None


def _address(tags: dict[str, Any]) -> str | None:
    parts = [
        _optional_text(tags.get("addr:street")),
        _optional_text(tags.get("addr:housenumber")),
        _optional_text(tags.get("addr:city")),
    ]
    value = " ".join(part for part in parts if part)
    return value or None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
