from __future__ import annotations

from fastapi import Request

from thiezer.api.resources import AppResources
from thiezer.services.recommendations import RecommendationService
from thiezer.services.stores import StoreSearchService
from thiezer.services.visibility import VisibilityService


def get_resources(request: Request) -> AppResources:
    resources = getattr(request.app.state, "resources", None)
    if not isinstance(resources, AppResources):
        raise RuntimeError("application resources are not initialized")
    return resources


def get_recommendation_service(request: Request) -> RecommendationService:
    return get_resources(request).recommendation_service


def get_store_service(request: Request) -> StoreSearchService:
    return get_resources(request).store_service


def get_visibility_service(request: Request) -> VisibilityService:
    return get_resources(request).visibility_service
