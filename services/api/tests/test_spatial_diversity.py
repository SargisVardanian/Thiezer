from dataclasses import dataclass

from thiezer.domain.contracts import GeoPoint
from thiezer.domain.spatial_diversity import spatial_nms


@dataclass(frozen=True)
class Item:
    point: GeoPoint
    score: float


def test_spatial_nms_removes_near_duplicates() -> None:
    items = [
        Item(GeoPoint(latitude_deg=40.0, longitude_deg=44.0), 0.9),
        Item(GeoPoint(latitude_deg=40.001, longitude_deg=44.001), 0.8),
        Item(GeoPoint(latitude_deg=40.3, longitude_deg=44.3), 0.7),
    ]
    selected = spatial_nms(
        items,
        point=lambda item: item.point,
        score=lambda item: item.score,
        min_separation_km=5.0,
        limit=10,
    )
    assert len(selected) == 2
    assert selected[0].score == 0.9
