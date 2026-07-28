from __future__ import annotations

from datetime import timedelta

from thiezer.domain.celestial_objects import (
    CatalogSource,
    CelestialObject,
    CelestialObjectClass,
    CelestialObjectId,
)
from thiezer.providers.catalogs.base import CatalogProvider, CatalogProviderError
from thiezer.services.ephemeral_cache import EphemeralTtlCache


class CelestialResolutionService:
    def __init__(
        self,
        providers: dict[CatalogSource, CatalogProvider],
        cache: EphemeralTtlCache[object] | None = None,
    ) -> None:
        self._providers = providers
        self._cache = cache or EphemeralTtlCache()

    async def search(
        self, query: str, *, limit: int, types: set[CelestialObjectClass] | None = None
    ) -> list[CelestialObject]:
        clean = query.strip()
        if not clean or len(clean) > 120:
            raise ValueError("query must contain 1-120 characters")
        # SIMBAD first for named targets; other expensive catalogs are only used on explicit lookup.
        selected_types = types or set()
        type_key = ",".join(sorted(item.value for item in selected_types))
        key = f"catalog-search:{clean.casefold()}:{type_key}:{min(limit, 20)}"
        cached = self._cache.get(key)
        if isinstance(cached, list):
            return cached
        sources = self._route_search(clean, selected_types)
        results: list[CelestialObject] = []
        for source in sources:
            provider = self._providers.get(source)
            if provider is None:
                continue
            try:
                results.extend(await provider.search(clean, limit=min(limit, 20)))
            except CatalogProviderError:
                continue
        unique = {
            f"{item.identifier.provider}:{item.identifier.object_id}": item for item in results
        }
        result = list(unique.values())
        if selected_types:
            result = [item for item in result if item.object_class in selected_types]
        result = result[: min(limit, 20)]
        self._cache.put(key, result, ttl=timedelta(hours=1))
        return result

    async def resolve(self, target: CelestialObjectId) -> CelestialObject:
        key = f"catalog-object:{target.provider}:{target.object_id.casefold()}"
        cached = self._cache.get(key)
        if isinstance(cached, CelestialObject):
            return cached
        provider = self._providers.get(target.provider)
        if provider is None:
            raise LookupError(f"catalog provider is not configured: {target.provider}")
        result = await provider.get(target.object_id)
        if result is None:
            raise LookupError(f"catalog object not found: {target.provider}/{target.object_id}")
        self._cache.put(
            key, result, ttl=timedelta(days=7 if target.provider == CatalogSource.GAIA else 1)
        )
        return result

    @staticmethod
    def _route_search(query: str, types: set[CelestialObjectClass]) -> tuple[CatalogSource, ...]:
        if types == {CelestialObjectClass.EXOPLANET}:
            return (CatalogSource.EXOPLANET_ARCHIVE,)
        if types and types <= {CelestialObjectClass.GALAXY}:
            return (CatalogSource.NED, CatalogSource.SIMBAD)
        if types and types <= {CelestialObjectClass.NEBULA, CelestialObjectClass.CLUSTER}:
            return (CatalogSource.VIZIER, CatalogSource.SIMBAD)
        if query.casefold() in {"sun", "moon", "mars", "jupiter"}:
            return (CatalogSource.SKYFIELD,)
        return (CatalogSource.SIMBAD,)
