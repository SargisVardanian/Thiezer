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


class CelestialObjectClass(StrEnum):
    STAR = "star"
    GALAXY = "galaxy"
    NEBULA = "nebula"
    CLUSTER = "cluster"
    EXOPLANET = "exoplanet"
    SOLAR_SYSTEM_BODY = "solar_system_body"
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


class CelestialPhysicalProperties(BaseModel):
    distance_parsec: float | None = Field(default=None, ge=0)
    spectral_type: str | None = None


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


class CelestialVisibilityResult(BaseModel):
    target: CelestialObject
    observer: CelestialObserver
    timestamp_utc: datetime
    altitude_deg: float
    azimuth_deg: float
    above_horizon: bool
    capability: VisibilityCapability
    source_attributions: tuple[str, ...]
    warnings: tuple[str, ...] = ()
