from __future__ import annotations

from thiezer.domain.celestial_objects import (
    CatalogSource,
    CelestialCoordinates,
    CelestialObject,
    CelestialObjectClass,
    CelestialObjectId,
)
from thiezer.providers.catalogs.tap import TapClient, adql_literal


class SimbadCatalogProvider:
    source = CatalogSource.SIMBAD
    attribution = "SIMBAD, CDS, Strasbourg"

    def __init__(
        self, fixtures: dict[str, CelestialObject] | None = None, *, tap: TapClient | None = None
    ) -> None:
        self._fixtures = fixtures or {}
        self._tap = tap

    async def search(self, query: str, *, limit: int) -> list[CelestialObject]:
        key = query.casefold().strip()
        matches = [
            item
            for item in self._fixtures.values()
            if key in item.name.casefold() or any(key in alias.casefold() for alias in item.aliases)
        ]
        fixture_matches = list({item.identifier.object_id: item for item in matches}.values())[
            :limit
        ]
        if fixture_matches or self._tap is None:
            return fixture_matches
        literal = adql_literal(query.strip())
        rows = await self._tap.query(
            "SELECT TOP 20 basic.oid, basic.main_id, basic.ra, basic.dec, basic.otype "
            "FROM basic JOIN ident ON basic.oid = ident.oidref "
            f"WHERE ident.id = {literal}",
            max_rows=limit,
        )
        return [_from_row(row) for row in rows]

    async def get(self, object_id: str) -> CelestialObject | None:
        fixture = self._fixtures.get(object_id.casefold())
        if fixture is not None or self._tap is None:
            return fixture
        literal = adql_literal(object_id)
        rows = await self._tap.query(
            "SELECT TOP 1 basic.oid, basic.main_id, basic.ra, basic.dec, basic.otype "
            "FROM basic JOIN ident ON basic.oid = ident.oidref "
            f"WHERE ident.id = {literal}",
            max_rows=1,
        )
        return _from_row(rows[0]) if rows else None


def _from_row(row: dict[str, object]) -> CelestialObject:
    identifier = str(row.get("main_id") or row.get("oid") or "unknown")
    otype = str(row.get("otype") or "").upper()
    object_class = CelestialObjectClass.GALAXY if "G" in otype else CelestialObjectClass.STAR
    return CelestialObject(
        identifier=CelestialObjectId(provider=CatalogSource.SIMBAD, object_id=identifier),
        name=identifier,
        object_class=object_class,
        coordinates=CelestialCoordinates(
            right_ascension_deg=_number(row["ra"]), declination_deg=_number(row["dec"])
        ),
        attribution=SimbadCatalogProvider.attribution,
    )


def _number(value: object) -> float:
    if not isinstance(value, (str, int, float)):
        raise ValueError("catalog response has an invalid numeric field")
    return float(value)


def simbad_fixture() -> SimbadCatalogProvider:
    def item(
        object_id: str,
        name: str,
        aliases: tuple[str, ...],
        kind: CelestialObjectClass,
        ra: float,
        dec: float,
    ) -> CelestialObject:
        return CelestialObject(
            identifier=CelestialObjectId(provider=CatalogSource.SIMBAD, object_id=object_id),
            name=name,
            aliases=aliases,
            object_class=kind,
            coordinates=CelestialCoordinates(right_ascension_deg=ra, declination_deg=dec),
            attribution="SIMBAD, CDS, Strasbourg",
        )

    objects = [
        item(
            "Sirius",
            "Sirius",
            ("Alpha Canis Majoris",),
            CelestialObjectClass.STAR,
            101.287155,
            -16.716116,
        ),
        item(
            "Alpha Centauri",
            "Alpha Centauri",
            ("Rigil Kentaurus",),
            CelestialObjectClass.STAR,
            219.902058,
            -60.833993,
        ),
        item(
            "Betelgeuse",
            "Betelgeuse",
            ("Alpha Orionis",),
            CelestialObjectClass.STAR,
            88.792939,
            7.407064,
        ),
        item(
            "51 Peg",
            "51 Pegasi",
            ("51 Peg",),
            CelestialObjectClass.STAR,
            344.366,
            20.768,
        ),
        item(
            "M 31",
            "Andromeda Galaxy",
            ("M31", "NGC 224"),
            CelestialObjectClass.GALAXY,
            10.684708,
            41.26875,
        ),
        item(
            "M 42",
            "Orion Nebula",
            ("M42", "NGC 1976"),
            CelestialObjectClass.NEBULA,
            83.822083,
            -5.391111,
        ),
        item(
            "Sgr A*",
            "Sagittarius A*",
            ("Sgr A*",),
            CelestialObjectClass.OTHER,
            266.416833,
            -29.007806,
        ),
    ]
    records = {
        alias.casefold(): value
        for value in objects
        for alias in (value.identifier.object_id, value.name, *value.aliases)
    }
    return SimbadCatalogProvider(records)
