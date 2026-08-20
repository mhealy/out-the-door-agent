from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.agent_run import AgentRun, RunPhase
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
from app.domain.vehicle import VehicleListing
from app.services.offer_comparison import build_comparison, project_offer


NOW = datetime(2026, 8, 19, 20, 0, tzinfo=timezone.utc)


def _run(run_id: str = "run-baytown", phase: RunPhase = "INTERACTION_COMPLETE") -> AgentRun:
    return AgentRun(
        id=run_id,
        run_id=run_id,
        thread_id=f"thread-{run_id}",
        vehicle_id=f"vehicle-{run_id}",
        phase=phase,
        initial_action_id=f"action-{run_id}",
        interaction_id=f"interaction-{run_id}",
        created_at=NOW,
        updated_at=NOW,
    )


def _listing(
    run_id: str = "run-baytown",
    *,
    advertised_price: str | None = "37800",
    distance_miles: float | None = 34,
) -> VehicleListing:
    return VehicleListing(
        id=f"vehicle-{run_id}",
        vin=f"VIN-{run_id}",
        stock_number=f"STOCK-{run_id}",
        year=2025,
        make="Hyundai",
        model="Tucson Hybrid",
        trim="Limited",
        condition="new",
        advertised_price=advertised_price,
        dealer_id=run_id.removeprefix("run-"),
        dealer_name=f"{run_id.removeprefix('run-').title()} Hyundai",
        distance_miles=distance_miles,
        source_url=f"https://example.test/{run_id}",
        source_provider="fixture",
    )


def _evidence(evidence_id: str, field_name: str, excerpt: str) -> Evidence:
    return Evidence(
        id=evidence_id,
        source_type="DEALER_EMAIL",
        source_id="message-1",
        field_name=field_name,
        excerpt=excerpt,
        created_at=NOW,
    )


def _interaction(
    run_id: str = "run-baytown",
    *,
    comparable: bool = True,
    claimed_otd: str | None = "40315",
    analysis_status: str = "ANALYZED",
) -> DealerInteraction:
    message = DealerMessage(
        id="message-1",
        dealer_id=run_id.removeprefix("run-"),
        vehicle_id=f"vehicle-{run_id}",
        subject="Written quote",
        body="Written OTD, add-on, and trade facts.",
        received_at=NOW,
        source_provider="fixture",
    )
    evidence = [
        _evidence("ev-otd", "claimed_otd", "Written OTD is $40,315."),
        _evidence("ev-addon", "addons", "Protection is mandatory at $500."),
        _evidence("ev-trade", "trade_required", "A qualifying trade is required."),
        _evidence(
            "ev-question",
            "unresolved_questions",
            "Dealer add-on status remains unresolved.",
        ),
    ]
    analysis = None
    if analysis_status == "ANALYZED":
        analysis = QuoteAnalysisResult(
            message=message,
            extraction=QuoteExtraction(
                vehicle_vin=f"VIN-{run_id}",
                claimed_otd=claimed_otd,
                addons=[
                    MoneyItem(
                        name="Protection",
                        amount="500",
                        stated_mandatory=True,
                        evidence_id="ev-addon",
                    )
                ],
                incentives=[
                    Incentive(
                        name="Trade assistance",
                        amount="1500",
                        eligibility_condition="Requires a qualifying trade",
                        requires_trade=True,
                        evidence_id="ev-trade",
                    )
                ],
                financing_required=False,
                trade_required=True,
                unresolved_questions=["Dealer add-on status remains unresolved."],
                evidence_ids=[item.id for item in evidence],
                extraction_confidence=1,
            ),
            evidence=evidence,
            assessment=QuoteAssessment(
                comparable=comparable,
                transparent=True,
                reconciled=False,
                missing_for_comparison=[] if comparable else ["addon_status"],
            ),
        )
    return DealerInteraction(
        id=f"interaction-{run_id}",
        initial_action_id=f"action-{run_id}",
        dealer_id=run_id.removeprefix("run-"),
        vehicle_id=f"vehicle-{run_id}",
        vehicle=OutreachVehicleSnapshot(
            id=f"vehicle-{run_id}",
            year=2025,
            make="Hyundai",
            model="Tucson Hybrid",
            trim="Limited",
            vin=f"VIN-{run_id}",
            stock_number=f"STOCK-{run_id}",
            dealer_id=run_id.removeprefix("run-"),
            dealer_name=f"{run_id.removeprefix('run-').title()} Hyundai",
        ),
        created_at=NOW,
        analysis_status=analysis_status,
        sent_followup_count=1,
        analysis=analysis,
        analysis_error_code=(
            "quote_extraction_failed" if analysis_status == "ANALYSIS_FAILED" else None
        ),
    )


