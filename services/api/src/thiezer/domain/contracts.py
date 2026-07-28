from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

UnitScore = Annotated[float, Field(ge=0.0, le=1.0)]
Latitude = Annotated[float, Field(ge=-90.0, le=90.0)]
Longitude = Annotated[float, Field(ge=-180.0, le=180.0)]
NonNegativeFloat = Annotated[float, Field(ge=0.0)]
CountryCode = Annotated[
    str,
    StringConstraints(to_upper=True, min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$"),
]


class TargetKind(StrEnum):
    ALPHA_CENTAURI = "alpha_centauri"
    MARS = "mars"
    JUPITER = "jupiter"
    MOON = "moon"
    MILKY_WAY = "milky_way"
    BEST_NIGHT_SKY = "best_night_sky"
    BRIGHT_PLANET = "bright_planet"


class ObservationMode(StrEnum):
    NAKED_EYE = "naked_eye"
    BINOCULARS = "binoculars"
    WIDE_ANGLE_CAMERA = "wide_angle_camera"


class SearchScope(StrEnum):
    """Boundary policy for a radius-based search.

    ADAPTIVE and GLOBAL both allow crossing borders. COUNTRY restricts known country codes.
    The engine never scans an entire large country; max_distance_km is always the hard spatial bound.
    """

    ADAPTIVE = "adaptive"
    COUNTRY = "country"
    GLOBAL = "global"


class PlaceKind(StrEnum):
    OBSERVATION_SITE = "observation_site"
    OBSERVATORY = "observatory"
    VIEWPOINT = "viewpoint"
    CAMPSITE = "campsite"
    PARKING = "parking"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    PARTNER_VERIFIED = "partner_verified"
    UNVERIFIED_SEED = "unverified_seed"
    UNVERIFIED_DISCOVERED = "unverified_discovered"


class StoreKind(StrEnum):
    PHYSICAL = "physical"
    ONLINE = "online"
    HYBRID = "hybrid"


class ForecastConfidenceBand(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    PRELIMINARY = "preliminary"
    TREND_ONLY = "trend_only"


class WarningCode(StrEnum):
    INVALID_SUN_ALTITUDE = "invalid_sun_altitude"
    TARGET_BELOW_HORIZON = "target_below_horizon"
    TARGET_NOT_VISIBLE_IN_SCOPE = "target_not_visible_in_scope"
    SEVERE_CLOUD = "severe_cloud"
    PRECIPITATION = "precipitation"
    INACCESSIBLE = "inaccessible"
    LOW_CONFIDENCE = "low_confidence"
    HIGH_DEW_RISK = "high_dew_risk"
    STRONG_WIND = "strong_wind"
    UNVERIFIED_PLACE = "unverified_place"
    WEATHER_UNAVAILABLE = "weather_unavailable"
    NO_CANDIDATE_PLACES = "no_candidate_places"
    NO_OBSERVATION_WINDOW = "no_observation_window"
    DISCOVERY_PROVIDER_UNAVAILABLE = "discovery_provider_unavailable"
    DARKNESS_IS_PROXY = "darkness_is_proxy"


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
    precipitation_mm: NonNegativeFloat
    visibility_m: NonNegativeFloat | None = None
    wind_speed_mps: NonNegativeFloat
    wind_gust_mps: NonNegativeFloat | None = None
    pressure_hpa: Annotated[float, Field(gt=0.0)] | None = None
    provider: str
    model_name: str | None = None
    run_timestamp_utc: datetime | None = None
    requested_point: GeoPoint
    returned_grid_point: GeoPoint
    attribution: str

    @model_validator(mode="after")
    def require_utc(self) -> HourlySkyCondition:
        _require_aware(self.timestamp_utc, "timestamp_utc")
        if self.run_timestamp_utc is not None:
            _require_aware(self.run_timestamp_utc, "run_timestamp_utc")
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
    scoring_version: str = "v1"


class AstronomySnapshot(BaseModel):
    timestamp_utc: datetime
    target: TargetKind
    target_label: str
    altitude_deg: float
    azimuth_deg: Annotated[float, Field(ge=0.0, lt=360.0)]
    sun_altitude_deg: float
    moon_altitude_deg: float
    moon_illumination_fraction: UnitScore
    moon_separation_deg: Annotated[float, Field(ge=0.0, le=180.0)]
    airmass: NonNegativeFloat | None
    above_geometric_horizon: bool

    @model_validator(mode="after")
    def validate_timestamp(self) -> AstronomySnapshot:
        _require_aware(self.timestamp_utc, "timestamp_utc")
        return self


class CandidatePlace(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    country_code: CountryCode | None = None
    region: str | None = None
    point: GeoPoint
    elevation_m: float
    kind: PlaceKind
    verification_status: VerificationStatus
    darkness_score: UnitScore
    horizon_openness_score: UnitScore
    accessibility_score: UnitScore
    risk_score: UnitScore
    road_access: str
    notes: str | None = None
    source_url: AnyHttpUrl | None = None
    source_provider: str = "seed"
    darkness_model: str = "seed_value"


class ExplanationItem(BaseModel):
    code: str
    message: str
    impact: str


class ObservationWindow(BaseModel):
    start_utc: datetime
    end_utc: datetime
    best_time_utc: datetime
    best_score: UnitScore
    mean_score: UnitScore
    best_astronomy: AstronomySnapshot
    best_conditions: HourlySkyCondition
    score_breakdown: SkyScoreBreakdown

    @model_validator(mode="after")
    def validate_window(self) -> ObservationWindow:
        for field_name in ("start_utc", "end_utc", "best_time_utc"):
            _require_aware(getattr(self, field_name), field_name)
        if self.end_utc < self.start_utc:
            raise ValueError("end_utc must not precede start_utc")
        if not self.start_utc <= self.best_time_utc <= self.end_utc:
            raise ValueError("best_time_utc must fall inside the window")
        return self


class RouteHandoff(BaseModel):
    provider: str
    url: str
    requires_api_key: bool = False
    note: str | None = None


class RankedPlace(BaseModel):
    rank: Annotated[int, Field(ge=1)]
    place: CandidatePlace
    distance_km: NonNegativeFloat
    observation_window: ObservationWindow
    utility: float
    explanations: list[ExplanationItem]
    warnings: list[WarningCode]
    routes: list[RouteHandoff]


class RecommendationSearchRequest(BaseModel):
    user_location: GeoPoint
    target: TargetKind
    observation_mode: ObservationMode = ObservationMode.NAKED_EYE
    start_utc: datetime
    end_utc: datetime
    scope: SearchScope = SearchScope.ADAPTIVE
    country_code: CountryCode | None = None
    max_distance_km: Annotated[float, Field(gt=0.0, le=1_000.0)] = 250.0
    max_candidates: Annotated[int, Field(ge=1, le=40)] = 16
    max_results: Annotated[int, Field(ge=1, le=10)] = 5
    minimum_score: UnitScore = 0.35
    include_unverified: bool = True

    @model_validator(mode="after")
    def validate_request(self) -> RecommendationSearchRequest:
        _require_aware(self.start_utc, "start_utc")
        _require_aware(self.end_utc, "end_utc")
        if self.end_utc <= self.start_utc:
            raise ValueError("end_utc must be after start_utc")
        if self.end_utc - self.start_utc > _MAX_SEARCH_RANGE:
            raise ValueError("search range cannot exceed 16 days")
        if self.scope == SearchScope.COUNTRY and self.country_code is None:
            raise ValueError("country_code is required for country scope")
        return self


class RecommendationSearchResponse(BaseModel):
    generated_at_utc: datetime
    target: TargetKind
    scope: SearchScope
    search_radius_km: NonNegativeFloat
    coverage_country_codes: list[str]
    discovery_sources: list[str]
    results: list[RankedPlace]
    warnings: list[WarningCode]
    provider_attributions: list[str]


class TargetVisibilityResponse(BaseModel):
    point: GeoPoint
    snapshot: AstronomySnapshot
    visible: bool
    reason: str


class EquipmentStore(BaseModel):
    id: str
    name: str
    kind: StoreKind
    country_code: CountryCode | None = None
    point: GeoPoint | None = None
    address: str | None = None
    website_url: AnyHttpUrl
    catalog_url: AnyHttpUrl | None = None
    phone: str | None = None
    categories: list[str]
    delivers_countrywide: bool = False
    verification_status: VerificationStatus
    source_checked_at_utc: datetime
    source_provider: str = "seed"

    @model_validator(mode="after")
    def validate_store(self) -> EquipmentStore:
        _require_aware(self.source_checked_at_utc, "source_checked_at_utc")
        if self.kind == StoreKind.PHYSICAL and self.point is None:
            raise ValueError("physical stores require coordinates")
        return self


class StoreSearchRequest(BaseModel):
    user_location: GeoPoint
    scope: SearchScope = SearchScope.ADAPTIVE
    country_code: CountryCode | None = None
    max_distance_km: Annotated[float, Field(gt=0.0, le=1_000.0)] = 250.0
    max_results: Annotated[int, Field(ge=1, le=30)] = 10

    @model_validator(mode="after")
    def validate_scope(self) -> StoreSearchRequest:
        if self.scope == SearchScope.COUNTRY and self.country_code is None:
            raise ValueError("country_code is required for country scope")
        return self


class StoreSearchResult(BaseModel):
    store: EquipmentStore
    distance_km: NonNegativeFloat | None
    routes: list[RouteHandoff]


class StoreSearchResponse(BaseModel):
    results: list[StoreSearchResult]
    search_radius_km: NonNegativeFloat
    coverage_country_codes: list[str]
    discovery_sources: list[str]
    warnings: list[WarningCode]
    provider_attributions: list[str]


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    if value.astimezone(UTC).utcoffset() is None:
        raise ValueError(f"{field_name} cannot be converted to UTC")


_MAX_SEARCH_RANGE = timedelta(days=16)
