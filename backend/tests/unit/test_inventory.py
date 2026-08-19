from decimal import Decimal

import pytest

from app.domain.criteria import VehicleSearchCriteria
from app.domain.vehicle import VehicleListing
from app.providers.inventory import FixtureInventoryProvider
from app.services.inventory import filter_candidates, shortlist_candidates


def criteria(**overrides: object) -> VehicleSearchCriteria:
    values: dict[str, object] = {
        "make": "Hyundai",
        "model": "Tucson Hybrid",
        "trims": ["Limited"],
        "condition": "new",
        "years": [2025, 2026],
        "home_location": "Houston, TX",
        "max_distance_miles": 40,
        "max_advertised_price": "40000",
        "required_features": ["AWD"],
        "excluded_features": ["damage"],
        "excluded_exterior_colors": ["Black"],
        "preferred_exterior_colors": ["Blue"],
    }
    values.update(overrides)
    return VehicleSearchCriteria(**values)


def listing(**overrides: object) -> VehicleListing:
    values: dict[str, object] = {
        "id": "candidate",
        "vin": "KM8JCDD10SU000001",
        "year": 2025,
        "make": "Hyundai",
        "model": "Tucson Hybrid",
        "trim": "Limited",
        "condition": "new",
        "mileage": 8,
        "advertised_price": "38500",
        "msrp": "42000",
        "exterior_color": "Blue",
        "interior_color": "Gray",
        "features": ["AWD", "panoramic roof"],
        "dealer_id": "dealer",
        "dealer_name": "Dealer",
        "distance_miles": 20,
        "source_url": "https://example.test/candidate",
        "source_provider": "fixture",
    }
    values.update(overrides)
    return VehicleListing(**values)


@pytest.mark.parametrize(
    ("change", "value"),
    [
        ("year", 2024),
        ("advertised_price", "40000.01"),
        ("distance_miles", 40.01),
        ("trim", "SEL"),
        ("exterior_color", "Black Pearl"),
        ("features", ["AWD", "damage"]),
        ("features", ["heated seats"]),
    ],
)
def test_filter_candidates_excludes_each_hard_constraint(
    change: str, value: object
) -> None:
    candidate = listing(**{change: value})

    assert filter_candidates(criteria(), [candidate]) == []


def test_filter_candidates_includes_boundaries_and_does_not_require_preferences() -> None:
    candidate = listing(
        advertised_price="40000",
        distance_miles=40,
        exterior_color="White",
    )

    assert filter_candidates(criteria(), [candidate]) == [candidate]


def test_filter_candidates_enforces_excluded_interior_color() -> None:
    candidate = listing(interior_color="Black leather")

    assert filter_candidates(criteria(excluded_interior_colors=["Black"]), [candidate]) == []


def test_shortlist_orders_exact_trim_then_color_then_price_then_distance() -> None:
    candidates = [
        listing(id="far", distance_miles=30),
        listing(id="cheap-white", exterior_color="White", advertised_price="37000"),
        listing(id="blue", advertised_price="39000"),
        listing(id="other-trim", trim="SEL", advertised_price="35000"),
    ]
    result = shortlist_candidates(criteria(), candidates)

    assert [item.id for item in result] == ["far", "blue", "cheap-white", "other-trim"]


async def test_fixture_provider_normalizes_records() -> None:
    results = await FixtureInventoryProvider().search(criteria())

    assert len(results) >= 3
    assert all(isinstance(item, VehicleListing) for item in results)
    assert all(item.source_provider == "fixture" for item in results)
    assert all(isinstance(item.advertised_price, Decimal) for item in results)
