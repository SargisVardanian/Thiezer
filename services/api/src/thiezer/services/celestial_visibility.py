from __future__ import annotations

import math
from datetime import UTC, datetime

from thiezer.domain.astronomy import airmass_kasten_young
from thiezer.domain.celestial_objects import (
    CelestialObject,
    CelestialVisibilityResult,
    VisibilityCapability,
)
from thiezer.domain.contracts import AstronomySnapshot, GeoPoint, TargetKind
from thiezer.domain.ephemeris import SkyfieldAstronomyProvider
from thiezer.services.celestial_resolution import CelestialResolutionService


class CelestialVisibilityService:
    """Compute observer-dependent catalog visibility with Skyfield's astrometry support."""

    def __init__(self, resolver: CelestialResolutionService | None = None) -> None:
        self._resolver = resolver
        self._preset_astronomy = SkyfieldAstronomyProvider()

    async def get(
        self, *, target: CelestialObject, point: GeoPoint, timestamp_utc: datetime
    ) -> CelestialVisibilityResult:
        if target.object_class.value == "exoplanet":
            if target.host_star is None or self._resolver is None:
                raise ValueError("exoplanet host-star metadata is unavailable")
            host = await self._resolver.resolve(target.host_star)
            result = await self.get(target=host, point=point, timestamp_utc=timestamp_utc)
            return result.model_copy(
                update={
                    "target": target,
                    "capability": VisibilityCapability.HOST_STAR_VISIBILITY,
                    "source_attributions": tuple(
                        dict.fromkeys((*result.source_attributions, target.attribution))
                    ),
                    "warnings": (
                        "Exoplanets are not directly visible; this is host-star visibility.",
                    ),
                }
            )
        if target.coordinates is None:
            return self._solar_system(target=target, point=point, timestamp_utc=timestamp_utc)
        return self._fixed_object(target=target, point=point, timestamp_utc=timestamp_utc)

    async def snapshot(
        self,
        *,
        target: CelestialObject,
        point: GeoPoint,
        timestamp_utc: datetime,
        scoring_target: TargetKind,
    ) -> AstronomySnapshot:
        """Use actual catalog-object coordinates while retaining a documented score profile."""
        visibility = await self.get(target=target, point=point, timestamp_utc=timestamp_utc)
        return AstronomySnapshot(
            timestamp_utc=visibility.timestamp_utc,
            target=scoring_target,
            target_label=target.name,
            altitude_deg=visibility.altitude_deg,
            azimuth_deg=visibility.azimuth_deg,
            sun_altitude_deg=visibility.sun_altitude_deg or 90.0,
            moon_altitude_deg=visibility.moon_altitude_deg or -90.0,
            moon_illumination_fraction=visibility.moon_illumination_fraction or 0.0,
            moon_separation_deg=visibility.moon_separation_deg or 180.0,
            airmass=visibility.airmass,
            above_geometric_horizon=visibility.above_horizon,
        )

    def _fixed_object(
        self, *, target: CelestialObject, point: GeoPoint, timestamp_utc: datetime
    ) -> CelestialVisibilityResult:
        from skyfield import almanac
        from skyfield.api import Loader, wgs84
        from skyfield_data import get_skyfield_data_path

        timestamp = _aware(timestamp_utc)
        loader = Loader(get_skyfield_data_path(), expire=False)
        timescale = loader.timescale(builtin=True)
        eph = loader("de421.bsp")
        observer = eph["earth"] + wgs84.latlon(point.latitude_deg, point.longitude_deg)
        star = _star_from(target)
        instant = timescale.from_datetime(timestamp)
        target_apparent = observer.at(instant).observe(star).apparent()
        moon_apparent = observer.at(instant).observe(eph["moon"]).apparent()
        sun_apparent = observer.at(instant).observe(eph["sun"]).apparent()
        altitude, azimuth, _ = target_apparent.altaz()
        moon_altitude, _, _ = moon_apparent.altaz()
        sun_altitude, _, _ = sun_apparent.altaz()
        altitude_deg = float(altitude.degrees)
        airmass = airmass_kasten_young(altitude_deg)
        return CelestialVisibilityResult(
            target=target,
            observer=point.model_dump(),
            timestamp_utc=timestamp,
            altitude_deg=altitude_deg,
            azimuth_deg=float(azimuth.degrees) % 360,
            above_horizon=altitude_deg > 0,
            airmass=airmass if math.isfinite(airmass) else None,
            sun_altitude_deg=float(sun_altitude.degrees),
            moon_altitude_deg=float(moon_altitude.degrees),
            moon_illumination_fraction=float(almanac.fraction_illuminated(eph, "moon", instant)),
            moon_separation_deg=float(target_apparent.separation_from(moon_apparent).degrees),
            capability=VisibilityCapability.DIRECT,
            source_attributions=(target.attribution,),
            warnings=target.warnings,
        )

    def _solar_system(
        self, *, target: CelestialObject, point: GeoPoint, timestamp_utc: datetime
    ) -> CelestialVisibilityResult:
        mapping = {
            "sun": TargetKind.BEST_NIGHT_SKY,
            "moon": TargetKind.MOON,
            "mars": TargetKind.MARS,
            "jupiter": TargetKind.JUPITER,
        }
        kind = mapping.get(target.identifier.object_id.casefold())
        if kind is None:
            raise ValueError("dynamic Solar-System objects require the Horizons ephemeris provider")
        snapshot = self._preset_astronomy.snapshot(
            target=kind, point=point, timestamp_utc=timestamp_utc
        )
        return CelestialVisibilityResult(
            target=target,
            observer=point.model_dump(),
            timestamp_utc=snapshot.timestamp_utc,
            altitude_deg=snapshot.altitude_deg,
            azimuth_deg=snapshot.azimuth_deg,
            above_horizon=snapshot.above_geometric_horizon,
            airmass=snapshot.airmass,
            sun_altitude_deg=snapshot.sun_altitude_deg,
            moon_altitude_deg=snapshot.moon_altitude_deg,
            moon_illumination_fraction=snapshot.moon_illumination_fraction,
            moon_separation_deg=snapshot.moon_separation_deg,
            capability=VisibilityCapability.DIRECT,
            source_attributions=(target.attribution,),
            warnings=target.warnings,
        )


def _star_from(target: CelestialObject) -> object:
    from skyfield.api import Star

    if target.coordinates is None:  # pragma: no cover - protected by the caller.
        raise ValueError("fixed catalog target requires coordinates")
    kwargs: dict[str, float] = {
        "ra_hours": target.coordinates.right_ascension_deg / 15,
        "dec_degrees": target.coordinates.declination_deg,
    }
    if target.motion is not None:
        if target.motion.proper_motion_ra_mas_per_year is not None:
            kwargs["ra_mas_per_year"] = target.motion.proper_motion_ra_mas_per_year
        if target.motion.proper_motion_dec_mas_per_year is not None:
            kwargs["dec_mas_per_year"] = target.motion.proper_motion_dec_mas_per_year
        if target.motion.parallax_mas is not None:
            kwargs["parallax_mas"] = target.motion.parallax_mas
        if target.motion.radial_velocity_km_s is not None:
            kwargs["radial_km_per_s"] = target.motion.radial_velocity_km_s
    return Star(**kwargs)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp_utc must be timezone-aware")
    return value.astimezone(UTC)
