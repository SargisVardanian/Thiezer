from __future__ import annotations

import json
import math
from importlib.resources import files
from pathlib import Path
from typing import Any

import h3
import httpx
from pydantic import TypeAdapter

from thiezer.domain.contracts import CandidatePlace, GeoPoint, SurfaceCell
from thiezer.domain.geospatial import haversine_distance_km
from thiezer.providers.static_layers.elevation import OpenMeteoElevationProvider


class HybridStaticLayerProvider:
    """Surface layers from an optional local pack, global elevation and conservative fallback.

    A production pack can contain VIIRS/Black Marble, DEM-derived slope/roughness, land cover and
    restrictions. When a field is unavailable, uncertainty increases instead of inventing precision.
    Existing seed sites only calibrate nearby development/test cells; they are never used as a
    global search boundary.
    """

    source_name = "hybrid_surface_layers"
    attribution = "Static layers: local surface pack when configured; elevation by Open-Meteo"

    def __init__(
        self,
        *,
        elevation_provider: OpenMeteoElevationProvider | None,
        surface_pack_path: str | None = None,
    ) -> None:
        self._elevation = elevation_provider
        self._pack = _load_surface_pack(surface_pack_path)
        self._seed_places = _load_seed_places()

    async def evaluate_cells(
        self,
        *,
        cell_ids: list[str],
        centers: list[GeoPoint],
        resolutions: list[int],
    ) -> list[SurfaceCell]:
        if not (len(cell_ids) == len(centers) == len(resolutions)):
            raise ValueError("cell_ids, centers and resolutions must have equal length")
        elevations: list[float | None]
        if self._elevation is None:
            elevations = [None] * len(centers)
        else:
            try:
                elevations = await self._elevation.get_elevations(centers)
            except (httpx.HTTPError, ValueError, RuntimeError):
                elevations = [None] * len(centers)

        base: list[dict[str, Any]] = []
        for cell_id, center, resolution, elevation in zip(
            cell_ids, centers, resolutions, elevations, strict=True
        ):
            packed = self._pack.get(cell_id)
            if packed is not None:
                row = dict(packed)
                row["source"] = str(row.get("source") or "local_surface_pack")
                row["uncertainty"] = float(row.get("uncertainty", 0.15))
            else:
                row = _fallback_row(center=center, elevation_m=elevation, seeds=self._seed_places)
            row["h3_index"] = cell_id
            row["resolution"] = resolution
            row["center"] = center
            if row.get("elevation_m") is None:
                row["elevation_m"] = elevation
            base.append(row)

        elevation_by_cell = {
            cell_id: row.get("elevation_m") for cell_id, row in zip(cell_ids, base, strict=True)
        }
        result: list[SurfaceCell] = []
        for cell_id, row in zip(cell_ids, base, strict=True):
            slope_deg, roughness = _terrain_from_neighbors(cell_id, elevation_by_cell)
            if row.get("slope_deg") is None:
                row["slope_deg"] = slope_deg
            if row.get("roughness_score") is None:
                row["roughness_score"] = roughness
            _finalize_scores(row)
            result.append(SurfaceCell.model_validate(row))
        return result

    async def aclose(self) -> None:
        return None


def _load_surface_pack(path_value: str | None) -> dict[str, dict[str, Any]]:
    if not path_value:
        return {}
    path = Path(path_value).expanduser()
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("cells"), list):
        rows = payload["cells"]
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ValueError("surface pack must be a list or an object containing a cells list")
    return {
        str(row["h3_index"]): dict(row)
        for row in rows
        if isinstance(row, dict) and row.get("h3_index")
    }


def _load_seed_places() -> list[CandidatePlace]:
    try:
        raw = files("thiezer.data").joinpath("armenia_places.json").read_text(encoding="utf-8")
        return TypeAdapter(list[CandidatePlace]).validate_python(json.loads(raw))
    except (FileNotFoundError, ValueError):
        return []


