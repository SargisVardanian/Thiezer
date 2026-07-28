"""JPL Horizons observer-table adapter for non-DE421 Solar-System targets."""

from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from thiezer.domain.celestial_objects import (
    CatalogSource,
    CelestialObject,
    CelestialObjectClass,
    CelestialObjectId,
)
from thiezer.providers.catalogs.base import CatalogProviderError


@dataclass(frozen=True, slots=True)
class HorizonsObserverEvent:
    timestamp_utc: datetime
    kind: str
    azimuth_deg: float
    altitude_deg: float


class HorizonsClient:
    attribution = "NASA/JPL Horizons System"

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str = "https://ssd.jpl.nasa.gov/api/horizons.api",
    ) -> None:
        self._client, self._base_url, self._semaphore = client, base_url, asyncio.Semaphore(1)

    async def lookup(self, command: str) -> CelestialObject | None:
        payload = await self._request({"COMMAND": _command(command), "MAKE_EPHEM": "NO"})
        result = _result(payload)
        match = re.search(r"Target body name:\s*([^\r\n]+)", result)
        if match is None:
            return None
        name = match.group(1).strip()
        numeric_identifier = re.search(r"\((\d+)\)\s*$", name)
        return CelestialObject(
            identifier=CelestialObjectId(
                provider=CatalogSource.HORIZONS,
                object_id=numeric_identifier.group(1) if numeric_identifier else command,
            ),
            name=name,
            object_class=_classify(command, name),
            attribution=self.attribution,
            warnings=("Position is computed dynamically by JPL Horizons.",),
        )

    async def observer(
        self, *, command: str, latitude_deg: float, longitude_deg: float, timestamp_utc: datetime
    ) -> tuple[float, float]:
        timestamp = timestamp_utc.strftime("%Y-%b-%d %H:%M")
        payload = await self._request(
            {
                "COMMAND": _command(command),
                "EPHEM_TYPE": "OBSERVER",
                "CENTER": "'coord@399'",
                "SITE_COORD": f"'{longitude_deg},{latitude_deg},0'",
                "TLIST": f"'{timestamp}'",
                "QUANTITIES": "'1,4'",
                "CSV_FORMAT": "YES",
            }
        )
        result = _result(payload)
        try:
            line = result.split("$$SOE", 1)[1].split("$$EOE", 1)[0].strip().splitlines()[0]
            cells = [cell.strip() for cell in line.split(",")]
            return float(cells[-2]), float(cells[-1])
        except (IndexError, ValueError) as exc:
            raise CatalogProviderError("Horizons observer response was not parseable") from exc

    async def observer_events(
        self,
        *,
        command: str,
        latitude_deg: float,
        longitude_deg: float,
        timestamp_utc: datetime,
    ) -> list[HorizonsObserverEvent]:
        start = timestamp_utc.astimezone(UTC) - timedelta(hours=12)
        stop = timestamp_utc.astimezone(UTC) + timedelta(hours=36)
        payload = await self._request(
            {
                "COMMAND": _command(command),
                "EPHEM_TYPE": "OBSERVER",
                "CENTER": "'coord@399'",
                "SITE_COORD": f"'{longitude_deg},{latitude_deg},0'",
                "START_TIME": f"'{start.strftime('%Y-%b-%d %H:%M')}'",
                "STOP_TIME": f"'{stop.strftime('%Y-%b-%d %H:%M')}'",
                # Official Horizons GEO mode emits rise/transit/set events only.
                "STEP_SIZE": "'1m GEO'",
                "QUANTITIES": "'1,4'",
                "CSV_FORMAT": "YES",
            }
        )
        return _parse_observer_events(_result(payload))

    async def _request(self, params: dict[str, str]) -> dict[str, object]:
        if not params.get("COMMAND"):
            raise ValueError("invalid Horizons object identifier")
        async with self._semaphore:
            for attempt in range(3):
                try:
                    response = await self._client.get(
                        self._base_url,
                        params={"format": "json", **params},
                        timeout=httpx.Timeout(connect=5, read=20, write=5, pool=5),
                    )
                    if response.status_code < 500:
                        response.raise_for_status()
                        if len(response.content) > 1_000_000:
                            raise CatalogProviderError(
                                "Horizons response too large", retryable=False
                            )
                        return response.json()
                except httpx.HTTPError as exc:
                    if attempt == 2:
                        raise CatalogProviderError("Horizons request failed") from exc
                await asyncio.sleep(0.1 * (2**attempt) + random.random() * 0.1)
        raise CatalogProviderError("Horizons temporary failure")


class HorizonsCatalogProvider:
    source = CatalogSource.HORIZONS
    attribution = HorizonsClient.attribution

    def __init__(
        self, client: HorizonsClient, *, fixtures: dict[str, CelestialObject] | None = None
    ) -> None:
        self._client, self._fixtures = client, fixtures or {}

    async def search(self, query: str, *, limit: int) -> list[CelestialObject]:
        fixture = self._fixtures.get(query.casefold())
        try:
            result = await self._client.lookup(query)
        except CatalogProviderError:
            result = _fallback_object(fixture)
        return [result] if result is not None else []

    async def get(self, object_id: str) -> CelestialObject | None:
        fixture = self._fixtures.get(object_id.casefold())
        try:
            return await self._client.lookup(object_id) or fixture
        except CatalogProviderError:
            return _fallback_object(fixture)


def _command(value: str) -> str:
    if not value or len(value) > 128 or any(char in value for char in "\r\n\x00"):
        raise ValueError("invalid Horizons object identifier")
    return f"'{value}'"


def _result(payload: dict[str, object]) -> str:
    result = payload.get("result")
    if not isinstance(result, str):
        raise CatalogProviderError("Horizons returned an invalid response")
    if "INPUT ERROR" in result or "Matching small-bodies" in result:
        raise CatalogProviderError("Horizons target is ambiguous or invalid", retryable=False)
    return result


def _classify(command: str, name: str) -> CelestialObjectClass:
    value = f"{command} {name}".casefold()
    if "comet" in value or value.startswith("1p"):
        return CelestialObjectClass.COMET
    if "asteroid" in value or command.strip().isdecimal():
        return CelestialObjectClass.ASTEROID
    return CelestialObjectClass.SOLAR_SYSTEM_BODY


def _parse_observer_events(result: str) -> list[HorizonsObserverEvent]:
    try:
        lines = result.split("$$SOE", 1)[1].split("$$EOE", 1)[0].strip().splitlines()
    except IndexError as exc:
        raise CatalogProviderError("Horizons event response was not parseable") from exc
    events: list[HorizonsObserverEvent] = []
    for line in lines:
        cells = [cell.strip() for cell in line.split(",")]
        if len(cells) < 7 or cells[2] not in {"r", "t", "s"}:
            continue
        try:
            timestamp = datetime.strptime(cells[0], "%Y-%b-%d %H:%M").replace(tzinfo=UTC)
            events.append(
                HorizonsObserverEvent(
                    timestamp_utc=timestamp,
                    kind=cells[2],
                    azimuth_deg=float(cells[-2]),
                    altitude_deg=float(cells[-1]),
                )
            )
        except ValueError as exc:
            raise CatalogProviderError("Horizons event row was not parseable") from exc
    return events


def _fallback_object(item: CelestialObject | None) -> CelestialObject | None:
    if item is None:
        return None
    return item.model_copy(
        update={
            "warnings": tuple(
                dict.fromkeys((*item.warnings, "Live Horizons unavailable; bundled fallback used."))
            )
        }
    )
