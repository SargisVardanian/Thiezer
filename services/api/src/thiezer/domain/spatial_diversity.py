from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

from thiezer.domain.contracts import GeoPoint
from thiezer.domain.geospatial import haversine_distance_km

T = TypeVar("T")


def spatial_nms(
    candidates: Sequence[T],
    *,
    point: Callable[[T], GeoPoint],
    score: Callable[[T], float],
    min_separation_km: float,
    limit: int,
) -> list[T]:
    if limit <= 0:
        return []
    selected: list[T] = []
    for candidate in sorted(candidates, key=score, reverse=True):
        candidate_point = point(candidate)
        if all(
            haversine_distance_km(candidate_point, point(previous)) >= min_separation_km
            for previous in selected
        ):
            selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected
