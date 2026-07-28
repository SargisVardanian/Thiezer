"""Small JPL Horizons API client for objects not represented by local DE421."""

from __future__ import annotations

import asyncio

import httpx

from thiezer.providers.catalogs.base import CatalogProviderError


class HorizonsClient:
    attribution = "NASA/JPL Horizons System"

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str = "https://ssd.jpl.nasa.gov/api/horizons.api",
    ) -> None:
        self._client, self._base_url, self._semaphore = client, base_url, asyncio.Semaphore(2)

    async def vectors(self, *, command: str, timestamp_utc: str) -> dict[str, object]:
        if not command or len(command) > 128 or "\n" in command:
            raise ValueError("invalid Horizons object identifier")
        async with self._semaphore:
            try:
                response = await self._client.get(
                    self._base_url,
                    params={
                        "format": "json",
                        "COMMAND": command,
                        "EPHEM_TYPE": "OBSERVER",
                        "CENTER": "500@399",
                        "TLIST": timestamp_utc,
                        "QUANTITIES": "1,4",
                    },
                    timeout=httpx.Timeout(connect=5, read=20, write=5, pool=5),
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise CatalogProviderError("Horizons request failed") from exc
            if len(response.content) > 1_000_000:
                raise CatalogProviderError("Horizons response too large", retryable=False)
            return response.json()
