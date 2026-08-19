import pytest

from app.providers.criteria import FixtureCriteriaInterpreter, UnsupportedCriteriaError


@pytest.mark.parametrize(
    ("goal", "condition"),
    [
        ("Find a new Hyundai Tucson Hybrid", "new"),
        ("Find a used Hyundai Tucson Hybrid", "used"),
        ("Find a new or used Hyundai Tucson Hybrid", "either"),
        ("Find either new or used Hyundai Tucson Hybrid", "either"),
        ("Find a Hyundai Tucson Hybrid", "either"),
    ],
)
async def test_fixture_interpreter_preserves_condition_intent(
    goal: str, condition: str
) -> None:
    result = await FixtureCriteriaInterpreter().interpret(goal)

    assert result.criteria.condition == condition


@pytest.mark.parametrize(
    "goal",
    [
        "Find me a Toyota RAV4",
        "Find me a Hyundai Santa Fe Hybrid",
        "Find me a Hyundai",
    ],
)
async def test_fixture_interpreter_rejects_unsupported_or_ambiguous_vehicle(
    goal: str,
) -> None:
    with pytest.raises(UnsupportedCriteriaError, match="Hyundai Tucson Hybrid"):
        await FixtureCriteriaInterpreter().interpret(goal)


async def test_fixture_interpreter_rejects_unsupported_location() -> None:
    with pytest.raises(UnsupportedCriteriaError, match="Houston"):
        await FixtureCriteriaInterpreter().interpret(
            "Find a Hyundai Tucson Hybrid near Dallas"
        )


async def test_fixture_interpreter_rejects_unsupported_explicit_feature() -> None:
    with pytest.raises(UnsupportedCriteriaError, match="feature"):
        await FixtureCriteriaInterpreter().interpret(
            "Find a Hyundai Tucson Hybrid that must have leather seats"
        )


async def test_fixture_interpreter_discloses_houston_default() -> None:
    result = await FixtureCriteriaInterpreter().interpret(
        "Find a Hyundai Tucson Hybrid"
    )

    assert result.criteria.home_location == "Houston, TX"
    assert any("Houston" in assumption for assumption in result.assumptions)


async def test_fixture_interpreter_derives_complete_hard_constraint_display() -> None:
    result = await FixtureCriteriaInterpreter().interpret(
        "Find a used 2025 Hyundai Tucson Hybrid Limited within 40 miles of Houston "
        "under $40,000. Must have AWD, no panoramic roof, avoid black exterior "
        "and gray interior."
    )

    criteria = result.criteria
    assert criteria.required_features == ["AWD"]
    assert criteria.excluded_features == ["panoramic roof"]
    assert criteria.excluded_exterior_colors == ["Black"]
    assert criteria.excluded_interior_colors == ["Gray"]
    assert criteria.hard_constraints == [
        "condition: used",
        "make: Hyundai",
        "model: Tucson Hybrid",
        "trim: Limited",
        "model year: 2025",
        "location: Houston, TX",
        "distance <= 40 miles",
        "advertised price <= $40,000",
        "required feature: AWD",
        "excluded feature: panoramic roof",
        "excluded exterior color: Black",
        "excluded interior color: Gray",
    ]
