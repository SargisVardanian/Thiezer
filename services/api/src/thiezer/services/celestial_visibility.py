from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from thiezer.domain.astronomy import airmass_kasten_young
from thiezer.domain.celestial_objects import (
    CelestialObject,
    CelestialObjectClass,
    CelestialVisibilityResult,
    ObservationCapability,
    VisibilityCapability,
)
from thiezer.domain.contracts import AstronomySnapshot, GeoPoint, TargetKind
from thiezer.domain.ephemeris import SkyfieldAstronomyProvider, classify_moon_phase
from thiezer.providers.ephemeris.horizons import (
    HorizonsClient,
    HorizonsObserverEvent,
)
from thiezer.services.celestial_resolution import CelestialResolutionService


class CelestialVisibilityService:
    """Compute observer-dependent catalog visibility with Skyfield's astrometry support."""

    def __init__(
        self,
        resolver: CelestialResolutionService | None = None,
        horizons: HorizonsClient | None = None,
    ) -> None:
        self._resolver = resolver
        self._horizons = horizons
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
            if target.identifier.provider.value == "horizons":
                return await self._horizons_object(
                    target=target, point=point, timestamp_utc=timestamp_utc
                )
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
            sun_altitude_deg=(
                visibility.sun_altitude_deg if visibility.sun_altitude_deg is not None else 90.0
            ),
            moon_altitude_deg=(
                visibility.moon_altitude_deg if visibility.moon_altitude_deg is not None else -90.0
            ),
            moon_illumination_fraction=(
                visibility.moon_illumination_fraction
                if visibility.moon_illumination_fraction is not None
                else 0.0
            ),
            moon_separation_deg=(
                visibility.moon_separation_deg
                if visibility.moon_separation_deg is not None
                else 180.0
            ),
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
        star = _star_from(target, timescale)
        instant = timescale.from_datetime(timestamp)
        target_apparent = observer.at(instant).observe(star).apparent()
        moon_apparent = observer.at(instant).observe(eph["moon"]).apparent()
        sun_apparent = observer.at(instant).observe(eph["sun"]).apparent()
        altitude, azimuth, _ = target_apparent.altaz()
        moon_altitude, _, _ = moon_apparent.altaz()
        sun_altitude, _, _ = sun_apparent.altaz()
        moon_phase_angle = float(almanac.moon_phase(eph, instant).degrees) % 360.0
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
            moon_phase=classify_moon_phase(moon_phase_angle),
            moon_phase_angle_deg=moon_phase_angle,
            **_event_details(
                almanac=almanac,
                ephemeris=eph,
                timescale=timescale,
                target_object=star,
                location=wgs84.latlon(point.latitude_deg, point.longitude_deg),
                timestamp=timestamp,
                currently_above=altitude_deg > 0,
            ),
            capability=VisibilityCapability.DIRECT,
            observation_capabilities=_observation_capabilities(target),
            source_attributions=(target.attribution,),
            warnings=(*target.warnings, *_capability_warnings(target)),
        )

    def _solar_system(
        self, *, target: CelestialObject, point: GeoPoint, timestamp_utc: datetime
    ) -> CelestialVisibilityResult:
        from skyfield import almanac
        from skyfield.api import Loader, wgs84
        from skyfield_data import get_skyfield_data_path

        timestamp = _aware(timestamp_utc)
        loader = Loader(get_skyfield_data_path(), expire=False)
        timescale = loader.timescale(builtin=True)
        ephemeris = loader("de421.bsp")
        bodies = {
            "sun": ephemeris["sun"],
            "moon": ephemeris["moon"],
            "mars": ephemeris["mars barycenter"],
            "jupiter": ephemeris["jupiter barycenter"],
        }
        body = bodies.get(target.identifier.object_id.casefold())
        if body is None:
            raise ValueError("dynamic Solar-System objects require the Horizons ephemeris provider")
        location = wgs84.latlon(point.latitude_deg, point.longitude_deg)
        observer = ephemeris["earth"] + location
        instant = timescale.from_datetime(timestamp)
        apparent = observer.at(instant).observe(body).apparent()
        altitude, azimuth, _ = apparent.altaz()
        sun_apparent = observer.at(instant).observe(ephemeris["sun"]).apparent()
        moon_apparent = observer.at(instant).observe(ephemeris["moon"]).apparent()
        altitude_deg = float(altitude.degrees)
        moon_separation = (
            0.0
            if target.identifier.object_id.casefold() == "moon"
            else float(apparent.separation_from(moon_apparent).degrees)
        )
        moon_phase_angle = float(almanac.moon_phase(ephemeris, instant).degrees) % 360.0
        airmass = airmass_kasten_young(altitude_deg)
        return CelestialVisibilityResult(
            target=target,
            observer=point.model_dump(),
            timestamp_utc=timestamp,
            altitude_deg=altitude_deg,
            azimuth_deg=float(azimuth.degrees) % 360,
            above_horizon=altitude_deg > 0,
            airmass=airmass if math.isfinite(airmass) else None,
            sun_altitude_deg=float(sun_apparent.altaz()[0].degrees),
            moon_altitude_deg=float(moon_apparent.altaz()[0].degrees),
            moon_illumination_fraction=float(
                almanac.fraction_illuminated(ephemeris, "moon", instant)
            ),
            moon_separation_deg=moon_separation,
            moon_phase=classify_moon_phase(moon_phase_angle),
            moon_phase_angle_deg=moon_phase_angle,
            **_event_details(
                almanac=almanac,
                ephemeris=ephemeris,
                timescale=timescale,
                target_object=body,
                location=location,
                timestamp=timestamp,
                currently_above=altitude_deg > 0,
            ),
            capability=VisibilityCapability.DIRECT,
            observation_capabilities=_observation_capabilities(target),
            source_attributions=(target.attribution,),
            warnings=(*target.warnings, *_capability_warnings(target)),
        )

    async def _horizons_object(
        self, *, target: CelestialObject, point: GeoPoint, timestamp_utc: datetime
    ) -> CelestialVisibilityResult:
        if self._horizons is None:
            raise ValueError("JPL Horizons visibility provider is not configured")
        azimuth_deg, altitude_deg = await self._horizons.observer(
            command=target.identifier.object_id,
            latitude_deg=point.latitude_deg,
            longitude_deg=point.longitude_deg,
            timestamp_utc=timestamp_utc,
        )
        event_loader = getattr(self._horizons, "observer_events", None)
        events = (
            await event_loader(
                command=target.identifier.object_id,
                latitude_deg=point.latitude_deg,
                longitude_deg=point.longitude_deg,
                timestamp_utc=timestamp_utc,
            )
            if callable(event_loader)
            else []
        )
        baseline = self._preset_astronomy.snapshot(
            target=TargetKind.BEST_NIGHT_SKY, point=point, timestamp_utc=timestamp_utc
        )
        airmass = airmass_kasten_young(altitude_deg)
        return CelestialVisibilityResult(
            target=target,
            observer=point.model_dump(),
            timestamp_utc=_aware(timestamp_utc),
            altitude_deg=altitude_deg,
            azimuth_deg=azimuth_deg % 360.0,
            above_horizon=altitude_deg > 0,
            airmass=airmass if math.isfinite(airmass) else None,
            sun_altitude_deg=baseline.sun_altitude_deg,
            moon_altitude_deg=baseline.moon_altitude_deg,
            moon_illumination_fraction=baseline.moon_illumination_fraction,
            moon_separation_deg=None,
            moon_phase=baseline.moon_phase,
            moon_phase_angle_deg=baseline.moon_phase_angle_deg,
            **_horizons_event_details(
                events=events,
                timestamp=_aware(timestamp_utc),
                currently_above=altitude_deg > 0,
            ),
            capability=VisibilityCapability.DIRECT,
            observation_capabilities=_observation_capabilities(target),
            source_attributions=(target.attribution, HorizonsClient.attribution),
            warnings=(
                *target.warnings,
                *_capability_warnings(target),
                "Moon separation is unavailable for this Horizons query.",
            ),
        )


