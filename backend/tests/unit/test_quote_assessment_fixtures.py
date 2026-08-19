import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.domain.quote import QuoteAssessmentContext, QuoteExtraction
from app.providers.dealer_messages import FixtureDealerMessageProvider
from app.providers.inventory import FixtureInventoryProvider
from app.services.quote_assessment import assess_quote


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXPECTED_EXTRACTIONS = {
    record["case_id"]: record["extraction"]
    for record in json.loads(
        (REPOSITORY_ROOT / "demo/expected/quote_analysis_expected.json").read_text(
            encoding="utf-8"
        )
    )
}


@pytest.mark.parametrize(
    (
        "case_id",
        "comparable",
        "transparent",
        "reconciled",
        "comparison_missing",
        "transparency_missing",
        "difference",
    ),
    [
        ("msg-fully-itemized", True, True, True, [], [], "0"),
        (
            "msg-otd-without-itemization",
            True,
            False,
            None,
            [],
            ["selling_price", "dealer_fee_detail", "government_fee_detail"],
            None,
        ),
        (
            "msg-plus-ttl",
            False,
            False,
            None,
            [
                "claimed_otd",
                "addon_status",
                "financing_dependency",
                "trade_dependency",
            ],
            [
                "dealer_fee_detail",
                "mandatory_addon_detail",
                "government_fee_detail",
            ],
            None,
        ),
        (
            "msg-financing-rebate",
            False,
            False,
            None,
            ["vehicle_identity", "addon_status"],
            [
                "dealer_fee_detail",
                "mandatory_addon_detail",
                "government_fee_detail",
            ],
            None,
        ),
        (
            "msg-trade-assistance",
            False,
            False,
            None,
            ["vehicle_identity", "addon_status"],
            [
                "dealer_fee_detail",
                "mandatory_addon_detail",
                "government_fee_detail",
            ],
            None,
        ),
        (
            "msg-military-incentive",
            True,
            False,
            None,
            [],
            ["dealer_fee_detail", "government_fee_detail"],
            None,
        ),
        (
            "msg-college-incentive",
            False,
            False,
            None,
            ["addon_status"],
            [
                "dealer_fee_detail",
                "mandatory_addon_detail",
                "government_fee_detail",
            ],
            None,
        ),
        ("msg-mandatory-addons", True, True, True, [], [], "0"),
        ("msg-explicit-no-addons", True, True, True, [], [], "0"),
        ("msg-inconsistent-math", True, True, False, [], [], "1000"),
        (
            "msg-wrong-vin",
            False,
            False,
            None,
            [
                "vehicle_identity_mismatch",
                "addon_status",
                "financing_dependency",
                "trade_dependency",
            ],
            [
                "dealer_fee_detail",
                "mandatory_addon_detail",
                "government_fee_detail",
            ],
            None,
        ),
        (
            "msg-multiple-vehicles",
            False,
            False,
            None,
            [
                "vehicle_identity",
                "claimed_otd",
                "addon_status",
                "financing_dependency",
                "trade_dependency",
            ],
            [
                "selling_price",
                "dealer_fee_detail",
                "mandatory_addon_detail",
                "government_fee_detail",
            ],
            None,
        ),
        (
            "msg-expiring-quote",
            True,
            False,
            None,
            [],
            ["dealer_fee_detail", "government_fee_detail"],
            None,
        ),
        (
            "msg-refusal-store-visit",
            False,
            False,
            None,
            [
                "vehicle_identity",
                "claimed_otd",
                "addon_status",
                "financing_dependency",
                "trade_dependency",
            ],
            [
                "selling_price",
                "dealer_fee_detail",
                "mandatory_addon_detail",
                "government_fee_detail",
            ],
            None,
        ),
        (
            "msg-prompt-injection",
            False,
            False,
            None,
            [
                "claimed_otd",
                "addon_status",
                "financing_dependency",
                "trade_dependency",
            ],
            [
                "dealer_fee_detail",
                "mandatory_addon_detail",
                "government_fee_detail",
            ],
            None,
        ),
    ],
)
async def test_issue_five_fixtures_follow_deterministic_assessment_policy(
    case_id: str,
    comparable: bool,
    transparent: bool,
    reconciled: bool | None,
    comparison_missing: list[str],
    transparency_missing: list[str],
    difference: str | None,
) -> None:
    message = await FixtureDealerMessageProvider().get_message(case_id)
    inventory = FixtureInventoryProvider()
    vehicle = (
        await inventory.get_by_id(message.vehicle_id)
        if message.vehicle_id is not None
        else None
    )
    context = QuoteAssessmentContext(
        expected_vehicle_id=message.vehicle_id,
        expected_vin=vehicle.vin if vehicle is not None else None,
        expected_stock_number=vehicle.stock_number if vehicle is not None else None,
    )

    assessment = assess_quote(
        QuoteExtraction.model_validate(EXPECTED_EXTRACTIONS[case_id]),
        context,
    )

    assert assessment.comparable is comparable
    assert assessment.transparent is transparent
    assert assessment.reconciled is reconciled
    assert assessment.missing_for_comparison == comparison_missing
    assert assessment.missing_for_transparency == transparency_missing
    assert assessment.reconciliation_difference == (
        Decimal(difference) if difference is not None else None
    )
