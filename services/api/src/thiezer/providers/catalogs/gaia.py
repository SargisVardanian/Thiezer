"""Gaia DR3 TAP adapter with a fixed, injection-safe schema projection."""

from __future__ import annotations

from thiezer.domain.celestial_objects import (
    CatalogSource,
    CelestialCoordinates,
    CelestialMotion,
    CelestialObject,
    CelestialObjectClass,
    CelestialObjectId,
    CelestialPhotometry,
)
from thiezer.providers.catalogs.tap import TapClient, adql_literal


class GaiaCatalogProvider:
    source = CatalogSource.GAIA
    attribution = "Gaia Data Processing and Analysis Consortium (DPAC), Gaia DR3"

    def __init__(
        self, *, tap: TapClient | None = None, fixtures: dict[str, CelestialObject] | None = None
    ) -> None:
        self._tap, self._fixtures = tap, fixtures or {}

    async def search(self, query: str, *, limit: int) -> list[CelestialObject]:
        # Gaia source IDs are stable numerical identifiers, not a general name resolver.
        return [item for key, item in self._fixtures.items() if query.casefold() in key][:limit]

    async def get(self, object_id: str) -> CelestialObject | None:
        if object_id in self._fixtures:
            return self._fixtures[object_id]
        if self._tap is None or not object_id.isdecimal():
            return None
        rows = await self._tap.query(
            "SELECT TOP 1 source_id, ra, dec, ref_epoch, pmra, pmdec, parallax, radial_velocity, phot_g_mean_mag "
            f"FROM gaiadr3.gaia_source WHERE source_id = {adql_literal(object_id)}",
            max_rows=1,
        )
        return _from_row(rows[0]) if rows else None


def _from_row(row: dict[str, object]) -> CelestialObject:
    return CelestialObject(
        identifier=CelestialObjectId(provider=CatalogSource.GAIA, object_id=str(row["source_id"])),
        name=f"Gaia DR3 {row['source_id']}",
        object_class=CelestialObjectClass.STAR,
        coordinates=CelestialCoordinates(
            right_ascension_deg=_required_number(row["ra"]),
            declination_deg=_required_number(row["dec"]),
            reference_epoch_jyear=_required_number(row.get("ref_epoch") or 2016.0),
        ),
        motion=CelestialMotion(
            proper_motion_ra_mas_per_year=_number(row.get("pmra")),
            proper_motion_dec_mas_per_year=_number(row.get("pmdec")),
            parallax_mas=_number(row.get("parallax")),
            radial_velocity_km_s=_number(row.get("radial_velocity")),
        ),
        photometry=CelestialPhotometry(gaia_g_magnitude=_number(row.get("phot_g_mean_mag"))),
        attribution=GaiaCatalogProvider.attribution,
    )


def _number(value: object) -> float | None:
    return _required_number(value) if value is not None else None


def _required_number(value: object) -> float:
    if not isinstance(value, (str, int, float)):
        raise ValueError("Gaia response has an invalid numeric field")
    return float(value)
