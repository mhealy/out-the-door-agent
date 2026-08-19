from decimal import Decimal

from app.domain.quote import (
    QuoteAssessment,
    QuoteAssessmentContext,
    QuoteExtraction,
)


VEHICLE_IDENTITY = "vehicle_identity"
VEHICLE_IDENTITY_MISMATCH = "vehicle_identity_mismatch"
CLAIMED_OTD = "claimed_otd"
ADDON_STATUS = "addon_status"
MANDATORY_ADDON_AMOUNT = "mandatory_addon_amount"
FINANCING_DEPENDENCY = "financing_dependency"
TRADE_DEPENDENCY = "trade_dependency"
PRICING_CONDITION = "pricing_condition"

SELLING_PRICE = "selling_price"
DEALER_FEE_DETAIL = "dealer_fee_detail"
MANDATORY_ADDON_DETAIL = "mandatory_addon_detail"
GOVERNMENT_FEE_DETAIL = "government_fee_detail"

RECONCILIATION_TOLERANCE = Decimal("0.01")


def _normalized_identifier(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip().casefold()


def _identity_requirement(
    extraction: QuoteExtraction,
    context: QuoteAssessmentContext,
) -> str | None:
    expected_and_extracted = (
        (context.expected_vin, extraction.vehicle_vin),
        (context.expected_stock_number, extraction.stock_number),
    )
    matched = False
    for expected, extracted in expected_and_extracted:
        normalized_expected = _normalized_identifier(expected)
        normalized_extracted = _normalized_identifier(extracted)
        if normalized_expected is None or normalized_extracted is None:
            continue
        if normalized_expected != normalized_extracted:
            return VEHICLE_IDENTITY_MISMATCH
        matched = True
    return None if matched else VEHICLE_IDENTITY


def _comparison_requirements(
    extraction: QuoteExtraction,
    context: QuoteAssessmentContext,
) -> list[str]:
    missing: list[str] = []
    identity_requirement = _identity_requirement(extraction, context)
    if identity_requirement is not None:
        missing.append(identity_requirement)
    if extraction.claimed_otd is None:
        missing.append(CLAIMED_OTD)

    if extraction.addons:
        if extraction.explicit_no_addons_statement or any(
            addon.stated_mandatory is None for addon in extraction.addons
        ):
            missing.append(ADDON_STATUS)
        if any(
            addon.stated_mandatory is True and addon.amount is None
            for addon in extraction.addons
        ):
            missing.append(MANDATORY_ADDON_AMOUNT)
    elif not extraction.explicit_no_addons_statement:
        missing.append(ADDON_STATUS)

    if extraction.financing_required is None or any(
        incentive.requires_financing is True
        and extraction.financing_required is not True
        for incentive in extraction.incentives
    ):
        missing.append(FINANCING_DEPENDENCY)
    if extraction.trade_required is None or any(
        incentive.requires_trade is True and extraction.trade_required is not True
        for incentive in extraction.incentives
    ):
        missing.append(TRADE_DEPENDENCY)
    if any(
        not (incentive.eligibility_condition or "").strip()
        and incentive.requires_financing is not True
        and incentive.requires_trade is not True
        for incentive in extraction.incentives
    ):
        missing.append(PRICING_CONDITION)
    return missing


def _transparency_requirements(extraction: QuoteExtraction) -> list[str]:
    missing: list[str] = []
    if extraction.selling_price is None:
        missing.append(SELLING_PRICE)
    if not extraction.dealer_fees or any(
        item.amount is None for item in extraction.dealer_fees
    ):
        missing.append(DEALER_FEE_DETAIL)

    if extraction.addons:
        if extraction.explicit_no_addons_statement or any(
            addon.stated_mandatory is None
            or (addon.stated_mandatory is True and addon.amount is None)
            for addon in extraction.addons
        ):
            missing.append(MANDATORY_ADDON_DETAIL)
    elif not extraction.explicit_no_addons_statement:
        missing.append(MANDATORY_ADDON_DETAIL)

    if not extraction.government_fees or any(
        item.amount is None for item in extraction.government_fees
    ):
        missing.append(GOVERNMENT_FEE_DETAIL)
    return missing


def _reconcile(
    extraction: QuoteExtraction,
    *,
    transparent: bool,
) -> tuple[bool | None, Decimal | None]:
    """Return arithmetic status and computed-total minus claimed-OTD difference."""

    if (
        not transparent
        or extraction.selling_price is None
        or extraction.claimed_otd is None
    ):
        return None, None

    computed_total = extraction.selling_price
    for item in (*extraction.dealer_fees, *extraction.government_fees):
        if item.amount is None or item.stated_mandatory is False:
            return None, None
        computed_total += item.amount

    for addon in extraction.addons:
        if addon.stated_mandatory is not True or addon.amount is None:
            return None, None
        computed_total += addon.amount

    difference = computed_total - extraction.claimed_otd
    return abs(difference) <= RECONCILIATION_TOLERANCE, difference


def assess_quote(
    extraction: QuoteExtraction,
    context: QuoteAssessmentContext,
) -> QuoteAssessment:
    """Apply deterministic policy to an evidence-validated quote extraction."""

    missing_for_comparison = _comparison_requirements(extraction, context)
    missing_for_transparency = _transparency_requirements(extraction)
    transparent = not missing_for_transparency
    reconciled, difference = _reconcile(extraction, transparent=transparent)
    return QuoteAssessment(
        comparable=not missing_for_comparison,
        transparent=transparent,
        reconciled=reconciled,
        missing_for_comparison=missing_for_comparison,
        missing_for_transparency=missing_for_transparency,
        reconciliation_difference=difference,
    )
