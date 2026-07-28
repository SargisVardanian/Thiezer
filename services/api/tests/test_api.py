from fastapi.testclient import TestClient

from thiezer.main import app


def test_live_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_score_preview() -> None:
    payload = {
        "target": "milky_way",
        "mode": "naked_eye",
        "cloud_clearance": 0.9,
        "darkness": 0.9,
        "transparency": 0.8,
        "moon_conditions": 0.9,
        "dew_margin": 0.8,
        "wind": 0.8,
        "target_altitude": 0.8,
        "accessibility": 0.9,
        "confidence": 0.8,
    }
    with TestClient(app) as client:
        response = client.post("/v1/scoring/preview", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert 0.0 < body["score"] <= 1.0
    assert body["scoring_version"] == "v1"
