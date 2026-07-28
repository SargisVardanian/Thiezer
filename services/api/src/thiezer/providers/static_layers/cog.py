from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import Any

import h3

from thiezer.domain.contracts import GeoPoint
from thiezer.domain.search_cells import cell_center
from thiezer.domain.static_scoring import RawSurfaceFeatures
from thiezer.domain.surface import SurfaceDataQuality


@dataclass(frozen=True, slots=True)
class CogLayerConfig:
    dem_url: str
    worldcover_url: str
    viirs_url: str | None = None


class CogSurfaceLayerProvider:
    """Read small windows from local or remote Cloud Optimized GeoTIFFs.

    The provider expects explicit asset URLs. Dataset discovery and download remain deployment
    concerns, while each interactive search reads only windows around the current H3 candidates.
    """

    source_name = "cog_surface_v1"
    attributions = (
        "Copernicus DEM",
        "ESA WorldCover (CC BY 4.0)",
        "NASA VIIRS/Black Marble when configured",
    )

    def __init__(self, config: CogLayerConfig) -> None:
        self._config = config
        self.darkness_is_proxy = config.viirs_url is None

    async def evaluate_cells(self, cell_ids: list[str]) -> list[RawSurfaceFeatures]:
        points = [cell_center(cell_id) for cell_id in cell_ids]
        resolutions = [int(h3.get_resolution(cell_id)) for cell_id in cell_ids]
        return await asyncio.to_thread(
            self._evaluate_sync,
            cell_ids,
            points,
            resolutions,
        )

    async def evaluate_points(
        self,
        *,
        points: list[GeoPoint],
        resolution: int,
    ) -> list[RawSurfaceFeatures]:
        identifiers = [f"point:{index}" for index in range(len(points))]
        return await asyncio.to_thread(
            self._evaluate_sync,
            identifiers,
            points,
            [resolution] * len(points),
        )

    async def aclose(self) -> None:
        return None

    def _evaluate_sync(
        self,
        identifiers: list[str],
        points: list[GeoPoint],
        resolutions: list[int],
    ) -> list[RawSurfaceFeatures]:
        try:
            import numpy as np
            import rasterio
        except ImportError as exc:  # pragma: no cover - optional deployment dependency
            raise RuntimeError(
                "install Thiezer with the geodata extra to use COG layers"
            ) from exc

        with rasterio.open(self._config.dem_url) as dem, rasterio.open(
            self._config.worldcover_url
        ) as land:
            viirs = rasterio.open(self._config.viirs_url) if self._config.viirs_url else None
            try:
                output: list[RawSurfaceFeatures] = []
                for identifier, point, resolution in zip(
                    identifiers,
                    points,
                    resolutions,
                    strict=True,
                ):
                    dem_values = _read_neighborhood(dem, point, radius_pixels=3, np=np)
                    land_values = _read_neighborhood(land, point, radius_pixels=8, np=np)
                    elevation = _safe_mean(dem_values, np)
                    roughness = _safe_percentile_range(dem_values, np)
                    x_metres, y_metres = _pixel_size_metres(dem, point)
                    slope = _slope_from_dem(dem_values, x_metres, y_metres, np)
                    fractions = _worldcover_fractions(land_values, np)

                    if viirs is not None:
                        local = _read_neighborhood(viirs, point, radius_pixels=1, np=np)
                        middle = _read_neighborhood(viirs, point, radius_pixels=8, np=np)
                        far = _read_neighborhood(viirs, point, radius_pixels=24, np=np)
                        radiance = (
                            _safe_mean(local, np),
                            _safe_mean(middle, np),
                            _safe_mean(far, np),
                        )
                        quality = SurfaceDataQuality.CALIBRATED_RASTER
                        uncertainty = 0.12
                    else:
                        built_fraction = fractions["urban"]
                        radiance = (
                            8.0 * built_fraction,
                            4.0 * built_fraction,
                            1.5 * built_fraction,
                        )
                        quality = SurfaceDataQuality.REMOTE_RASTER
                        uncertainty = 0.30

                    output.append(
                        RawSurfaceFeatures(
                            h3_index=identifier,
                            resolution=resolution,
                            latitude_deg=point.latitude_deg,
                            longitude_deg=point.longitude_deg,
                            elevation_m=elevation,
                            slope_deg=slope,
                            roughness_m=roughness,
                            mean_radiance_0_5_km=radiance[0],
                            mean_radiance_5_25_km=radiance[1],
                            mean_radiance_25_80_km=radiance[2],
                            water_fraction=fractions["water"],
                            urban_fraction=fractions["urban"],
                            forest_fraction=fractions["forest"],
                            open_land_fraction=fractions["open"],
                            distance_to_road_km=_road_distance_proxy(fractions),
                            distance_to_settlement_km=_settlement_distance_proxy(
                                fractions
                            ),
                            restricted=False,
                            uncertainty=uncertainty,
                            data_quality=quality,
                            attribution=self.attributions,
                        )
                    )
                return output
            finally:
                if viirs is not None:
                    viirs.close()


