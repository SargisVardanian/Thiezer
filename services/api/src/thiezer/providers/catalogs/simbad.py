from __future__ import annotations

from thiezer.domain.celestial_objects import (
    CatalogSource,
    CelestialCoordinates,
    CelestialObject,
    CelestialObjectClass,
    CelestialObjectId,
    CelestialPhotometry,
)
from thiezer.providers.catalogs.base import CatalogProviderError
from thiezer.providers.catalogs.tap import TapClient, adql_contains_literal, adql_literal


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
        if self._tap is None:
            return fixture_matches
        literal = adql_contains_literal(query.strip())
        try:
            rows = await self._tap.query(
                "SELECT TOP 20 basic.oid, basic.main_id, basic.ra, basic.dec, basic.otype, "
                "allfluxes.V FROM basic JOIN ident ON basic.oid = ident.oidref "
                "LEFT OUTER JOIN allfluxes ON basic.oid = allfluxes.oidref "
                f"WHERE ident.id LIKE {literal}",
                max_rows=limit,
            )
            live = _parse_rows(rows)
        except CatalogProviderError:
            return _fallback(fixture_matches)
        except (KeyError, TypeError, ValueError) as exc:
            raise CatalogProviderError("SIMBAD returned invalid object metadata") from exc
        reference = self._fixtures.get(key)
        return _normalise_known_name(live, reference) or fixture_matches

    async def get(self, object_id: str) -> CelestialObject | None:
        fixture = self._fixtures.get(object_id.casefold())
        if self._tap is None:
            return fixture
        literal = adql_literal(object_id)
        try:
            rows = await self._tap.query(
                "SELECT TOP 1 basic.oid, basic.main_id, basic.ra, basic.dec, basic.otype, "
                "allfluxes.V FROM basic JOIN ident ON basic.oid = ident.oidref "
                "LEFT OUTER JOIN allfluxes ON basic.oid = allfluxes.oidref "
                f"WHERE ident.id = {literal}",
                max_rows=1,
            )
            return _from_row(rows[0]) if rows else fixture
        except CatalogProviderError:
            return _fallback_object(fixture)
        except (KeyError, TypeError, ValueError) as exc:
            raise CatalogProviderError("SIMBAD returned invalid object metadata") from exc


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
        photometry=CelestialPhotometry(visual_magnitude=_optional_number(row.get("V"))),
        attribution=SimbadCatalogProvider.attribution,
    )


def _number(value: object) -> float:
    if not isinstance(value, (str, int, float)):
        raise ValueError("catalog response has an invalid numeric field")
    return float(value)


def _optional_number(value: object) -> float | None:
    return _number(value) if value is not None else None


def _parse_rows(rows: list[dict[str, object]]) -> list[CelestialObject]:
    parsed: dict[str, CelestialObject] = {}
    for row in rows:
        try:
            item = _from_row(row)
        except (KeyError, TypeError, ValueError):
            continue
        parsed[item.identifier.object_id] = item
    if rows and not parsed:
        raise CatalogProviderError("SIMBAD returned no rows with usable coordinates")
    return list(parsed.values())


def _normalise_known_name(
    items: list[CelestialObject], reference: CelestialObject | None
) -> list[CelestialObject]:
    if reference is None or reference.coordinates is None or not items:
        return items
    ordered = sorted(
        items,
        key=lambda item: _coordinate_distance_squared(item, reference),
    )
    closest = ordered[0]
    if _coordinate_distance_squared(closest, reference) <= (1 / 60) ** 2:
        ordered[0] = closest.model_copy(
            update={"name": reference.name, "aliases": reference.aliases}
        )
    return ordered


def _coordinate_distance_squared(item: CelestialObject, reference: CelestialObject) -> float:
    if item.coordinates is None or reference.coordinates is None:
        return float("inf")
    return (
        item.coordinates.right_ascension_deg - reference.coordinates.right_ascension_deg
    ) ** 2 + (item.coordinates.declination_deg - reference.coordinates.declination_deg) ** 2


def _fallback(items: list[CelestialObject]) -> list[CelestialObject]:
    return [item for item in (_fallback_object(value) for value in items) if item is not None]


def _fallback_object(item: CelestialObject | None) -> CelestialObject | None:
    if item is None:
        return None
    return item.model_copy(
        update={
            "warnings": tuple(
                dict.fromkeys((*item.warnings, "Live SIMBAD unavailable; bundled fallback used."))
            )
        }
    )


def simbad_fixture(*, tap: TapClient | None = None) -> SimbadCatalogProvider:
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
    return SimbadCatalogProvider(records, tap=tap)
