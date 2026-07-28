from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from thiezer.domain.contracts import (
    CandidatePlace,
    EquipmentStore,
    GeoPoint,
    PlaceKind,
    StoreKind,
    VerificationStatus,
)
from thiezer.domain.geospatial import haversine_distance_km

_ELEMENT_LIMIT_MULTIPLIER = 6
_ELEVATION_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


class OverpassDiscoveryProvider:
    """Low-cost OpenStreetMap discovery adapter.

    The provider discovers real mapped features within a radius. Darkness is deliberately a
    transparent settlement-distance proxy until a global VIIRS raster is installed.
    """

    source_name = "openstreetmap_overpass"
    attribution = "© OpenStreetMap contributors"

    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 25.0,
    ) -> None:
        self._base_url = base_url
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=5.0,
                read=timeout_seconds,
                write=5.0,
                pool=5.0,
            ),
            headers={"User-Agent": "Thiezer/0.3 (+https://github.com/SargisVardanian/Thiezer)"},
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def discover_places(
        self,
        *,
        user_location: GeoPoint,
        radius_km: float,
        limit: int,
    ) -> list[CandidatePlace]:
        radius_m = int(min(1_000.0, max(1.0, radius_km)) * 1_000)
        payload = await self._request(_place_query(user_location, radius_m))
        elements = payload.get("elements", [])
        if not isinstance(elements, list):
            raise ValueError("Overpass response does not contain an elements array")

        settlements = [
            element
            for element in elements
            if isinstance(element, dict)
            and isinstance(element.get("tags"), dict)
            and element["tags"].get("place") in {"city", "town", "village"}
        ]
        candidates: list[CandidatePlace] = []
        for element in elements:
            if not isinstance(element, dict):
                continue
            tags = element.get("tags")
            if not isinstance(tags, dict) or "place" in tags:
                continue
            candidate = _candidate_from_element(
                element=element,
                tags=tags,
                origin=user_location,
                settlements=settlements,
            )
            if candidate is not None:
                candidates.append(candidate)

        candidates.sort(
            key=lambda place: (
                -place.darkness_score,
                haversine_distance_km(user_location, place.point),
                place.name,
            )
        )
        return candidates[: max(limit * _ELEMENT_LIMIT_MULTIPLIER, limit)]

    async def discover_stores(
        self,
        *,
        user_location: GeoPoint,
        radius_km: float,
        limit: int,
    ) -> list[EquipmentStore]:
        radius_m = int(min(1_000.0, max(1.0, radius_km)) * 1_000)
        payload = await self._request(_store_query(user_location, radius_m))
        elements = payload.get("elements", [])
        if not isinstance(elements, list):
            raise ValueError("Overpass response does not contain an elements array")

        stores: list[EquipmentStore] = []
        for element in elements:
            if not isinstance(element, dict):
                continue
            tags = element.get("tags")
            if not isinstance(tags, dict):
                continue
            point = _element_point(element)
            if point is None:
                continue
            element_type = str(element.get("type", "node"))
            element_id = str(element.get("id", "unknown"))
            shop = str(tags.get("shop", "electronics"))
            name = _clean_name(tags.get("name")) or f"{shop.replace('_', ' ').title()} shop"
            osm_url = f"https://www.openstreetmap.org/{element_type}/{element_id}"
            website = _website(tags) or osm_url
            stores.append(
                EquipmentStore(
                    id=f"osm:{element_type}:{element_id}",
                    name=name,
                    kind=StoreKind.PHYSICAL,
                    country_code=_country_code(tags),
                    point=point,
                    address=_address(tags),
                    website_url=website,
                    catalog_url=_website(tags),
                    phone=_clean_name(tags.get("contact:phone") or tags.get("phone")),
                    categories=_store_categories(shop),
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
                else float("inf"),
                store.name,
            )
        )
        return stores[: max(limit * 2, limit)]

    async def _request(self, query: str) -> dict[str, Any]:
        response = await self._client.post(self._base_url, data={"data": query})
        response.raise_for_status()
        if len(response.content) > 12_000_000:
            raise ValueError("Overpass response exceeds safety limit")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Overpass response must be a JSON object")
        return payload


