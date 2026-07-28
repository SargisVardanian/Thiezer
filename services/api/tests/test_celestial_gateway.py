from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
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
from thiezer.providers.catalogs.base import CatalogProviderError
from thiezer.providers.catalogs.exoplanet_archive import ExoplanetArchiveProvider
from thiezer.providers.catalogs.gaia import GaiaCatalogProvider
from thiezer.providers.catalogs.ned import NedCatalogProvider
from thiezer.providers.catalogs.simbad import simbad_fixture
from thiezer.providers.catalogs.skyfield import SkyfieldPresetCatalogProvider
from thiezer.providers.catalogs.tap import TapClient
from thiezer.providers.catalogs.vizier import VizierCatalogProvider
from thiezer.providers.ephemeris.horizons import HorizonsObserverEvent
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
async def test_exoplanet_name_pattern_routes_without_requiring_a_filter() -> None:
    planet = CelestialObject(
        identifier=CelestialObjectId(
            provider=CatalogSource.EXOPLANET_ARCHIVE, object_id="51 Peg b"
        ),
        name="51 Peg b",
        object_class=CelestialObjectClass.EXOPLANET,
        host_star=CelestialObjectId(provider=CatalogSource.SIMBAD, object_id="51 Peg"),
        attribution="NASA Exoplanet Archive",
    )
    service = CelestialResolutionService(
        {
            CatalogSource.SIMBAD: simbad_fixture(),
            CatalogSource.EXOPLANET_ARCHIVE: ExoplanetArchiveProvider(
                fixtures={"51 peg b": planet}
            ),
        }
    )
    results = await service.search("51 Peg b", limit=5)
    assert any(item.object_class == CelestialObjectClass.EXOPLANET for item in results)


@pytest.mark.asyncio
async def test_partial_gaia_failure_keeps_simbad_star_with_warning() -> None:
    class FailingGaia:
        source = CatalogSource.GAIA
        attribution = "Gaia DR3"

        async def search(self, query: str, *, limit: int) -> list[CelestialObject]:
            return []

        async def get(self, object_id: str) -> CelestialObject | None:
            return None

        async def enrich_nearest(self, target: CelestialObject) -> CelestialObject | None:
            raise CatalogProviderError("Gaia unavailable")

    service = CelestialResolutionService(
        {CatalogSource.SIMBAD: simbad_fixture(), CatalogSource.GAIA: FailingGaia()}
    )
    response = await service.search_with_diagnostics("Sirius", limit=5)
    assert response.results[0].identifier.provider == CatalogSource.SIMBAD
    assert "Gaia enrichment is currently unavailable." in response.results[0].warnings
    assert "SIMBAD fallback" in response.warnings[0]


@pytest.mark.asyncio
async def test_cancelled_catalog_search_stops_provider_work() -> None:
    started = asyncio.Event()
    stopped = asyncio.Event()

    class SlowSimbad:
        source = CatalogSource.SIMBAD
        attribution = "SIMBAD"

        async def search(self, query: str, *, limit: int) -> list[CelestialObject]:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        async def get(self, object_id: str) -> CelestialObject | None:
            return None

    service = CelestialResolutionService({CatalogSource.SIMBAD: SlowSimbad()})
    task = asyncio.create_task(service.search("Sirius", limit=5))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await stopped.wait()


@pytest.mark.asyncio
async def test_gaia_enrichment_adds_motion_parallax_velocity_and_three_band_photometry() -> None:
    class GaiaTapStub:
        async def query(self, adql: str, *, max_rows: int) -> list[dict[str, object]]:
            assert "gaiadr3.gaia_source" in adql
            return [
                {
                    "source_id": "2835207319109249920",
                    "ra": 344.36757,
                    "dec": 20.76910,
                    "ref_epoch": 2016.0,
                    "pmra": 207.3,
                    "pmdec": 61.2,
                    "parallax": 64.4,
                    "radial_velocity": -33.3,
                    "phot_g_mean_mag": 5.28,
                    "phot_bp_mean_mag": 5.62,
                    "phot_rp_mean_mag": 4.79,
                }
            ]

    gaia = GaiaCatalogProvider(tap=GaiaTapStub())  # type: ignore[arg-type]
    service = CelestialResolutionService(
        {CatalogSource.SIMBAD: simbad_fixture(), CatalogSource.GAIA: gaia}
    )
    result = (await service.search("51 Peg", limit=5))[0]
    assert result.identifier.provider == CatalogSource.GAIA
    assert result.coordinates is not None
    assert result.coordinates.reference_epoch_jyear == 2016.0
    assert result.motion is not None
    assert result.motion.parallax_mas == 64.4
    assert result.motion.radial_velocity_km_s == -33.3
    assert result.photometry is not None
    assert result.photometry.gaia_bp_magnitude == 5.62
    assert result.photometry.gaia_rp_magnitude == 4.79


