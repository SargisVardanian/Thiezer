from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from thiezer.domain.contracts import (
    AstronomySnapshot,
    CandidatePlace,
    ExplanationItem,
    HourlySkyCondition,
    ObservationWindow,
    RankedPlace,
    RecommendationSearchRequest,
    RecommendationSearchResponse,
    SkyScoreBreakdown,
    VerificationStatus,
    WarningCode,
)
from thiezer.domain.ephemeris import AstronomyProvider
from thiezer.domain.geospatial import build_route_handoffs
from thiezer.domain.quality import build_score_inputs
from thiezer.domain.scoring import calculate_sky_score
from thiezer.domain.travel import calculate_travel_utility
from thiezer.providers.weather.base import WeatherProvider, weather_point_key
from thiezer.repositories.base import PlaceRepository


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
    ) -> None:
        self._places = place_repository
        self._weather = weather_provider
        self._astronomy = astronomy_provider

    async def search(
        self,
        request: RecommendationSearchRequest,
    ) -> RecommendationSearchResponse:
        place_batch = await self._places.search(
            user_location=request.user_location,
            scope=request.scope,
            country_code=request.country_code,
            max_distance_km=request.max_distance_km,
            limit=request.max_candidates,
            include_unverified=request.include_unverified,
        )
        generated_at = datetime.now(UTC)
        if not place_batch.matches:
            return RecommendationSearchResponse(
                generated_at_utc=generated_at,
                target=request.target,
                scope=request.scope,
                search_radius_km=request.max_distance_km,
                coverage_country_codes=place_batch.coverage_country_codes,
                discovery_sources=place_batch.discovery_sources,
                results=[],
                warnings=list(
                    dict.fromkeys([*place_batch.warnings, WarningCode.NO_CANDIDATE_PLACES])
                ),
                provider_attributions=place_batch.attributions,
                metrics=place_batch.metrics,
            )

        points = [place.point for place, _ in place_batch.matches]
        elevations = {
            weather_point_key(place.point): place.elevation_m
            for place, _ in place_batch.matches
        }
        forecast_by_point = await self._weather.get_hourly_forecasts(
            points=points,
            start_utc=request.start_utc,
            end_utc=request.end_utc,
            elevations_m=elevations,
        )
        ranked: list[RankedPlace] = []
        attributions: set[str] = set(place_batch.attributions)
        places_with_weather = 0
        any_geometry_visible = False

        for place, distance_km in place_batch.matches:
            conditions = forecast_by_point.get(weather_point_key(place.point), [])
            if not conditions:
                continue
            places_with_weather += 1
            attributions.update(item.attribution for item in conditions)
            samples, geometry_visible = self._evaluate_place(
                request=request,
                place=place,
                conditions=conditions,
                generated_at_utc=generated_at,
            )
            any_geometry_visible = any_geometry_visible or geometry_visible
            window = _best_window(samples, minimum_score=request.minimum_score)
            if window is None:
                continue
            confidence = _component_value(window.score_breakdown, "confidence")
            travel = calculate_travel_utility(
                sky_quality=window.best_score,
                distance_km=distance_km,
                maximum_distance_km=request.max_distance_km,
                place=place,
                forecast_confidence=confidence,
            )
            warnings = list(window.score_breakdown.warnings)
            if place.verification_status in {
                VerificationStatus.UNVERIFIED_SEED,
                VerificationStatus.UNVERIFIED_DISCOVERED,
            }:
                warnings.append(WarningCode.UNVERIFIED_PLACE)
            ranked.append(
                RankedPlace(
                    rank=1,
                    place=place,
                    distance_km=distance_km,
                    observation_window=window,
                    utility=travel.total,
                    travel_utility=travel,
                    explanations=_explain(place.name, distance_km, window.score_breakdown),
                    warnings=list(dict.fromkeys(warnings)),
                    routes=build_route_handoffs(
                        origin=request.user_location,
                        destination=place.point,
                        label=place.name,
                    ),
                )
            )

        ranked.sort(
            key=lambda result: (
                -result.travel_utility.total,
                -result.observation_window.best_score,
                result.distance_km,
                result.place.id,
            )
        )
        results = [
            result.model_copy(update={"rank": index})
            for index, result in enumerate(ranked, 1)
        ][: request.max_results]

        response_warnings = list(place_batch.warnings)
        if not results:
            if places_with_weather == 0:
                response_warnings.append(WarningCode.WEATHER_UNAVAILABLE)
            elif not any_geometry_visible:
                response_warnings.append(WarningCode.TARGET_NOT_VISIBLE_IN_SCOPE)
            else:
                response_warnings.append(WarningCode.NO_OBSERVATION_WINDOW)

        metrics = place_batch.metrics.model_copy(
            update={
                "weather_points_requested": len(points),
                "weather_batches": self._weather.last_batch_count,
            }
        )
        return RecommendationSearchResponse(
            generated_at_utc=generated_at,
            target=request.target,
            scope=request.scope,
            search_radius_km=request.max_distance_km,
            coverage_country_codes=place_batch.coverage_country_codes,
            discovery_sources=place_batch.discovery_sources,
            results=results,
            warnings=list(dict.fromkeys(response_warnings)),
            provider_attributions=sorted(attributions),
            metrics=metrics,
        )

    def _evaluate_place(
        self,
        *,
        request: RecommendationSearchRequest,
        place: CandidatePlace,
        conditions: list[HourlySkyCondition],
        generated_at_utc: datetime,
    ) -> tuple[list[_EvaluatedSample], bool]:
        evaluated: list[_EvaluatedSample] = []
        geometry_visible = request.target.value == "best_night_sky"
        for item in conditions:
            astronomy = self._astronomy.snapshot(
                target=request.target,
                point=place.point,
                timestamp_utc=item.timestamp_utc,
            )
            geometry_visible = geometry_visible or astronomy.above_geometric_horizon
            inputs = build_score_inputs(
                target=request.target,
                mode=request.observation_mode,
                place=place,
                conditions=item,
                astronomy=astronomy,
                search_started_utc=generated_at_utc,
                distance_km=0.0,
                maximum_distance_km=1.0,
            )
            score = calculate_sky_score(
                target=request.target,
                mode=request.observation_mode,
                inputs=inputs,
            )
            evaluated.append(_EvaluatedSample(item, astronomy, score))
        return evaluated, geometry_visible


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
    best_sample = max(best_group, key=lambda sample: sample.score.score)
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


def _component_value(score: SkyScoreBreakdown, name: str) -> float:
    for component in score.components:
        if component.name == name:
            return component.value
    return 0.5


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
                message=(
                    f"{component.name.replace('_', ' ')} score is {component.value * 100:.0f}%."
                ),
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