def _offer(
    run_id: str,
    *,
    otd: str | None,
    advertised: str | None = "38000",
    distance: float | None = 20,
    comparable: bool = True,
    phase: RunPhase = "INTERACTION_COMPLETE",
):
    return project_offer(
        _run(run_id, phase),
        _interaction(run_id, comparable=comparable, claimed_otd=otd),
        _listing(run_id, advertised_price=advertised, distance_miles=distance),
    )


def test_projects_only_authoritative_facts_and_preserves_provenance() -> None:
    offer = _offer("run-baytown", otd="40315")

    assert offer.eligible is True
    assert offer.comparison_status == "VERIFIED"
    assert offer.claimed_otd == Decimal("40315")
    assert offer.reconciled is False  # Reconciliation does not tighten comparability.
    assert offer.inventory_provenance.model_dump() == {
        "source_type": "INVENTORY_LISTING",
        "listing_id": "vehicle-run-baytown",
        "source_provider": "fixture",
        "source_url": "https://example.test/run-baytown",
    }
    assert offer.claimed_otd_evidence_ids == ["ev-otd"]
    assert offer.mandatory_addons[0].evidence_id == "ev-addon"
    assert any(
        "trade" in condition.description.casefold()
        and "ev-trade" in condition.evidence_ids
        and "$1,500.00" in condition.description
        for condition in offer.conditions
    )
    assert {item.id for item in offer.evidence} >= {
        "ev-otd",
        "ev-addon",
        "ev-trade",
    }


@pytest.mark.parametrize(
    "phase",
    [
        "STARTING",
        "WAITING_FOR_APPROVAL",
        "WAITING_FOR_EXTERNAL_RESPONSE",
        "WAITING_FOR_ANALYSIS",
        "ANALYSIS_FAILED",
        "INTERACTION_INCOMPLETE_MAX_FOLLOWUPS",
        "INTERACTION_COMPLETE",
    ],
)
def test_analyzed_comparable_quote_overrides_nonblocking_run_projection(
    phase: RunPhase,
) -> None:
    offer = _offer("run-phase", otd="39000", phase=phase)

    assert offer.run_phase == phase
    assert offer.analysis_status == "ANALYZED"
    assert offer.comparable is True
    assert offer.claimed_otd == Decimal("39000")
    assert offer.comparison_status == "VERIFIED"
    assert offer.eligible is True


@pytest.mark.parametrize(
    ("phase", "expected_status"),
    [
        ("DELIVERY_UNCONFIRMED", "BLOCKED"),
        ("RUN_REJECTED", "REJECTED"),
        ("RUN_FAILED", "FAILED"),
    ],
)
def test_explicit_blocking_and_terminal_phases_remain_ineligible(
    phase: RunPhase,
    expected_status: str,
) -> None:
    offer = _offer("run-phase", otd="39000", phase=phase)

    assert offer.analysis_status == "ANALYZED"
    assert offer.comparable is True
    assert offer.claimed_otd == Decimal("39000")
    assert offer.comparison_status == expected_status
    assert offer.eligible is False


def test_current_interaction_analysis_failure_remains_failed() -> None:
    offer = project_offer(
        _run("run-analysis-failed", "WAITING_FOR_APPROVAL"),
        _interaction("run-analysis-failed", analysis_status="ANALYSIS_FAILED"),
        _listing("run-analysis-failed"),
    )

    assert offer.run_phase == "WAITING_FOR_APPROVAL"
    assert offer.analysis_status == "ANALYSIS_FAILED"
    assert offer.comparable is None
    assert offer.claimed_otd is None
    assert offer.comparison_status == "FAILED"
    assert offer.eligible is False


