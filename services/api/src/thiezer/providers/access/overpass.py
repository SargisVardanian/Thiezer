from __future__ import annotations

import asyncio
from typing import Any

import httpx

from thiezer.domain.contracts import GeoPoint
from thiezer.domain.geospatial import haversine_distance_km
from thiezer.domain.static_scoring import passes_static_filters, score_raw_features
from thiezer.domain.surface import SurfaceCell, SurfaceSite
from thiezer.providers.access.procedural import ProceduralAccessPointProvider
from thiezer.providers.static_layers.base import StaticLayerProvider


class LocalOverpassAccessPointProvider:
    """Use Overpass only around the strongest surface cells, never the full search radius."""

    source_name = "local_openstreetmap_access"
    attribution = "© OpenStreetMap contributors"

    def __init__(
        self,
        *,
        base_url: str,
        static_layers: StaticLayerProvider,
        client: httpx.AsyncClient,
        local_radius_km: float = 5.0,
        concurrency: int = 3,
        maximum_local_queries: int = 16,
    ) -> None:
        self._base_url = base_url
        self._static = static_layers
        self._client = client
        self._local_radius_km = min(10.0, max(2.0, local_radius_km))
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        self._maximum_local_queries = max(1, maximum_local_queries)
        self._fallback = ProceduralAccessPointProvider(static_layers)
        self.large_radius_calls = 0
        self.local_calls = 0

    async def materialize_sites(
        self,
        *,
        cells: list[SurfaceCell],
        maximum_sites: int,
    ) -> list[SurfaceSite]:
        queried_cells = cells[: min(self._maximum_local_queries, maximum_sites)]
        tasks = [self._discover_cell(cell) for cell in queried_cells]
        batches = await asyncio.gather(*tasks, return_exceptions=True)
        sites: list[SurfaceSite] = []
        fallback_cells: list[SurfaceCell] = []
        for cell, batch in zip(queried_cells, batches, strict=True):
            if isinstance(batch, Exception) or not batch:
                fallback_cells.append(cell)
            else:
                sites.extend(batch)
        fallback_cells.extend(cells[len(queried_cells) : maximum_sites])
        if fallback_cells and len(sites) < maximum_sites:
            sites.extend(
                await self._fallback.materialize_sites(
                    cells=fallback_cells,
                    maximum_sites=maximum_sites - len(sites),
                )
            )
        sites.sort(key=lambda site: site.cell.static_score, reverse=True)
        return sites[:maximum_sites]

    async def _discover_cell(self, cell: SurfaceCell) -> list[SurfaceSite]:
        radius_m = int(self._local_radius_km * 1000.0)
        if self._local_radius_km > 10.0:
            self.large_radius_calls += 1
        query = _local_access_query(cell.center, radius_m)
        async with self._semaphore:
            self.local_calls += 1
            response = await self._client.post(self._base_url, data={"data": query})
        response.raise_for_status()
        payload = response.json()
        elements = payload.get("elements", []) if isinstance(payload, dict) else []
        points: list[tuple[GeoPoint, dict[str, Any], str]] = []
        for element in elements:
            if not isinstance(element, dict):
                continue
            point = _element_point(element)
            tags = element.get("tags")
            if point is None or not isinstance(tags, dict):
                continue
            element_type = element.get("type", "node")
            element_id = element.get("id")
            source = f"https://www.openstreetmap.org/{element_type}/{element_id}"
            points.append((point, tags, source))
        if not points:
            return []

        raw = await self._static.evaluate_points(
            points=[point for point, _, _ in points],
            resolution=cell.resolution,
        )
        scored = [score_raw_features(item) for item in raw]
        sites: list[SurfaceSite] = []
        for (point, tags, source), evaluated in zip(points, scored, strict=True):
            if not passes_static_filters(evaluated, _local_point_policy()):
                continue
            kind = _kind(tags)
            access_bonus = {
                "parking": 0.16,
                "viewpoint": 0.10,
                "campsite": 0.12,
                "road": 0.06,
            }.get(kind, 0.0)
            accessibility = min(1.0, evaluated.access_potential + access_bonus)
            sites.append(
                SurfaceSite(
                    id=f"osm-access:{source.rsplit('/', 1)[-1]}",
                    name=str(tags.get("name") or f"Mapped {kind} access"),
                    point=point,
                    cell=evaluated,
                    elevation_m=evaluated.elevation_m,
                    slope_deg=evaluated.slope_deg,
                    horizon_openness_score=max(
                        0.15,
                        1.0 - evaluated.roughness_m / 180.0,
                    ),
                    accessibility_score=accessibility,
                    risk_score=min(
                        1.0,
                        0.18
                        + 0.30 * evaluated.uncertainty
                        + 0.15 * (1.0 - accessibility),
                    ),
                    road_access=f"Local OSM {kind}; verify legal and seasonal access",
                    source_url=source,
                    source_provider=self.source_name,
                    country_code=_country_code(tags),
                    region=_region(tags),
                )
            )
        sites.sort(
            key=lambda site: (
                -site.cell.static_score,
                haversine_distance_km(cell.center, site.point),
            )
        )
        return sites[:3]

    async def aclose(self) -> None:
        return None


def _local_access_query(center: GeoPoint, radius_m: int) -> str:
    return f"""
[out:json][timeout:20];
(
  nwr(around:{radius_m},{center.latitude_deg},{center.longitude_deg})["amenity"="parking"]["access"!~"private|no"];
  nwr(around:{radius_m},{center.latitude_deg},{center.longitude_deg})["tourism"="viewpoint"];
  nwr(around:{radius_m},{center.latitude_deg},{center.longitude_deg})["tourism"="camp_site"];
  way(around:{radius_m},{center.latitude_deg},{center.longitude_deg})["highway"~"primary|secondary|tertiary|unclassified|track"];
);
out center tags qt;
""".strip()


def _element_point(element: dict[str, Any]) -> GeoPoint | None:
    latitude = element.get("lat")
    longitude = element.get("lon")
    center = element.get("center")
    if (latitude is None or longitude is None) and isinstance(center, dict):
        latitude = center.get("lat")
        longitude = center.get("lon")
    try:
        return GeoPoint(
            latitude_deg=float(latitude),
            longitude_deg=float(longitude),
        )
    except (TypeError, ValueError):
        return None


def _kind(tags: dict[str, Any]) -> str:
    if tags.get("amenity") == "parking":
        return "parking"
    if tags.get("tourism") == "viewpoint":
        return "viewpoint"
    if tags.get("tourism") == "camp_site":
        return "campsite"
    return "road"


def _country_code(tags: dict[str, Any]) -> str | None:
    value = tags.get("addr:country") or tags.get("ISO3166-1")
    normalized = str(value).strip().upper() if value is not None else ""
    return normalized if len(normalized) == 2 and normalized.isalpha() else None


def _region(tags: dict[str, Any]) -> str | None:
    value = tags.get("addr:state") or tags.get("addr:region") or tags.get("is_in")
    return str(value).strip() if value else None


def _local_point_policy():
    from thiezer.domain.static_scoring import StaticFilterPolicy

    return StaticFilterPolicy(
        minimum_land_fraction=0.70,
        maximum_urban_fraction=0.25,
        maximum_slope_deg=12.0,
        minimum_access_potential=0.04,
        maximum_uncertainty=0.98,
    )
