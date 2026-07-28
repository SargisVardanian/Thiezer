from __future__ import annotations

from datetime import datetime

from thiezer.domain.contracts import GeoPoint, TargetKind, TargetVisibilityResponse
from thiezer.domain.ephemeris import AstronomyProvider
from thiezer.domain.quality import minimum_target_altitude_deg, sun_is_dark_enough


class VisibilityService:
    def __init__(self, astronomy_provider: AstronomyProvider) -> None:
        self._astronomy = astronomy_provider

    def get(
        self,
        *,
        point: GeoPoint,
        target: TargetKind,
        timestamp_utc: datetime,
    ) -> TargetVisibilityResponse:
        snapshot = self._astronomy.snapshot(
            target=target,
            point=point,
            timestamp_utc=timestamp_utc,
        )
        minimum_altitude = minimum_target_altitude_deg(target)
        altitude_ok = (
            target == TargetKind.BEST_NIGHT_SKY
            or snapshot.altitude_deg >= minimum_altitude
        )
        darkness_ok = sun_is_dark_enough(target, snapshot.sun_altitude_deg)
        visible = altitude_ok and darkness_ok
        if not altitude_ok:
            reason = (
                f"Target altitude is {snapshot.altitude_deg:.1f}°, below the operational "
                f"minimum of {minimum_altitude:.1f}°."
            )
        elif not darkness_ok:
            reason = f"The Sun is still too high at {snapshot.sun_altitude_deg:.1f}°."
        else:
            reason = "Target geometry and solar darkness satisfy the operational visibility gates."
        return TargetVisibilityResponse(
            point=point,
            snapshot=snapshot,
            visible=visible,
            reason=reason,
        )
