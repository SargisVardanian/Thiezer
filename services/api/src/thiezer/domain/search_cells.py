from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import h3

from thiezer.domain.contracts import GeoPoint
from thiezer.domain.geospatial import haversine_distance_km


@dataclass(frozen=True, slots=True)
class H3SearchPlan:
    coarse_resolution: int
    fine_resolution: int


def choose_h3_search_plan(radius_km: float) -> H3SearchPlan:
    if radius_km <= 300.0:
        return H3SearchPlan(5, 7)
    if radius_km <= 700.0:
        return H3SearchPlan(4, 7)
    return H3SearchPlan(3, 6)


def cover_circle(center: GeoPoint, radius_km: float, resolution: int) -> list[str]:
    origin = h3.latlng_to_cell(
        center.latitude_deg,
        center.longitude_deg,
        resolution,
    )
    edge_km = float(h3.average_hexagon_edge_length(resolution, unit="km"))
    ring_step_km = max(0.1, 1.5 * edge_km)
    k = max(1, math.ceil(radius_km / ring_step_km) + 2)
    cells = h3.grid_disk(origin, k)
    padding_km = 2.2 * edge_km
    return sorted(
        cell
        for cell in cells
        if haversine_distance_km(center, cell_center(cell)) <= radius_km + padding_km
    )


def refine_cells(parent_cells: Iterable[str], fine_resolution: int) -> list[str]:
    children: set[str] = set()
    for parent in parent_cells:
        parent_resolution = h3.get_resolution(parent)
        if parent_resolution > fine_resolution:
            children.add(h3.cell_to_parent(parent, fine_resolution))
        elif parent_resolution == fine_resolution:
            children.add(parent)
        else:
            children.update(h3.cell_to_children(parent, fine_resolution))
    return sorted(children)


def cell_center(cell_id: str) -> GeoPoint:
    latitude, longitude = h3.cell_to_latlng(cell_id)
    return GeoPoint(
        latitude_deg=float(latitude),
        longitude_deg=float(longitude),
    )


def cell_sample_points(cell_id: str) -> list[GeoPoint]:
    boundary = [
        GeoPoint(latitude_deg=latitude, longitude_deg=longitude)
        for latitude, longitude in h3.cell_to_boundary(cell_id)
    ]
    center = cell_center(cell_id)
    samples = [center, *boundary]
    shifted = boundary[1:] + boundary[:1]
    for first, second in zip(boundary, shifted, strict=True):
        samples.append(
            GeoPoint(
                latitude_deg=(first.latitude_deg + second.latitude_deg) / 2.0,
                longitude_deg=(first.longitude_deg + second.longitude_deg) / 2.0,
            )
        )
    return samples
