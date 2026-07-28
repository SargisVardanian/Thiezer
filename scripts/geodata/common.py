from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def load_aoi(path: str | Path) -> dict[str, Any]:
    with Path(path).open() as handle:
        return json.load(handle)


def aoi_polygon(aoi: dict[str, Any]) -> dict[str, Any]:
    geometry = aoi["geometry"]
    if geometry["type"] in {"Polygon", "MultiPolygon"}:
        return geometry
    if geometry["type"] == "bbox":
        west, south, east, north = geometry["bbox"]
        return {
            "type": "Polygon",
            "coordinates": [
                [[west, south], [east, south], [east, north], [west, north], [west, south]]
            ],
        }
    if geometry["type"] == "center_radius":
        longitude, latitude = geometry["center"]
        angular = float(geometry["radius_km"]) / 6371.0088
        points: list[list[float]] = []
        for bearing in range(0, 361, 5):
            direction = math.radians(bearing)
            input_latitude = math.radians(latitude)
            output_latitude = math.asin(
                math.sin(input_latitude) * math.cos(angular)
                + math.cos(input_latitude) * math.sin(angular) * math.cos(direction)
            )
            output_longitude = math.radians(longitude) + math.atan2(
                math.sin(direction) * math.sin(angular) * math.cos(input_latitude),
                math.cos(angular) - math.sin(input_latitude) * math.sin(output_latitude),
            )
            points.append([math.degrees(output_longitude), math.degrees(output_latitude)])
        return {"type": "Polygon", "coordinates": [points]}
    raise ValueError(f"unsupported AOI geometry: {geometry['type']}")


def bounds(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    coordinates = geometry["coordinates"]
    rings = (
        coordinates
        if geometry["type"] == "Polygon"
        else [ring for polygon in coordinates for ring in polygon]
    )
    points = [point for ring in rings for point in ring]
    longitudes, latitudes = zip(*points, strict=True)
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
