from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.agent_run import AgentRun, RunPhase
from app.domain.approval import (
    ActionStatus,
    ApprovalRecord,
    OutreachProposal,
    OutreachVehicleSnapshot,
    ProposedAction,
)
from app.domain.comparison import (
    AdvertisedVsVerified,
    ComparedOffer,
    ComparisonResult,
    ComparisonStatus,
    InventoryProvenance,
    OfferRecommendation,
)
from app.domain.interaction import DealerInteraction, InteractionAnalysisStatus
from app.domain.message import DeliveryReceipt
from app.domain.purchase import PurchaseWorkspace
from app.domain.vehicle import VehicleListing
from app.services.purchases import PurchaseChildSource, derive_purchase_workspace


NOW = datetime(2026, 8, 19, 20, 0, tzinfo=timezone.utc)
GOAL = "Coordinate a verified written offer across selected dealers."


def _vehicle(index: int) -> VehicleListing:
    suffix = str(index)
    return VehicleListing(
        id=f"vehicle-{suffix}",
        vin=f"VIN-{suffix}",
        stock_number=f"STOCK-{suffix}",
        year=2025,
        make="Hyundai",
        model="Tucson Hybrid",
        trim="Limited",
        condition="new",
        advertised_price=Decimal("38000") + index,
        dealer_id=f"dealer-{suffix}",
        dealer_name=f"Dealer {suffix}",
        distance_miles=10 + index,
        source_url=f"https://example.test/inventory/vehicle-{suffix}",
        source_provider="fixture",
    )


def _run(
    index: int,
    *,
    phase: RunPhase,
    current_action_id: str | None = None,
) -> AgentRun:
    action_id = f"action-{index}"
    return AgentRun(
        id=f"run-{index}",
        run_id=f"run-{index}",
        thread_id=f"thread-{index}",
        vehicle_id=f"vehicle-{index}",
        phase=phase,
        initial_action_id=action_id,
        current_action_id=current_action_id or action_id,
        interaction_id=f"interaction-{index}",
        created_at=NOW,
        updated_at=NOW,
    )


def _proposal(index: int, status: ActionStatus) -> OutreachProposal:
    action_id = f"action-{index}"
    vehicle = _vehicle(index)
    proposed = ProposedAction(
        id=action_id,
        action_type="SEND_INITIAL_QUOTE_REQUEST",
        dealer_id=vehicle.dealer_id,
        vehicle_id=vehicle.id,
        recipient=f"quotes@dealer-{index}.example.test",
        subject="Written quote request",
        body="Please provide a complete written out-the-door quote.",
        reason="Obtain comparable written pricing.",
        requested_information=["claimed_otd"],
    )
    approval = None
    if status in {"APPROVED", "SENT", "SEND_FAILED"}:
        approval = ApprovalRecord(
            decision="APPROVED",
            decided_at=NOW,
            action_snapshot=proposed,
        )
    elif status == "REJECTED":
        approval = ApprovalRecord(
            decision="REJECTED",
            decided_at=NOW,
            action_snapshot=proposed,
        )
    delivery = (
        DeliveryReceipt(
            action_id=action_id,
            provider="purchase-unit-test",
            external_message_id=f"external-{index}",
            sent_at=NOW,
        )
        if status == "SENT"
        else None
    )
    return OutreachProposal(
        **proposed.model_dump(),
        requested_information_labels=["Written out-the-door total"],
        status=status,
        vehicle=OutreachVehicleSnapshot(
            id=vehicle.id,
            year=vehicle.year,
            make=vehicle.make,
            model=vehicle.model,
            trim=vehicle.trim,
            vin=vehicle.vin,
            stock_number=vehicle.stock_number,
            dealer_id=vehicle.dealer_id,
            dealer_name=vehicle.dealer_name,
        ),
        created_at=NOW,
        approval=approval,
        delivery=delivery,
    )


