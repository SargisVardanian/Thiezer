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
                    response.raise_for_status()
                    if len(response.content) > 2_000_000:
                        raise ValueError("catalog response too large")
                    payload = response.json()
                    return payload.get("data", payload) if isinstance(payload, dict) else payload
                await asyncio.sleep((0.1 * 2**attempt) + random.random() * 0.1)
        raise CatalogProviderError("catalog temporary failure")


def adql_literal(value: str) -> str:
    """Escape a typed string literal; callers still own a fixed query template."""
    if not value or len(value) > 256 or "\x00" in value:
        raise ValueError("invalid catalog identifier")
    return "'" + value.replace("'", "''") + "'"
