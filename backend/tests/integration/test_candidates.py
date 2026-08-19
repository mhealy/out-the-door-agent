from fastapi.testclient import TestClient

from app.main import app


def test_search_returns_interpretation_and_only_qualified_candidates() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/candidates/search",
            json={
                "goal": "Find a new 2025 or 2026 Hyundai Tucson Hybrid Limited within "
                "40 miles of Houston under $40,000. I prefer blue and require AWD."
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["interpretation"]["criteria"]["max_distance_miles"] == 40
    assert payload["interpretation"]["criteria"]["hard_constraints"]
    assert 1 <= len(payload["candidates"]) <= 5
    assert all(item["distance_miles"] <= 40 for item in payload["candidates"])
    assert all(float(item["advertised_price"]) <= 40000 for item in payload["candidates"])


def test_search_returns_empty_without_relaxing_constraints() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/candidates/search",
            json={"goal": "Find a new Hyundai Tucson Hybrid under $1,000 near Houston."},
        )

    assert response.status_code == 200
    assert response.json()["candidates"] == []
