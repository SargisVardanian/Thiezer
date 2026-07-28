from __future__ import annotations

import json
from importlib.resources import files
from typing import Protocol

from pydantic import TypeAdapter

from thiezer.domain.contracts import (
    CandidatePlace,
    EquipmentStore,
    GeoPoint,
    SearchScope,
)
from thiezer.domain.geospatial import haversine_distance_km


class PlaceRepository(Protocol):
    @property
    def coverage_country_codes(self) -> list[str]: ...

    def search(
        self,
        *,
        user_location: GeoPoint,
        scope: SearchScope,
        country_code: str | None,
        max_distance_km: float,
        limit: int,
    ) -> list[tuple[CandidatePlace, float]]: ...


class StoreRepository(Protocol):
    @property
    def coverage_country_codes(self) -> list[str]: ...

    def search(
        self,
        *,
        user_location: GeoPoint,
        scope: SearchScope,
        country_code: str | None,
        max_distance_km: float,
        limit: int,
    ) -> list[tuple[EquipmentStore, float | None]]: ...


class SeedPlaceRepository:
    def __init__(self, places: list[CandidatePlace] | None = None) -> None:
        self._places = places if places is not None else _load_places()

    @property
    def coverage_country_codes(self) -> list[str]:
        return sorted({place.country_code for place in self._places})

    def search(
        self,
        *,
        user_location: GeoPoint,
        scope: SearchScope,
        country_code: str | None,
        max_distance_km: float,
        limit: int,
    ) -> list[tuple[CandidatePlace, float]]:
        matches: list[tuple[CandidatePlace, float]] = []
        for place in self._places:
            if scope == SearchScope.COUNTRY and place.country_code != country_code:
                continue
            distance = haversine_distance_km(user_location, place.point)
            if distance <= max_distance_km:
                matches.append((place, distance))
        # Cheap first-stage ranking before any weather call: retain nearby locations while
        # allowing a materially darker site to beat a slightly closer urban site.
        matches.sort(
            key=lambda item: (
                item[1] / max_distance_km - 0.30 * item[0].darkness_score,
                item[1],
            )
        )
        return matches[:limit]


class SeedStoreRepository:
    def __init__(self, stores: list[EquipmentStore] | None = None) -> None:
        self._stores = stores if stores is not None else _load_stores()

    @property
    def coverage_country_codes(self) -> list[str]:
        return sorted({store.country_code for store in self._stores})

    def search(
        self,
        *,
        user_location: GeoPoint,
        scope: SearchScope,
        country_code: str | None,
        max_distance_km: float,
        limit: int,
    ) -> list[tuple[EquipmentStore, float | None]]:
        matches: list[tuple[EquipmentStore, float | None]] = []
        for store in self._stores:
            if scope == SearchScope.COUNTRY and store.country_code != country_code:
                continue
            distance = (
                haversine_distance_km(user_location, store.point)
                if store.point is not None
                else None
            )
            if distance is None or distance <= max_distance_km:
                matches.append((store, distance))
        matches.sort(key=lambda item: (item[1] is None, item[1] or float("inf"), item[0].name))
        return matches[:limit]


def _load_places() -> list[CandidatePlace]:
    raw = files("thiezer.data").joinpath("armenia_places.json").read_text(encoding="utf-8")
    return TypeAdapter(list[CandidatePlace]).validate_python(json.loads(raw))


def _load_stores() -> list[EquipmentStore]:
    raw = files("thiezer.data").joinpath("armenia_stores.json").read_text(encoding="utf-8")
    return TypeAdapter(list[EquipmentStore]).validate_python(json.loads(raw))
