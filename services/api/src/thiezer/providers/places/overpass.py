from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from thiezer.domain.contracts import CandidatePlace, EquipmentStore, GeoPoint, StoreKind, VerificationStatus
from thiezer.domain.geospatial import haversine_distance_km


class OverpassDiscoveryProvider:
    """Overpass adapter retained only for equipment-store discovery.

    Observation-site discovery is intentionally disabled: the surface-first H3 pipeline is the sole
    generator of sky candidates. This provider implements the historical protocol so the store
    repository can reuse its lifecycle and attribution fields.
    """

    source_name = "openstreetmap_overpass_stores"
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
            headers={"User-Agent": "Thiezer/0.4 (+https://github.com/SargisVardanian/Thiezer)"},
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
        del user_location, radius_km, limit
        return []

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


def _store_query(origin: GeoPoint, radius_m: int) -> str:
    return f"""
[out:json][timeout:25];
(
  nwr(around:{radius_m},{origin.latitude_deg},{origin.longitude_deg})["shop"~"camera|photo|electronics|optician|outdoor"];
);
out center tags qt;
""".strip()


def _element_point(element: dict[str, Any]) -> GeoPoint | None:
    latitude = element.get("lat")
    longitude = element.get("lon")
    if latitude is None or longitude is None:
        center = element.get("center")
        if isinstance(center, dict):
            latitude = center.get("lat")
            longitude = center.get("lon")
    if latitude is None or longitude is None:
        return None
    try:
        return GeoPoint(
            latitude_deg=float(latitude),
            longitude_deg=float(longitude),
        )
    except (TypeError, ValueError):
        return None


def _country_code(tags: dict[str, Any]) -> str | None:
    value = tags.get("addr:country") or tags.get("ISO3166-1")
    if value is None:
        return None
    normalized = str(value).strip().upper()
    return normalized if len(normalized) == 2 and normalized.isalpha() else None


def _website(tags: dict[str, Any]) -> str | None:
    cleaned = _clean_name(tags.get("contact:website") or tags.get("website"))
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


def _clean_name(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
