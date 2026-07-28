from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CatalogSource(StrEnum):
    SIMBAD = "simbad"
    GAIA = "gaia"
    VIZIER = "vizier"
    NED = "ned"
    EXOPLANET_ARCHIVE = "exoplanet_archive"
    HORIZONS = "horizons"
    SKYFIELD = "skyfield"


class MoonPhase(StrEnum):
    ANY = "any"
    NEW = "new"
    CRESCENT = "crescent"
    FIRST_QUARTER = "first_quarter"
    GIBBOUS = "gibbous"
    FULL = "full"
    LAST_QUARTER = "last_quarter"


class CelestialObjectClass(StrEnum):
    STAR = "star"
    GALAXY = "galaxy"
    NEBULA = "nebula"
    CLUSTER = "cluster"
    EXOPLANET = "exoplanet"
    SOLAR_SYSTEM_BODY = "solar_system_body"
    ASTEROID = "asteroid"
    COMET = "comet"
    DWARF_PLANET = "dwarf_planet"
    NATURAL_SATELLITE = "natural_satellite"
    SPACECRAFT = "spacecraft"
    OTHER = "other"


class CelestialObjectId(BaseModel):
    provider: CatalogSource
    object_id: str = Field(min_length=1, max_length=256)


class CelestialCoordinates(BaseModel):
    right_ascension_deg: float = Field(ge=0, lt=360)
    declination_deg: float = Field(ge=-90, le=90)
    reference_epoch_jyear: float = Field(default=2000.0, ge=1800, le=2200)
    frame: str = "ICRS"


class CelestialObserver(BaseModel):
    """A location copied into visibility results without coupling catalog models to requests."""

    latitude_deg: float = Field(ge=-90, le=90)
    longitude_deg: float = Field(ge=-180, le=180)


class CelestialMotion(BaseModel):
    proper_motion_ra_mas_per_year: float | None = None
    proper_motion_dec_mas_per_year: float | None = None
    parallax_mas: float | None = Field(default=None, ge=0)
    radial_velocity_km_s: float | None = None


class CelestialPhotometry(BaseModel):
    visual_magnitude: float | None = None
    gaia_g_magnitude: float | None = None
    gaia_bp_magnitude: float | None = None
    gaia_rp_magnitude: float | None = None


class CelestialPhysicalProperties(BaseModel):
    distance_parsec: float | None = Field(default=None, ge=0)
    spectral_type: str | None = None
    redshift: float | None = None
    angular_major_axis_arcmin: float | None = Field(default=None, ge=0)
    orbital_period_days: float | None = Field(default=None, ge=0)
    transit_detected: bool | None = None


class CelestialObject(BaseModel):
    model_config = ConfigDict(frozen=True)
    identifier: CelestialObjectId
    name: str
    aliases: tuple[str, ...] = ()
    object_class: CelestialObjectClass
    coordinates: CelestialCoordinates | None = None
    motion: CelestialMotion | None = None
    photometry: CelestialPhotometry | None = None
    physical: CelestialPhysicalProperties | None = None
    host_star: CelestialObjectId | None = None
    attribution: str
    uncertainty: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class CelestialSearchResults(BaseModel):
    results: tuple[CelestialObject, ...]
    source_attributions: tuple[str, ...]
    warnings: tuple[str, ...] = ()


class CelestialTargetRef(BaseModel):
    preset: str | None = None
    catalog_object: CelestialObjectId | None = None

    def model_post_init(self, __context: object) -> None:
        if (self.preset is None) == (self.catalog_object is None):
            raise ValueError("provide exactly one of preset or catalog_object")


class VisibilityCapability(StrEnum):
    DIRECT = "direct"
    HOST_STAR_VISIBILITY = "host_star_visibility"
    NOT_DIRECTLY_VISIBLE = "not_directly_visible"


class ObservationCapability(StrEnum):
    NAKED_EYE = "naked_eye"
    BINOCULARS = "binoculars"
    TELESCOPE = "telescope"
    CAMERA = "camera"


class CelestialVisibilityResult(BaseModel):
    target: CelestialObject
    observer: CelestialObserver
    timestamp_utc: datetime
    altitude_deg: float
    azimuth_deg: float
    above_horizon: bool
    airmass: float | None = Field(default=None, ge=0)
    sun_altitude_deg: float | None = None
    moon_altitude_deg: float | None = None
    moon_illumination_fraction: float | None = Field(default=None, ge=0, le=1)
    moon_separation_deg: float | None = Field(default=None, ge=0, le=180)
    moon_phase: MoonPhase = MoonPhase.ANY
    moon_phase_angle_deg: float | None = Field(default=None, ge=0.0, lt=360.0)
    visibility_window: tuple[datetime, datetime] | None = None
    rise_utc: datetime | None = None
    set_utc: datetime | None = None
    culmination_utc: datetime | None = None
    maximum_altitude_deg: float | None = None
    capability: VisibilityCapability
    observation_capabilities: tuple[ObservationCapability, ...] = ()
    source_attributions: tuple[str, ...]
    warnings: tuple[str, ...] = ()
