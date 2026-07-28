from __future__ import annotations

from datetime import datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from thiezer.api.dependencies import (
    get_recommendation_service,
    get_store_service,
    get_visibility_service,
)
from thiezer.domain.contracts import (
    GeoPoint,
    RecommendationSearchRequest,
    RecommendationSearchResponse,
    StoreSearchRequest,
    StoreSearchResponse,
    TargetKind,
    TargetVisibilityResponse,
)
from thiezer.services.recommendations import RecommendationService
from thiezer.services.stores import StoreSearchService
from thiezer.services.visibility import VisibilityService

router = APIRouter(prefix="/v1", tags=["discovery"])


@router.get("/targets", response_model=list[dict[str, str]])
async def list_targets() -> list[dict[str, str]]:
    return [
        {"id": TargetKind.ALPHA_CENTAURI, "label": "Alpha Centauri"},
        {"id": TargetKind.MARS, "label": "Mars"},
        {"id": TargetKind.JUPITER, "label": "Jupiter"},
        {"id": TargetKind.MOON, "label": "Moon"},
        {"id": TargetKind.MILKY_WAY, "label": "Milky Way core"},
        {"id": TargetKind.BEST_NIGHT_SKY, "label": "Best general night sky"},
    ]


@router.get("/targets/{target}/visibility", response_model=TargetVisibilityResponse)
async def target_visibility(
    target: TargetKind,
    latitude_deg: Annotated[float, Query(ge=-90.0, le=90.0)],
    longitude_deg: Annotated[float, Query(ge=-180.0, le=180.0)],
    at_utc: datetime,
    service: Annotated[VisibilityService, Depends(get_visibility_service)],
) -> TargetVisibilityResponse:
    return service.get(
        point=GeoPoint(latitude_deg=latitude_deg, longitude_deg=longitude_deg),
        target=target,
        timestamp_utc=at_utc,
    )


@router.post("/recommendations/search", response_model=RecommendationSearchResponse)
async def search_recommendations(
    request: RecommendationSearchRequest,
    service: Annotated[RecommendationService, Depends(get_recommendation_service)],
) -> RecommendationSearchResponse:
    try:
        return await service.search(request)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"external provider failure: {exc}") from exc


@router.post("/stores/search", response_model=StoreSearchResponse)
async def search_stores(
    request: StoreSearchRequest,
    service: Annotated[StoreSearchService, Depends(get_store_service)],
) -> StoreSearchResponse:
    return await service.search(request)
