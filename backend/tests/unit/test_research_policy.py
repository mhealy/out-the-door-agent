from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.domain.approval import OutreachVehicleSnapshot
from app.domain.evidence import Evidence
from app.domain.interaction import DealerInteraction
from app.domain.message import DealerMessage
from app.domain.quote import (
    Incentive,
    MoneyItem,
    QuoteAnalysisResult,
    QuoteAssessment,
    QuoteExtraction,
)
from app.services.quote_assessment import MANDATORY_ADDON_AMOUNT
from app.services.research_policy import derive_research_targets


NOW = datetime(2026, 8, 19, 15, 0, tzinfo=timezone.utc)


def _evidence(evidence_id: str, field_name: str, message_id: str) -> Evidence:
    return Evidence(
        id=evidence_id,
        source_type="DEALER_EMAIL",
        source_id=message_id,
        field_name=field_name,
        excerpt=f"Source excerpt for {evidence_id}.",
        created_at=NOW,
    )


def _interaction(
    *,
    addons: list[MoneyItem] | None = None,
    dealer_fees: list[MoneyItem] | None = None,
    government_fees: list[MoneyItem] | None = None,
    incentives: list[Incentive] | None = None,
    missing_for_comparison: list[str] | None = None,
    message_id: str = "message-current",
    interaction_id: str = "interaction-houston",
    dealer_id: str = "houston",
    dealer_name: str = "Houston Hyundai",
    vehicle_id: str = "houston-white",
    analysis_status: str = "ANALYZED",
) -> DealerInteraction:
    addons = addons or []
    dealer_fees = dealer_fees or []
    government_fees = government_fees or []
    incentives = incentives or []
    missing_for_comparison = missing_for_comparison or []
    message = DealerMessage(
        id=message_id,
        dealer_id=dealer_id,
        vehicle_id=vehicle_id,
        subject="Written quote",
        body="Authoritative persisted dealer response.",
        received_at=NOW,
        source_provider="fixture",
    )
    evidence = [
        *(_evidence(item.evidence_id, "addons", message_id) for item in addons),
        *(
            _evidence(item.evidence_id, "dealer_fees", message_id)
            for item in dealer_fees
        ),
        *(
            _evidence(item.evidence_id, "government_fees", message_id)
            for item in government_fees
        ),
        *(_evidence(item.evidence_id, "incentives", message_id) for item in incentives),
    ]
    extraction = QuoteExtraction(
        addons=addons,
        dealer_fees=dealer_fees,
        government_fees=government_fees,
        incentives=incentives,
        evidence_ids=[item.id for item in evidence],
        extraction_confidence=1,
    )
    assessment = QuoteAssessment(
        comparable=not missing_for_comparison,
        transparent=False,
        missing_for_comparison=missing_for_comparison,
        missing_for_transparency=[],
    )
    analysis = (
        QuoteAnalysisResult(
            message=message,
            extraction=extraction,
            evidence=evidence,
            assessment=assessment,
        )
        if analysis_status == "ANALYZED"
        else None
    )
    return DealerInteraction(
        id=interaction_id,
        initial_action_id="initial-action-houston",
        dealer_id=dealer_id,
        vehicle_id=vehicle_id,
        vehicle=OutreachVehicleSnapshot(
            id=vehicle_id,
            year=2025,
            make="Hyundai",
            model="Tucson Hybrid",
            trim="Limited",
            vin="KM8JCDD11SU000002",
            stock_number="H2002",
            dealer_id=dealer_id,
            dealer_name=dealer_name,
        ),
        created_at=NOW,
        analysis_status=analysis_status,
        messages=[message],
        analysis=analysis,
    )


def _targets(interaction: DealerInteraction):
    return derive_research_targets(
        purchase_run_id="purchase-houston",
        agent_run_id="agent-run-houston",
        interaction=interaction,
    )


def test_canonical_houston_material_addons_become_application_owned_targets() -> None:
    interaction = _interaction(
        addons=[
            MoneyItem(
                name="Ceramic Shield",
                amount="1299",
                stated_mandatory=True,
                evidence_id="ev-addons-ceramic",
            ),
            MoneyItem(
                name="SecureTrack theft recovery",
                amount="596",
                stated_mandatory=True,
                evidence_id="ev-addons-theft",
            ),
        ]
    )

    targets = _targets(interaction)

    assert [target.canonical_name for target in targets] == [
        "Ceramic Shield",
        "SecureTrack theft recovery",
    ]
    assert [target.dealer_stated_amount for target in targets] == [
        Decimal("1299"),
        Decimal("596"),
    ]
    assert all(target.target_type == "MANDATORY_ADDON" for target in targets)
    assert all(target.stated_mandatory is True for target in targets)
    assert all(target.purchase_run_id == "purchase-houston" for target in targets)
    assert all(target.agent_run_id == "agent-run-houston" for target in targets)
    assert all(target.interaction_id == interaction.id for target in targets)
    assert all(target.source_message_id == "message-current" for target in targets)
    assert all(target.dealer_id == "houston" for target in targets)
    assert all(target.dealer_name == "Houston Hyundai" for target in targets)
    assert all(target.vehicle_id == "houston-white" for target in targets)
    assert targets[0].source_evidence_ids == ["ev-addons-ceramic"]
    assert targets[1].source_evidence_ids == ["ev-addons-theft"]
    assert len({target.target_id for target in targets}) == 2


