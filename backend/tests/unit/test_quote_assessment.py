from decimal import Decimal

import pytest

from app.domain.quote import (
    Incentive,
    MoneyItem,
    QuoteAssessmentContext,
    QuoteExtraction,
)
from app.services.quote_assessment import assess_quote


def money_item(
    name: str,
    amount: str | None,
    *,
    mandatory: bool | None,
    evidence_id: str,
) -> MoneyItem:
    return MoneyItem(
        name=name,
        amount=amount,
        stated_mandatory=mandatory,
        evidence_id=evidence_id,
    )


def complete_extraction(**overrides: object) -> QuoteExtraction:
    values: dict[str, object] = {
        "vehicle_vin": "KM8JCDD10SU000001",
        "stock_number": "B1001",
        "selling_price": "37800",
        "claimed_otd": "40415",
        "dealer_fees": [
            money_item(
                "Documentation fee",
                "225",
                mandatory=True,
                evidence_id="dealer-fee",
            )
        ],
        "government_fees": [
            money_item(
                "Texas sales tax",
                "2293",
                mandatory=None,
                evidence_id="sales-tax",
            ),
            money_item(
                "Title and license",
                "97",
                mandatory=None,
                evidence_id="title-license",
            ),
        ],
        "addons": [],
        "incentives": [],
        "financing_required": False,
        "trade_required": False,
        "explicit_no_addons_statement": True,
        "explicit_all_fees_included_statement": True,
        "unresolved_questions": [],
        "evidence_ids": [],
        "extraction_confidence": 0.95,
    }
    values.update(overrides)
    return QuoteExtraction(**values)


def expected_identity(**overrides: object) -> QuoteAssessmentContext:
    values: dict[str, object] = {
        "expected_vehicle_id": "baytown-blue",
        "expected_vin": "KM8JCDD10SU000001",
        "expected_stock_number": "B1001",
    }
    values.update(overrides)
    return QuoteAssessmentContext(**values)


def test_complete_itemized_quote_is_comparable_transparent_and_reconciled() -> None:
    assessment = assess_quote(complete_extraction(), expected_identity())

    assert assessment.comparable is True
    assert assessment.transparent is True
    assert assessment.reconciled is True
    assert assessment.missing_for_comparison == []
    assert assessment.missing_for_transparency == []
    assert assessment.reconciliation_difference == Decimal("0")


@pytest.mark.parametrize(
    ("context", "extraction"),
    [
        (
            expected_identity(expected_stock_number=None),
            complete_extraction(stock_number=None),
        ),
        (
            expected_identity(expected_vin=None),
            complete_extraction(vehicle_vin=None),
        ),
    ],
)
def test_matching_known_vin_or_stock_satisfies_identity(
    context: QuoteAssessmentContext,
    extraction: QuoteExtraction,
) -> None:
    assessment = assess_quote(extraction, context)

    assert assessment.comparable is True
    assert "vehicle_identity" not in assessment.missing_for_comparison
    assert "vehicle_identity_mismatch" not in assessment.missing_for_comparison


@pytest.mark.parametrize(
    ("context", "extraction"),
    [
        (
            expected_identity(expected_stock_number=None),
            complete_extraction(
                vehicle_vin="KM8JCDD99SU999999",
                stock_number=None,
            ),
        ),
        (
            expected_identity(expected_vin=None),
            complete_extraction(
                vehicle_vin=None,
                stock_number="WRONG-STOCK",
            ),
        ),
        (
            expected_identity(),
            complete_extraction(
                vehicle_vin="KM8JCDD99SU999999",
                stock_number="B1001",
            ),
        ),
    ],
)
def test_any_known_vehicle_identity_mismatch_blocks_comparability(
    context: QuoteAssessmentContext,
    extraction: QuoteExtraction,
) -> None:
    assessment = assess_quote(extraction, context)

    assert assessment.comparable is False
    assert assessment.missing_for_comparison == ["vehicle_identity_mismatch"]


