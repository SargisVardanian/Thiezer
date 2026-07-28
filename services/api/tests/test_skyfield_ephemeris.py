from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("skyfield")
pytest.importorskip("skyfield_data")

from thiezer.domain.contracts import GeoPoint, TargetKind
from thiezer.domain.ephemeris import SkyfieldAstronomyProvider


def test_alpha_centauri_never_rises_from_yerevan_latitude() -> None:
    provider = SkyfieldAstronomyProvider()
    point = GeoPoint(latitude_deg=40.1772, longitude_deg=44.5035)
    start = datetime(2026, 7, 29, tzinfo=UTC)
    altitudes = [
        provider.snapshot(
            target=TargetKind.ALPHA_CENTAURI,
            point=point,
            timestamp_utc=start + timedelta(hours=hour),
        ).altitude_deg
        for hour in range(24)
    ]
    assert max(altitudes) < 0.0


def test_jpl_moon_snapshot_is_finite_and_bounded() -> None:
    provider = SkyfieldAstronomyProvider()
    snapshot = provider.snapshot(
        target=TargetKind.MOON,
        point=GeoPoint(latitude_deg=40.1772, longitude_deg=44.5035),
        timestamp_utc=datetime(2026, 7, 29, 20, tzinfo=UTC),
    )
    assert 0.0 <= snapshot.azimuth_deg < 360.0
    assert 0.0 <= snapshot.moon_illumination_fraction <= 1.0
    assert snapshot.moon_separation_deg == 0.0
