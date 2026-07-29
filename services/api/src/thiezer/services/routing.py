from __future__ import annotations

from thiezer.domain.contracts import RoadRoute, RoadRouteRequest
from thiezer.providers.routing.base import RoadRoutingProvider


class RoadRoutingService:
    def __init__(self, provider: RoadRoutingProvider) -> None:
        self._provider = provider

    async def route(self, request: RoadRouteRequest) -> RoadRoute:
        return await self._provider.route(request)