@pytest.mark.parametrize(
    ("phase", "analysis_status"),
    [
        ("ANALYSIS_FAILED", "AWAITING_RESPONSE"),
        ("INTERACTION_COMPLETE", "RESPONSE_RECEIVED"),
        ("INTERACTION_INCOMPLETE_MAX_FOLLOWUPS", "ANALYSIS_IN_PROGRESS"),
    ],
)
def test_current_pending_analysis_state_overrides_stale_run_projection(
    phase: RunPhase,
    analysis_status: str,
) -> None:
    offer = project_offer(
        _run("run-current-analysis", phase),
        _interaction("run-current-analysis", analysis_status=analysis_status),
        _listing("run-current-analysis"),
    )

    assert offer.run_phase == phase
    assert offer.analysis_status == analysis_status
    assert offer.comparison_status == "IN_PROGRESS"
    assert offer.eligible is False


def test_incomplete_assessment_keeps_stated_otd_visible_but_unranked() -> None:
    offer = _offer("run-incomplete", otd="39000", comparable=False)

    assert offer.claimed_otd == Decimal("39000")
    assert offer.comparable is False
    assert offer.comparison_status == "INCOMPLETE"
    assert offer.eligible is False


def test_missing_otd_is_never_estimated_from_advertised_price() -> None:
    offer = _offer("run-missing", otd=None, advertised="35000")

    assert offer.claimed_otd is None
    assert offer.eligible is False


def test_offer_without_analysis_preserves_unknown_comparability() -> None:
    run = _run("run-pending", "WAITING_FOR_EXTERNAL_RESPONSE")

    offer = project_offer(run, None, _listing("run-pending"))

    assert offer.comparable is None
    assert offer.transparent is None
    assert offer.reconciled is None
    assert offer.claimed_otd is None
    assert offer.comparison_status == "IN_PROGRESS"
    assert offer.eligible is False


def test_lower_verified_otd_wins_even_with_higher_advertised_price() -> None:
    cheaper_online = _offer("run-online", otd="42000", advertised="35000")
    cheaper_verified = _offer("run-verified", otd="40000", advertised="38000")

    result = build_comparison([cheaper_online, cheaper_verified])

    assert result.ranked_agent_run_ids == ["run-verified", "run-online"]
    assert result.offers[0].verified_rank == 1


def test_exact_otd_tie_prefers_known_shorter_distance_then_known_lower_listing() -> None:
    unknown = _offer("run-unknown", otd="40000", advertised=None, distance=None)
    farther = _offer("run-farther", otd="40000", advertised="37000", distance=30)
    nearer_higher_listing = _offer(
        "run-nearer-high", otd="40000", advertised="39000", distance=10
    )
    nearer_lower_listing = _offer(
        "run-nearer-low", otd="40000", advertised="38000", distance=10
    )

    result = build_comparison(
        [unknown, farther, nearer_higher_listing, nearer_lower_listing]
    )

    assert result.ranked_agent_run_ids == [
        "run-nearer-low",
        "run-nearer-high",
        "run-farther",
        "run-unknown",
    ]


def test_final_identifier_tie_breaker_is_stable() -> None:
    result = build_comparison(
        [
            _offer("run-z", otd="40000"),
            _offer("run-a", otd="40000"),
        ]
    )

    assert result.ranked_agent_run_ids == ["run-a", "run-z"]


def test_otd_tie_explanation_names_distance_tie_break_without_false_savings() -> None:
    result = build_comparison(
        [
            _offer("run-far", otd="40000", distance=30),
            _offer("run-near", otd="40000", distance=10),
        ]
    )

    assert result.recommendation is not None
    facts = " ".join(result.recommendation.explanation_facts).casefold()
    assert "tied" in facts
    assert "shorter known distance" in facts
    assert "$0.00 below" not in facts
    assert result.advertised_vs_verified.advertised_price_difference == Decimal("0")
    assert result.advertised_vs_verified.verified_otd_savings == Decimal("0")


