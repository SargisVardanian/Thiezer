from __future__ import annotations

from thiezer.domain.celestial_objects import (
    CatalogSource,
    CelestialObject,
    CelestialObjectClass,
    CelestialObjectId,
)


class SkyfieldPresetCatalogProvider:
    """Names backed by the local DE421 ephemeris rather than a remote catalogue."""

    source = CatalogSource.SKYFIELD
    attribution = "JPL DE421 via Skyfield"
    _names = ("Sun", "Moon", "Mars", "Jupiter")

    async def search(self, query: str, *, limit: int) -> list[CelestialObject]:
        needle = query.casefold()
        return [self._object(name) for name in self._names if needle in name.casefold()][:limit]

    async def get(self, object_id: str) -> CelestialObject | None:
        names = {name.casefold() for name in self._names}
        return self._object(object_id) if object_id.casefold() in names else None

    def _object(self, name: str) -> CelestialObject:
        canonical = next(item for item in self._names if item.casefold() == name.casefold())
        return CelestialObject(
            identifier=CelestialObjectId(
                provider=CatalogSource.SKYFIELD, object_id=canonical.casefold()
            ),
            name=canonical,
            object_class=CelestialObjectClass.SOLAR_SYSTEM_BODY,
            attribution=self.attribution,
        )
