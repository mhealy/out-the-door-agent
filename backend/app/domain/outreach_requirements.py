from typing import Final


INITIAL_QUOTE_REQUEST_REQUIREMENTS: Final[tuple[str, ...]] = (
    "vehicle_identity",
    "selling_price",
    "dealer_fees",
    "mandatory_addons",
    "government_charges",
    "out_the_door_total",
    "incentives_and_eligibility",
    "financing_requirement",
    "trade_in_requirement",
    "quote_expiration",
)

INITIAL_QUOTE_REQUEST_LABELS: Final[dict[str, str]] = {
    "vehicle_identity": "Exact VIN and/or stock number for the quoted vehicle",
    "selling_price": "Selling price before taxes and fees",
    "dealer_fees": "All dealer and documentation fees",
    "mandatory_addons": (
        "All mandatory dealer-installed products or add-ons and their amounts"
    ),
    "government_charges": "Taxes, title, license, and other government charges",
    "out_the_door_total": "Written out-the-door total",
    "incentives_and_eligibility": (
        "Every included incentive or rebate and its eligibility conditions"
    ),
    "financing_requirement": "Whether the quoted economics require dealer financing",
    "trade_in_requirement": "Whether the quoted economics require a trade-in",
    "quote_expiration": "Quote expiration or validity period, if applicable",
}

# These identifiers are owned by deterministic quote assessment. The drafting
# model receives code-owned labels and safe options only after policy selection.
FOLLOWUP_REQUIREMENT_LABELS: Final[dict[str, str]] = {
    "vehicle_identity": "Confirmation of the exact VIN or stock number",
    "vehicle_identity_mismatch": (
        "Confirmation that the quote applies to the requested vehicle"
    ),
    "claimed_otd": "Written out-the-door total",
    "addon_status": (
        "Whether any dealer-installed products or add-ons are mandatory"
    ),
    "mandatory_addon_amount": (
        "Amount of each mandatory dealer-installed product or add-on"
    ),
    "financing_dependency": (
        "Whether the quoted price requires dealer financing"
    ),
    "trade_dependency": "Whether the quoted price requires a trade-in",
    "pricing_condition": (
        "Every unresolved eligibility condition included in the quoted price"
    ),
}

# Model output is restricted to these reviewed phrases. This turns semantic
# requirement coverage and prohibited-content safety into structural checks:
# arbitrary model prose never reaches the persisted outbound message.
FOLLOWUP_WORDING_OPTIONS: Final[dict[str, tuple[str, ...]]] = {
    "vehicle_identity": (
        "Please confirm the VIN or stock number for the quoted vehicle.",
        "Please identify the exact VIN or stock number this quote covers.",
    ),
    "vehicle_identity_mismatch": (
        "Please confirm that the quote applies to the requested vehicle.",
        "Please confirm which quoted terms apply to the requested vehicle.",
    ),
    "claimed_otd": (
        "Please confirm the written out-the-door total.",
        "Please provide the complete written out-the-door total.",
    ),
    "addon_status": (
        "Please confirm whether any dealer-installed products are mandatory.",
        (
            "Please confirm whether dealer-installed products or add-ons are "
            "required or optional."
        ),
    ),
    "mandatory_addon_amount": (
        "Please confirm the amount of each mandatory dealer-installed product.",
        (
            "Please provide the price of each mandatory dealer-installed product "
            "or add-on."
        ),
    ),
    "financing_dependency": (
        "Please confirm whether the quoted price requires dealer financing.",
        "Please confirm whether dealer financing is a condition of this price.",
    ),
    "trade_dependency": (
        "Please confirm whether the quoted price requires a trade-in.",
        "Please confirm whether a trade-in is a condition of this price.",
    ),
    "pricing_condition": (
        (
            "Please confirm every incentive or rebate eligibility condition "
            "included in the quoted price."
        ),
        (
            "Please identify each unresolved incentive, rebate, or other eligibility "
            "condition in the quoted total."
        ),
    ),
}

FOLLOWUP_SUBJECT_OPTIONS: Final[tuple[str, ...]] = (
    "Quote clarification",
    "Written quote clarification",
    "Follow-up on the written quote",
    "Quote details needed",
)

OUTREACH_REQUIREMENT_LABELS_BY_ACTION_TYPE: Final[
    dict[str, dict[str, str]]
] = {
    "SEND_INITIAL_QUOTE_REQUEST": INITIAL_QUOTE_REQUEST_LABELS,
    "SEND_FOLLOWUP": FOLLOWUP_REQUIREMENT_LABELS,
}
