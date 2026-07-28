"""VizieR TAP adapter limited to reviewed deep-sky catalogue schemas."""

from __future__ import annotations

import re

from thiezer.domain.celestial_objects import (
    CatalogSource,
    CelestialCoordinates,
    CelestialObject,
    CelestialObjectClass,
    CelestialObjectId,
    CelestialPhotometry,
    CelestialPhysicalProperties,
)
from thiezer.providers.catalogs.base import CatalogProviderError
from thiezer.providers.catalogs.tap import TapClient, adql_literal


class VizierCatalogProvider:
    source = CatalogSource.VIZIER
    attribution = "VizieR catalogue service, CDS, Strasbourg"
    # Table and column identifiers remain code-owned; users can never select either.
    allowlisted_catalogues = ("VII/118/names", "VII/118/ngc2000")

    def __init__(
        self, *, tap: TapClient | None = None, fixtures: dict[str, CelestialObject] | None = None
    ) -> None:
        self._tap = tap
        self._fixtures = fixtures or {}

    async def search(self, query: str, *, limit: int) -> list[CelestialObject]:
        matches = self._fixture_matches(query, limit)
        if self._tap is None:
            return matches
        try:
            designation = await self._resolve_designation(query)
            if designation is None:
                return matches
            rows = await self._query_catalogue(designation, limit)
            live = [_from_ngc_row(row, query) for row in rows]
            return live or matches
        except CatalogProviderError:
            return _fallback(matches)
        except (KeyError, TypeError, ValueError) as exc:
            raise CatalogProviderError("VizieR returned invalid object metadata") from exc

    async def get(self, object_id: str) -> CelestialObject | None:
        fixture = self._fixtures.get(object_id.casefold())
        if self._tap is None:
            return fixture
        try:
            designation = await self._resolve_designation(object_id)
            if designation is None:
                return fixture
            rows = await self._query_catalogue(designation, 1)
            return _from_ngc_row(rows[0], object_id) if rows else fixture
        except CatalogProviderError:
            return _fallback_object(fixture)
        except (KeyError, TypeError, ValueError) as exc:
            raise CatalogProviderError("VizieR returned invalid object metadata") from exc

    def _fixture_matches(self, query: str, limit: int) -> list[CelestialObject]:
        needle = query.casefold()
        return [
            item
            for item in self._fixtures.values()
            if needle in item.name.casefold()
            or any(needle in alias.casefold() for alias in item.aliases)
        ][:limit]

    async def _resolve_designation(self, query: str) -> str | None:
        if self._tap is None:
            return None
        messier = re.fullmatch(r"\s*M\s*(\d{1,3})\s*", query, flags=re.IGNORECASE)
        if messier is not None:
            # The wildcard is code-owned and only follows a validated integer.
            pattern = adql_literal(f"M%{int(messier.group(1))}")
            rows = await self._tap.query(
                f'SELECT TOP 5 "Object", "Name" FROM "VII/118/names" WHERE "Object" LIKE {pattern}',
                max_rows=5,
            )
            return str(rows[0]["Name"]) if rows else None
        ngc = re.fullmatch(r"\s*NGC\s*(\d{1,4})\s*", query, flags=re.IGNORECASE)
        if ngc is not None:
            return f" {int(ngc.group(1)):04d}"
        ic = re.fullmatch(r"\s*IC\s*(\d{1,4})\s*", query, flags=re.IGNORECASE)
        if ic is not None:
            return f"I{int(ic.group(1)):04d}"
        return query.strip()

    async def _query_catalogue(self, designation: str, limit: int) -> list[dict[str, object]]:
        assert self._tap is not None
        return await self._tap.query(
            'SELECT TOP 20 "Name", "Type", "RAB2000", "DEB2000", "size", "mag" '
            'FROM "VII/118/ngc2000" '
            f'WHERE "Name" = {adql_literal(designation)}',
            max_rows=limit,
        )


def _from_ngc_row(row: dict[str, object], requested_name: str) -> CelestialObject:
    from astropy import units
    from astropy.coordinates import FK4, SkyCoord
    from astropy.time import Time

    catalogue_name = str(row["Name"]).strip()
    b2000 = SkyCoord(
        ra=_number(row["RAB2000"]) * units.deg,
        dec=_number(row["DEB2000"]) * units.deg,
        frame=FK4(equinox=Time(2000.0, format="byear")),
    )
    icrs = b2000.icrs
    object_type = str(row.get("Type") or "").strip().casefold()
    kind = _classify(object_type)
    magnitude = _optional_number(row.get("mag"))
    angular_size = _optional_number(row.get("size"))
    canonical = requested_name.strip().upper() if requested_name.strip() else catalogue_name
    return CelestialObject(
        identifier=CelestialObjectId(provider=CatalogSource.VIZIER, object_id=catalogue_name),
        name=canonical,
        aliases=(catalogue_name,) if canonical != catalogue_name else (),
        object_class=kind,
        coordinates=CelestialCoordinates(
            right_ascension_deg=float(icrs.ra.deg),
            declination_deg=float(icrs.dec.deg),
            frame="ICRS",
        ),
        photometry=(
            CelestialPhotometry(visual_magnitude=magnitude) if magnitude is not None else None
        ),
        physical=(
            CelestialPhysicalProperties(angular_major_axis_arcmin=angular_size)
            if angular_size is not None
            else None
        ),
        attribution=VizierCatalogProvider.attribution,
        uncertainty=("VizieR NGC 2000.0 positions are transformed from FK4 B2000 to ICRS.",),
    )


def _classify(value: str) -> CelestialObjectClass:
    if value in {"oc", "gc"}:
        return CelestialObjectClass.CLUSTER
    if value in {"nb", "pn", "df"}:
        return CelestialObjectClass.NEBULA
    return CelestialObjectClass.OTHER


def _number(value: object) -> float:
    if not isinstance(value, (str, int, float)):
        raise ValueError("VizieR response has an invalid coordinate")
    return float(value)


def _optional_number(value: object) -> float | None:
    return _number(value) if value is not None else None


def _fallback(items: list[CelestialObject]) -> list[CelestialObject]:
    return [item for item in (_fallback_object(value) for value in items) if item is not None]


def _fallback_object(item: CelestialObject | None) -> CelestialObject | None:
    if item is None:
        return None
    return item.model_copy(
        update={
            "warnings": tuple(
                dict.fromkeys((*item.warnings, "Live VizieR unavailable; bundled fallback used."))
            )
        }
    )
