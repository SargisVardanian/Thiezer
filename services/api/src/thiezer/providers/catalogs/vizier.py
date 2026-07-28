"""VizieR TAP adapter limited to a reviewed deep-sky catalogue allowlist."""

from __future__ import annotations

from thiezer.domain.celestial_objects import (
    CatalogSource,
    CelestialCoordinates,
    CelestialObject,
    CelestialObjectClass,
    CelestialObjectId,
)
from thiezer.providers.catalogs.tap import TapClient, adql_literal


class VizierCatalogProvider:
    source = CatalogSource.VIZIER
    attribution = "VizieR catalogue service, CDS, Strasbourg"
    # Do not interpolate catalogue names from a request. New catalogues require code review.
    allowlisted_catalogues = ("VII/118/ngc2000", "VII/281/glade2")

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
        literal = adql_literal(query.strip())
        # The catalogue and columns are code-owned allowlists; callers cannot choose either.
        rows = await self._tap.query(
            'SELECT TOP 20 Name, RA2000, DE2000, Type FROM "VII/118/ngc2000" '
            f"WHERE Name = {literal}",
            max_rows=limit,
        )
        return [_from_ngc_row(row) for row in rows]

    async def get(self, object_id: str) -> CelestialObject | None:
        fixture = self._fixtures.get(object_id.casefold())
        if fixture is not None or self._tap is None:
            return fixture
        rows = await self._tap.query(
            'SELECT TOP 1 Name, RA2000, DE2000, Type FROM "VII/118/ngc2000" '
            f"WHERE Name = {adql_literal(object_id)}",
            max_rows=1,
        )
        return _from_ngc_row(rows[0]) if rows else None


def _from_ngc_row(row: dict[str, object]) -> CelestialObject:
    name = str(row["Name"])
    object_type = str(row.get("Type") or "").casefold()
    kind = CelestialObjectClass.CLUSTER if "cluster" in object_type else CelestialObjectClass.NEBULA
    return CelestialObject(
        identifier=CelestialObjectId(provider=CatalogSource.VIZIER, object_id=name),
        name=name,
        object_class=kind,
        coordinates=CelestialCoordinates(
            right_ascension_deg=_number(row["RA2000"]),
            declination_deg=_number(row["DE2000"]),
        ),
        attribution=VizierCatalogProvider.attribution,
    )


def _number(value: object) -> float:
    if not isinstance(value, (str, int, float)):
        raise ValueError("VizieR response has an invalid coordinate")
    return float(value)
