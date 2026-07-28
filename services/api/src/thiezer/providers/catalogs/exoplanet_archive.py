"""NASA Exoplanet Archive TAP adapter with host-star linkage."""

from __future__ import annotations

from thiezer.domain.celestial_objects import CatalogSource, CelestialObject


class ExoplanetArchiveProvider:
    source = CatalogSource.EXOPLANET_ARCHIVE
    attribution = "NASA Exoplanet Archive"

    def __init__(self, *, fixtures: dict[str, CelestialObject] | None = None) -> None:
        self._fixtures = fixtures or {}

    async def search(self, query: str, *, limit: int) -> list[CelestialObject]:
        needle = query.casefold()
        return [
            item
            for item in self._fixtures.values()
            if needle in item.identifier.object_id.casefold()
            or needle in item.name.casefold()
            or any(needle in alias.casefold() for alias in item.aliases)
        ][:limit]

    async def get(self, object_id: str) -> CelestialObject | None:
        return self._fixtures.get(object_id.casefold())