def _fallback_row(
    *,
    center: GeoPoint,
    elevation_m: float | None,
    seeds: list[CandidatePlace],
) -> dict[str, Any]:
    nearest: CandidatePlace | None = None
    nearest_distance = float("inf")
    for seed in seeds:
        distance = haversine_distance_km(center, seed.point)
        if distance < nearest_distance:
            nearest = seed
            nearest_distance = distance

    if nearest is not None and nearest_distance <= 45.0:
        influence = math.exp(-nearest_distance / 18.0)
        darkness = 0.50 * (1.0 - influence) + nearest.darkness_score * influence
        horizon = 0.55 * (1.0 - influence) + nearest.horizon_openness_score * influence
        uncertainty = 0.80 - 0.45 * influence
        source = "seed_calibrated_surface_fallback"
        if elevation_m is None:
            elevation_m = nearest.elevation_m
    else:
        darkness = 0.50
        horizon = 0.50
        uncertainty = 0.95
        source = "conservative_global_surface_fallback"

    return {
        "country_code": None,
        "elevation_m": elevation_m,
        "slope_deg": None,
        "roughness_score": None,
        "viirs_radiance_nw_cm2_sr": None,
        "darkness_score": darkness,
        "water_fraction": 0.0,
        "urban_fraction": 0.15,
        "forest_fraction": 0.15,
        "restricted_fraction": 0.0,
        "distance_to_road_km": None,
        "distance_to_settlement_km": None,
        "horizon_openness_score": horizon,
        "static_score": 0.0,
        "upper_bound": 0.0,
        "uncertainty": uncertainty,
        "source": source,
    }


def _terrain_from_neighbors(
    cell_id: str,
    elevation_by_cell: dict[str, float | None],
) -> tuple[float | None, float | None]:
    center = elevation_by_cell.get(cell_id)
    if center is None:
        return None, None
    neighbors = [
        elevation_by_cell.get(neighbor)
        for neighbor in h3.grid_disk(cell_id, 1)
        if neighbor != cell_id
    ]
    values = [value for value in neighbors if value is not None]
    if not values:
        return None, None
    edge_m = max(
        1.0,
        h3.average_hexagon_edge_length(h3.get_resolution(cell_id), unit="km") * 1000.0,
    )
    max_delta = max(abs(value - center) for value in values)
    slope_deg = math.degrees(math.atan(max_delta / edge_m))
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    roughness = min(1.0, math.sqrt(variance) / 500.0)
    return slope_deg, roughness


def _finalize_scores(row: dict[str, Any]) -> None:
    elevation = row.get("elevation_m")
    elevation_score = (
        0.45
        if elevation is None
        else 0.35
        + 0.65 * (1.0 - math.exp(-max(0.0, float(elevation)) / 1800.0))
    )
    slope = float(row.get("slope_deg") or 0.0)
    roughness = float(row.get("roughness_score") or 0.0)
    terrain_score = max(0.0, 1.0 - slope / 25.0) * max(0.0, 1.0 - 0.6 * roughness)
    land_score = (
        1.0
        - 0.85 * float(row.get("water_fraction", 0.0))
        - 0.75 * float(row.get("urban_fraction", 0.0))
        - 0.95 * float(row.get("restricted_fraction", 0.0))
    )
    land_score = min(1.0, max(0.0, land_score))
    darkness = float(row.get("darkness_score", 0.5))
    horizon = float(row.get("horizon_openness_score", 0.5))
    uncertainty = float(row.get("uncertainty", 0.95))
    static_score = (
        0.48 * darkness
        + 0.15 * elevation_score
        + 0.14 * terrain_score
        + 0.13 * land_score
        + 0.10 * horizon
    )
    static_score = min(1.0, max(0.0, static_score))
    row["static_score"] = static_score
    row["upper_bound"] = min(1.0, static_score + 0.18 * uncertainty)
