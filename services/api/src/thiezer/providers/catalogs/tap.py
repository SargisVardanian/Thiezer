from __future__ import annotations

import asyncio
import random

import httpx

from thiezer.providers.catalogs.base import CatalogProviderError


class TapClient:
    def __init__(self, endpoint: str, client: httpx.AsyncClient) -> None:
        self._endpoint, self._client, self._semaphore = endpoint, client, asyncio.Semaphore(4)

    async def query(self, adql: str, *, max_rows: int = 10) -> list[dict[str, object]]:
        if len(adql) > 4000 or not 1 <= max_rows <= 25:
            raise ValueError("unsafe TAP query limit")
        async with self._semaphore:
            for attempt in range(3):
                try:
                    response = await self._client.post(
                        self._endpoint,
                        data={
                            "REQUEST": "doQuery",
                            "LANG": "ADQL",
                            "FORMAT": "json",
                            "MAXREC": str(max_rows),
                            "QUERY": adql,
                        },
                        timeout=httpx.Timeout(connect=5, read=20, write=5, pool=5),
                    )
                except httpx.HTTPError as exc:
                    if attempt == 2:
                        raise CatalogProviderError("catalog request failed") from exc
                    await asyncio.sleep((0.1 * 2**attempt) + random.random() * 0.1)
                    continue
                if response.status_code < 500:
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        # A remote TAP service can reject a valid user query because of
                        # a transient catalogue-side issue.  Surface that through the
                        # provider boundary so resolution can fall back instead of
                        # turning an autocomplete request into a 500 response.
                        raise CatalogProviderError(
                            "catalog request was rejected", retryable=False
                        ) from exc
                    if len(response.content) > 2_000_000:
                        raise ValueError("catalog response too large")
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise CatalogProviderError("catalog returned invalid JSON") from exc
                    return _normalise_tap_rows(payload)
                await asyncio.sleep((0.1 * 2**attempt) + random.random() * 0.1)
        raise CatalogProviderError("catalog temporary failure")


def adql_literal(value: str) -> str:
    """Escape a typed string literal; callers still own a fixed query template."""
    if not value or len(value) > 256 or "\x00" in value:
        raise ValueError("invalid catalog identifier")
    return "'" + value.replace("'", "''") + "'"


def adql_contains_literal(value: str) -> str:
    """Build the sole permitted user-controlled LIKE literal for fixed query templates."""
    if not value or len(value) > 120 or "\x00" in value:
        raise ValueError("invalid catalog search")
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return adql_literal(f"%{escaped}%")


def _normalise_tap_rows(payload: object) -> list[dict[str, object]]:
    """Return a stable mapping form for both common TAP JSON encodings.

    TAP services are allowed to return rows either as JSON objects or as arrays
    accompanied by a ``metadata`` column declaration.  Providers should never
    have to depend on a service-specific encoding.
    """
    if isinstance(payload, list):
        if not all(isinstance(row, dict) for row in payload):
            raise CatalogProviderError("catalog returned rows without column names")
        return list(payload)
    if not isinstance(payload, dict):
        raise CatalogProviderError("catalog returned an invalid JSON envelope")
    rows = payload.get("data", payload)
    if not isinstance(rows, list):
        raise CatalogProviderError("catalog returned invalid rows")
    if not rows or all(isinstance(row, dict) for row in rows):
        return list(rows)
    metadata = payload.get("metadata")
    if not isinstance(metadata, list):
        raise CatalogProviderError("catalog rows are missing metadata")
    names: list[str] = []
    for entry in metadata:
        if not isinstance(entry, dict):
            raise CatalogProviderError("catalog returned invalid column metadata")
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise CatalogProviderError("catalog returned invalid column metadata")
        names.append(name)
    result: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(names):
            raise CatalogProviderError("catalog returned malformed row data")
        result.append(dict(zip(names, row, strict=True)))
    return result
