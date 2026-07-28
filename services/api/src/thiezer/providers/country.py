from __future__ import annotations

from typing import Any

from thiezer.domain.contracts import GeoPoint


class CountryResolver:
    """Offline nearest-settlement country resolver.

    This is adequate for optional strict-country filtering away from borders. The default adaptive
    search does not depend on country boundaries. Results near borders carry an explicit warning.
    """

    source_name = "reverse_geocoder_nearest_settlement"

    def resolve(self, points: list[GeoPoint]) -> list[str | None]:
        if not points:
            return []
        try:
            import reverse_geocoder as rg

            rows: Any = rg.search(
                [(point.latitude_deg, point.longitude_deg) for point in points],
                mode=1,
                verbose=False,
            )
        except (ImportError, OSError, ValueError):
            return [None] * len(points)
        if not isinstance(rows, list) or len(rows) != len(points):
            return [None] * len(points)
        result: list[str | None] = []
        for row in rows:
            code = row.get("cc") if isinstance(row, dict) else None
            result.append(str(code).upper() if code else None)
        return result
