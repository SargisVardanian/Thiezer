from __future__ import annotations

import math
from urllib.parse import quote, urlencode

from thiezer.domain.contracts import GeoPoint, RouteHandoff

_EARTH_RADIUS_KM = 6371.0088


def haversine_distance_km(origin: GeoPoint, destination: GeoPoint) -> float:
    lat1 = math.radians(origin.latitude_deg)
    lat2 = math.radians(destination.latitude_deg)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(destination.longitude_deg - origin.longitude_deg)
    haversine = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2.0) ** 2
    )
    return 2.0 * _EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(haversine)))


def build_route_handoffs(
    *,
    origin: GeoPoint,
    destination: GeoPoint,
    label: str,
) -> list[RouteHandoff]:
    origin_text = _coordinates(origin)
    destination_text = _coordinates(destination)
    google_query = urlencode(
        {
            "api": "1",
            "origin": origin_text,
            "destination": destination_text,
            "travelmode": "driving",
            "dir_action": "navigate",
        }
    )
    apple_query = urlencode(
        {
            "saddr": origin_text,
            "daddr": destination_text,
            "dirflg": "d",
        }
    )
    # Yandex's documented app URL schemes require an issued access key. The web route URL is
    # included as a best-effort browser handoff and can later be replaced by a registered app key.
    yandex_destination = quote(destination_text, safe=",")
    yandex_origin = quote(origin_text, safe=",")
    local_label = quote(label)

    return [
        RouteHandoff(
            provider="google_maps",
            url=f"https://www.google.com/maps/dir/?{google_query}",
            note="Universal Maps URL; no Google API key required.",
        ),
        RouteHandoff(
            provider="apple_maps",
            url=f"https://maps.apple.com/?{apple_query}",
            note="Opens Apple Maps on supported Apple devices.",
        ),
        RouteHandoff(
            provider="yandex_maps_web",
            url=(
                "https://yandex.com/maps/?"
                f"rtext={yandex_origin}~{yandex_destination}&rtt=auto"
            ),
            note=(
                "Best-effort web handoff. Native Yandex Navigator integration requires "
                "a Yandex access key."
            ),
        ),
        RouteHandoff(
            provider="geo_uri",
            url=f"geo:{destination_text}?q={destination_text}({local_label})",
            note="Local device map intent where the geo URI scheme is supported.",
        ),
    ]


def _coordinates(point: GeoPoint) -> str:
    return f"{point.latitude_deg:.6f},{point.longitude_deg:.6f}"