def _place_query(origin: GeoPoint, radius_m: int) -> str:
    lat = origin.latitude_deg
    lon = origin.longitude_deg
    return f"""
[out:json][timeout:25];
(
  nwr(around:{radius_m},{lat},{lon})["tourism"="viewpoint"];
  nwr(around:{radius_m},{lat},{lon})["man_made"="observatory"];
  nwr(around:{radius_m},{lat},{lon})["tourism"="camp_site"];
  nwr(around:{radius_m},{lat},{lon})["amenity"="parking"]["access"!~"private|no"];
  nwr(around:{radius_m},{lat},{lon})["place"~"city|town|village"];
);
out center tags qt;
""".strip()


def _store_query(origin: GeoPoint, radius_m: int) -> str:
    lat = origin.latitude_deg
    lon = origin.longitude_deg
    return f"""
[out:json][timeout:25];
(
  nwr(around:{radius_m},{lat},{lon})["shop"~"camera|photo|electronics|optician|outdoor"];
);
out center tags qt;
""".strip()


def _candidate_from_element(
    *,
    element: dict[str, Any],
    tags: dict[str, Any],
    origin: GeoPoint,
    settlements: list[dict[str, Any]],
) -> CandidatePlace | None:
    point = _element_point(element)
    if point is None:
        return None
    kind = _place_kind(tags)
    if kind is None:
        return None
    element_type = str(element.get("type", "node"))
    element_id = str(element.get("id", "unknown"))
    default_name = {
        PlaceKind.OBSERVATORY: "Mapped observatory",
        PlaceKind.VIEWPOINT: "Mapped viewpoint",
        PlaceKind.CAMPSITE: "Mapped campsite",
        PlaceKind.PARKING: "Mapped parking area",
    }[kind]
    name = _clean_name(tags.get("name")) or f"{default_name} {element_id}"
    distance_from_origin = haversine_distance_km(origin, point)
    darkness = _darkness_proxy(
        point=point,
        distance_from_origin_km=distance_from_origin,
        settlements=settlements,
        kind=kind,
    )
    source_url = f"https://www.openstreetmap.org/{element_type}/{element_id}"
    elevation = _parse_elevation(tags.get("ele"))
    horizon = {
        PlaceKind.OBSERVATORY: 0.92,
        PlaceKind.VIEWPOINT: 0.86,
        PlaceKind.CAMPSITE: 0.76,
        PlaceKind.PARKING: 0.66,
    }[kind]
    accessibility = {
        PlaceKind.OBSERVATORY: 0.78,
        PlaceKind.VIEWPOINT: 0.70,
        PlaceKind.CAMPSITE: 0.82,
        PlaceKind.PARKING: 0.92,
    }[kind]
    risk = {
        PlaceKind.OBSERVATORY: 0.18,
        PlaceKind.VIEWPOINT: 0.32,
        PlaceKind.CAMPSITE: 0.24,
        PlaceKind.PARKING: 0.25,
    }[kind]
    return CandidatePlace(
        id=f"osm:{element_type}:{element_id}",
        name=name,
        country_code=_country_code(tags),
        region=_region(tags),
        point=point,
        elevation_m=elevation,
        kind=kind,
        verification_status=VerificationStatus.UNVERIFIED_DISCOVERED,
        darkness_score=darkness,
        horizon_openness_score=horizon,
        accessibility_score=accessibility,
        risk_score=risk,
        road_access=_road_access(kind, tags),
        notes=(
            "Dynamically discovered from OpenStreetMap. Access, parking, road condition, "
            "night safety, and the darkness proxy require verification."
        ),
        source_url=source_url,
        source_provider="openstreetmap_overpass",
        darkness_model="settlement_distance_proxy_v1",
    )


def _element_point(element: dict[str, Any]) -> GeoPoint | None:
    lat = element.get("lat")
    lon = element.get("lon")
    if lat is None or lon is None:
        center = element.get("center")
        if isinstance(center, dict):
            lat = center.get("lat")
            lon = center.get("lon")
    try:
        return GeoPoint(latitude_deg=float(lat), longitude_deg=float(lon))
    except (TypeError, ValueError):
        return None