@pytest.mark.parametrize(
    "context",
    [
        expected_identity(),
        QuoteAssessmentContext(expected_vehicle_id="baytown-blue"),
    ],
)
def test_missing_comparable_identity_is_not_treated_as_a_match(
    context: QuoteAssessmentContext,
) -> None:
    extraction = complete_extraction(vehicle_vin=None, stock_number=None)

    assessment = assess_quote(extraction, context)

    assert assessment.comparable is False
    assert assessment.missing_for_comparison == ["vehicle_identity"]


def test_missing_written_otd_is_a_comparison_gap_even_when_not_source_flagged() -> None:
    extraction = complete_extraction(
        claimed_otd=None,
        government_fees=[
            money_item(
                "Tax, title, and license",
                None,
                mandatory=None,
                evidence_id="ttl",
            )
        ],
        unresolved_questions=[],
    )

    assessment = assess_quote(extraction, expected_identity())

    assert assessment.comparable is False
    assert "claimed_otd" in assessment.missing_for_comparison
    assert assessment.reconciled is None
    assert assessment.reconciliation_difference is None


def test_empty_addon_list_without_explicit_statement_does_not_prove_no_addons() -> None:
    assessment = assess_quote(
        complete_extraction(explicit_no_addons_statement=False),
        expected_identity(),
    )

    assert assessment.comparable is False
    assert "addon_status" in assessment.missing_for_comparison
    assert "mandatory_addon_detail" in assessment.missing_for_transparency
    assert assessment.reconciled is None


def test_explicit_no_addons_statement_resolves_addon_policy() -> None:
    assessment = assess_quote(complete_extraction(), expected_identity())

    assert "addon_status" not in assessment.missing_for_comparison
    assert "mandatory_addon_detail" not in assessment.missing_for_transparency


def test_conflicting_no_addons_statement_and_listed_addon_remains_ambiguous() -> None:
    assessment = assess_quote(
        complete_extraction(
            addons=[
                money_item(
                    "Protection package",
                    "699",
                    mandatory=True,
                    evidence_id="protection",
                )
            ],
            explicit_no_addons_statement=True,
        ),
        expected_identity(),
    )

    assert "addon_status" in assessment.missing_for_comparison
    assert "mandatory_addon_detail" in assessment.missing_for_transparency
    assert assessment.reconciled is None


def test_unknown_addon_status_and_mandatory_amount_remain_unknown() -> None:
    unknown_status = money_item(
        "Protection package",
        "1299",
        mandatory=None,
        evidence_id="unknown-addon",
    )
    missing_amount = money_item(
        "SecureTrack",
        None,
        mandatory=True,
        evidence_id="mandatory-addon",
    )

    status_assessment = assess_quote(
        complete_extraction(
            addons=[unknown_status],
            explicit_no_addons_statement=False,
        ),
        expected_identity(),
    )
    amount_assessment = assess_quote(
        complete_extraction(
            addons=[missing_amount],
            explicit_no_addons_statement=False,
        ),
        expected_identity(),
    )

    assert "addon_status" in status_assessment.missing_for_comparison
    assert status_assessment.reconciled is None
    assert "mandatory_addon_amount" in amount_assessment.missing_for_comparison
    assert "mandatory_addon_detail" in amount_assessment.missing_for_transparency
    assert amount_assessment.reconciled is None


@pytest.mark.parametrize(
    ("field_name", "missing_identifier"),
    [
        ("financing_required", "financing_dependency"),
        ("trade_required", "trade_dependency"),
    ],
)
def test_unknown_quote_dependencies_block_comparability_without_becoming_false(
    field_name: str,
    missing_identifier: str,
) -> None:
    extraction = complete_extraction(**{field_name: None})

    assessment = assess_quote(extraction, expected_identity())

    assert assessment.comparable is False
    assert missing_identifier in assessment.missing_for_comparison
    assert getattr(extraction, field_name) is None


