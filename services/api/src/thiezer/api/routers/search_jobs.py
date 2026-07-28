from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from thiezer.domain.contracts import RecommendationSearchRequest
from thiezer.services.query_jobs import job_events_payload, job_payload

router = APIRouter(prefix="/v1", tags=["search-jobs"])


@router.post("/search")
async def search(body: RecommendationSearchRequest, request: Request) -> object:
    return await request.app.state.resources.recommendation_service.search(body)


@router.post("/search-jobs")
async def create_job(body: RecommendationSearchRequest, request: Request) -> dict[str, object]:
    return job_payload(request.app.state.resources.query_jobs.start(body))


@router.get("/search-jobs/{query_id}")
async def get_job(query_id: str, request: Request) -> dict[str, object]:
    job = request.app.state.resources.query_jobs.get(query_id)
    if job is None:
        raise HTTPException(status_code=404, detail="query job not found or expired")
    return job_payload(job)


@router.get("/search-jobs/{query_id}/events")
async def events(query_id: str, request: Request) -> dict[str, object]:
    job = request.app.state.resources.query_jobs.get(query_id)
    if job is None:
        raise HTTPException(status_code=404, detail="query job not found or expired")
    return job_events_payload(job)


@router.delete("/search-jobs/{query_id}")
async def delete_job(query_id: str, request: Request) -> dict[str, bool]:
    return {"cancelled": request.app.state.resources.query_jobs.cancel(query_id)}