def _star_from(target: CelestialObject, timescale: Any | None = None) -> object:
    from skyfield.api import Star

    if target.coordinates is None:  # pragma: no cover - protected by the caller.
        raise ValueError("fixed catalog target requires coordinates")
    kwargs: dict[str, float] = {
        "ra_hours": target.coordinates.right_ascension_deg / 15,
        "dec_degrees": target.coordinates.declination_deg,
    }
    if timescale is not None:
        kwargs["epoch"] = float(timescale.J(target.coordinates.reference_epoch_jyear).tt)
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


def _event_details(
    *,
    almanac: Any,
    ephemeris: Any,
    timescale: Any,
    target_object: Any,
    location: Any,
    timestamp: datetime,
    currently_above: bool,
) -> dict[str, object]:
    """Use Skyfield's almanac to find geometric events around the requested instant."""
    start = timestamp - timedelta(hours=24)
    end = timestamp + timedelta(hours=48)
    t0 = timescale.from_datetime(start)
    t1 = timescale.from_datetime(end)
    event_times, states = almanac.find_discrete(
        t0,
        t1,
        almanac.risings_and_settings(ephemeris, target_object, location),
    )
    rises = [
        instant.utc_datetime().astimezone(UTC)
        for instant, state in zip(event_times, states, strict=True)
        if bool(state)
    ]
    sets = [
        instant.utc_datetime().astimezone(UTC)
        for instant, state in zip(event_times, states, strict=True)
        if not bool(state)
    ]

    if currently_above:
        rise = max((item for item in rises if item <= timestamp), default=None)
        setting = min((item for item in sets if item > timestamp), default=None)
        window_start = rise or timestamp
    else:
        rise = min((item for item in rises if item > timestamp), default=None)
        setting = (
            min((item for item in sets if rise is not None and item > rise), default=None)
            if rise is not None
            else None
        )
        window_start = rise
    window = (window_start, setting) if window_start is not None and setting is not None else None

    transit_times, transit_kinds = almanac.find_discrete(
        t0,
        t1,
        almanac.meridian_transits(ephemeris, target_object, location),
    )
    upper_transits = [
        instant
        for instant, kind in zip(transit_times, transit_kinds, strict=True)
        if int(kind) == 1 and instant.utc_datetime().astimezone(UTC) >= timestamp
    ]
    culmination = upper_transits[0] if upper_transits else None
    culmination_utc = (
        culmination.utc_datetime().astimezone(UTC) if culmination is not None else None
    )
    maximum_altitude = None
    if culmination is not None:
        observer = ephemeris["earth"] + location
        altitude, _, _ = observer.at(culmination).observe(target_object).apparent().altaz()
        maximum_altitude = float(altitude.degrees)
    return {
        "rise_utc": rise,
        "set_utc": setting,
        "culmination_utc": culmination_utc,
        "maximum_altitude_deg": maximum_altitude,
        "visibility_window": window,
    }


