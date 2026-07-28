from thiezer.domain.contracts import GeoPoint, SearchScope, StoreKind, VerificationStatus
from thiezer.repositories.seed import SeedPlaceRepository, SeedStoreRepository


def test_packaged_armenia_places_are_explicitly_unverified() -> None:
    repository = SeedPlaceRepository()
    results = repository.search(
        user_location=GeoPoint(latitude_deg=40.1772, longitude_deg=44.5035),
        scope=SearchScope.COUNTRY,
        country_code="AM",
        max_distance_km=500.0,
        limit=20,
    )
    assert len(results) >= 8
    assert all(place.country_code == "AM" for place, _ in results)
    assert all(
        place.verification_status == VerificationStatus.UNVERIFIED_SEED for place, _ in results
    )


def test_store_repository_returns_physical_before_online() -> None:
    repository = SeedStoreRepository()
    results = repository.search(
        user_location=GeoPoint(latitude_deg=40.1772, longitude_deg=44.5035),
        scope=SearchScope.COUNTRY,
        country_code="AM",
        max_distance_km=300.0,
        limit=10,
    )
    assert results
    assert results[0][0].kind in {StoreKind.PHYSICAL, StoreKind.HYBRID}
    assert results[0][1] is not None
    assert any(store.kind == StoreKind.ONLINE for store, _ in results)
