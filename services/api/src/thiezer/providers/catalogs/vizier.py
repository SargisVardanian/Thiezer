"""VizieR TAP adapter limited to a reviewed deep-sky catalogue allowlist."""

from __future__ import annotations

from thiezer.domain.celestial_objects import CatalogSource, CelestialObject


class VizierCatalogProvider:
    source = CatalogSource.VIZIER
    attribution = "VizieR catalogue service, CDS, Strasbourg"
    # Do not interpolate catalogue names from a request. New catalogues require code review.
    allowlisted_catalogues = ("VII/118/ngc2000", "VII/281/glade2")

    def __init__(self, *, fixtures: dict[str, CelestialObject] | None = None) -> None:
        self._fixtures = fixtures or {}

    async def search(self, query: str, *, limit: int) -> list[CelestialObject]:
        needle = query.casefold()
        return [
            item
            for item in self._fixtures.values()
            if needle in item.name.casefold()
            or any(needle in alias.casefold() for alias in item.aliases)
        ][:limit]

    async def get(self, object_id: str) -> CelestialObject | None:
        return self._fixtures.get(object_id.casefold())
