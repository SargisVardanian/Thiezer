from __future__ import annotations

from datetime import UTC, datetime, timedelta

from thiezer.domain.contracts import (
    AstronomySnapshot,
    CandidatePlace,
    GeoPoint,
    HourlySkyCondition,
    PlaceKind,
    TargetKind,
    VerificationStatus,
)
from thiezer.providers.weather.base import WeatherPointKey, weather_point_key


class FakeAstronomyProvider:
    def snapshot(
        self,
        *,
        target: TargetKind,
        point: GeoPoint,
        timestamp_utc: datetime,
    ) -> AstronomySnapshot:
        altitude = -12.0 if target == TargetKind.ALPHA_CENTAURI else 48.0
        if target == TargetKind.BEST_NIGHT_SKY:
            altitude = 90.0
        return AstronomySnapshot(
            timestamp_utc=timestamp_utc,
            target=target,
            target_label=target.value,
            altitude_deg=altitude,
            azimuth_deg=180.0,
            sun_altitude_deg=-24.0,
            moon_altitude_deg=-5.0,
            moon_illumination_fraction=0.1,
            moon_separation_deg=130.0,
            airmass=None if altitude <= 0.0 else 1.3,
            above_geometric_horizon=altitude > 0.0,
        )


class FakeWeatherProvider:
    def __init__(self, *, cloud_by_longitude: dict[float, float] | None = None) -> None:
        self.cloud_by_longitude = cloud_by_longitude or {}
        self.batch_calls = 0

    async def get_hourly_forecast(
        self,
        *,
        point: GeoPoint,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[HourlySkyCondition]:
        result = await self.get_hourly_forecasts(
            points=[point],
            start_utc=start_utc,
            end_utc=end_utc,
        )
        return result[weather_point_key(point)]

    async def get_hourly_forecasts(
        self,
        *,
        points: list[GeoPoint],
        start_utc: datetime,
        end_utc: datetime,
    ) -> dict[WeatherPointKey, list[HourlySkyCondition]]:
        self.batch_calls += 1
        result: dict[WeatherPointKey, list[HourlySkyCondition]] = {}
        for point in points:
            cloud = self.cloud_by_longitude.get(round(point.longitude_deg, 3), 0.05)
            result[weather_point_key(point)] = [
                make_condition(
                    point=point,
                    timestamp_utc=start_utc + timedelta(hours=offset),
                    cloud=cloud,
                )
                for offset in range(4)
                if start_utc + timedelta(hours=offset) <= end_utc
            ]
        return result

    async def aclose(self) -> None:
        return None


def make_place(
    *,
    place_id: str,
    name: str,
    latitude_deg: float,
    longitude_deg: float,
    darkness: float,
    elevation_m: float = 1500.0,
) -> CandidatePlace:
    return CandidatePlace(
        id=place_id,
        name=name,
        country_code="AM",
        region="Test",
        point=GeoPoint(latitude_deg=latitude_deg, longitude_deg=longitude_deg),
        elevation_m=elevation_m,
        kind=PlaceKind.OBSERVATION_SITE,
        verification_status=VerificationStatus.UNVERIFIED_SEED,
        darkness_score=darkness,
        horizon_openness_score=0.9,
        accessibility_score=0.9,
        risk_score=0.1,
        road_access="test road",
        notes="Synthetic test fixture",
    )


def make_condition(
    *,
    point: GeoPoint,
    timestamp_utc: datetime,
    cloud: float = 0.05,
) -> HourlySkyCondition:
    return HourlySkyCondition(
        timestamp_utc=timestamp_utc.astimezone(UTC),
        total_cloud_fraction=cloud,
        low_cloud_fraction=cloud * 0.4,
        mid_cloud_fraction=cloud * 0.3,
        high_cloud_fraction=cloud * 0.3,
        temperature_c=12.0,
        relative_humidity_fraction=0.4,
        dew_point_c=1.0,
        precipitation_mm=0.0,
        visibility_m=40_000.0,
        wind_speed_mps=2.0,
        wind_gust_mps=3.0,
        pressure_hpa=850.0,
        provider="fake",
        model_name="deterministic",
        requested_point=point,
        returned_grid_point=point,
        attribution="Synthetic test weather",
    )
