from __future__ import annotations

from typing import Protocol

from thiezer.domain.contracts import GeoPoint


class CountryBoundaryProvider(Protocol):
    def supports(self, country_code: str) -> bool: ...

    def contains(self, country_code: str, point: GeoPoint) -> bool: ...


class StaticCountryBoundaryProvider:
    """Small zero-cost boundary set used by the first country-scoped prototype."""

    def __init__(self) -> None:
        self._polygons: dict[str, tuple[tuple[float, float], ...]] = {
            "AM": (
                (43.44, 41.13),
                (44.59, 41.30),
                (45.00, 41.24),
                (45.62, 40.87),
                (45.96, 40.23),
                (46.63, 39.56),
                (46.48, 38.88),
                (45.29, 38.43),
                (44.77, 39.05),
                (43.56, 39.18),
                (43.66, 40.11),
                (43.44, 41.13),
            )
        }

    def supports(self, country_code: str) -> bool:
        return country_code.upper() in self._polygons

    def contains(self, country_code: str, point: GeoPoint) -> bool:
        polygon = self._polygons.get(country_code.upper())
        if polygon is None:
            return False
        return _point_in_polygon(
            longitude=point.longitude_deg,
            latitude=point.latitude_deg,
            polygon=polygon,
        )


def _point_in_polygon(
    *,
    longitude: float,
    latitude: float,
    polygon: tuple[tuple[float, float], ...],
) -> bool:
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > latitude) != (y2 > latitude):
            crossing = (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
            if longitude < crossing:
                inside = not inside
        previous = current
    return inside
