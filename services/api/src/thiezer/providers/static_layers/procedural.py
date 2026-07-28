from __future__ import annotations

import math

import h3

from thiezer.domain.contracts import GeoPoint
from thiezer.domain.search_cells import cell_center
from thiezer.domain.static_scoring import RawSurfaceFeatures
from thiezer.domain.surface import SurfaceDataQuality


class ProceduralSurfaceLayerProvider:
    """Deterministic zero-key fallback and oracle fixture.

    It scans the surface correctly but its feature values are proxies. Production should configure
    COG layers. The provider is useful for CI, disconnected development and algorithm validation.
    """

    source_name = "procedural_surface_v1"
    attributions: tuple[str, ...] = (
        "Procedural development surface model; not calibrated geodata",
    )
    darkness_is_proxy = True

    async def evaluate_cells(self, cell_ids: list[str]) -> list[RawSurfaceFeatures]:
        return [self._evaluate(cell_id, cell_center(cell_id)) for cell_id in cell_ids]

    async def evaluate_points(
        self,
        *,
        points: list[GeoPoint],
        resolution: int,
    ) -> list[RawSurfaceFeatures]:
        return [
            self._evaluate(f"point:{index}", point, resolution)
            for index, point in enumerate(points)
        ]

    async def aclose(self) -> None:
        return None

    def _evaluate(
        self,
        cell_id: str,
        point: GeoPoint,
        resolution: int | None = None,
    ) -> RawSurfaceFeatures:
        resolved = resolution if resolution is not None else int(h3.get_resolution(cell_id))
        latitude = point.latitude_deg
        longitude = point.longitude_deg

        city_pressure = sum(
            weight
            * math.exp(-((_distance_deg(latitude, longitude, city_lat, city_lon) / radius) ** 2))
            for city_lat, city_lon, weight, radius in (
                (40.1772, 44.5035, 20.0, 0.55),
                (40.7894, 43.8475, 8.0, 0.42),
                (40.8128, 44.4883, 6.0, 0.34),
                (39.2075, 46.4058, 4.0, 0.30),
                (40.5500, 44.9500, 3.0, 0.35),
            )
        )
        elevation = self._elevation(latitude, longitude)
        delta = 0.01
        e_x1 = self._elevation(latitude, longitude - delta)
        e_x2 = self._elevation(latitude, longitude + delta)
        e_y1 = self._elevation(latitude - delta, longitude)
        e_y2 = self._elevation(latitude + delta, longitude)
        gradient = math.hypot(e_x2 - e_x1, e_y2 - e_y1) / 2.2
        slope = min(35.0, math.degrees(math.atan(gradient / 1000.0)))
        roughness = min(250.0, 6.0 + gradient * 0.18)

        sevan = ((_distance_deg(latitude, longitude, 40.35, 45.28) / 0.48) ** 2) < 1.0
        water = 0.92 if sevan else 0.01
        urban = min(0.95, city_pressure / 18.0)
        forest = _bounded(0.15 + 0.25 * math.sin(math.radians(longitude * 9.0)) - 0.10 * urban)
        open_land = _bounded(0.82 - 0.65 * forest - 0.55 * urban - 0.85 * water)
        road_distance = 0.2 + 5.0 * abs(math.sin(math.radians(latitude * 19.0 + longitude * 13.0)))
        settlement_distance = min(180.0, 5.0 + 100.0 * math.exp(-city_pressure / 4.0))
        uncertainty = 0.34 if resolved >= 7 else 0.45

        return RawSurfaceFeatures(
            h3_index=cell_id,
            resolution=resolved,
            latitude_deg=latitude,
            longitude_deg=longitude,
            elevation_m=elevation,
            slope_deg=slope,
            roughness_m=roughness,
            mean_radiance_0_5_km=city_pressure,
            mean_radiance_5_25_km=0.55 * city_pressure,
            mean_radiance_25_80_km=0.22 * city_pressure,
            water_fraction=water,
            urban_fraction=urban,
            forest_fraction=forest,
            open_land_fraction=open_land,
            distance_to_road_km=road_distance,
            distance_to_settlement_km=settlement_distance,
            restricted=False,
            uncertainty=uncertainty,
            data_quality=SurfaceDataQuality.PROCEDURAL_FALLBACK,
            attribution=self.attributions,
        )

    @staticmethod
    def _elevation(latitude: float, longitude: float) -> float:
        mountain = 3200.0 * math.exp(
            -((_distance_deg(latitude, longitude, 40.53, 44.19) / 0.42) ** 2)
        )
        geghama = 2400.0 * math.exp(
            -((_distance_deg(latitude, longitude, 40.25, 45.05) / 0.55) ** 2)
        )
        syunik = 2100.0 * math.exp(
            -((_distance_deg(latitude, longitude, 39.25, 46.25) / 0.50) ** 2)
        )
        return max(0.0, 500.0 + mountain + geghama + syunik)


def _distance_deg(
    latitude: float,
    longitude: float,
    other_latitude: float,
    other_longitude: float,
) -> float:
    return math.hypot(
        latitude - other_latitude,
        (longitude - other_longitude) * math.cos(math.radians(latitude)),
    )


def _bounded(value: float) -> float:
    return min(1.0, max(0.0, value))
