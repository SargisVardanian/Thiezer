from __future__ import annotations

from thiezer.domain.contracts import (
    StoreSearchRequest,
    StoreSearchResponse,
    StoreSearchResult,
)
from thiezer.domain.geospatial import build_route_handoffs
from thiezer.repositories.seed import StoreRepository


class StoreSearchService:
    def __init__(self, repository: StoreRepository) -> None:
        self._repository = repository

    def search(self, request: StoreSearchRequest) -> StoreSearchResponse:
        matches = self._repository.search(
            user_location=request.user_location,
            scope=request.scope,
            country_code=request.country_code,
            max_distance_km=request.max_distance_km,
            limit=request.max_results,
        )
        results = []
        for store, distance in matches:
            routes = (
                build_route_handoffs(
                    origin=request.user_location,
                    destination=store.point,
                    label=store.name,
                )
                if store.point is not None
                else []
            )
            results.append(StoreSearchResult(store=store, distance_km=distance, routes=routes))
        return StoreSearchResponse(
            results=results,
            coverage_country_codes=self._repository.coverage_country_codes,
        )
