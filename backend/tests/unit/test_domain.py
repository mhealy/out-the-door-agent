from decimal import Decimal

from app.domain.criteria import VehicleSearchCriteria
from app.domain.quote import QuoteExtraction


def test_search_criteria_preserves_decimal_money() -> None:
    criteria = VehicleSearchCriteria(
        make="Hyundai",
        model="Tucson",
        condition="new",
        home_location="Houston, TX",
        max_distance_miles=50,
        max_otd_price="42000.01",
    )

    assert criteria.max_otd_price == Decimal("42000.01")


def test_mutable_domain_defaults_are_not_shared() -> None:
    first = QuoteExtraction(extraction_confidence=0.9)
    second = QuoteExtraction(extraction_confidence=0.8)

    first.unresolved_questions.append("Written OTD")

    assert second.unresolved_questions == []