@pytest.mark.parametrize("field_name", ["financing_required", "trade_required"])
@pytest.mark.parametrize("known_value", [False, True])
def test_known_quote_dependencies_remain_visible_and_resolve_policy(
    field_name: str,
    known_value: bool,
) -> None:
    extraction = complete_extraction(**{field_name: known_value})

    assessment = assess_quote(extraction, expected_identity())

    assert assessment.comparable is True
    assert getattr(extraction, field_name) is known_value


def test_incentive_without_stated_eligibility_leaves_pricing_condition_missing() -> None:
    incentive = Incentive(
        name="Conditional rebate",
        amount="1000",
        eligibility_condition=None,
        requires_financing=None,
        requires_trade=None,
        evidence_id="rebate",
    )

    assessment = assess_quote(
        complete_extraction(incentives=[incentive]),
        expected_identity(),
    )

    assert assessment.comparable is False
    assert "pricing_condition" in assessment.missing_for_comparison


def test_non_modeled_buyer_eligibility_leaves_pricing_condition_missing() -> None:
    incentive = Incentive(
        name="Membership incentive",
        amount="500",
        eligibility_condition="Buyer membership must be verified",
        requires_financing=False,
        requires_trade=None,
        evidence_id="membership",
    )

    assessment = assess_quote(
        complete_extraction(incentives=[incentive]),
        expected_identity(),
    )

    assert assessment.comparable is False
    assert assessment.missing_for_comparison == ["pricing_condition"]


def test_typed_incentive_dependency_can_supply_its_pricing_condition() -> None:
    incentive = Incentive(
        name="Finance rebate",
        amount="1000",
        eligibility_condition=None,
        requires_financing=True,
        requires_trade=False,
        evidence_id="rebate",
    )

    assessment = assess_quote(
        complete_extraction(
            incentives=[incentive],
            financing_required=True,
        ),
        expected_identity(),
    )

    assert "pricing_condition" not in assessment.missing_for_comparison
    assert assessment.comparable is True


def test_typed_trade_dependency_can_supply_its_pricing_condition() -> None:
    incentive = Incentive(
        name="Trade assistance",
        amount="1500",
        eligibility_condition="Requires a qualifying trade-in",
        requires_financing=False,
        requires_trade=True,
        evidence_id="trade-assistance",
    )

    assessment = assess_quote(
        complete_extraction(
            incentives=[incentive],
            trade_required=True,
        ),
        expected_identity(),
    )

    assert "pricing_condition" not in assessment.missing_for_comparison
    assert "trade_dependency" not in assessment.missing_for_comparison
    assert assessment.comparable is True


def test_multiple_unmodeled_incentives_add_pricing_condition_only_once() -> None:
    incentives = [
        Incentive(
            name="Membership incentive",
            amount="500",
            eligibility_condition="Buyer membership must be verified",
            requires_financing=False,
            requires_trade=False,
            evidence_id="membership",
        ),
        Incentive(
            name="Unspecified rebate",
            amount="250",
            eligibility_condition=None,
            requires_financing=None,
            requires_trade=None,
            evidence_id="unspecified",
        ),
    ]

    assessment = assess_quote(
        complete_extraction(incentives=incentives),
        expected_identity(),
    )

    assert assessment.missing_for_comparison.count("pricing_condition") == 1


def test_incentive_dependency_conflict_keeps_quote_dependency_unresolved() -> None:
    incentive = Incentive(
        name="Finance rebate",
        amount="1000",
        eligibility_condition="Requires dealer financing",
        requires_financing=True,
        requires_trade=False,
        evidence_id="rebate",
    )

    assessment = assess_quote(
        complete_extraction(
            incentives=[incentive],
            financing_required=False,
        ),
        expected_identity(),
    )

    assert "financing_dependency" in assessment.missing_for_comparison
    assert assessment.comparable is False


