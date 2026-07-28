from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, Protocol

from thiezer.domain.astronomy import airmass_kasten_young
from thiezer.domain.contracts import AstronomySnapshot, GeoPoint, TargetKind


class AstronomyProvider(Protocol):
    def snapshot(
        self,
        *,
        target: TargetKind,
        point: GeoPoint,
        timestamp_utc: datetime,
    ) -> AstronomySnapshot: ...


_TARGET_LABELS: dict[TargetKind, str] = {
    TargetKind.ALPHA_CENTAURI: "Alpha Centauri",
    TargetKind.MARS: "Mars",
    TargetKind.JUPITER: "Jupiter",
    TargetKind.MOON: "Moon",
    TargetKind.MILKY_WAY: "Milky Way core",
    TargetKind.BEST_NIGHT_SKY: "General night sky",
    TargetKind.BRIGHT_PLANET: "Bright planet",
}


class SkyfieldAstronomyProvider:
    """Offline JPL DE421 calculations backed by the packaged ``skyfield-data`` files.

    Importing this module does not require Skyfield. Dependencies are imported lazily when
    the provider is instantiated, which keeps pure domain tests lightweight and makes an
    absent astronomy runtime fail with one explicit configuration error.
    """

    def __init__(self) -> None:
        try:
            from skyfield import almanac
            from skyfield.api import Loader, Star, wgs84
            from skyfield_data import get_skyfield_data_path
        except ImportError as exc:  # pragma: no cover - exercised in minimal installations.
            raise RuntimeError(
                "Skyfield astronomy support requires the 'skyfield' and 'skyfield-data' packages"
            ) from exc

        self._almanac = almanac
        self._wgs84 = wgs84
        self._loader = Loader(get_skyfield_data_path(), expire=False)
        self._timescale = self._loader.timescale(builtin=True)
        self._ephemeris = self._loader("de421.bsp")
        self._earth = self._ephemeris["earth"]
        self._sun = self._ephemeris["sun"]
        self._moon = self._ephemeris["moon"]
        self._fixed_targets = {
            TargetKind.ALPHA_CENTAURI: Star(
                ra_hours=14.66013783,
                dec_degrees=-60.8339925,
            ),
            # Galactic centre (Sgr A*) is the operational proxy for the visible Milky Way core.
            TargetKind.MILKY_WAY: Star(
                ra_hours=17.761122,
                dec_degrees=-29.00781,
            ),
        }

    def snapshot(
        self,
        *,
        target: TargetKind,
        point: GeoPoint,
        timestamp_utc: datetime,
    ) -> AstronomySnapshot:
        timestamp = _require_aware_utc(timestamp_utc)
        t = self._timescale.from_datetime(timestamp)
        observer = self._earth + self._wgs84.latlon(
            latitude_degrees=point.latitude_deg,
            longitude_degrees=point.longitude_deg,
        )

        sun_apparent = observer.at(t).observe(self._sun).apparent()
        sun_altitude_deg = float(sun_apparent.altaz()[0].degrees)
        moon_apparent = observer.at(t).observe(self._moon).apparent()
        moon_altitude_deg = float(moon_apparent.altaz()[0].degrees)
        moon_illumination = float(self._almanac.fraction_illuminated(self._ephemeris, "moon", t))

        if target == TargetKind.BEST_NIGHT_SKY:
            altitude_deg = 90.0
            azimuth_deg = 0.0
            moon_separation_deg = 180.0
        else:
            target_object = self._target_object(target)
            target_apparent = observer.at(t).observe(target_object).apparent()
            altitude, azimuth, _ = target_apparent.altaz()
            altitude_deg = float(altitude.degrees)
            azimuth_deg = float(azimuth.degrees) % 360.0
            if target == TargetKind.MOON:
                moon_separation_deg = 0.0
            else:
                moon_separation_deg = float(target_apparent.separation_from(moon_apparent).degrees)

        airmass = airmass_kasten_young(altitude_deg)
        return AstronomySnapshot(
            timestamp_utc=timestamp,
            target=target,
            target_label=_TARGET_LABELS[target],
            altitude_deg=altitude_deg,
            azimuth_deg=azimuth_deg,
            sun_altitude_deg=sun_altitude_deg,
            moon_altitude_deg=moon_altitude_deg,
            moon_illumination_fraction=_bounded(moon_illumination),
            moon_separation_deg=min(180.0, max(0.0, moon_separation_deg)),
            airmass=None if not math.isfinite(airmass) else airmass,
            above_geometric_horizon=altitude_deg > 0.0,
        )

    def _target_object(self, target: TargetKind) -> Any:
        if target in self._fixed_targets:
            return self._fixed_targets[target]
        if target == TargetKind.MARS:
            return self._ephemeris["mars barycenter"]
        if target == TargetKind.JUPITER:
            return self._ephemeris["jupiter barycenter"]
        if target == TargetKind.MOON:
            return self._moon
        if target == TargetKind.BRIGHT_PLANET:
            return self._ephemeris["jupiter barycenter"]
        raise ValueError(f"unsupported astronomy target: {target}")


def _require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp_utc must be timezone-aware")
    return value.astimezone(UTC)


def _bounded(value: float) -> float:
    return min(1.0, max(0.0, value))