def test_materiality_threshold_is_inclusive_and_code_owned() -> None:
    interaction = _interaction(
        addons=[
            MoneyItem(
                name="At threshold",
                amount="500",
                stated_mandatory=True,
                evidence_id="ev-at-threshold",
            ),
            MoneyItem(
                name="Below threshold",
                amount="499.99",
                stated_mandatory=True,
                evidence_id="ev-below-threshold",
            ),
        ]
    )

    targets = _targets(interaction)

    assert [target.canonical_name for target in targets] == ["At threshold"]


def test_unknown_mandatory_amount_is_targeted_only_when_materially_unresolved() -> None:
    addon = MoneyItem(
        name="SecureTrack",
        amount=None,
        stated_mandatory=True,
        evidence_id="ev-securetrack",
    )

    unresolved = _targets(
        _interaction(
            addons=[addon],
            missing_for_comparison=[MANDATORY_ADDON_AMOUNT],
        )
    )
    not_unresolved = _targets(_interaction(addons=[addon]))

    assert len(unresolved) == 1
    assert unresolved[0].dealer_stated_amount is None
    assert not_unresolved == []


def test_optional_ambiguous_low_value_and_blank_addons_are_not_automatic_targets() -> None:
    interaction = _interaction(
        addons=[
            MoneyItem(
                name="Optional protection",
                amount="1900",
                stated_mandatory=False,
                evidence_id="ev-optional",
            ),
            MoneyItem(
                name="Ambiguous protection",
                amount="1900",
                stated_mandatory=None,
                evidence_id="ev-ambiguous",
            ),
            MoneyItem(
                name="Low value",
                amount="49",
                stated_mandatory=True,
                evidence_id="ev-low",
            ),
            MoneyItem(
                name="   ",
                amount="900",
                stated_mandatory=True,
                evidence_id="ev-blank",
            ),
        ]
    )

    assert _targets(interaction) == []


def test_taxes_doc_fees_and_incentives_never_become_addon_research_targets() -> None:
    interaction = _interaction(
        dealer_fees=[
            MoneyItem(
                name="Documentation fee",
                amount="899",
                stated_mandatory=True,
                evidence_id="ev-doc",
            )
        ],
        government_fees=[
            MoneyItem(
                name="Tax, title, and license",
                amount="2500",
                stated_mandatory=True,
                evidence_id="ev-ttl",
            )
        ],
        incentives=[
            Incentive(
                name="Finance rebate",
                amount="1000",
                requires_financing=True,
                evidence_id="ev-rebate",
            )
        ],
    )

    assert _targets(interaction) == []


def test_exact_duplicate_normalized_items_collapse_with_deterministic_evidence() -> None:
    first = MoneyItem(
        name="  Ceramic   Shield ",
        amount="1299.00",
        stated_mandatory=True,
        evidence_id="evidence-b",
    )
    second = MoneyItem(
        name="ceramic shield",
        amount="1299",
        stated_mandatory=True,
        evidence_id="evidence-a",
    )

    forward = _targets(_interaction(addons=[first, second]))
    reverse = _targets(_interaction(addons=[second, first]))

    assert len(forward) == 1
    assert len(reverse) == 1
    assert forward[0].target_id == reverse[0].target_id
    assert forward[0].canonical_name == reverse[0].canonical_name
    assert forward[0].source_evidence_ids == ["evidence-a", "evidence-b"]
    assert reverse[0].source_evidence_ids == ["evidence-a", "evidence-b"]


def test_same_normalized_name_with_different_amounts_is_not_silently_merged() -> None:
    interaction = _interaction(
        addons=[
            MoneyItem(
                name="SecureTrack",
                amount="596",
                stated_mandatory=True,
                evidence_id="ev-first",
            ),
            MoneyItem(
                name=" securetrack ",
                amount="696",
                stated_mandatory=True,
                evidence_id="ev-second",
            ),
        ]
    )

    targets = _targets(interaction)

    assert len(targets) == 2
    assert {target.dealer_stated_amount for target in targets} == {
        Decimal("596"),
        Decimal("696"),
    }
    assert len({target.target_id for target in targets}) == 2


def test_target_identity_is_stable_but_changes_with_authoritative_source_version() -> None:
    addon = MoneyItem(
        name="Ceramic Shield",
        amount="1299",
        stated_mandatory=True,
        evidence_id="ev-ceramic",
    )

    first = _targets(_interaction(addons=[addon], message_id="message-a"))[0]
    repeated = _targets(_interaction(addons=[addon], message_id="message-a"))[0]
    replacement = _targets(_interaction(addons=[addon], message_id="message-b"))[0]

    assert first.target_id == repeated.target_id
    assert replacement.target_id != first.target_id


def test_target_identity_changes_when_authoritative_economics_change() -> None:
    original = _targets(
        _interaction(
            addons=[
                MoneyItem(
                    name="Ceramic Shield",
                    amount="1299",
                    stated_mandatory=True,
                    evidence_id="ev-ceramic",
                )
            ]
        )
    )[0]
    changed = _targets(
        _interaction(
            addons=[
                MoneyItem(
                    name="Ceramic Shield",
                    amount="1499",
                    stated_mandatory=True,
                    evidence_id="ev-ceramic",
                )
            ]
        )
    )[0]

    assert changed.target_id != original.target_id


def test_noncurrent_or_failed_analysis_exposes_no_research_target() -> None:
    addon = MoneyItem(
        name="Ceramic Shield",
        amount="1299",
        stated_mandatory=True,
        evidence_id="ev-ceramic",
    )

    for status in (
        "AWAITING_RESPONSE",
        "RESPONSE_RECEIVED",
        "ANALYSIS_IN_PROGRESS",
        "ANALYSIS_FAILED",
    ):
        assert _targets(_interaction(addons=[addon], analysis_status=status)) == []
