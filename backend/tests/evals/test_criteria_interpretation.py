import pytest

from app.providers.criteria import FixtureCriteriaInterpreter


@pytest.mark.parametrize(
    ("goal", "expected"),
    [
        (
            "Find a new 2025 or 2026 Hyundai Tucson Hybrid Limited within 40 miles "
            "of Houston under $40,000. I prefer blue and require AWD.",
            {
                "make": "Hyundai",
                "model": "Tucson Hybrid",
                "trims": ["Limited"],
                "years": [2025, 2026],
                "max_distance_miles": 40,
                "max_advertised_price": "40000",
                "required_features": ["AWD"],
                "preferred_exterior_colors": ["Blue"],
            },
        ),
        (
            "I want a new Hyundai Tucson Hybrid near Houston. Avoid black cars.",
            {
                "make": "Hyundai",
                "model": "Tucson Hybrid",
                "excluded_exterior_colors": ["Black"],
            },
        ),
    ],
)
async def test_representative_goal_is_structured(goal: str, expected: dict[str, object]) -> None:
    result = await FixtureCriteriaInterpreter().interpret(goal)

    actual = result.criteria.model_dump(mode="json")
    for field, value in expected.items():
        assert actual[field] == value
    assert result.criteria.hard_constraints