def _followup_proposal(
    index: int,
    status: ActionStatus,
    *,
    delivery_confirmed: bool,
) -> OutreachProposal:
    action_id = f"followup-{index}"
    proposal = _proposal(index, status)
    delivery = (
        DeliveryReceipt(
            action_id=action_id,
            provider="purchase-unit-test",
            external_message_id=f"followup-external-{index}",
            sent_at=NOW,
        )
        if delivery_confirmed
        else None
    )
    action_snapshot = ProposedAction(
        **{
            **proposal.model_dump(
                include={
                    "dealer_id",
                    "vehicle_id",
                    "recipient",
                    "subject",
                    "body",
                    "reason",
                    "requested_information",
                    "requires_approval",
                }
            ),
            "id": action_id,
            "action_type": "SEND_FOLLOWUP",
        }
    )
    return proposal.model_copy(
        update={
            "id": action_id,
            "action_type": "SEND_FOLLOWUP",
            "approval": (
                ApprovalRecord(
                    decision="APPROVED",
                    decided_at=NOW,
                    action_snapshot=action_snapshot,
                )
                if status in {"APPROVED", "SENT", "SEND_FAILED"}
                else proposal.approval
            ),
            "delivery": delivery,
        }
    )


def _interaction(
    index: int,
    *,
    analysis_status: InteractionAnalysisStatus,
    sent_followup_count: int = 0,
) -> DealerInteraction:
    vehicle = _vehicle(index)
    return DealerInteraction(
        id=f"interaction-{index}",
        initial_action_id=f"action-{index}",
        dealer_id=vehicle.dealer_id,
        vehicle_id=vehicle.id,
        vehicle=OutreachVehicleSnapshot(
            id=vehicle.id,
            year=vehicle.year,
            make=vehicle.make,
            model=vehicle.model,
            trim=vehicle.trim,
            vin=vehicle.vin,
            stock_number=vehicle.stock_number,
            dealer_id=vehicle.dealer_id,
            dealer_name=vehicle.dealer_name,
        ),
        created_at=NOW,
        analysis_status=analysis_status,
        sent_followup_count=sent_followup_count,
        analysis_error_code=(
            "quote_extraction_failed"
            if analysis_status == "ANALYSIS_FAILED"
            else None
        ),
    )


def _offer(
    index: int,
    *,
    status: ComparisonStatus,
    phase: RunPhase,
) -> ComparedOffer:
    vehicle = _vehicle(index)
    verified = status == "VERIFIED"
    analyzed = status in {"VERIFIED", "INCOMPLETE"}
    return ComparedOffer(
        agent_run_id=f"run-{index}",
        interaction_id=f"interaction-{index}",
        vehicle_id=vehicle.id,
        dealer_id=vehicle.dealer_id,
        dealer_name=vehicle.dealer_name,
        advertised_price=vehicle.advertised_price,
        distance_miles=vehicle.distance_miles,
        inventory_provenance=InventoryProvenance(
            listing_id=vehicle.id,
            source_provider=vehicle.source_provider,
            source_url=vehicle.source_url,
        ),
        claimed_otd=Decimal("40000") + index if analyzed else None,
        comparable=verified if analyzed else None,
        transparent=verified if analyzed else None,
        missing_for_comparison=[] if verified else ["claimed_otd"],
        run_phase=phase,
        analysis_status="ANALYZED" if analyzed else None,
        comparison_status=status,
        eligible=verified,
        verified_rank=None,
    )


