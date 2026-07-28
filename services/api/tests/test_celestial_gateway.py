from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from thiezer.domain.celestial_objects import (
    CatalogSource,
    CelestialCoordinates,
    CelestialMotion,
    CelestialObject,
    CelestialObjectClass,
    CelestialObjectId,
)
from thiezer.domain.contracts import GeoPoint, RecommendationSearchRequest, TargetKind
from thiezer.providers.catalogs.simbad import simbad_fixture
from thiezer.providers.catalogs.tap import TapClient
from thiezer.services.celestial_resolution import CelestialResolutionService
from thiezer.services.celestial_visibility import CelestialVisibilityService
from thiezer.services.ephemeral_cache import EphemeralTtlCache
from thiezer.services.query_jobs import EphemeralQueryJobs, QueryJobStage


@pytest.mark.asyncio
async def test_simbad_aliases_resolve_without_live_network() -> None:
    service = CelestialResolutionService({CatalogSource.SIMBAD: simbad_fixture()})
    result = await service.search("NGC 224", limit=10)
    assert result[0].identifier.object_id == "M 31"
    resolved = await service.resolve(
        CelestialObjectId(provider=CatalogSource.SIMBAD, object_id="M 31")
    )
    assert resolved.name == "Andromeda Galaxy"


@pytest.mark.asyncio
async def test_tap_query_limits_reject_oversized_adql_without_network() -> None:
    with pytest.raises(ValueError, match="unsafe TAP query limit"):
        await TapClient("https://example.invalid", object()).query("x" * 4001)  # type: ignore[arg-type]


def test_ephemeral_cache_expires_and_rejects_coordinate_or_token_keys() -> None:
    current = datetime(2026, 1, 1, tzinfo=UTC)
    cache: EphemeralTtlCache[str] = EphemeralTtlCache(now=lambda: current)
    cache.put("catalog-object:simbad:sirius", "Sirius", ttl=timedelta(seconds=1))
    assert cache.get("catalog-object:simbad:sirius") == "Sirius"
    current += timedelta(seconds=2)
    assert cache.get("catalog-object:simbad:sirius") is None
    with pytest.raises(ValueError):
        cache.put("latitude=40.1772", "forbidden", ttl=timedelta(seconds=1))


def test_query_job_expiration_drops_ephemeral_state() -> None:
    # Constructing the store does not retain a request, user point, or result in its public status.
    jobs = EphemeralQueryJobs(object(), ttl_seconds=60)  # type: ignore[arg-type]
    now = datetime.now(UTC)
    from thiezer.services.query_jobs import QueryJob

    jobs._jobs["expired"] = QueryJob(
        "expired", QueryJobStage.QUEUED, now, now - timedelta(seconds=1)
    )  # type: ignore[attr-defined]
    assert jobs.get("expired") is None


@pytest.mark.asyncio
async def test_catalog_visibility_uses_skyfield_geometry_for_m31_and_alpha_centauri() -> None:
    resolver = CelestialResolutionService({CatalogSource.SIMBAD: simbad_fixture()})
    yerevan = GeoPoint(latitude_deg=40.1772, longitude_deg=44.5035)
    service = CelestialVisibilityService()
    m31 = await resolver.resolve(CelestialObjectId(provider=CatalogSource.SIMBAD, object_id="M 31"))
    m31_result = await service.get(
        target=m31, point=yerevan, timestamp_utc=datetime(2026, 10, 1, 20, tzinfo=UTC)
    )
    assert m31_result.above_horizon is True
    alpha = await resolver.resolve(
        CelestialObjectId(provider=CatalogSource.SIMBAD, object_id="Alpha Centauri")
    )
    alpha_result = await service.get(
        target=alpha, point=yerevan, timestamp_utc=datetime(2026, 7, 29, 20, tzinfo=UTC)
    )
    assert alpha_result.above_horizon is False


def test_recommendation_request_accepts_legacy_and_catalog_target_shapes() -> None:
    base = {
        "user_location": {"latitude_deg": 40.1772, "longitude_deg": 44.5035},
        "start_utc": "2026-07-29T18:00:00Z",
        "end_utc": "2026-07-29T22:00:00Z",
    }
    legacy = RecommendationSearchRequest.model_validate({**base, "target": "jupiter"})
    catalog = RecommendationSearchRequest.model_validate(
        {**base, "target": {"catalog_object": {"provider": "simbad", "object_id": "M 31"}}}
    )
    assert legacy.preset_target is TargetKind.JUPITER
    assert catalog.catalog_target == CelestialObjectId(
        provider=CatalogSource.SIMBAD, object_id="M 31"
    )


@pytest.mark.asyncio
async def test_exoplanet_returns_host_star_visibility() -> None:
    host = CelestialObject(
        identifier=CelestialObjectId(provider=CatalogSource.SIMBAD, object_id="host"),
        name="Host",
        object_class=CelestialObjectClass.STAR,
        coordinates=CelestialCoordinates(right_ascension_deg=10, declination_deg=40),
        attribution="SIMBAD",
    )
    planet = CelestialObject(
        identifier=CelestialObjectId(provider=CatalogSource.EXOPLANET_ARCHIVE, object_id="planet"),
        name="Planet",
        object_class=CelestialObjectClass.EXOPLANET,
        host_star=host.identifier,
        attribution="NASA Exoplanet Archive",
    )
    from thiezer.providers.catalogs.exoplanet_archive import ExoplanetArchiveProvider

    resolver = CelestialResolutionService(
        {
            CatalogSource.SIMBAD: SimbadStub(host),
            CatalogSource.EXOPLANET_ARCHIVE: ExoplanetArchiveProvider(fixtures={"planet": planet}),
        }
    )
    result = await CelestialVisibilityService(resolver).get(
        target=planet,
        point=GeoPoint(latitude_deg=40, longitude_deg=44),
        timestamp_utc=datetime(2026, 7, 29, 20, tzinfo=UTC),
    )
    assert result.capability.value == "host_star_visibility"
    assert "not directly visible" in result.warnings[0]


@pytest.mark.asyncio
async def test_gaia_motion_is_passed_to_skyfield_propagation() -> None:
    target = CelestialObject(
        identifier=CelestialObjectId(provider=CatalogSource.GAIA, object_id="1"),
        name="moving",
        object_class=CelestialObjectClass.STAR,
        coordinates=CelestialCoordinates(
            right_ascension_deg=100, declination_deg=20, reference_epoch_jyear=2016
        ),
        motion=CelestialMotion(
            proper_motion_ra_mas_per_year=100000, proper_motion_dec_mas_per_year=0
        ),
        attribution="Gaia DR3",
    )
    static = target.model_copy(update={"motion": None})
    point = GeoPoint(latitude_deg=40, longitude_deg=44)
    moving = await CelestialVisibilityService().get(
        target=target, point=point, timestamp_utc=datetime(2050, 1, 1, tzinfo=UTC)
    )
    baseline = await CelestialVisibilityService().get(
        target=static, point=point, timestamp_utc=datetime(2050, 1, 1, tzinfo=UTC)
    )
    assert abs(moving.azimuth_deg - baseline.azimuth_deg) > 0.05


class SimbadStub:
    source = CatalogSource.SIMBAD
    attribution = "SIMBAD"

    def __init__(self, item: CelestialObject) -> None:
        self._item = item

    async def search(self, query: str, *, limit: int) -> list[CelestialObject]:
        return [self._item]

    async def get(self, object_id: str) -> CelestialObject | None:
        return self._item if object_id == self._item.identifier.object_id else None
