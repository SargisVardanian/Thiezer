"""NED modern OverviewOfObject API and TAP adapter.

Legacy ``cgi-bin`` endpoints are intentionally excluded. Name resolution uses the
current stateless NED API; TAP remains a bounded fallback for preferred names.
"""

from __future__ import annotations

import asyncio
import random
import xml.etree.ElementTree as ElementTree

import httpx

from thiezer.domain.celestial_objects import (
    CatalogSource,
    CelestialCoordinates,
    CelestialObject,
    CelestialObjectClass,
    CelestialObjectId,
    CelestialPhysicalProperties,
)
from thiezer.providers.catalogs.base import CatalogProviderError
from thiezer.providers.catalogs.tap import TapClient, adql_contains_literal, adql_literal


class NedCatalogProvider:
    source = CatalogSource.NED
    attribution = "NASA/IPAC Extragalactic Database (NED)"

    def __init__(
        self,
        *,
        tap: TapClient | None = None,
        client: httpx.AsyncClient | None = None,
        fixtures: dict[str, CelestialObject] | None = None,
        overview_url: str = "https://ned.ipac.caltech.edu/NED::API/OverviewOfObject",
    ) -> None:
        self._tap = tap
        self._client = client
        self._fixtures = fixtures or {}
        self._overview_url = overview_url
        self._semaphore = asyncio.Semaphore(2)

    async def search(self, query: str, *, limit: int) -> list[CelestialObject]:
        matches = self._fixture_matches(query, limit)
        try:
            overview = await self._overview(query)
            if overview is not None:
                return [overview]
            live = await self._tap_search(query, limit)
            return live or matches
        except CatalogProviderError:
            return _fallback(matches)

    async def get(self, object_id: str) -> CelestialObject | None:
        fixture = self._fixtures.get(object_id.casefold())
        try:
            overview = await self._overview(object_id)
            if overview is not None:
                return overview
            live = await self._tap_get(object_id)
            return live or fixture
        except CatalogProviderError:
            return _fallback_object(fixture)

    def _fixture_matches(self, query: str, limit: int) -> list[CelestialObject]:
        needle = query.casefold()
        return [
            item
            for item in self._fixtures.values()
            if needle in item.name.casefold()
            or any(needle in alias.casefold() for alias in item.aliases)
        ][:limit]

    async def _overview(self, target: str) -> CelestialObject | None:
        if self._client is None:
            return None
        if not target or len(target) > 256 or any(char in target for char in "\r\n\x00"):
            raise ValueError("invalid NED object identifier")
        async with self._semaphore:
            for attempt in range(3):
                try:
                    response = await self._client.get(
                        self._overview_url,
                        params={"TARGET": target},
                        timeout=httpx.Timeout(connect=5, read=20, write=5, pool=5),
                    )
                    if response.status_code < 500:
                        response.raise_for_status()
                        if len(response.content) > 2_000_000:
                            raise CatalogProviderError("NED response too large", retryable=False)
                        return _parse_overview(response.content, target)
                except httpx.HTTPError as exc:
                    if attempt == 2:
                        raise CatalogProviderError("NED request failed") from exc
                await asyncio.sleep(0.1 * (2**attempt) + random.random() * 0.1)
        raise CatalogProviderError("NED temporary failure")

    async def _tap_search(self, query: str, limit: int) -> list[CelestialObject]:
        if self._tap is None:
            return []
        rows = await self._tap.query(
            "SELECT TOP 20 prefname, ra, dec, prefphytype, z FROM objdir "
            f"WHERE prefname LIKE {adql_contains_literal(query.strip())}",
            max_rows=limit,
        )
        return _parse_tap_rows(rows)

    async def _tap_get(self, object_id: str) -> CelestialObject | None:
        if self._tap is None:
            return None
        rows = await self._tap.query(
            "SELECT TOP 1 prefname, ra, dec, prefphytype, z FROM objdir "
            f"WHERE prefname = {adql_literal(object_id)}",
            max_rows=1,
        )
        parsed = _parse_tap_rows(rows)
        return parsed[0] if parsed else None


def _parse_overview(payload: bytes, requested_name: str) -> CelestialObject | None:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise CatalogProviderError("NED returned invalid VOTable XML") from exc
    fields = root.findall(".//{*}TABLE/{*}FIELD")
    cells = root.findall(".//{*}TABLE/{*}DATA/{*}TABLEDATA/{*}TR/{*}TD")
    if not cells:
        return None
    if len(fields) != len(cells):
        raise CatalogProviderError("NED VOTable columns do not match row data")
    values = {
        field.get("ID", ""): (cell.text or "").strip()
        for field, cell in zip(fields, cells, strict=True)
    }
    aliases = tuple(
        dict.fromkeys(
            value.strip() for value in values.get("CrossID_list", "").split(";") if value.strip()
        )
    )
    canonical = aliases[0] if aliases else requested_name.strip()
    ra = _required_number(values.get("equ_j2000_lon"))
    dec = _required_number(values.get("equ_j2000_lat"))
    angular_arcmin = _optional_number(values.get("o_diam_maj_dia"))
    uncertainty = _optional_number(values.get("unc_sma"))
    return CelestialObject(
        identifier=CelestialObjectId(provider=CatalogSource.NED, object_id=canonical),
        name=canonical,
        aliases=tuple(item for item in aliases[1:] if item != canonical),
        object_class=_classify(values.get("ptype", "")),
        coordinates=CelestialCoordinates(right_ascension_deg=ra, declination_deg=dec),
        physical=CelestialPhysicalProperties(
            redshift=_optional_number(values.get("z")),
            angular_major_axis_arcmin=(angular_arcmin / 60 if angular_arcmin is not None else None),
        ),
        attribution=NedCatalogProvider.attribution,
        uncertainty=(
            (f"NED 95% positional semi-major uncertainty: {uncertainty} arcsec",)
            if uncertainty is not None
            else ()
        ),
    )


def _parse_tap_rows(rows: list[dict[str, object]]) -> list[CelestialObject]:
    result: list[CelestialObject] = []
    for row in rows:
        try:
            name = str(row["prefname"])
            result.append(
                CelestialObject(
                    identifier=CelestialObjectId(provider=CatalogSource.NED, object_id=name),
                    name=name,
                    object_class=_classify(str(row.get("prefphytype") or "")),
                    coordinates=CelestialCoordinates(
                        right_ascension_deg=_required_number(row["ra"]),
                        declination_deg=_required_number(row["dec"]),
                    ),
                    physical=CelestialPhysicalProperties(redshift=_optional_number(row.get("z"))),
                    attribution=NedCatalogProvider.attribution,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    if rows and not result:
        raise CatalogProviderError("NED returned no rows with usable coordinates")
    return result


def _classify(value: str) -> CelestialObjectClass:
    return CelestialObjectClass.GALAXY if "g" in value.casefold() else CelestialObjectClass.OTHER


def _required_number(value: object) -> float:
    if not isinstance(value, (str, int, float)) or value == "":
        raise ValueError("NED response has an invalid numeric field")
    return float(value)


def _optional_number(value: object) -> float | None:
    return _required_number(value) if value not in {None, ""} else None


def _fallback(items: list[CelestialObject]) -> list[CelestialObject]:
    return [item for item in (_fallback_object(value) for value in items) if item is not None]


def _fallback_object(item: CelestialObject | None) -> CelestialObject | None:
    if item is None:
        return None
    return item.model_copy(
        update={
            "warnings": tuple(
                dict.fromkeys((*item.warnings, "Live NED unavailable; bundled fallback used."))
            )
        }
    )