def _comparison(*offers: ComparedOffer) -> ComparisonResult | None:
    if not offers:
        return None
    verified = [offer for offer in offers if offer.eligible]
    ranked = [
        offer.model_copy(update={"verified_rank": rank})
        for rank, offer in enumerate(verified, start=1)
    ]
    unresolved = [offer for offer in offers if not offer.eligible]
    ordered = [*ranked, *unresolved]
    recommendation = None
    if ranked:
        winner = ranked[0]
        recommendation = OfferRecommendation(
            recommended_agent_run_id=winner.agent_run_id,
            recommended_dealer_id=winner.dealer_id,
            recommended_dealer_name=winner.dealer_name,
            recommended_otd=winner.claimed_otd or Decimal("0"),
            next_best_verified_otd=(
                ranked[1].claimed_otd if len(ranked) > 1 else None
            ),
            savings_vs_next_verified=(
                ranked[1].claimed_otd - winner.claimed_otd
                if len(ranked) > 1
                and ranked[1].claimed_otd is not None
                and winner.claimed_otd is not None
                else None
            ),
            has_unresolved_alternatives=bool(unresolved),
        )
    return ComparisonResult(
        offers=ordered,
        ranked_agent_run_ids=[offer.agent_run_id for offer in ranked],
        recommendation=recommendation,
        advertised_vs_verified=AdvertisedVsVerified(
            recommended_agent_run_id=(
                ranked[0].agent_run_id if ranked else None
            ),
            recommended_advertised_price=(
                ranked[0].advertised_price if ranked else None
            ),
            recommended_verified_otd=(
                ranked[0].claimed_otd if ranked else None
            ),
        ),
    )


def _source(
    index: int,
    *,
    phase: RunPhase | None,
    action_status: ActionStatus | None = None,
    analysis_status: InteractionAnalysisStatus | None = None,
    comparison_status: ComparisonStatus | None = None,
    sent_followup_count: int = 0,
    creation_error_code: str | None = None,
    selection_index: int | None = None,
) -> PurchaseChildSource:
    run = _run(index, phase=phase) if phase is not None else None
    action = _proposal(index, action_status) if action_status is not None else None
    interaction = (
        _interaction(
            index,
            analysis_status=analysis_status,
            sent_followup_count=sent_followup_count,
        )
        if analysis_status is not None
        else None
    )
    return PurchaseChildSource(
        selection_index=index if selection_index is None else selection_index,
        vehicle=_vehicle(index),
        agent_run=run,
        initial_action=action,
        current_action=action,
        interaction=interaction,
        creation_error_code=creation_error_code,
    )


