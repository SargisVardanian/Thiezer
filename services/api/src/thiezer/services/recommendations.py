from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from thiezer.domain.celestial_objects import CelestialObject, CelestialTargetRef
from thiezer.domain.contracts import (
    AstronomySnapshot,
    CandidatePlace,
    ExplanationItem,
    HourlySkyCondition,
    MoonPhase,
    ObservationWindow,
    RankedPlace,
    RecommendationSearchRequest,
    RecommendationSearchResponse,
    SkyScoreBreakdown,
    TargetKind,
    VerificationStatus,
    WarningCode,
)
from thiezer.domain.ephemeris import AstronomyProvider
from thiezer.domain.geospatial import build_route_handoffs
from thiezer.domain.quality import build_score_inputs
from thiezer.domain.scoring import calculate_sky_score
from thiezer.providers.weather.base import WeatherProvider, weather_point_key
from thiezer.repositories.base import PlaceRepository
from thiezer.services.celestial_resolution import CelestialResolutionService
from thiezer.services.celestial_visibility import CelestialVisibilityService
from thiezer.services.progress import ProgressCallback, report_progress


@dataclass(frozen=True, slots=True)
class _EvaluatedSample:
    conditions: HourlySkyCondition
    astronomy: AstronomySnapshot
    score: SkyScoreBreakdown


class RecommendationService:
    def __init__(
        self,
        *,
        place_repository: PlaceRepository,
        weather_provider: WeatherProvider,
        astronomy_provider: AstronomyProvider,
        celestial_resolution: CelestialResolutionService | None = None,
        celestial_visibility: CelestialVisibilityService | None = None,
    ) -> None:
        self._places = place_repository
        self._weather = weather_provider
        self._astronomy = astronomy_provider
        self._celestial_resolution = celestial_resolution
        self._celestial_visibility = celestial_visibility

    async def search(
        self,
        request: RecommendationSearchRequest,
        progress: ProgressCallback | None = None,
    ) -> RecommendationSearchResponse:
        await report_progress(progress, "resolving_target")
        scoring_target = _scoring_target(request.target)
        catalog_target = await self._resolve_catalog_target(request)
        batch = await self._places.search(
            user_location=request.user_location,
            scope=request.scope,
            country_code=request.country_code,
            max_distance_km=request.max_distance_km,
            limit=request.max_candidates,
            include_unverified=request.include_unverified,
            progress=progress,
        )
        candidates = batch.matches
        generated_at = datetime.now(UTC)
        if not candidates:
            warnings = [*batch.warnings, WarningCode.NO_CANDIDATE_PLACES]
            return RecommendationSearchResponse(
                generated_at_utc=generated_at,
                target=request.target,
                scope=request.scope,
                search_radius_km=request.max_distance_km,
                coverage_country_codes=batch.coverage_country_codes,
                discovery_sources=batch.discovery_sources,
                results=[],
                warnings=list(dict.fromkeys(warnings)),
                provider_attributions=batch.attributions,
            )

        await report_progress(progress, "fetching_weather")
        forecast_by_point = await self._weather.get_hourly_forecasts(
            points=[place.point for place, _ in candidates],
            start_utc=request.start_utc,
            end_utc=request.end_utc,
        )
        ranked: list[RankedPlace] = []
        attributions: set[str] = set(batch.attributions)
        places_with_weather = 0

        await report_progress(progress, "calculating_astronomy")
        for place, distance_km in candidates:
            conditions = forecast_by_point.get(weather_point_key(place.point), [])
            if not conditions:
                continue
            places_with_weather += 1
            attributions.update(item.attribution for item in conditions)
            samples = await self._evaluate_place(
                request=request,
                scoring_target=scoring_target,
                catalog_target=catalog_target,
                place=place,
                distance_km=distance_km,
                conditions=conditions,
                generated_at_utc=generated_at,
            )
            window = _best_window(samples, minimum_score=request.minimum_score)
            if window is None:
                continue
            warnings = list(window.score_breakdown.warnings)
            if place.verification_status in {
                VerificationStatus.UNVERIFIED_SEED,
                VerificationStatus.UNVERIFIED_DISCOVERED,
            }:
                warnings.append(WarningCode.UNVERIFIED_PLACE)
            if place.darkness_model != "viirs_raster":
                warnings.append(WarningCode.DARKNESS_IS_PROXY)
            ranked.append(
                RankedPlace(
                    rank=1,
                    place=place,
                    distance_km=distance_km,
                    observation_window=window,
                    utility=window.score_breakdown.utility,
                    explanations=_explain(place.name, distance_km, window.score_breakdown),
                    warnings=list(dict.fromkeys(warnings)),
                    routes=build_route_handoffs(
                        origin=request.user_location,
                        destination=place.point,
                        label=place.name,
                    ),
                )
            )

        await report_progress(progress, "ranking")
        ranked.sort(
            key=lambda result: (
                -result.utility,
                -result.observation_window.best_score,
                result.distance_km,
                result.place.id,
            )
        )
        results = [
            result.model_copy(update={"rank": index}) for index, result in enumerate(ranked, 1)
        ][: request.max_results]

        response_warnings = list(batch.warnings)
        if not results:
            if places_with_weather == 0:
                response_warnings.append(WarningCode.WEATHER_UNAVAILABLE)
            elif scoring_target == TargetKind.ALPHA_CENTAURI:
                response_warnings.append(WarningCode.TARGET_NOT_VISIBLE_IN_SCOPE)
            else:
                response_warnings.append(WarningCode.NO_OBSERVATION_WINDOW)

        return RecommendationSearchResponse(
            generated_at_utc=generated_at,
            target=request.target,
            scope=request.scope,
            search_radius_km=request.max_distance_km,
            coverage_country_codes=batch.coverage_country_codes,
            discovery_sources=batch.discovery_sources,
            results=results,
            warnings=list(dict.fromkeys(response_warnings)),
            provider_attributions=sorted(attributions),
        )

    async def _evaluate_place(
        self,
        *,
        request: RecommendationSearchRequest,
        scoring_target: TargetKind,
        catalog_target: CelestialObject | None,
        place: CandidatePlace,
        distance_km: float,
        conditions: list[HourlySkyCondition],
        generated_at_utc: datetime,
    ) -> list[_EvaluatedSample]:
        evaluated: list[_EvaluatedSample] = []
        for item in conditions:
            if catalog_target is None:
                astronomy = self._astronomy.snapshot(
                    target=scoring_target,
                    point=place.point,
                    timestamp_utc=item.timestamp_utc,
                )
            else:
                assert self._celestial_visibility is not None
                astronomy = await self._celestial_visibility.snapshot(
                    target=catalog_target,
                    point=place.point,
                    timestamp_utc=item.timestamp_utc,
                    scoring_target=scoring_target,
                )
            if request.preferences.moon_phase != MoonPhase.ANY and (
                astronomy.moon_phase != request.preferences.moon_phase
            ):
                continue
            inputs = build_score_inputs(
                target=scoring_target,
                mode=request.observation_mode,
                place=place,
                conditions=item,
                astronomy=astronomy,
                search_started_utc=generated_at_utc,
                distance_km=distance_km,
                maximum_distance_km=request.max_distance_km,
                preferences=request.preferences,
            )
            score = calculate_sky_score(
                target=scoring_target,
                mode=request.observation_mode,
                inputs=inputs,
            )
            evaluated.append(_EvaluatedSample(item, astronomy, score))
        return evaluated

    async def _resolve_catalog_target(
        self, request: RecommendationSearchRequest
    ) -> CelestialObject | None:
        target = request.catalog_target
        if target is None:
            return None
        if self._celestial_resolution is None or self._celestial_visibility is None:
            raise ValueError("catalog target recommendations are not configured")
        return await self._celestial_resolution.resolve(target)


