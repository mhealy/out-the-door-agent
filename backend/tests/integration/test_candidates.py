from fastapi.testclient import TestClient

from app.dependencies import get_criteria_interpreter, get_inventory_provider
from app.domain.criteria import CriteriaExtractionResult, VehicleSearchCriteria
from app.main import app


def test_search_uses_configured_provider_dependencies() -> None:
    class StubInterpreter:
        async def interpret(self, goal: str) -> CriteriaExtractionResult:
            assert goal == "provider boundary"
            return CriteriaExtractionResult(
                criteria=VehicleSearchCriteria(
                    make="Toyota",
                    model="RAV4",
                    condition="either",
                    home_location="Dallas, TX",
                    max_distance_miles=25,
                )
            )

    class StubInventoryProvider:
        async def search(self, criteria: VehicleSearchCriteria) -> list[object]:
            assert criteria.make == "Toyota"
            return []

    app.dependency_overrides[get_criteria_interpreter] = StubInterpreter
    app.dependency_overrides[get_inventory_provider] = StubInventoryProvider
    try:
        with TestClient(app) as client:
            response = client.post(
                "/candidates/search", json={"goal": "provider boundary"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["interpretation"]["criteria"]["make"] == "Toyota"


def test_search_rejects_unsupported_fixture_vehicle_without_rewriting() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/candidates/search", json={"goal": "Find me a Toyota RAV4"}
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unsupported_fixture_criteria"
    assert "Hyundai Tucson Hybrid" in response.json()["detail"]["message"]


def test_search_rejects_unsupported_fixture_location_without_rewriting() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/candidates/search",
            json={"goal": "Find me a Hyundai Tucson Hybrid near Dallas"},
        )

    assert response.status_code == 422
    assert "Houston" in response.json()["detail"]["message"]


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