def _read_neighborhood(
    dataset: Any,
    point: GeoPoint,
    *,
    radius_pixels: int,
    np: Any,
) -> Any:
    from rasterio.windows import Window
    from rasterio.warp import transform

    longitude = point.longitude_deg
    latitude = point.latitude_deg
    if dataset.crs is not None and str(dataset.crs).upper() not in {
        "EPSG:4326",
        "OGC:CRS84",
    }:
        xs, ys = transform("EPSG:4326", dataset.crs, [longitude], [latitude])
        longitude, latitude = float(xs[0]), float(ys[0])
    row, col = dataset.index(longitude, latitude)
    window = Window(
        col_off=max(0, col - radius_pixels),
        row_off=max(0, row - radius_pixels),
        width=2 * radius_pixels + 1,
        height=2 * radius_pixels + 1,
    )
    values = dataset.read(1, window=window, masked=True).astype("float64")
    return np.asarray(values.filled(np.nan))


def _pixel_size_metres(dataset: Any, point: GeoPoint) -> tuple[float, float]:
    x_resolution = abs(float(dataset.res[0]))
    y_resolution = abs(float(dataset.res[1]))
    if dataset.crs is not None and dataset.crs.is_geographic:
        latitude_radians = math.radians(point.latitude_deg)
        x_resolution *= 111_320.0 * max(0.05, math.cos(latitude_radians))
        y_resolution *= 110_574.0
    return max(0.1, x_resolution), max(0.1, y_resolution)


def _slope_from_dem(values: Any, x_metres: float, y_metres: float, np: Any) -> float:
    if values.shape[0] < 3 or values.shape[1] < 3:
        return 0.0
    gy, gx = np.gradient(values, y_metres, x_metres)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    return float(np.nanmedian(slope)) if np.isfinite(slope).any() else 0.0


def _safe_mean(values: Any, np: Any) -> float:
    return float(np.nanmean(values)) if np.isfinite(values).any() else 0.0


def _safe_percentile_range(values: Any, np: Any) -> float:
    if not np.isfinite(values).any():
        return 0.0
    return float(np.nanpercentile(values, 95) - np.nanpercentile(values, 5))


def _worldcover_fractions(values: Any, np: Any) -> dict[str, float]:
    valid = values[np.isfinite(values)]
    if valid.size == 0:
        return {"water": 0.0, "urban": 0.0, "forest": 0.0, "open": 0.5}
    total = float(valid.size)

    def fraction(classes: list[int]) -> float:
        return float(np.isin(valid, classes).sum()) / total

    return {
        "water": fraction([80, 90, 95]),
        "urban": fraction([50]),
        "forest": fraction([10]),
        "open": fraction([20, 30, 40, 60, 100]),
    }


def _road_distance_proxy(fractions: dict[str, float]) -> float:
    developed = fractions["urban"] + 0.35 * fractions["open"]
    return max(0.2, 5.0 * (1.0 - min(1.0, developed)))


def _settlement_distance_proxy(fractions: dict[str, float]) -> float:
    urban = min(1.0, fractions["urban"])
    return 5.0 + 95.0 * (1.0 - urban)