def _place_kind(tags: dict[str, Any]) -> PlaceKind | None:
    if tags.get("man_made") == "observatory":
        return PlaceKind.OBSERVATORY
    if tags.get("tourism") == "viewpoint":
        return PlaceKind.VIEWPOINT
    if tags.get("tourism") == "camp_site":
        return PlaceKind.CAMPSITE
    if tags.get("amenity") == "parking":
        return PlaceKind.PARKING
    return None


def _darkness_proxy(
    *,
    point: GeoPoint,
    distance_from_origin_km: float,
    settlements: list[dict[str, Any]],
    kind: PlaceKind,
) -> float:
    pressure = 0.0
    for settlement in settlements:
        settlement_point = _element_point(settlement)
        tags = settlement.get("tags")
        if settlement_point is None or not isinstance(tags, dict):
            continue
        distance = haversine_distance_km(point, settlement_point)
        place_type = str(tags.get("place", "village"))
        type_weight = {"city": 1.0, "town": 0.58, "village": 0.24}.get(place_type, 0.2)
        population = _parse_population(tags.get("population"))
        population_weight = 1.0 + min(3.0, math.log10(max(1.0, population)) / 2.2)
        pressure += type_weight * population_weight * math.exp(-distance / 28.0)

    settlement_darkness = math.exp(-0.55 * pressure) if settlements else 0.62
    travel_darkness = 0.40 + 0.60 * (1.0 - math.exp(-distance_from_origin_km / 70.0))
    kind_bonus = 0.06 if kind in {PlaceKind.OBSERVATORY, PlaceKind.VIEWPOINT} else 0.0
    return _bounded(0.62 * settlement_darkness + 0.38 * travel_darkness + kind_bonus)


def _parse_population(value: Any) -> float:
    try:
        return max(1.0, float(str(value).replace(",", "").replace(" ", "")))
    except (TypeError, ValueError):
        return 2_500.0


def _parse_elevation(value: Any) -> float:
    if value is None:
        return 0.0
    match = _ELEVATION_PATTERN.search(str(value))
    if match is None:
        return 0.0
    try:
        return float(match.group())
    except ValueError:
        return 0.0


def _country_code(tags: dict[str, Any]) -> str | None:
    value = tags.get("addr:country") or tags.get("ISO3166-1")
    if value is None:
        return None
    normalized = str(value).strip().upper()
    return normalized if len(normalized) == 2 and normalized.isalpha() else None


def _region(tags: dict[str, Any]) -> str | None:
    return _clean_name(tags.get("addr:state") or tags.get("addr:region") or tags.get("is_in"))


def _website(tags: dict[str, Any]) -> str | None:
    value = tags.get("contact:website") or tags.get("website")
    cleaned = _clean_name(value)
    if cleaned is None:
        return None
    if cleaned.startswith(("http://", "https://")):
        return cleaned
    return f"https://{cleaned}"


def _address(tags: dict[str, Any]) -> str | None:
    parts = [
        _clean_name(tags.get("addr:street")),
        _clean_name(tags.get("addr:housenumber")),
        _clean_name(tags.get("addr:city")),
    ]
    compact = [part for part in parts if part]
    return ", ".join(compact) if compact else None


def _store_categories(shop: str) -> list[str]:
    mapping = {
        "camera": ["cameras", "lenses", "tripods"],
        "photo": ["cameras", "lenses", "accessories"],
        "electronics": ["electronics", "power", "adapters"],
        "optician": ["optics", "binoculars"],
        "outdoor": ["outdoor", "camping", "power"],
    }
    return mapping.get(shop, ["equipment"])


def _road_access(kind: PlaceKind, tags: dict[str, Any]) -> str:
    access = _clean_name(tags.get("access"))
    base = {
        PlaceKind.OBSERVATORY: "Mapped observatory access",
        PlaceKind.VIEWPOINT: "Mapped viewpoint; verify final road and walking section",
        PlaceKind.CAMPSITE: "Mapped campsite access",
        PlaceKind.PARKING: "Mapped public or non-private parking",
    }[kind]
    return f"{base}; OSM access={access}" if access else base


def _clean_name(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bounded(value: float) -> float:
    return min(1.0, max(0.0, value))
