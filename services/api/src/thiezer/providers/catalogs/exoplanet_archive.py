"""NASA Exoplanet Archive TAP adapter with host-star linkage."""

from __future__ import annotations

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


class ExoplanetArchiveProvider:
    source = CatalogSource.EXOPLANET_ARCHIVE
    attribution = "NASA Exoplanet Archive"

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
            if needle in item.identifier.object_id.casefold()
            or needle in item.name.casefold()
            or any(needle in alias.casefold() for alias in item.aliases)
        ][:limit]
        if self._tap is None:
            return matches
        try:
            rows = await self._tap.query(
                "SELECT TOP 20 pl_name, hostname, ra, dec, pl_orbper, tran_flag "
                "FROM pscomppars "
                f"WHERE pl_name LIKE {adql_contains_literal(query.strip())}",
                max_rows=limit,
            )
            live = [_from_row(row) for row in rows]
        except CatalogProviderError:
            return _fallback(matches)
        except (KeyError, TypeError, ValueError) as exc:
            raise CatalogProviderError("Exoplanet Archive returned invalid metadata") from exc
        return live or matches

    async def get(self, object_id: str) -> CelestialObject | None:
        fixture = self._fixtures.get(object_id.casefold())
        if self._tap is None:
            return fixture
        try:
            rows = await self._tap.query(
                "SELECT TOP 1 pl_name, hostname, ra, dec, pl_orbper, tran_flag "
                "FROM pscomppars "
                f"WHERE pl_name = {adql_literal(object_id)}",
                max_rows=1,
            )
            return _from_row(rows[0]) if rows else fixture
        except CatalogProviderError:
            return _fallback_object(fixture)
        except (KeyError, TypeError, ValueError) as exc:
            raise CatalogProviderError("Exoplanet Archive returned invalid metadata") from exc


def _from_row(row: dict[str, object]) -> CelestialObject:
    name = str(row["pl_name"])
    host_name = str(row["hostname"])
    host = CelestialObjectId(provider=CatalogSource.SIMBAD, object_id=host_name)
    coordinates = None
    if row.get("ra") is not None and row.get("dec") is not None:
        coordinates = CelestialCoordinates(
            right_ascension_deg=_number(row["ra"]), declination_deg=_number(row["dec"])
        )
    return CelestialObject(
        identifier=CelestialObjectId(provider=CatalogSource.EXOPLANET_ARCHIVE, object_id=name),
        name=name,
        object_class=CelestialObjectClass.EXOPLANET,
        coordinates=coordinates,
        host_star=host,
        physical=CelestialPhysicalProperties(
            orbital_period_days=_optional_number(row.get("pl_orbper")),
            transit_detected=_truthy(row.get("tran_flag")),
        ),
        attribution=ExoplanetArchiveProvider.attribution,
        warnings=("Visibility refers to the host star, not direct planet detection.",),
    )


def _number(value: object) -> float:
    if not isinstance(value, (str, int, float)):
        raise ValueError("Exoplanet Archive response has an invalid coordinate")
    return float(value)


def _optional_number(value: object) -> float | None:
    return _number(value) if value is not None else None


def _truthy(value: object) -> bool | None:
    if value is None:
        return None
    return str(value).casefold() in {"1", "true", "t", "yes"}


def _fallback(items: list[CelestialObject]) -> list[CelestialObject]:
    return [item for item in (_fallback_object(value) for value in items) if item is not None]


def _fallback_object(item: CelestialObject | None) -> CelestialObject | None:
    if item is None:
        return None
    return item.model_copy(
        update={
            "warnings": tuple(
                dict.fromkeys(
                    (*item.warnings, "Live Exoplanet Archive unavailable; bundled fallback used.")
                )
            )
        }
    )
