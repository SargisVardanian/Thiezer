from __future__ import annotations

from typing import Protocol

from thiezer.domain.contracts import RoadRoute, RoadRouteRequest


class RoadRoutingProvider(Protocol):
    """External road routing is isolated behind this provider contract."""

    async def route(self, request: RoadRouteRequest) -> RoadRoute: ...
