from __future__ import annotations

from datetime import UTC, datetime

import pytest

from thiezer.domain.contracts import (
    EquipmentStore,
    GeoPoint,
    SearchScope,
    StoreKind,
    VerificationStatus,
)
from thiezer.repositories.adaptive import AdaptiveStoreRepository
from thiezer.repositories.seed import SeedStoreRepository


class FakeAccessProvider:
    source_name = "fake_local_access"
    attribution = "Synthetic local access"

    async def discover_access_points(self, **_: object) -> dict[str, list[object]]:
        return {}

    async def discover_stores(
        self,
        *,
        user_location: GeoPoint,
        radius_km: float,
        limit: int,
    ) -> list[EquipmentStore]:
        del user_location, radius_km, limit
        return [
            EquipmentStore(
                id="ge-store",
                name="Cross-border optics",
                kind=StoreKind.PHYSICAL,
                country_code="GE",
                point=GeoPoint(latitude_deg=41.0, longitude_deg=44.1),
                website_url="https://example.com",
                categories=["optics"],
                verification_status=VerificationStatus.UNVERIFIED_DISCOVERED,
                source_checked_at_utc=datetime.now(UTC),
                source_provider=self.source_name,
            )
        ]

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_adaptive_store_repository_can_return_cross_border_store() -> None:
    repository = AdaptiveStoreRepository(
        seed_repository=SeedStoreRepository([]),
        discovery_provider=FakeAccessProvider(),
    )
    batch = await repository.search(
        user_location=GeoPoint(latitude_deg=40.2, longitude_deg=44.5),
        scope=SearchScope.ADAPTIVE,
        country_code=None,
        max_distance_km=250,
        limit=10,
    )
    assert batch.matches[0][0].country_code == "GE"


@pytest.mark.asyncio
async def test_country_store_scope_filters_cross_border_result() -> None:
    repository = AdaptiveStoreRepository(
        seed_repository=SeedStoreRepository([]),
        discovery_provider=FakeAccessProvider(),
    )
    batch = await repository.search(
        user_location=GeoPoint(latitude_deg=40.2, longitude_deg=44.5),
        scope=SearchScope.COUNTRY,
        country_code="AM",
        max_distance_km=250,
        limit=10,
    )
    assert batch.matches == []
