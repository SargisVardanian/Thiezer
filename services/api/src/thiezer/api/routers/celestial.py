from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from thiezer.api.dependencies import get_recommendation_service
from thiezer.domain.celestial_objects import CatalogSource, CelestialObjectClass, CelestialObjectId
from thiezer.domain.contracts import (
    GeoPoint,
    RecommendationSearchRequest,
    RecommendationSearchResponse,
)
from thiezer.providers.catalogs.base import CatalogProviderError
from thiezer.services.recommendations import RecommendationService

router = APIRouter(prefix="/v1/celestial-objects", tags=["celestial"])


class ResolveRequest(BaseModel):
    provider: CatalogSource
    object_id: str = Field(min_length=1, max_length=256)


class VisibilityRequest(ResolveRequest):
    point: GeoPoint
    timestamp_utc: datetime


@router.get("/search")
async def search(
    q: str,
    request: Request,
    types: str | None = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> dict[str, object]:
    try:
        selected = _parse_types(types)
        results = await request.app.state.resources.celestial_resolution.search_with_diagnostics(
            q, limit=limit, types=selected
        )
        return results.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{provider}/{object_id}")
async def get(provider: CatalogSource, object_id: str, request: Request) -> dict[str, object]:
    try:
        result = await request.app.state.resources.celestial_resolution.resolve(
            CelestialObjectId(provider=provider, object_id=object_id)
        )
        return result.model_dump(mode="json")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CatalogProviderError as exc:
        raise HTTPException(
            status_code=503, detail="catalog provider is temporarily unavailable"
        ) from exc


@router.post("/resolve")
async def resolve(body: ResolveRequest, request: Request) -> dict[str, object]:
    return await get(body.provider, body.object_id, request)


@router.post("/visibility")
async def visibility(body: VisibilityRequest, request: Request) -> dict[str, object]:
    try:
        target = await request.app.state.resources.celestial_resolution.resolve(
            CelestialObjectId(provider=body.provider, object_id=body.object_id)
        )
        return (
            await request.app.state.resources.celestial_visibility.get(
                target=target, point=body.point, timestamp_utc=body.timestamp_utc
            )
        ).model_dump(mode="json")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CatalogProviderError as exc:
        raise HTTPException(
            status_code=503, detail="ephemeris provider is temporarily unavailable"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/recommendations", response_model=RecommendationSearchResponse)
async def recommendations(
    body: RecommendationSearchRequest,
    service: Annotated[RecommendationService, Depends(get_recommendation_service)],
) -> RecommendationSearchResponse:
    try:
        return await service.search(body)
    except CatalogProviderError as exc:
        raise HTTPException(
            status_code=503, detail="catalog provider is temporarily unavailable"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _parse_types(value: str | None) -> set[CelestialObjectClass] | None:
    if value is None or not value.strip():
        return None
    try:
        return {CelestialObjectClass(item.strip()) for item in value.split(",")}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid celestial object type") from exc