def test_known_conditional_incentive_does_not_become_an_unconditional_reduction() -> None:
    incentive = Incentive(
        name="Finance rebate",
        amount="1000",
        eligibility_condition="Requires Hyundai Motor Finance financing",
        requires_financing=True,
        requires_trade=False,
        evidence_id="rebate",
    )
    extraction = complete_extraction(
        incentives=[incentive],
        financing_required=True,
    )

    assessment = assess_quote(extraction, expected_identity())

    assert assessment.comparable is True
    assert "pricing_condition" not in assessment.missing_for_comparison
    assert extraction.financing_required is True
    assert extraction.incentives == [incentive]
    assert assessment.reconciled is True
    assert assessment.reconciliation_difference == Decimal("0")


def test_written_otd_can_be_comparable_without_transparency_or_reconciliation() -> None:
    extraction = complete_extraction(
        selling_price=None,
        dealer_fees=[],
        government_fees=[],
        explicit_all_fees_included_statement=True,
    )

    assessment = assess_quote(extraction, expected_identity())

    assert assessment.comparable is True
    assert assessment.transparent is False
    assert assessment.missing_for_transparency == [
        "selling_price",
        "dealer_fee_detail",
        "government_fee_detail",
    ]
    assert assessment.reconciled is None
    assert assessment.reconciliation_difference is None


@pytest.mark.parametrize(
    ("overrides", "missing_identifier"),
    [
        ({"selling_price": None}, "selling_price"),
        ({"dealer_fees": []}, "dealer_fee_detail"),
        (
            {
                "addons": [
                    money_item(
                        "Protection package",
                        None,
                        mandatory=True,
                        evidence_id="addon",
                    )
                ],
                "explicit_no_addons_statement": False,
            },
            "mandatory_addon_detail",
        ),
        ({"government_fees": []}, "government_fee_detail"),
    ],
)
def test_each_transparency_requirement_is_evaluated_independently(
    overrides: dict[str, object],
    missing_identifier: str,
) -> None:
    assessment = assess_quote(
        complete_extraction(**overrides),
        expected_identity(),
    )

    assert assessment.transparent is False
    assert missing_identifier in assessment.missing_for_transparency


@pytest.mark.parametrize(
    ("claimed_otd", "expected_reconciled", "expected_difference"),
    [
        ("40415", True, Decimal("0")),
        ("40414.99", True, Decimal("0.01")),
        ("40414.98", False, Decimal("0.02")),
        ("40415.02", False, Decimal("-0.02")),
    ],
)
def test_reconciliation_uses_one_cent_tolerance_and_documented_difference_sign(
    claimed_otd: str,
    expected_reconciled: bool,
    expected_difference: Decimal,
) -> None:
    assessment = assess_quote(
        complete_extraction(claimed_otd=claimed_otd),
        expected_identity(),
    )

    assert assessment.reconciled is expected_reconciled
    assert assessment.reconciliation_difference == expected_difference


def test_unknown_line_item_amount_is_never_zero_filled_for_reconciliation() -> None:
    assessment = assess_quote(
        complete_extraction(
            government_fees=[
                money_item(
                    "Tax, title, and license",
                    None,
                    mandatory=None,
                    evidence_id="ttl",
                )
            ]
        ),
        expected_identity(),
    )

    assert assessment.reconciled is None
    assert assessment.reconciliation_difference is None


@pytest.mark.parametrize("collection_name", ["dealer_fees", "government_fees"])
def test_explicitly_optional_charge_is_not_guessed_into_reconciliation(
    collection_name: str,
) -> None:
    optional_charge = money_item(
        "Optional charge",
        "225",
        mandatory=False,
        evidence_id="optional-charge",
    )

    assessment = assess_quote(
        complete_extraction(**{collection_name: [optional_charge]}),
        expected_identity(),
    )

    assert assessment.transparent is True
    assert assessment.reconciled is None
    assert assessment.reconciliation_difference is None


