from __future__ import annotations

import re
from datetime import timedelta

from thiezer.domain.celestial_objects import (
    CatalogSource,
    CelestialObject,
    CelestialObjectClass,
    CelestialObjectId,
    CelestialSearchResults,
)
from thiezer.providers.catalogs.base import CatalogProvider, CatalogProviderError
from thiezer.services.ephemeral_cache import EphemeralTtlCache


class CelestialResolutionService:
    def __init__(
        self,
        providers: dict[CatalogSource, CatalogProvider],
        cache: EphemeralTtlCache[object] | None = None,
        *,
        catalog_ttl_seconds: int = 86_400,
        horizons_ttl_seconds: int = 1_800,
        search_ttl_seconds: int = 3_600,
    ) -> None:
        self._providers = providers
        self._cache = cache or EphemeralTtlCache()
        self._catalog_ttl = timedelta(seconds=catalog_ttl_seconds)
        self._horizons_ttl = timedelta(seconds=horizons_ttl_seconds)
        self._search_ttl = timedelta(seconds=search_ttl_seconds)

    async def search(
        self, query: str, *, limit: int, types: set[CelestialObjectClass] | None = None
    ) -> list[CelestialObject]:
        return list((await self.search_with_diagnostics(query, limit=limit, types=types)).results)

    async def search_with_diagnostics(
        self, query: str, *, limit: int, types: set[CelestialObjectClass] | None = None
    ) -> CelestialSearchResults:
        clean = query.strip()
        if not clean or len(clean) > 120:
            raise ValueError("query must contain 1-120 characters")
        # SIMBAD first for named targets; other expensive catalogs are only used on explicit lookup.
        selected_types = types or set()
        type_key = ",".join(sorted(item.value for item in selected_types))
        key = f"catalog-search:{clean.casefold()}:{type_key}:{min(limit, 20)}"
        cached = self._cache.get(key)
        if isinstance(cached, CelestialSearchResults):
            return cached
        sources = self._route_search(clean, selected_types)
        results: list[CelestialObject] = []
        warnings: list[str] = []
        attributions: list[str] = []
        for source in sources:
            provider = self._providers.get(source)
            if provider is None:
                warnings.append(f"{source.value} provider is not configured")
                continue
            attributions.append(provider.attribution)
            try:
                results.extend(await provider.search(clean, limit=min(limit, 20)))
            except CatalogProviderError:
                warnings.append(f"{source.value} provider is temporarily unavailable")
                continue
        unique = {
            f"{item.identifier.provider}:{item.identifier.object_id}": item for item in results
        }
        result = list(unique.values())
        if selected_types:
            result = [item for item in result if item.object_class in selected_types]
        result = result[: min(limit, 20)]
        if CelestialObjectClass.STAR in selected_types or not selected_types:
            result, gaia_warning = await self._enrich_stars(result)
            if gaia_warning is not None:
                warnings.append(gaia_warning)
            if any(item.identifier.provider == CatalogSource.GAIA for item in result):
                gaia = self._providers.get(CatalogSource.GAIA)
                if gaia is not None:
                    attributions.append(gaia.attribution)
        warnings.extend(warning for item in result for warning in item.warnings)
        response = CelestialSearchResults(
            results=tuple(result),
            source_attributions=tuple(dict.fromkeys(attributions)),
            warnings=tuple(dict.fromkeys(warnings)),
        )
        self._cache.put(key, response, ttl=self._search_ttl)
        return response

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
        ttl = (
            timedelta(days=7)
            if target.provider == CatalogSource.GAIA
            else self._horizons_ttl
            if target.provider == CatalogSource.HORIZONS
            else self._catalog_ttl
        )
        self._cache.put(key, result, ttl=ttl)
        return result

    async def _enrich_stars(
        self, results: list[CelestialObject]
    ) -> tuple[list[CelestialObject], str | None]:
        provider = self._providers.get(CatalogSource.GAIA)
        enrich = getattr(provider, "enrich_nearest", None)
        if not callable(enrich):
            return results, None
        enriched: list[CelestialObject] = []
        failed = False
        for item in results:
            if item.object_class != CelestialObjectClass.STAR:
                enriched.append(item)
                continue
            try:
                replacement = await enrich(item)
            except CatalogProviderError:
                failed = True
                replacement = None
            enriched.append(
                replacement
                or item.model_copy(
                    update={
                        "warnings": tuple(
                            dict.fromkeys(
                                (*item.warnings, "Gaia enrichment is currently unavailable.")
                            )
                        )
                    }
                )
            )
        warning = (
            "Gaia enrichment is currently unavailable; SIMBAD fallback was used."
            if failed
            else None
        )
        return enriched, warning

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
        if re.search(r"\s[b-z]$", query.casefold()):
            return (CatalogSource.EXOPLANET_ARCHIVE, CatalogSource.SIMBAD)
        if types and types <= {
            CelestialObjectClass.ASTEROID,
            CelestialObjectClass.COMET,
            CelestialObjectClass.DWARF_PLANET,
            CelestialObjectClass.NATURAL_SATELLITE,
            CelestialObjectClass.SPACECRAFT,
        }:
            return (CatalogSource.HORIZONS,)
        if query.casefold() in {"halley", "1p", "ceres"} or query.strip().isdecimal():
            return (CatalogSource.HORIZONS,)
        return (CatalogSource.SIMBAD,)
