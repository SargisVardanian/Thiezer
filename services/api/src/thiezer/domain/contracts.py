from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

UnitScore = Annotated[float, Field(ge=0.0, le=1.0)]
Latitude = Annotated[float, Field(ge=-90.0, le=90.0)]
Longitude = Annotated[float, Field(ge=-180.0, le=180.0)]


class TargetKind(StrEnum):
    MILKY_WAY = "milky_way"
    MOON = "moon"
    BRIGHT_PLANET = "bright_planet"


class ObservationMode(StrEnum):
    NAKED_EYE = "naked_eye"
    BINOCULARS = "binoculars"
    WIDE_ANGLE_CAMERA = "wide_angle_camera"


class ForecastConfidenceBand(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    PRELIMINARY = "preliminary"
    TREND_ONLY = "trend_only"


class WarningCode(StrEnum):
    INVALID_SUN_ALTITUDE = "invalid_sun_altitude"
    TARGET_BELOW_HORIZON = "target_below_horizon"
    SEVERE_CLOUD = "severe_cloud"
    INACCESSIBLE = "inaccessible"
    LOW_CONFIDENCE = "low_confidence"
    HIGH_DEW_RISK = "high_dew_risk"
    STRONG_WIND = "strong_wind"


class GeoPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    latitude_deg: Latitude
    longitude_deg: Longitude


class BoundingBox(BaseModel):
    south_west: GeoPoint
    north_east: GeoPoint

    @model_validator(mode="after")
    def validate_order(self) -> BoundingBox:
        if self.south_west.latitude_deg > self.north_east.latitude_deg:
            raise ValueError("south_west latitude must not exceed north_east latitude")
        return self


class HourlySkyCondition(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp_utc: datetime
    total_cloud_fraction: UnitScore
    low_cloud_fraction: UnitScore
    mid_cloud_fraction: UnitScore
    high_cloud_fraction: UnitScore
    temperature_c: float
    relative_humidity_fraction: UnitScore
    dew_point_c: float
    precipitation_mm: Annotated[float, Field(ge=0.0)]
    visibility_m: Annotated[float, Field(ge=0.0)] | None = None
    wind_speed_mps: Annotated[float, Field(ge=0.0)]
    wind_gust_mps: Annotated[float, Field(ge=0.0)] | None = None
    pressure_hpa: Annotated[float, Field(gt=0.0)] | None = None
    provider: str
    model_name: str | None = None
    run_timestamp_utc: datetime | None = None
    requested_point: GeoPoint
    returned_grid_point: GeoPoint
    attribution: str

    @model_validator(mode="after")
    def require_utc(self) -> HourlySkyCondition:
        if self.timestamp_utc.tzinfo is None or self.timestamp_utc.utcoffset() is None:
            raise ValueError("timestamp_utc must be timezone-aware")
        return self


class SkyScoreComponent(BaseModel):
    name: str
    value: UnitScore
    weight: UnitScore


class SkyScoreBreakdown(BaseModel):
    valid: bool
    score: UnitScore
    utility: float
    components: list[SkyScoreComponent]
    warnings: list[WarningCode]
    explanation_codes: list[str]
    scoring_version: str = "v0"
