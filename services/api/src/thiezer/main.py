from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from thiezer import __version__
from thiezer.api.routers import health, scoring
from thiezer.config import get_settings
from thiezer.observability import configure_logging
from thiezer.persistence.database import dispose_engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    yield
    await dispose_engine()


app = FastAPI(
    title="Thiezer API",
    version=__version__,
    description="Astronomy travel recommendation foundation",
    lifespan=lifespan,
)
app.include_router(health.router)
app.include_router(scoring.router)
