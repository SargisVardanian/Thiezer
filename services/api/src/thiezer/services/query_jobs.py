from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from thiezer.domain.contracts import RecommendationSearchRequest, RecommendationSearchResponse
from thiezer.services.recommendations import RecommendationService


class QueryJobStage(StrEnum):
    QUEUED = "queued"
    RESOLVING_TARGET = "resolving_target"
    GENERATING_CELLS = "generating_cells"
    FETCHING_ELEVATION = "fetching_elevation"
    READING_SURFACE_WINDOWS = "reading_surface_windows"
    APPLYING_STATIC_FILTERS = "applying_static_filters"
    FETCHING_WEATHER = "fetching_weather"
    CALCULATING_ASTRONOMY = "calculating_astronomy"
    CHECKING_ACCESS = "checking_access"
    RANKING = "ranking"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass(slots=True)
class QueryJob:
    query_id: str
    stage: QueryJobStage
    created_at_utc: datetime
    expires_at_utc: datetime
    error: str | None = None
    result: RecommendationSearchResponse | None = None
    task: asyncio.Task[None] | None = None


class EphemeralQueryJobs:
    def __init__(self, service: RecommendationService, *, ttl_seconds: int) -> None:
        self._service = service
        self._ttl = timedelta(seconds=ttl_seconds)
        self._jobs: dict[str, QueryJob] = {}

    def start(self, request: RecommendationSearchRequest) -> QueryJob:
        now = datetime.now(UTC)
        job = QueryJob(uuid.uuid4().hex, QueryJobStage.QUEUED, now, now + self._ttl)
        job.task = asyncio.create_task(self._run(job, request))
        self._jobs[job.query_id] = job
        return job

    def get(self, query_id: str) -> QueryJob | None:
        job = self._jobs.get(query_id)
        if job is not None and job.expires_at_utc <= datetime.now(UTC):
            job.stage = QueryJobStage.EXPIRED
            self._jobs.pop(query_id, None)
            return None
        return job

    def cancel(self, query_id: str) -> bool:
        job = self.get(query_id)
        if job is None or job.task is None:
            return False
        job.task.cancel()
        job.stage = QueryJobStage.CANCELLED
        return True

    async def _run(self, job: QueryJob, request: RecommendationSearchRequest) -> None:
        try:
            job.stage = QueryJobStage.RESOLVING_TARGET
            await asyncio.sleep(0)
            job.stage = QueryJobStage.GENERATING_CELLS
            await asyncio.sleep(0)
            job.stage = QueryJobStage.FETCHING_ELEVATION
            await asyncio.sleep(0)
            job.stage = QueryJobStage.READING_SURFACE_WINDOWS
            await asyncio.sleep(0)
            job.stage = QueryJobStage.APPLYING_STATIC_FILTERS
            await asyncio.sleep(0)
            job.stage = QueryJobStage.FETCHING_WEATHER
            await asyncio.sleep(0)
            job.stage = QueryJobStage.CALCULATING_ASTRONOMY
            result = await self._service.search(request)
            job.stage = QueryJobStage.CHECKING_ACCESS
            await asyncio.sleep(0)
            job.stage = QueryJobStage.RANKING
            await asyncio.sleep(0)
            job.result = result
            job.stage = QueryJobStage.COMPLETED
        except asyncio.CancelledError:
            job.stage = QueryJobStage.CANCELLED
            raise
        except Exception:
            job.stage = QueryJobStage.FAILED
            job.error = "query execution failed"


def job_payload(job: QueryJob) -> dict[str, object]:
    return {
        "query_id": job.query_id,
        "stage": job.stage,
        "created_at_utc": job.created_at_utc,
        "expires_at_utc": job.expires_at_utc,
        "error": job.error,
        "result": job.result.model_dump(mode="json")
        if job.stage == QueryJobStage.COMPLETED and job.result
        else None,
    }
