from __future__ import annotations

from thiezer.domain.contracts import (
    EquipmentStore,
    GeoPoint,
    SearchScope,
    VerificationStatus,
    WarningCode,
)
from thiezer.domain.geospatial import haversine_distance_km
from thiezer.providers.access.base import AccessPointProvider
from thiezer.repositories.base import StoreRepository, StoreSearchBatch


class AdaptiveStoreRepository:
    """Combine packaged stores with radius-bounded local OSM discovery."""

    def __init__(
        self,
        *,
        seed_repository: StoreRepository,
        discovery_provider: AccessPointProvider | None,
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


def _verification_priority(item: EquipmentStore) -> int:
    return {
        VerificationStatus.VERIFIED: 4,
        VerificationStatus.PARTNER_VERIFIED: 3,
        VerificationStatus.UNVERIFIED_SEED: 2,
        VerificationStatus.UNVERIFIED_DISCOVERED: 1,
    }[item.verification_status]