@pytest.mark.asyncio
async def test_ned_modern_api_parses_cross_ids_redshift_and_angular_size() -> None:
    xml = b"""<?xml version='1.0'?>
    <VOTABLE xmlns='http://www.ivoa.net/xml/VOTable/v1.3'><RESOURCE><TABLE>
      <FIELD ID='CrossID_list'/><FIELD ID='equ_j2000_lon'/>
      <FIELD ID='equ_j2000_lat'/><FIELD ID='z'/><FIELD ID='ptype'/>
      <FIELD ID='o_diam_maj_dia'/><FIELD ID='unc_sma'/>
      <DATA><TABLEDATA><TR><TD>Messier 031;NGC 0224</TD><TD>10.6848</TD>
      <TD>41.2691</TD><TD>-0.000991</TD><TD>G</TD><TD>12250.4</TD>
      <TD>0.08</TD></TR></TABLEDATA></DATA>
    </TABLE></RESOURCE></VOTABLE>"""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=xml, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = NedCatalogProvider(client=client)
        results = await provider.search("M31", limit=5)
    result = results[0]
    assert result.identifier.object_id == "Messier 031"
    assert "NGC 0224" in result.aliases
    assert result.physical is not None
    assert result.physical.redshift == pytest.approx(-0.000991)
    assert result.physical.angular_major_axis_arcmin == pytest.approx(204.1733, rel=1e-4)


@pytest.mark.asyncio
async def test_vizier_allowlisted_messier_lookup_transforms_and_parses_metadata() -> None:
    class VizierTapStub:
        async def query(self, adql: str, *, max_rows: int) -> list[dict[str, object]]:
            if '"VII/118/names"' in adql:
                return [{"Object": "M  42", "Name": " 1976"}]
            assert '"VII/118/ngc2000"' in adql
            return [
                {
                    "Name": " 1976",
                    "Type": " Nb",
                    "RAB2000": 83.85,
                    "DEB2000": -5.45,
                    "size": 66.0,
                    "mag": 4.0,
                }
            ]

    provider = VizierCatalogProvider(tap=VizierTapStub())  # type: ignore[arg-type]
    result = (await provider.search("M42", limit=5))[0]
    assert result.object_class == CelestialObjectClass.NEBULA
    assert result.coordinates is not None
    assert result.coordinates.frame == "ICRS"
    assert result.photometry is not None
    assert result.photometry.visual_magnitude == 4.0
    assert result.physical is not None
    assert result.physical.angular_major_axis_arcmin == 66.0


@pytest.mark.asyncio
async def test_tap_query_limits_reject_oversized_adql_without_network() -> None:
    with pytest.raises(ValueError, match="unsafe TAP query limit"):
        await TapClient("https://example.invalid", object()).query("x" * 4001)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_tap_http_rejection_is_a_provider_failure_for_partial_fallback() -> None:
    class RejectingClient:
        async def post(self, *_: object, **__: object) -> httpx.Response:
            return httpx.Response(
                400,
                request=httpx.Request("POST", "https://example.invalid/tap"),
            )

    with pytest.raises(CatalogProviderError):
        await TapClient("https://example.invalid/tap", RejectingClient()).query("SELECT 1")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_tap_normalises_metadata_and_array_rows() -> None:
    class TapJsonClient:
        async def post(self, *_: object, **__: object) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "metadata": [{"name": "main_id"}, {"name": "ra"}],
                    "data": [["Sirius", 101.287155]],
                },
                request=httpx.Request("POST", "https://example.invalid/tap"),
            )

    rows = await TapClient("https://example.invalid/tap", TapJsonClient()).query("SELECT 1")  # type: ignore[arg-type]
    assert rows == [{"main_id": "Sirius", "ra": 101.287155}]


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
async def test_query_job_records_real_service_progress_and_is_lost_on_restart() -> None:
    stages = [
        QueryJobStage.RESOLVING_TARGET,
        QueryJobStage.GENERATING_CELLS,
        QueryJobStage.FETCHING_WEATHER,
        QueryJobStage.CALCULATING_ASTRONOMY,
        QueryJobStage.RANKING,
    ]

    class ProgressService:
        async def search(self, request: object, progress: object = None) -> object:
            assert callable(progress)
            for stage in stages:
                await progress(stage.value)
            return object()

    request = RecommendationSearchRequest.model_validate(
        {
            "user_location": {"latitude_deg": 40, "longitude_deg": 44},
            "target": "jupiter",
            "start_utc": "2026-07-29T18:00:00Z",
            "end_utc": "2026-07-29T22:00:00Z",
        }
    )
    jobs = EphemeralQueryJobs(ProgressService(), ttl_seconds=60)  # type: ignore[arg-type]
    job = jobs.start(request)
    assert job.task is not None
    await job.task
    assert job.stage == QueryJobStage.COMPLETED
    assert [event.stage for event in (job.events or [])] == [
        QueryJobStage.QUEUED,
        *stages,
        QueryJobStage.COMPLETED,
    ]
    restarted = EphemeralQueryJobs(ProgressService(), ttl_seconds=60)  # type: ignore[arg-type]
    assert restarted.get(job.query_id) is None