def test_known_mandatory_addons_participate_in_reconciliation() -> None:
    assessment = assess_quote(
        complete_extraction(
            selling_price="37500",
            claimed_otd="41780",
            dealer_fees=[
                money_item(
                    "Documentation fee",
                    "225",
                    mandatory=True,
                    evidence_id="doc",
                )
            ],
            government_fees=[
                money_item(
                    "Tax, title, and license",
                    "2160",
                    mandatory=None,
                    evidence_id="ttl",
                )
            ],
            addons=[
                money_item(
                    "Ceramic Shield",
                    "1299",
                    mandatory=True,
                    evidence_id="ceramic",
                ),
                money_item(
                    "SecureTrack",
                    "596",
                    mandatory=True,
                    evidence_id="secure-track",
                ),
            ],
            explicit_no_addons_statement=False,
        ),
        expected_identity(),
    )

    assert assessment.comparable is True
    assert assessment.transparent is True
    assert assessment.reconciled is True
    assert assessment.reconciliation_difference == Decimal("0")


@pytest.mark.parametrize("mandatory_status", [False, None])
def test_optional_or_ambiguous_addon_inclusion_is_not_guessed_into_total(
    mandatory_status: bool | None,
) -> None:
    assessment = assess_quote(
        complete_extraction(
            addons=[
                money_item(
                    "Protection package",
                    "699",
                    mandatory=mandatory_status,
                    evidence_id="protection",
                )
            ],
            explicit_no_addons_statement=False,
        ),
        expected_identity(),
    )

    assert assessment.reconciled is None
    assert assessment.reconciliation_difference is None


def test_inconsistent_fixture_arithmetic_is_detected_with_positive_difference() -> None:
    assessment = assess_quote(
        complete_extraction(
            vehicle_vin="KM8JCDD12TU000003",
            stock_number=None,
            selling_price="37000",
            claimed_otd="40225",
            dealer_fees=[
                money_item(
                    "Documentation fee",
                    "225",
                    mandatory=True,
                    evidence_id="doc",
                )
            ],
            government_fees=[
                money_item(
                    "Taxes, title, and license",
                    "2500",
                    mandatory=True,
                    evidence_id="ttl",
                )
            ],
            addons=[
                money_item(
                    "Protection package",
                    "1500",
                    mandatory=True,
                    evidence_id="addon",
                )
            ],
            explicit_no_addons_statement=False,
            explicit_all_fees_included_statement=False,
        ),
        expected_identity(
            expected_vehicle_id="katy-blue",
            expected_vin="KM8JCDD12TU000003",
            expected_stock_number="K3003",
        ),
    )

    assert assessment.reconciled is False
    assert assessment.reconciliation_difference == Decimal("1000")


def test_source_uncertainty_is_not_copied_into_policy_missing_lists() -> None:
    source_question = "Military eligibility has not been confirmed."
    source_only_extraction = complete_extraction(
        unresolved_questions=[source_question],
    )
    source_only_assessment = assess_quote(
        source_only_extraction,
        expected_identity(),
    )
    incentive = Incentive(
        name="Military appreciation incentive",
        amount="500",
        eligibility_condition="Eligible military status and verification required",
        requires_financing=False,
        requires_trade=False,
        evidence_id="military",
    )
    extraction = complete_extraction(
        incentives=[incentive],
        unresolved_questions=[source_question],
    )

    assessment = assess_quote(extraction, expected_identity())

    assert source_only_assessment.comparable is True
    assert source_only_assessment.missing_for_comparison == []
    assert source_only_assessment.missing_for_transparency == []
    assert assessment.comparable is False
    assert assessment.missing_for_comparison == ["pricing_condition"]
    assert source_question in extraction.unresolved_questions
    assert source_question not in assessment.missing_for_comparison
    assert source_question not in assessment.missing_for_transparency
    assert len(assessment.missing_for_comparison) == len(
        set(assessment.missing_for_comparison)
    )
    assert len(assessment.missing_for_transparency) == len(
        set(assessment.missing_for_transparency)
    )
