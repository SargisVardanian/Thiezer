from __future__ import annotations

from thiezer.domain.contracts import (
    CandidatePlace,
    EquipmentStore,
    GeoPoint,
    SearchScope,
    VerificationStatus,
    WarningCode,
)
from thiezer.domain.geospatial import haversine_distance_km
from thiezer.providers.places.base import PlaceDiscoveryProvider
from thiezer.repositories.base import (
    PlaceRepository,
    PlaceSearchBatch,
    StoreRepository,
    StoreSearchBatch,
)


class AdaptivePlaceRepository:
    """Merge packaged/verified places with live radius-based discovery."""

    def __init__(
        self,
        *,
        seed_repository: PlaceRepository,
        discovery_provider: PlaceDiscoveryProvider | None,
    ) -> None:
        self._seed = seed_repository
        self._discovery = discovery_provider

    async def search(
        self,
        *,
        user_location: GeoPoint,
        scope: SearchScope,
        country_code: str | None,
        max_distance_km: float,
        limit: int,
        include_unverified: bool = True,
    ) -> PlaceSearchBatch:
        seed = await self._seed.search(
            user_location=user_location,
            scope=scope,
            country_code=country_code,
            max_distance_km=max_distance_km,
            limit=limit,
            include_unverified=include_unverified,
        )
        warnings = list(seed.warnings)
        sources = list(seed.discovery_sources)
        attributions = list(seed.attributions)
        candidates = list(seed.matches)

        if self._discovery is not None:
            try:
                discovered = await self._discovery.discover_places(
                    user_location=user_location,
                    radius_km=max_distance_km,
                    limit=limit,
                )
                for place in discovered:
                    if not include_unverified and place.verification_status not in {
                        VerificationStatus.VERIFIED,
                        VerificationStatus.PARTNER_VERIFIED,
                    }:
                        continue
                    if (
                        scope == SearchScope.COUNTRY
                        and country_code is not None
                        and place.country_code != country_code
                    ):
                        continue
                    distance = haversine_distance_km(user_location, place.point)
                    if distance <= max_distance_km:
                        candidates.append((place, distance))
                sources.append(self._discovery.source_name)
                attributions.append(self._discovery.attribution)
                if discovered:
                    warnings.append(WarningCode.DARKNESS_IS_PROXY)
            except Exception:
                warnings.append(WarningCode.DISCOVERY_PROVIDER_UNAVAILABLE)

        merged = _merge_place_matches(candidates)
        merged.sort(
            key=lambda item: (
                _place_rank_cost(item[0], item[1], max_distance_km),
                item[1],
                item[0].id,
            )
        )
        coverage = sorted(
            {place.country_code for place, _ in merged if place.country_code is not None}
        )
        return PlaceSearchBatch(
            matches=merged[:limit],
            coverage_country_codes=coverage,
            discovery_sources=sorted(set(sources)),
            attributions=sorted(set(attributions)),
            warnings=list(dict.fromkeys(warnings)),
        )


class AdaptiveStoreRepository:
    def __init__(
        self,
        *,
        seed_repository: StoreRepository,
        discovery_provider: PlaceDiscoveryProvider | None,
    ) -> None:
        self._seed = seed_repository
        self._discovery = discovery_provider

    async def search(
        self,
        *,
        user_location: GeoPoint,
        scope: SearchScope,
        country_code: str | None,
        max_distance_km: float,
        limit: int,
    ) -> StoreSearchBatch:
        seed = await self._seed.search(
            user_location=user_location,
            scope=scope,
            country_code=country_code,
            max_distance_km=max_distance_km,
            limit=limit,
        )
        warnings = list(seed.warnings)
        sources = list(seed.discovery_sources)
        attributions = list(seed.attributions)
        stores = list(seed.matches)

        if self._discovery is not None:
            try:
                discovered = await self._discovery.discover_stores(
                    user_location=user_location,
                    radius_km=max_distance_km,
                    limit=limit,
                )
                for store in discovered:
                    if (
                        scope == SearchScope.COUNTRY
                        and country_code is not None
                        and store.country_code != country_code
                    ):
                        continue
                    distance = (
                        haversine_distance_km(user_location, store.point)
                        if store.point is not None
                        else None
                    )
                    if distance is None or distance <= max_distance_km:
                        stores.append((store, distance))
                sources.append(self._discovery.source_name)
                attributions.append(self._discovery.attribution)
            except Exception:
                warnings.append(WarningCode.DISCOVERY_PROVIDER_UNAVAILABLE)

        merged = _merge_store_matches(stores)
        merged.sort(
            key=lambda item: (
                item[1] is None,
                item[1] if item[1] is not None else float("inf"),
                item[0].name,
            )
        )
        coverage = sorted(
            {store.country_code for store, _ in merged if store.country_code is not None}
        )
        return StoreSearchBatch(
            matches=merged[:limit],
            coverage_country_codes=coverage,
            discovery_sources=sorted(set(sources)),
            attributions=sorted(set(attributions)),
            warnings=list(dict.fromkeys(warnings)),
        )


def _merge_place_matches(
    matches: list[tuple[CandidatePlace, float]],
) -> list[tuple[CandidatePlace, float]]:
    by_key: dict[tuple[int, int, str], tuple[CandidatePlace, float]] = {}
    for place, distance in matches:
        key = (
            round(place.point.latitude_deg * 10_000),
            round(place.point.longitude_deg * 10_000),
            place.name.casefold(),
        )
        current = by_key.get(key)
        if current is None or _verification_priority(place) > _verification_priority(current[0]):
            by_key[key] = (place, distance)
    return list(by_key.values())


def _merge_store_matches(
    matches: list[tuple[EquipmentStore, float | None]],
) -> list[tuple[EquipmentStore, float | None]]:
    by_key: dict[tuple[str, int | None, int | None], tuple[EquipmentStore, float | None]] = {}
    for store, distance in matches:
        point_key = (
            round(store.point.latitude_deg * 10_000) if store.point is not None else None,
            round(store.point.longitude_deg * 10_000) if store.point is not None else None,
        )
        key = (store.name.casefold(), *point_key)
        current = by_key.get(key)
        if current is None or _verification_priority(store) > _verification_priority(current[0]):
            by_key[key] = (store, distance)
    return list(by_key.values())


def _verification_priority(item: CandidatePlace | EquipmentStore) -> int:
    return {
        VerificationStatus.VERIFIED: 4,
        VerificationStatus.PARTNER_VERIFIED: 3,
        VerificationStatus.UNVERIFIED_SEED: 2,
        VerificationStatus.UNVERIFIED_DISCOVERED: 1,
    }[item.verification_status]


def _place_rank_cost(place: CandidatePlace, distance_km: float, max_distance_km: float) -> float:
    verification_penalty = {
        VerificationStatus.VERIFIED: 0.0,
        VerificationStatus.PARTNER_VERIFIED: 0.02,
        VerificationStatus.UNVERIFIED_SEED: 0.06,
        VerificationStatus.UNVERIFIED_DISCOVERED: 0.10,
    }[place.verification_status]
    distance_term = distance_km / max(1.0, max_distance_km)
    return (
        0.60 * distance_term
        - 0.28 * place.darkness_score
        - 0.07 * place.horizon_openness_score
        + verification_penalty
    )
