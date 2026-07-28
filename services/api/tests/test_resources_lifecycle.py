import pytest

from thiezer.api.resources import build_resources
from thiezer.config import Settings
from thiezer.repositories.surface import SurfacePlaceRepository


@pytest.mark.asyncio
async def test_resources_use_surface_repository_and_shared_client() -> None:
    resources = build_resources(Settings(overpass_enabled=False))
    try:
        assert resources.client is not None
        assert resources.recommendation_service is not None
        assert resources.store_service is not None
        place_repository = resources.recommendation_service._places
        assert isinstance(place_repository, SurfacePlaceRepository)
    finally:
        await resources.aclose()
