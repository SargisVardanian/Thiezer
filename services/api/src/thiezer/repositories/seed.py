from __future__ import annotations

import json
from importlib.resources import files

from pydantic import TypeAdapter

from thiezer.domain.contracts import (
    CandidatePlace,
    EquipmentStore,
    GeoPoint,
    SearchScope,
    VerificationStatus,
)
from thiezer.domain.geospatial import haversine_distance_km
from thiezer.repositories.base import PlaceSearchBatch, StoreSearchBatch
from thiezer.services.progress import ProgressCallback, report_progress


class SeedPlaceRepository:
    def __init__(self, places: list[CandidatePlace] | None = None) -> None:
        self._places = places if places is not None else _load_places()

    async def search(
        self,
        *,
        user_location: GeoPoint,
        scope: SearchScope,
        country_code: str | None,
        max_distance_km: float,
        limit: int,
        include_unverified: bool = True,
        progress: ProgressCallback | None = None,
    ) -> PlaceSearchBatch:
        await report_progress(progress, "generating_cells")
        await report_progress(progress, "applying_static_filters")
        matches: list[tuple[CandidatePlace, float]] = []
        for place in self._places:
            if scope == SearchScope.COUNTRY and place.country_code != country_code:
                continue
            if not include_unverified and place.verification_status not in {
                VerificationStatus.VERIFIED,
                VerificationStatus.PARTNER_VERIFIED,
            }:
                continue
            distance = haversine_distance_km(user_location, place.point)
            if distance <= max_distance_km:
                matches.append((place, distance))
        matches.sort(
            key=lambda item: (
                item[1] / max_distance_km - 0.30 * item[0].darkness_score,
                item[1],
            )
        )
        coverage = sorted(
            {place.country_code for place, _ in matches if place.country_code is not None}
        )
        return PlaceSearchBatch(
            matches=matches[:limit],
            coverage_country_codes=coverage,
            discovery_sources=["packaged_seed"],
            attributions=["Thiezer packaged seed data"],
            warnings=[],
        )


class SeedStoreRepository:
    def __init__(self, stores: list[EquipmentStore] | None = None) -> None:
        self._stores = stores if stores is not None else _load_stores()

    async def search(
        self,
        *,
        user_location: GeoPoint,
        scope: SearchScope,
        country_code: str | None,
        max_distance_km: float,
        limit: int,
    ) -> StoreSearchBatch:
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
        coverage = sorted(
            {store.country_code for store, _ in matches if store.country_code is not None}
        )
        return StoreSearchBatch(
            matches=matches[:limit],
            coverage_country_codes=coverage,
            discovery_sources=["packaged_seed"],
            attributions=["Thiezer packaged seed data"],
            warnings=[],
        )


def _load_places() -> list[CandidatePlace]:
    raw = files("thiezer.data").joinpath("armenia_places.json").read_text(encoding="utf-8")
    return TypeAdapter(list[CandidatePlace]).validate_python(json.loads(raw))


def _load_stores() -> list[EquipmentStore]:
    raw = files("thiezer.data").joinpath("armenia_stores.json").read_text(encoding="utf-8")
    return TypeAdapter(list[EquipmentStore]).validate_python(json.loads(raw))
