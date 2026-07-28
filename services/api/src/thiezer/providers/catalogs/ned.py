"""NED modern API/TAP boundary; legacy NED endpoints are intentionally excluded."""

from __future__ import annotations

from thiezer.domain.celestial_objects import (
    CatalogSource,
    CelestialCoordinates,
    CelestialObject,
    CelestialObjectClass,
    CelestialObjectId,
    CelestialPhysicalProperties,
)
from thiezer.providers.catalogs.tap import TapClient, adql_contains_literal, adql_literal


class NedCatalogProvider:
    source = CatalogSource.NED
    attribution = "NASA/IPAC Extragalactic Database (NED)"

    def __init__(
        self, *, tap: TapClient | None = None, fixtures: dict[str, CelestialObject] | None = None
    ) -> None:
        self._tap = tap
        self._fixtures = fixtures or {}

    async def search(self, query: str, *, limit: int) -> list[CelestialObject]:
        needle = query.casefold()
        matches = [
            item
            for item in self._fixtures.values()
            if needle in item.name.casefold()
            or any(needle in alias.casefold() for alias in item.aliases)
        ][:limit]
        if matches or self._tap is None:
            return matches
        rows = await self._tap.query(
            "SELECT TOP 20 prefname, ra, dec, type, z, diameter_major FROM objdir "
            f"WHERE prefname LIKE {adql_contains_literal(query.strip())}",
            max_rows=limit,
        )
        return [_from_row(row) for row in rows]

    async def get(self, object_id: str) -> CelestialObject | None:
        fixture = self._fixtures.get(object_id.casefold())
        if fixture is not None or self._tap is None:
            return fixture
        rows = await self._tap.query(
            "SELECT TOP 1 prefname, ra, dec, type, z, diameter_major FROM objdir "
            f"WHERE prefname = {adql_literal(object_id)}",
            max_rows=1,
        )
        return _from_row(rows[0]) if rows else None


def _from_row(row: dict[str, object]) -> CelestialObject:
    name = str(row["prefname"])
    return CelestialObject(
        identifier=CelestialObjectId(provider=CatalogSource.NED, object_id=name),
        name=name,
        object_class=CelestialObjectClass.GALAXY,
        coordinates=CelestialCoordinates(
            right_ascension_deg=_number(row["ra"]), declination_deg=_number(row["dec"])
        ),
        physical=CelestialPhysicalProperties(
            redshift=_optional_number(row.get("z")),
            angular_major_axis_arcmin=_optional_number(row.get("diameter_major")),
        ),
        attribution=NedCatalogProvider.attribution,
    )


def _number(value: object) -> float:
    if not isinstance(value, (str, int, float)):
        raise ValueError("NED response has an invalid coordinate")
    return float(value)


def _optional_number(value: object) -> float | None:
    return _number(value) if value is not None else None