@pytest.mark.asyncio
async def test_cancelling_query_job_stops_downstream_service() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class SlowService:
        async def search(self, request: object, progress: object = None) -> object:
            assert callable(progress)
            await progress(QueryJobStage.RESOLVING_TARGET.value)
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    request = RecommendationSearchRequest.model_validate(
        {
            "user_location": {"latitude_deg": 40, "longitude_deg": 44},
            "target": "jupiter",
            "start_utc": "2026-07-29T18:00:00Z",
            "end_utc": "2026-07-29T22:00:00Z",
        }
    )
    jobs = EphemeralQueryJobs(SlowService(), ttl_seconds=60)  # type: ignore[arg-type]
    job = jobs.start(request)
    await started.wait()
    assert jobs.cancel(job.query_id) is True
    await cancelled.wait()
    assert job.stage == QueryJobStage.CANCELLED


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
    assert m31_result.rise_utc is not None
    assert m31_result.set_utc is not None
    assert m31_result.visibility_window is not None
    assert m31_result.culmination_utc is not None
    assert m31_result.maximum_altitude_deg is not None
    assert m31_result.maximum_altitude_deg > m31_result.altitude_deg
    assert "binoculars" in m31_result.observation_capabilities
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


@pytest.mark.asyncio
async def test_horizons_catalog_object_uses_dynamic_observer_ephemeris() -> None:
    halley = CelestialObject(
        identifier=CelestialObjectId(provider=CatalogSource.HORIZONS, object_id="90000030"),
        name="1P/Halley",
        object_class=CelestialObjectClass.COMET,
        attribution="NASA/JPL Horizons System",
    )
    result = await CelestialVisibilityService(horizons=HorizonsStub()).get(
        target=halley,
        point=GeoPoint(latitude_deg=40, longitude_deg=44),
        timestamp_utc=datetime(2026, 7, 29, 20, tzinfo=UTC),
    )
    assert result.altitude_deg == 25.0
    assert result.azimuth_deg == 100.0
    assert result.moon_separation_deg is None
    assert result.rise_utc == datetime(2026, 7, 29, 18, tzinfo=UTC)
    assert result.set_utc == datetime(2026, 7, 30, 1, tzinfo=UTC)
    assert result.culmination_utc == datetime(2026, 7, 29, 21, tzinfo=UTC)
    assert result.maximum_altitude_deg == 40.0


@pytest.mark.asyncio
async def test_skyfield_catalog_planet_includes_real_events() -> None:
    provider = SkyfieldPresetCatalogProvider()
    jupiter = await provider.get("jupiter")
    assert jupiter is not None
    result = await CelestialVisibilityService().get(
        target=jupiter,
        point=GeoPoint(latitude_deg=40, longitude_deg=44),
        timestamp_utc=datetime(2026, 7, 29, 20, tzinfo=UTC),
    )
    assert result.rise_utc is not None
    assert result.set_utc is not None
    assert result.culmination_utc is not None
    assert result.maximum_altitude_deg is not None
    assert "naked_eye" in result.observation_capabilities


class SimbadStub:
    source = CatalogSource.SIMBAD
    attribution = "SIMBAD"

    def __init__(self, item: CelestialObject) -> None:
        self._item = item

    async def search(self, query: str, *, limit: int) -> list[CelestialObject]:
        return [self._item]

    async def get(self, object_id: str) -> CelestialObject | None:
        return self._item if object_id == self._item.identifier.object_id else None


class HorizonsStub:
    async def observer(self, **_: object) -> tuple[float, float]:
        return 100.0, 25.0

    async def observer_events(self, **_: object) -> list[HorizonsObserverEvent]:
        return [
            HorizonsObserverEvent(datetime(2026, 7, 29, 18, tzinfo=UTC), "r", 80, 0),
            HorizonsObserverEvent(datetime(2026, 7, 29, 21, tzinfo=UTC), "t", 180, 40),
            HorizonsObserverEvent(datetime(2026, 7, 30, 1, tzinfo=UTC), "s", 270, 0),
        ]
