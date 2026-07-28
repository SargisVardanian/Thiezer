from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from thiezer.domain.celestial_objects import CatalogSource, CelestialObjectClass, CelestialObjectId
from thiezer.domain.contracts import GeoPoint

router = APIRouter(prefix="/v1/celestial-objects", tags=["celestial"])


class ResolveRequest(BaseModel):
    provider: CatalogSource
    object_id: str = Field(min_length=1, max_length=256)


class VisibilityRequest(ResolveRequest):
    point: GeoPoint
    timestamp_utc: datetime


@router.get("/search")
async def search(
    q: str, request: Request, types: str | None = None, limit: int = 10
) -> list[dict[str, object]]:
    try:
        selected = _parse_types(types)
        results = await request.app.state.resources.celestial_resolution.search(
            q, limit=limit, types=selected
        )
        return [item.model_dump(mode="json") for item in results]
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


@router.post("/resolve")
async def resolve(body: ResolveRequest, request: Request) -> dict[str, object]:
    return await get(body.provider, body.object_id, request)


@router.post("/visibility")
async def visibility(body: VisibilityRequest, request: Request) -> dict[str, object]:
    target = await request.app.state.resources.celestial_resolution.resolve(
        CelestialObjectId(provider=body.provider, object_id=body.object_id)
    )
    return (
        await request.app.state.resources.celestial_visibility.get(
            target=target, point=body.point, timestamp_utc=body.timestamp_utc
        )
    ).model_dump(mode="json")


def _parse_types(value: str | None) -> set[CelestialObjectClass] | None:
    if value is None or not value.strip():
        return None
    try:
        return {CelestialObjectClass(item.strip()) for item in value.split(",")}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid celestial object type") from exc