def test_remaining_tie_explanation_names_advertised_price_tie_break() -> None:
    result = build_comparison(
        [
            _offer("run-higher-list", otd="40000", advertised="39000", distance=10),
            _offer("run-lower-list", otd="40000", advertised="38000", distance=10),
        ]
    )

    assert result.recommendation is not None
    facts = " ".join(result.recommendation.explanation_facts).casefold()
    assert "tied" in facts
    assert "lower known advertised price" in facts


def test_complete_tie_explanation_discloses_stable_identifier_ordering() -> None:
    result = build_comparison(
        [
            _offer("run-z", otd="40000", advertised="38000", distance=10),
            _offer("run-a", otd="40000", advertised="38000", distance=10),
        ]
    )

    assert result.recommendation is not None
    facts = " ".join(result.recommendation.explanation_facts).casefold()
    assert "stable agentrun identifier" in facts


def test_incomplete_offer_never_outranks_verified_offer() -> None:
    result = build_comparison(
        [
            _offer("run-incomplete", otd="1", comparable=False),
            _offer("run-verified", otd="40000"),
        ]
    )

    assert result.ranked_agent_run_ids == ["run-verified"]
    assert result.offers[1].claimed_otd == Decimal("1")
    assert result.offers[1].verified_rank is None


def test_canonical_decimal_savings_keep_advertised_and_otd_deltas_separate() -> None:
    baytown = _offer("run-baytown", otd="40315", advertised="37800", distance=34)
    houston = _offer("run-houston", otd="41780", advertised="37250", distance=12)
    katy = _offer(
        "run-katy",
        otd="40250",
        advertised="39500",
        distance=28,
        comparable=False,
    )

    result = build_comparison([katy, houston, baytown])

    assert result.recommendation is not None
    assert result.recommendation.recommended_agent_run_id == "run-baytown"
    assert result.recommendation.savings_vs_next_verified == Decimal("1465")
    assert result.recommendation.has_unresolved_alternatives is True
    assert result.advertised_vs_verified.advertised_price_difference == Decimal("550")
    assert result.advertised_vs_verified.verified_otd_savings == Decimal("1465")


def test_unresolved_lowest_listing_keeps_price_delta_without_inventing_otd_delta() -> None:
    result = build_comparison(
        [
            _offer("run-baytown", otd="40315", advertised="37800"),
            _offer(
                "run-katy",
                otd="40250",
                advertised="36000",
                comparable=False,
            ),
        ]
    )

    assert result.advertised_vs_verified.advertised_price_difference == Decimal("1800")
    assert result.advertised_vs_verified.lowest_advertised_verified_otd is None
    assert result.advertised_vs_verified.verified_otd_savings is None
    assert result.recommendation is not None
    facts = " ".join(result.recommendation.explanation_facts).casefold()
    assert "looked $1,800.00 cheaper" not in facts


def test_zero_eligible_offers_produces_no_false_recommendation() -> None:
    result = build_comparison(
        [
            _offer("run-a", otd=None),
            _offer("run-b", otd="1", comparable=False),
        ]
    )

    assert result.ranked_agent_run_ids == []
    assert result.recommendation is None


def test_one_eligible_offer_is_best_verified_without_fake_next_savings() -> None:
    result = build_comparison(
        [
            _offer("run-only", otd="40315"),
            _offer("run-unresolved", otd=None),
        ]
    )

    assert result.recommendation is not None
    assert result.recommendation.recommended_agent_run_id == "run-only"
    assert result.recommendation.next_best_verified_otd is None
    assert result.recommendation.savings_vs_next_verified is None
    assert result.recommendation.has_unresolved_alternatives is True


@pytest.mark.parametrize("phase", ["RUN_REJECTED", "RUN_FAILED"])
def test_terminal_stopped_offer_does_not_create_unresolved_caveat(
    phase: RunPhase,
) -> None:
    result = build_comparison(
        [
            _offer("run-only", otd="40315"),
            _offer("run-stopped", otd=None, phase=phase),
        ]
    )

    assert result.recommendation is not None
    assert result.recommendation.has_unresolved_alternatives is False