def _workspace(
    children: list[PurchaseChildSource],
    comparison: ComparisonResult | None = None,
) -> PurchaseWorkspace:
    return derive_purchase_workspace(
        purchase_id="purchase-1",
        goal=GOAL,
        children=children,
        comparison=comparison,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.parametrize(
    (
        "source",
        "offer",
        "expected_status",
        "expected_action_id",
        "expected_active",
    ),
    [
        (
            _source(
                1,
                phase="WAITING_FOR_APPROVAL",
                action_status="PENDING_APPROVAL",
            ),
            None,
            "APPROVAL_REQUIRED",
            "action-1",
            True,
        ),
        (
            _source(
                2,
                phase="WAITING_FOR_APPROVAL",
                action_status="SENT",
                analysis_status="AWAITING_RESPONSE",
            ),
            None,
            "WAITING_FOR_DEALER",
            None,
            True,
        ),
        (
            _source(
                3,
                phase="INTERACTION_COMPLETE",
                action_status="SENT",
                analysis_status="RESPONSE_RECEIVED",
            ),
            None,
            "WAITING_FOR_ANALYSIS",
            None,
            True,
        ),
        (
            _source(
                4,
                phase="INTERACTION_COMPLETE",
                action_status="SENT",
                analysis_status="ANALYSIS_IN_PROGRESS",
            ),
            None,
            "WAITING_FOR_ANALYSIS",
            None,
            True,
        ),
        (
            _source(
                5,
                phase="INTERACTION_COMPLETE",
                action_status="SENT",
                analysis_status="ANALYSIS_FAILED",
            ),
            _offer(5, status="FAILED", phase="INTERACTION_COMPLETE"),
            "ANALYSIS_FAILED",
            None,
            False,
        ),
        (
            _source(
                6,
                phase="WAITING_FOR_APPROVAL",
                action_status="APPROVED",
            ),
            _offer(6, status="BLOCKED", phase="WAITING_FOR_APPROVAL"),
            "DELIVERY_UNCONFIRMED",
            "action-6",
            False,
        ),
        (
            _source(
                7,
                phase="RUN_REJECTED",
                action_status="REJECTED",
            ),
            _offer(7, status="REJECTED", phase="RUN_REJECTED"),
            "RUN_REJECTED",
            None,
            False,
        ),
        (
            _source(
                8,
                phase="RUN_FAILED",
                action_status="SEND_FAILED",
            ),
            _offer(8, status="FAILED", phase="RUN_FAILED"),
            "RUN_FAILED",
            None,
            False,
        ),
        (
            _source(
                9,
                phase="INTERACTION_INCOMPLETE_MAX_FOLLOWUPS",
                action_status="SENT",
                analysis_status="ANALYZED",
                sent_followup_count=2,
            ),
            _offer(
                9,
                status="INCOMPLETE",
                phase="INTERACTION_INCOMPLETE_MAX_FOLLOWUPS",
            ),
            "OFFER_INCOMPLETE",
            None,
            False,
        ),
        (
            _source(
                10,
                phase="WAITING_FOR_EXTERNAL_RESPONSE",
                action_status="SENT",
                analysis_status="ANALYZED",
            ),
            _offer(
                10,
                status="INCOMPLETE",
                phase="WAITING_FOR_EXTERNAL_RESPONSE",
            ),
            "OFFER_INCOMPLETE",
            None,
            True,
        ),
        (
            _source(
                11,
                phase="WAITING_FOR_APPROVAL",
                action_status="SENT",
                analysis_status="ANALYZED",
            ),
            _offer(
                11,
                status="VERIFIED",
                phase="WAITING_FOR_APPROVAL",
            ),
            "OFFER_VERIFIED",
            None,
            False,
        ),
    ],
    ids=[
        "pending-action-over-stale-phase",
        "sent-action-waits-for-dealer-over-stale-phase",
        "received-response-over-complete-phase",
        "analysis-in-progress-over-complete-phase",
        "analysis-failure-over-complete-phase",
        "approved-without-delivery",
        "rejected-run",
        "failed-run",
        "max-followup-incomplete-is-settled",
        "incomplete-with-followup-capacity-is-active",
        "verified-economics-over-stale-wait",
    ],
)
def test_workflow_attention_uses_authoritative_action_and_interaction_state(
    source: PurchaseChildSource,
    offer: ComparedOffer | None,
    expected_status: str,
    expected_action_id: str | None,
    expected_active: bool,
) -> None:
    comparison = _comparison(offer) if offer is not None else None

    workspace = _workspace([source], comparison)

    child = workspace.children[0]
    assert child.workflow_status == expected_status
    assert child.active_unresolved is expected_active
    assert child.comparison_status == (
        offer.comparison_status if offer is not None else None
    )
    if expected_status == "OFFER_VERIFIED":
        assert workspace.attention_items == []
    else:
        assert len(workspace.attention_items) == 1
        attention = workspace.attention_items[0]
        assert attention.category == expected_status
        assert attention.action_id == expected_action_id
        assert attention.message.strip()


@pytest.mark.parametrize("phase", [None, "STARTING"])
def test_missing_or_unadvanced_child_requires_recovery(
    phase: RunPhase | None,
) -> None:
    source = _source(
        1,
        phase=phase,
        creation_error_code="child_advancement_failed",
    )

    workspace = _workspace([source])

    assert workspace.setup_status == "RECOVERY_REQUIRED"
    child = workspace.children[0]
    assert child.workflow_status == "RECOVERY_REQUIRED"
    assert child.creation_error_code == "child_advancement_failed"
    assert child.active_unresolved is True
    assert workspace.attention_items[0].category == "RECOVERY_REQUIRED"
    assert workspace.attention_items[0].action_id is None


def test_stale_creation_error_does_not_override_a_safely_advanced_child() -> None:
    source = _source(
        1,
        phase="WAITING_FOR_APPROVAL",
        action_status="PENDING_APPROVAL",
        creation_error_code="agent_run_advancement_failed",
    )

    workspace = _workspace([source])

    assert workspace.setup_status == "READY"
    child = workspace.children[0]
    assert child.workflow_status == "APPROVAL_REQUIRED"
    assert child.creation_error_code is None
    assert workspace.attention_items[0].category == "APPROVAL_REQUIRED"


@pytest.mark.parametrize(
    ("delivery_confirmed", "expected_status", "expected_active"),
    [
        (True, "WAITING_FOR_DEALER", True),
        (False, "DELIVERY_UNCONFIRMED", False),
    ],
)
def test_latest_followup_delivery_precedes_older_incomplete_analysis(
    delivery_confirmed: bool,
    expected_status: str,
    expected_active: bool,
) -> None:
    source = _source(
        1,
        phase="INTERACTION_COMPLETE",
        action_status="SENT",
        analysis_status="ANALYZED",
    )
    source = PurchaseChildSource(
        **{
            **source.__dict__,
            "current_action": _followup_proposal(
                1,
                "SENT",
                delivery_confirmed=delivery_confirmed,
            ),
        }
    )
    comparison = _comparison(
        _offer(1, status="INCOMPLETE", phase="INTERACTION_COMPLETE")
    )

    workspace = _workspace([source], comparison)

    child = workspace.children[0]
    assert child.workflow_status == expected_status
    assert child.active_unresolved is expected_active
    assert workspace.attention_items[0].category == expected_status


def test_approval_attention_exposes_only_the_exact_authoritative_action() -> None:
    approval = _source(
        1,
        phase="WAITING_FOR_APPROVAL",
        action_status="PENDING_APPROVAL",
    )
    waiting = _source(
        2,
        phase="WAITING_FOR_EXTERNAL_RESPONSE",
        action_status="SENT",
        analysis_status="AWAITING_RESPONSE",
    )

    workspace = _workspace([approval, waiting])

    approval_attention = next(
        item
        for item in workspace.attention_items
        if item.category == "APPROVAL_REQUIRED"
    )
    assert approval_attention.action_id == "action-1"
    assert approval_attention.requires_buyer_action is True
    waiting_attention = next(
        item
        for item in workspace.attention_items
        if item.category == "WAITING_FOR_DEALER"
    )
    assert waiting_attention.action_id is None
    assert waiting_attention.requires_buyer_action is False


def test_counts_use_selected_intents_and_authoritative_child_facts() -> None:
    pending = _source(
        1,
        phase="WAITING_FOR_APPROVAL",
        action_status="PENDING_APPROVAL",
        selection_index=4,
    )
    analyzing = _source(
        2,
        phase="WAITING_FOR_ANALYSIS",
        action_status="SENT",
        analysis_status="ANALYSIS_IN_PROGRESS",
        selection_index=1,
    )
    verified = _source(
        3,
        phase="INTERACTION_COMPLETE",
        action_status="SENT",
        analysis_status="ANALYZED",
        selection_index=0,
    )
    incomplete = _source(
        4,
        phase="INTERACTION_INCOMPLETE_MAX_FOLLOWUPS",
        action_status="SENT",
        analysis_status="ANALYZED",
        sent_followup_count=2,
        selection_index=3,
    )
    missing = _source(
        5,
        phase=None,
        creation_error_code="child_creation_failed",
        selection_index=2,
    )
    comparison = _comparison(
        _offer(3, status="VERIFIED", phase="INTERACTION_COMPLETE"),
        _offer(
            4,
            status="INCOMPLETE",
            phase="INTERACTION_INCOMPLETE_MAX_FOLLOWUPS",
        ),
        _offer(2, status="IN_PROGRESS", phase="WAITING_FOR_ANALYSIS"),
        _offer(1, status="IN_PROGRESS", phase="WAITING_FOR_APPROVAL"),
    )

    workspace = _workspace(
        [pending, analyzing, verified, incomplete, missing],
        comparison,
    )

    assert workspace.counts.model_dump() == {
        "selected_vehicles": 5,
        "linked_children": 4,
        "quote_requests_prepared": 4,
        "responses_analyzed": 2,
        "verified_offers": 1,
        "incomplete_offers": 1,
        "pending_approvals": 1,
    }
    assert workspace.setup_status == "RECOVERY_REQUIRED"


@pytest.mark.parametrize(
    ("verified_count", "extra_status", "expected"),
    [
        (0, None, "GATHERING_OFFERS"),
        (1, None, "COMPARISON_AVAILABLE"),
        (2, "APPROVAL_REQUIRED", "COMPARISON_AVAILABLE"),
        (2, "WAITING_FOR_DEALER", "COMPARISON_AVAILABLE"),
        (2, "WAITING_FOR_ANALYSIS", "COMPARISON_AVAILABLE"),
        (2, "RECOVERY_REQUIRED", "COMPARISON_AVAILABLE"),
        (2, "OFFER_INCOMPLETE_ACTIVE", "COMPARISON_AVAILABLE"),
        (2, "DELIVERY_UNCONFIRMED", "DECISION_READY"),
        (2, "ANALYSIS_FAILED", "DECISION_READY"),
        (2, "RUN_REJECTED", "DECISION_READY"),
        (2, "RUN_FAILED", "DECISION_READY"),
        (2, "MAX_FOLLOWUPS", "DECISION_READY"),
    ],
)
def test_decision_status_requires_two_verified_and_no_active_unresolved_work(
    verified_count: int,
    extra_status: str | None,
    expected: str,
) -> None:
    children: list[PurchaseChildSource] = []
    offers: list[ComparedOffer] = []
    for index in range(verified_count):
        child_index = index + 1
        children.append(
            _source(
                child_index,
                phase="INTERACTION_COMPLETE",
                action_status="SENT",
                analysis_status="ANALYZED",
            )
        )
        offers.append(
            _offer(
                child_index,
                status="VERIFIED",
                phase="INTERACTION_COMPLETE",
            )
        )

    # Purchase creation requires at least two selections. Keep the zero/one
    # verified cases realistic instead of exercising impossible empty or
    # single-child aggregates.
    if verified_count == 0 and extra_status is None:
        for child_index in (1, 2):
            children.append(
                _source(
                    child_index,
                    phase="WAITING_FOR_APPROVAL",
                    action_status="PENDING_APPROVAL",
                )
            )
            offers.append(
                _offer(
                    child_index,
                    status="IN_PROGRESS",
                    phase="WAITING_FOR_APPROVAL",
                )
            )
    elif verified_count == 1 and extra_status is None:
        children.append(
            _source(
                5,
                phase="RUN_REJECTED",
                action_status="REJECTED",
            )
        )
        offers.append(_offer(5, status="REJECTED", phase="RUN_REJECTED"))

    if extra_status is not None:
        index = 5
        if extra_status == "APPROVAL_REQUIRED":
            children.append(
                _source(
                    index,
                    phase="WAITING_FOR_APPROVAL",
                    action_status="PENDING_APPROVAL",
                )
            )
            offers.append(
                _offer(index, status="IN_PROGRESS", phase="WAITING_FOR_APPROVAL")
            )
        elif extra_status == "WAITING_FOR_DEALER":
            children.append(
                _source(
                    index,
                    phase="WAITING_FOR_EXTERNAL_RESPONSE",
                    action_status="SENT",
                    analysis_status="AWAITING_RESPONSE",
                )
            )
            offers.append(
                _offer(
                    index,
                    status="IN_PROGRESS",
                    phase="WAITING_FOR_EXTERNAL_RESPONSE",
                )
            )
        elif extra_status == "WAITING_FOR_ANALYSIS":
            children.append(
                _source(
                    index,
                    phase="WAITING_FOR_ANALYSIS",
                    action_status="SENT",
                    analysis_status="ANALYSIS_IN_PROGRESS",
                )
            )
            offers.append(
                _offer(index, status="IN_PROGRESS", phase="WAITING_FOR_ANALYSIS")
            )
        elif extra_status == "RECOVERY_REQUIRED":
            children.append(
                _source(
                    index,
                    phase=None,
                    creation_error_code="child_creation_failed",
                )
            )
        elif extra_status == "OFFER_INCOMPLETE_ACTIVE":
            children.append(
                _source(
                    index,
                    phase="WAITING_FOR_EXTERNAL_RESPONSE",
                    action_status="SENT",
                    analysis_status="ANALYZED",
                    sent_followup_count=0,
                )
            )
            offers.append(
                _offer(
                    index,
                    status="INCOMPLETE",
                    phase="WAITING_FOR_EXTERNAL_RESPONSE",
                )
            )
        elif extra_status == "DELIVERY_UNCONFIRMED":
            children.append(
                _source(
                    index,
                    phase="DELIVERY_UNCONFIRMED",
                    action_status="APPROVED",
                )
            )
            offers.append(
                _offer(index, status="BLOCKED", phase="DELIVERY_UNCONFIRMED")
            )
        elif extra_status == "ANALYSIS_FAILED":
            children.append(
                _source(
                    index,
                    phase="ANALYSIS_FAILED",
                    action_status="SENT",
                    analysis_status="ANALYSIS_FAILED",
                )
            )
            offers.append(
                _offer(index, status="FAILED", phase="ANALYSIS_FAILED")
            )
        elif extra_status == "RUN_REJECTED":
            children.append(
                _source(
                    index,
                    phase="RUN_REJECTED",
                    action_status="REJECTED",
                )
            )
            offers.append(
                _offer(index, status="REJECTED", phase="RUN_REJECTED")
            )
        elif extra_status == "RUN_FAILED":
            children.append(
                _source(
                    index,
                    phase="RUN_FAILED",
                    action_status="SEND_FAILED",
                )
            )
            offers.append(_offer(index, status="FAILED", phase="RUN_FAILED"))
        elif extra_status == "MAX_FOLLOWUPS":
            children.append(
                _source(
                    index,
                    phase="INTERACTION_INCOMPLETE_MAX_FOLLOWUPS",
                    action_status="SENT",
                    analysis_status="ANALYZED",
                    sent_followup_count=2,
                )
            )
            offers.append(
                _offer(
                    index,
                    status="INCOMPLETE",
                    phase="INTERACTION_INCOMPLETE_MAX_FOLLOWUPS",
                )
            )

    workspace = _workspace(children, _comparison(*offers))

    assert workspace.decision_status == expected


def test_child_and_attention_order_follow_durable_selection_order() -> None:
    third = _source(
        3,
        phase="WAITING_FOR_EXTERNAL_RESPONSE",
        action_status="SENT",
        analysis_status="AWAITING_RESPONSE",
        selection_index=2,
    )
    first = _source(
        1,
        phase="WAITING_FOR_APPROVAL",
        action_status="PENDING_APPROVAL",
        selection_index=0,
    )
    second = _source(
        2,
        phase="WAITING_FOR_ANALYSIS",
        action_status="SENT",
        analysis_status="ANALYSIS_IN_PROGRESS",
        selection_index=1,
    )

    first_result = _workspace([third, first, second])
    second_result = _workspace([second, third, first])

    assert [child.vehicle.id for child in first_result.children] == [
        "vehicle-1",
        "vehicle-2",
        "vehicle-3",
    ]
    assert [item.vehicle_id for item in first_result.attention_items] == [
        "vehicle-1",
        "vehicle-2",
        "vehicle-3",
    ]
    assert first_result == second_result
