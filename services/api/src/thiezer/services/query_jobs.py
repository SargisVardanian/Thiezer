from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from thiezer.domain.contracts import RecommendationSearchRequest, RecommendationSearchResponse
from thiezer.services.recommendations import RecommendationService

logger = logging.getLogger(__name__)


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
class QueryJobEvent:
    stage: QueryJobStage
    timestamp_utc: datetime


@dataclass(slots=True)
class QueryJob:
    query_id: str
    stage: QueryJobStage
    created_at_utc: datetime
    expires_at_utc: datetime
    error: str | None = None
    result: RecommendationSearchResponse | None = None
    task: asyncio.Task[None] | None = None
    events: list[QueryJobEvent] | None = None


class EphemeralQueryJobs:
    def __init__(
        self,
        service: RecommendationService,
        *,
        ttl_seconds: int,
        result_ttl_seconds: int | None = None,
    ) -> None:
        self._service = service
        self._ttl = timedelta(seconds=ttl_seconds)
        self._result_ttl = timedelta(seconds=result_ttl_seconds or ttl_seconds)
        self._jobs: dict[str, QueryJob] = {}

    def start(self, request: RecommendationSearchRequest) -> QueryJob:
        now = datetime.now(UTC)
        job = QueryJob(
            uuid.uuid4().hex,
            QueryJobStage.QUEUED,
            now,
            now + self._ttl,
            events=[QueryJobEvent(QueryJobStage.QUEUED, now)],
        )
        job.task = asyncio.create_task(self._run(job, request))
        self._jobs[job.query_id] = job
        return job

    def get(self, query_id: str) -> QueryJob | None:
        job = self._jobs.get(query_id)
        if job is not None and job.expires_at_utc <= datetime.now(UTC):
            if job.task is not None and not job.task.done():
                job.task.cancel()
            self._set_stage(job, QueryJobStage.EXPIRED)
            self._jobs.pop(query_id, None)
            return None
        return job

    def cancel(self, query_id: str) -> bool:
        job = self.get(query_id)
        if job is None or job.task is None or job.task.done():
            return False
        job.task.cancel()
        self._set_stage(job, QueryJobStage.CANCELLED)
        return True

    async def _run(self, job: QueryJob, request: RecommendationSearchRequest) -> None:
        try:

            async def progress(stage: str) -> None:
                self._set_stage(job, QueryJobStage(stage))

            result = await self._service.search(request, progress=progress)
            job.result = result
            job.expires_at_utc = datetime.now(UTC) + self._result_ttl
            self._set_stage(job, QueryJobStage.COMPLETED)
        except asyncio.CancelledError:
            if job.stage != QueryJobStage.EXPIRED:
                self._set_stage(job, QueryJobStage.CANCELLED)
            raise
        except Exception:
            logger.exception("ephemeral query job failed", extra={"query_id": job.query_id})
            self._set_stage(job, QueryJobStage.FAILED)
            job.error = "query execution failed"
        finally:
            # Release the task closure, including the request's exact coordinates.
            job.task = None

    @staticmethod
    def _set_stage(job: QueryJob, stage: QueryJobStage) -> None:
        if job.stage == stage:
            return
        job.stage = stage
        if job.events is None:
            job.events = []
        job.events.append(QueryJobEvent(stage, datetime.now(UTC)))


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


def job_events_payload(job: QueryJob) -> dict[str, object]:
    return {
        "query_id": job.query_id,
        "events": [
            {"stage": event.stage, "timestamp_utc": event.timestamp_utc}
            for event in (job.events or [])
        ],
    }