def _best_window(
    samples: list[_EvaluatedSample],
    *,
    minimum_score: float,
) -> ObservationWindow | None:
    eligible = [
        sample for sample in samples if sample.score.valid and sample.score.score >= minimum_score
    ]
    if not eligible:
        return None
    eligible.sort(key=lambda sample: sample.conditions.timestamp_utc)

    groups: list[list[_EvaluatedSample]] = []
    current: list[_EvaluatedSample] = []
    for sample in eligible:
        if current and (
            sample.conditions.timestamp_utc - current[-1].conditions.timestamp_utc
        ) > timedelta(minutes=90):
            groups.append(current)
            current = []
        current.append(sample)
    if current:
        groups.append(current)

    def group_value(group: list[_EvaluatedSample]) -> tuple[float, float, int]:
        mean_score = sum(sample.score.score for sample in group) / len(group)
        best_score = max(sample.score.score for sample in group)
        return (mean_score, best_score, len(group))

    best_group = max(groups, key=group_value)
    best_sample = max(
        best_group,
        key=lambda sample: (sample.score.utility, sample.score.score),
    )
    mean_score = sum(sample.score.score for sample in best_group) / len(best_group)
    return ObservationWindow(
        start_utc=best_group[0].conditions.timestamp_utc,
        end_utc=best_group[-1].conditions.timestamp_utc,
        best_time_utc=best_sample.conditions.timestamp_utc,
        best_score=best_sample.score.score,
        mean_score=mean_score,
        best_astronomy=best_sample.astronomy,
        best_conditions=best_sample.conditions,
        score_breakdown=best_sample.score,
    )


def _explain(
    place_name: str,
    distance_km: float,
    score: SkyScoreBreakdown,
) -> list[ExplanationItem]:
    strongest = sorted(score.components, key=lambda component: component.value, reverse=True)[:3]
    weakest = min(score.components, key=lambda component: component.value)
    explanations = [
        ExplanationItem(
            code="distance",
            message=f"{place_name} is approximately {distance_km:.1f} km away in a straight line.",
            impact="neutral",
        ),
        *[
            ExplanationItem(
                code=f"component_{component.name}",
                message=f"{component.name.replace('_', ' ')} score is {component.value * 100:.0f}%.",
                impact="positive",
            )
            for component in strongest
        ],
    ]
    if weakest.value < 0.5:
        explanations.append(
            ExplanationItem(
                code=f"limiting_{weakest.name}",
                message=f"The main limiting factor is {weakest.name.replace('_', ' ')}.",
                impact="negative",
            )
        )
    return explanations


def _scoring_target(target: TargetKind | CelestialTargetRef) -> TargetKind:
    """Choose a conservative existing surface-scoring profile for catalog objects.

    This only selects weather/darkness weights; visibility is resolved independently by
    the celestial endpoint and never changes the catalog object's identity.
    """
    if isinstance(target, TargetKind):
        return target
    if target.preset is not None:
        return TargetKind(target.preset)
    # The current scoring model has two non-Solar profiles. A catalog object is never
    # rewritten into a Solar-System identity: this internal profile is deliberately not
    # exposed as the requested target.
    return TargetKind.MILKY_WAY