def _observation_capabilities(
    target: CelestialObject,
) -> tuple[ObservationCapability, ...]:
    photometry = target.photometry
    magnitude = None
    if photometry is not None:
        magnitude = (
            photometry.visual_magnitude
            if photometry.visual_magnitude is not None
            else photometry.gaia_g_magnitude
        )
    result: list[ObservationCapability] = []
    if (
        target.identifier.provider.value == "skyfield"
        and target.identifier.object_id.casefold() in {"sun", "moon", "mars", "jupiter"}
    ):
        result.extend((ObservationCapability.NAKED_EYE, ObservationCapability.BINOCULARS))
    if magnitude is not None and magnitude <= 6.5:
        result.append(ObservationCapability.NAKED_EYE)
    if (magnitude is not None and magnitude <= 10) or target.object_class in {
        CelestialObjectClass.GALAXY,
        CelestialObjectClass.NEBULA,
        CelestialObjectClass.CLUSTER,
    }:
        result.append(ObservationCapability.BINOCULARS)
    result.extend((ObservationCapability.TELESCOPE, ObservationCapability.CAMERA))
    return tuple(dict.fromkeys(result))


def _capability_warnings(target: CelestialObject) -> tuple[str, ...]:
    if target.identifier.provider.value == "skyfield":
        return ()
    if target.photometry is None or (
        target.photometry.visual_magnitude is None and target.photometry.gaia_g_magnitude is None
    ):
        return ("Apparent magnitude is unavailable; observing modes are conservative estimates.",)
    return ()


def _horizons_event_details(
    *,
    events: list[HorizonsObserverEvent],
    timestamp: datetime,
    currently_above: bool,
) -> dict[str, object]:
    rises = [event for event in events if event.kind == "r"]
    sets = [event for event in events if event.kind == "s"]
    transits = [event for event in events if event.kind == "t"]
    window_start: datetime | None
    if currently_above:
        rise = max(
            (event for event in rises if event.timestamp_utc <= timestamp),
            key=lambda event: event.timestamp_utc,
            default=None,
        )
        setting = min(
            (event for event in sets if event.timestamp_utc > timestamp),
            key=lambda event: event.timestamp_utc,
            default=None,
        )
        window_start = rise.timestamp_utc if rise is not None else timestamp
    else:
        rise = min(
            (event for event in rises if event.timestamp_utc > timestamp),
            key=lambda event: event.timestamp_utc,
            default=None,
        )
        setting = min(
            (
                event
                for event in sets
                if rise is not None and event.timestamp_utc > rise.timestamp_utc
            ),
            key=lambda event: event.timestamp_utc,
            default=None,
        )
        window_start = rise.timestamp_utc if rise is not None else None
    transit = min(
        (event for event in transits if event.timestamp_utc >= timestamp),
        key=lambda event: event.timestamp_utc,
        default=None,
    )
    return {
        "rise_utc": rise.timestamp_utc if rise is not None else None,
        "set_utc": setting.timestamp_utc if setting is not None else None,
        "culmination_utc": transit.timestamp_utc if transit is not None else None,
        "maximum_altitude_deg": transit.altitude_deg if transit is not None else None,
        "visibility_window": (
            (window_start, setting.timestamp_utc)
            if window_start is not None and setting is not None
            else None
        ),
    }


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp_utc must be timezone-aware")
    return value.astimezone(UTC)
