from __future__ import annotations

from thiezer.domain.search_cells import cell_sample_points
from thiezer.domain.static_scoring import passes_static_filters, score_raw_features
from thiezer.domain.surface import SurfaceCell, SurfaceSite
from thiezer.providers.static_layers.base import StaticLayerProvider


class ProceduralAccessPointProvider:
    source_name = "surface_sampling"
    attribution = "H3 in-cell surface sampling"
    large_radius_calls = 0

    def __init__(self, static_layers: StaticLayerProvider) -> None:
        self._static = static_layers

    async def materialize_sites(
        self,
        *,
        cells: list[SurfaceCell],
        maximum_sites: int,
    ) -> list[SurfaceSite]:
        sites: list[SurfaceSite] = []
        for cell in cells:
            samples = cell_sample_points(cell.h3_index)
            raw = await self._static.evaluate_points(
                points=samples,
                resolution=cell.resolution,
            )
            scored = [score_raw_features(item) for item in raw]
            valid = [item for item in scored if passes_static_filters(item, _point_policy())]
            if not valid:
                continue
            best = max(valid, key=lambda item: item.static_score)
            accessibility = best.access_potential
            sites.append(
                SurfaceSite(
                    id=f"surface:{cell.h3_index}",
                    name=f"Surface candidate {cell.h3_index[-7:]}",
                    point=best.center,
                    cell=best,
                    elevation_m=best.elevation_m,
                    slope_deg=best.slope_deg,
                    horizon_openness_score=max(
                        0.15,
                        1.0 - best.roughness_m / 180.0,
                    ),
                    accessibility_score=accessibility,
                    risk_score=min(
                        1.0,
                        0.20 + 0.35 * best.uncertainty + 0.20 * (1.0 - accessibility),
                    ),
                    road_access=(
                        "Surface-selected point; legal and road access require verification"
                    ),
                    source_url=None,
                    source_provider=self.source_name,
                )
            )
            if len(sites) >= maximum_sites:
                break
        return sites

    async def aclose(self) -> None:
        return None


def _point_policy():
    from thiezer.domain.static_scoring import StaticFilterPolicy

    return StaticFilterPolicy(
        minimum_land_fraction=0.70,
        maximum_urban_fraction=0.25,
        maximum_slope_deg=12.0,
        minimum_access_potential=0.04,
        maximum_uncertainty=0.98,
    )
