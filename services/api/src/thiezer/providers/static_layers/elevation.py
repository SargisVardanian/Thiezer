from __future__ import annotations

import asyncio
from typing import Any

import httpx

from thiezer.domain.contracts import GeoPoint


class OpenMeteoElevationProvider:
    """Low-cost global elevation lookup with chunking and bounded concurrency."""

    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.AsyncClient,
        chunk_size: int = 100,
        max_concurrency: int = 3,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._chunk_size = max(1, min(100, chunk_size))
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def get_elevations(self, points: list[GeoPoint]) -> list[float | None]:
        if not points:
            return []
        chunks = [
            points[index : index + self._chunk_size]
            for index in range(0, len(points), self._chunk_size)
        ]
        results = await asyncio.gather(*(self._fetch_chunk(chunk) for chunk in chunks))
        return [value for chunk in results for value in chunk]

    async def _fetch_chunk(self, points: list[GeoPoint]) -> list[float | None]:
        params = {
            "latitude": ",".join(f"{point.latitude_deg:.6f}" for point in points),
            "longitude": ",".join(f"{point.longitude_deg:.6f}" for point in points),
        }
        async with self._semaphore:
            response = await self._client.get(f"{self._base_url}/elevation", params=params)
        response.raise_for_status()
        payload: Any = response.json()
        if not isinstance(payload, dict):
            raise ValueError("elevation provider payload must be an object")
        raw = payload.get("elevation")
        if not isinstance(raw, list) or len(raw) != len(points):
            raise ValueError("elevation provider returned an unexpected number of values")
        return [None if value is None else float(value) for value in raw]
