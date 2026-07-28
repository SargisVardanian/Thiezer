from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from thiezer.domain.contracts import GeoPoint


class SurfaceDataQuality(StrEnum):
    CALIBRATED_RASTER = "calibrated_raster"
    REMOTE_RASTER = "remote_raster"
    PROCEDURAL_FALLBACK = "procedural_fallback"


@dataclass(frozen=True, slots=True)
class SurfaceCell:
    h3_index: str
    resolution: int
    center: GeoPoint
    elevation_m: float
    slope_deg: float
    roughness_m: float
    mean_radiance_0_5_km: float
    mean_radiance_5_25_km: float
    mean_radiance_25_80_km: float
    water_fraction: float
    urban_fraction: float
    forest_fraction: float
    open_land_fraction: float
    distance_to_road_km: float
    distance_to_settlement_km: float
    restricted: bool
    darkness_score: float
    terrain_score: float
    land_score: float
    access_potential: float
    static_score: float
    static_upper_bound: float
    uncertainty: float
    data_quality: SurfaceDataQuality
    attribution: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class SurfaceSite:
    id: str
    name: str
    point: GeoPoint
    cell: SurfaceCell
    elevation_m: float
    slope_deg: float
    horizon_openness_score: float
    accessibility_score: float
    risk_score: float
    road_access: str
    source_url: str | None
    source_provider: str
    country_code: str | None = None
    region: str | None = None


@dataclass(frozen=True, slots=True)
class SurfaceSearchBudget:
    coarse_parent_limit: int = 32
    fine_cell_limit: int = 96
    materialized_site_limit: int = 60
    weather_candidate_limit: int = 40
    coarse_min_separation_km: float = 18.0
    fine_min_separation_km: float = 6.0
    site_min_separation_km: float = 8.0


@dataclass(frozen=True, slots=True)
class SurfaceSearchDiagnostics:
    coarse_resolution: int
    fine_resolution: int
    coarse_cells: int
    coarse_after_filters: int
    selected_parents: int
    fine_cells: int
    fine_after_filters: int
    selected_fine_cells: int
    materialized_sites: int
    weather_candidates: int
    static_evaluations: int
    large_radius_overpass_calls: int


@dataclass(frozen=True, slots=True)
class SurfaceSearchResult:
    sites: list[SurfaceSite]
    diagnostics: SurfaceSearchDiagnostics
    attributions: tuple[str, ...]
    darkness_is_proxy: bool
