from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import make_place

from thiezer.domain.contracts import (
    CandidatePlace,
    EquipmentStore,
    GeoPoint,
    PlaceKind,
    SearchScope,
    StoreKind,
    VerificationStatus,
    WarningCode,
)
from thiezer.repositories.adaptive import AdaptivePlaceRepository, AdaptiveStoreRepository
from thiezer.repositories.seed import SeedPlaceRepository, SeedStoreRepository


class FakeDiscoveryProvider:
    source_name = "fake_discovery"
    attribution = "Synthetic discovery"

    async def discover_places(
        self,
        *,
        user_location: GeoPoint,
        radius_km: float,
        limit: int,
    ) -> list[CandidatePlace]:
        return [
            CandidatePlace(
                id="ge-viewpoint",
                name="Nearby cross-border viewpoint",
                country_code="GE",
                region="Test",
                point=GeoPoint(latitude_deg=41.0, longitude_deg=44.0),
                elevation_m=1700,
                kind=PlaceKind.VIEWPOINT,
                verification_status=VerificationStatus.UNVERIFIED_DISCOVERED,
                darkness_score=0.88,
                horizon_openness_score=0.85,
                accessibility_score=0.7,
                risk_score=0.3,
                road_access="synthetic",
                source_provider="fake_discovery",
                darkness_model="settlement_distance_proxy_v1",
            )
        ]

    async def discover_stores(
        self,
        *,
        user_location: GeoPoint,
        radius_km: float,
        limit: int,
    ) -> list[EquipmentStore]:
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
                source_provider="fake_discovery",
            )
        ]

    async def aclose(self) -> None:
        return None


class FailingDiscoveryProvider(FakeDiscoveryProvider):
    async def discover_places(
        self,
        *,
        user_location: GeoPoint,
        radius_km: float,
        limit: int,
    ) -> list[CandidatePlace]:
        raise RuntimeError("provider unavailable")


@pytest.mark.asyncio
async def test_adaptive_radius_can_cross_small_country_boundaries() -> None:
    origin = GeoPoint(latitude_deg=40.2, longitude_deg=44.5)
    local = make_place(
        place_id="am-site",
        name="Armenia site",
        latitude_deg=40.4,
        longitude_deg=44.4,
        darkness=0.7,
    )
    repository = AdaptivePlaceRepository(
        seed_repository=SeedPlaceRepository([local]),
        discovery_provider=FakeDiscoveryProvider(),
    )

    batch = await repository.search(
        user_location=origin,
        scope=SearchScope.ADAPTIVE,
        country_code=None,
        max_distance_km=250,
        limit=10,
    )

    assert {place.country_code for place, _ in batch.matches} == {"AM", "GE"}
    assert batch.discovery_sources == ["fake_discovery", "packaged_seed"]


@pytest.mark.asyncio
async def test_country_scope_is_strict_but_still_radius_bounded() -> None:
    origin = GeoPoint(latitude_deg=40.2, longitude_deg=44.5)
    local = make_place(
        place_id="am-site",
        name="Armenia site",
        latitude_deg=40.4,
        longitude_deg=44.4,
        darkness=0.7,
    )
    repository = AdaptivePlaceRepository(
        seed_repository=SeedPlaceRepository([local]),
        discovery_provider=FakeDiscoveryProvider(),
    )

    batch = await repository.search(
        user_location=origin,
        scope=SearchScope.COUNTRY,
        country_code="AM",
        max_distance_km=250,
        limit=10,
    )

    assert [place.country_code for place, _ in batch.matches] == ["AM"]


@pytest.mark.asyncio
async def test_discovery_failure_falls_back_to_packaged_data() -> None:
    origin = GeoPoint(latitude_deg=40.2, longitude_deg=44.5)
    local = make_place(
        place_id="am-site",
        name="Armenia site",
        latitude_deg=40.4,
        longitude_deg=44.4,
        darkness=0.7,
    )
    repository = AdaptivePlaceRepository(
        seed_repository=SeedPlaceRepository([local]),
        discovery_provider=FailingDiscoveryProvider(),
    )

    batch = await repository.search(
        user_location=origin,
        scope=SearchScope.ADAPTIVE,
        country_code=None,
        max_distance_km=250,
        limit=10,
    )

    assert [place.id for place, _ in batch.matches] == ["am-site"]
    assert WarningCode.DISCOVERY_PROVIDER_UNAVAILABLE in batch.warnings


@pytest.mark.asyncio
async def test_adaptive_store_repository_can_return_cross_border_store() -> None:
    repository = AdaptiveStoreRepository(
        seed_repository=SeedStoreRepository([]),
        discovery_provider=FakeDiscoveryProvider(),
    )
    batch = await repository.search(
        user_location=GeoPoint(latitude_deg=40.2, longitude_deg=44.5),
        scope=SearchScope.ADAPTIVE,
        country_code=None,
        max_distance_km=250,
        limit=10,
    )
    assert batch.matches[0][0].country_code == "GE"
