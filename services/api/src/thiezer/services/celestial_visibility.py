from __future__ import annotations

from datetime import UTC, datetime

from thiezer.domain.celestial_objects import (
    CelestialObject,
    CelestialVisibilityResult,
    VisibilityCapability,
)
from thiezer.domain.contracts import GeoPoint, TargetKind
from thiezer.domain.ephemeris import SkyfieldAstronomyProvider
from thiezer.services.celestial_resolution import CelestialResolutionService


class CelestialVisibilityService:
    def __init__(self, resolver: CelestialResolutionService | None = None) -> None:
        self._resolver = resolver

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
        from skyfield.api import Loader, Star, wgs84
        from skyfield_data import get_skyfield_data_path

        timestamp = timestamp_utc.astimezone(UTC)
        loader = Loader(get_skyfield_data_path(), expire=False)
        eph = loader("de421.bsp")
        observer = eph["earth"] + wgs84.latlon(point.latitude_deg, point.longitude_deg)
        star_kwargs: dict[str, float] = {
            "ra_hours": target.coordinates.right_ascension_deg / 15,
            "dec_degrees": target.coordinates.declination_deg,
        }
        if target.motion is not None:
            if target.motion.proper_motion_ra_mas_per_year is not None:
                star_kwargs["ra_mas_per_year"] = target.motion.proper_motion_ra_mas_per_year
            if target.motion.proper_motion_dec_mas_per_year is not None:
                star_kwargs["dec_mas_per_year"] = target.motion.proper_motion_dec_mas_per_year
            if target.motion.parallax_mas is not None:
                star_kwargs["parallax_mas"] = target.motion.parallax_mas
            if target.motion.radial_velocity_km_s is not None:
                star_kwargs["radial_km_per_s"] = target.motion.radial_velocity_km_s
        star = Star(**star_kwargs)
        altitude, azimuth, _ = (
            observer.at(loader.timescale(builtin=True).from_datetime(timestamp))
            .observe(star)
            .apparent()
            .altaz()
        )
        return CelestialVisibilityResult(
            target=target,
            observer=point.model_dump(),
            timestamp_utc=timestamp,
            altitude_deg=float(altitude.degrees),
            azimuth_deg=float(azimuth.degrees) % 360,
            above_horizon=float(altitude.degrees) > 0,
            capability=VisibilityCapability.DIRECT,
            source_attributions=(target.attribution,),
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
        snapshot = SkyfieldAstronomyProvider().snapshot(
            target=kind, point=point, timestamp_utc=timestamp_utc
        )
        return CelestialVisibilityResult(
            target=target,
            observer=point.model_dump(),
            timestamp_utc=snapshot.timestamp_utc,
            altitude_deg=snapshot.altitude_deg,
            azimuth_deg=snapshot.azimuth_deg,
            above_horizon=snapshot.above_geometric_horizon,
            capability=VisibilityCapability.DIRECT,
            source_attributions=(target.attribution,),
        )
