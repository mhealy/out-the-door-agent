from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.agent.graph import AgentWorkflowService
from app.config import get_settings
from app.dependencies import (
    get_dealer_message_provider,
    get_followup_drafter,
    get_inventory_provider,
    get_messaging_provider,
    get_quote_extractor,
)
from app.domain.followup import (
    FollowupDraft,
    FollowupDraftContext,
    FollowupDraftRequest,
)
from app.domain.message import DealerMessage, DeliveryReceipt, OutboundDealerMessage
from app.main import app
from app.persistence.db import build_engine, create_schema, get_session
from app.providers.dealer_messages import FixtureDealerMessageProvider
from app.providers.inventory import FixtureInventoryProvider
from app.providers.quote_extraction import QuoteExtractorOutput


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RAW_CASE_ID_BY_BODY = {
    record["body"]: record["id"]
    for record in json.loads(
        (
            REPOSITORY_ROOT / "demo/dealer_messages/quote_analysis_cases.json"
        ).read_text(encoding="utf-8")
    )
}
EXPECTED_OUTPUT_BY_CASE_ID = {
    record["case_id"]: QuoteExtractorOutput.model_validate(
        {
            "extraction": record["extraction"],
            "evidence": record["evidence"],
        }
    )
    for record in json.loads(
        (
            REPOSITORY_ROOT / "demo/expected/quote_analysis_expected.json"
        ).read_text(encoding="utf-8")
    )
}


class ExpectedFixtureExtractor:
    async def extract(self, message: DealerMessage) -> QuoteExtractorOutput:
        case_id = RAW_CASE_ID_BY_BODY[message.body]
        return EXPECTED_OUTPUT_BY_CASE_ID[case_id].model_copy(deep=True)


class RecordingMessagingProvider:
    def __init__(self) -> None:
        self.calls: list[OutboundDealerMessage] = []

    async def send(self, message: OutboundDealerMessage) -> DeliveryReceipt:
        self.calls.append(message)
        return DeliveryReceipt(
            action_id=message.action_id,
            provider="offer-comparison-test",
            external_message_id=f"comparison-{message.action_id}",
            sent_at=datetime.now(timezone.utc),
        )


class RecordingFollowupDrafter:
    def __init__(self) -> None:
        self.calls: list[FollowupDraftContext] = []

    async def draft(self, context: FollowupDraftContext) -> FollowupDraft:
        self.calls.append(context)
        return FollowupDraft(
            subject="Written quote clarification",
            requests=[
                FollowupDraftRequest(
                    requirement_id=requirement.id,
                    text=requirement.wording_options[0],
                )
                for requirement in context.requirements
            ],
        )


@dataclass(frozen=True)
class ComparisonHarness:
    messaging: RecordingMessagingProvider
    drafter: RecordingFollowupDrafter


@pytest.fixture
def comparison_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, ComparisonHarness]]:
    application_database = tmp_path / "offer-comparison.db"
    checkpoint_database = tmp_path / "offer-comparison-checkpoints.db"
    engine = build_engine(f"sqlite:///{application_database}")
    create_schema(engine)
    test_session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    messaging = RecordingMessagingProvider()
    drafter = RecordingFollowupDrafter()
    inventory = FixtureInventoryProvider()
    dealer_messages = FixtureDealerMessageProvider()

    def override_session() -> Iterator[Session]:
        with test_session_factory() as session:
            yield session

    monkeypatch.setenv(
        "OTD_LANGGRAPH_CHECKPOINT_PATH",
        str(checkpoint_database),
    )
    get_settings.cache_clear()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_inventory_provider] = lambda: inventory
    app.dependency_overrides[get_dealer_message_provider] = lambda: dealer_messages
    app.dependency_overrides[get_messaging_provider] = lambda: messaging
    app.dependency_overrides[get_quote_extractor] = ExpectedFixtureExtractor
    app.dependency_overrides[get_followup_drafter] = lambda: drafter
    try:
        with TestClient(app) as client:
            yield client, ComparisonHarness(messaging=messaging, drafter=drafter)
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
        engine.dispose()


def _create_run_at_latest_authoritative_state(
    client: TestClient,
    vehicle_id: str,
) -> dict[str, object]:
    created_response = client.post(
        "/agent-runs",
        json={"vehicle_id": vehicle_id},
    )
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()

    approved_response = client.post(
        f"/outreach/proposals/{created['initial_action_id']}/approve",
        json={},
    )
    assert approved_response.status_code == 200, approved_response.text
    assert approved_response.json()["status"] == "SENT"

    waiting_response = client.post(
        f"/agent-runs/{created['id']}/resume",
        json={},
    )
    assert waiting_response.status_code == 200, waiting_response.text
    assert waiting_response.json()["phase"] == "WAITING_FOR_EXTERNAL_RESPONSE"

    release_response = client.post(
        f"/outreach/proposals/{created['initial_action_id']}/demo-response",
        json={},
    )
    assert release_response.status_code == 200, release_response.text
    assert release_response.json()["analysis_status"] == "ANALYZED"

    latest_response = client.post(
        f"/agent-runs/{created['id']}/resume",
        json={},
    )
    assert latest_response.status_code == 200, latest_response.text
    return latest_response.json()


@pytest.mark.parametrize(
    "agent_run_ids",
    [
        [],
        ["only-one-run"],
        ["duplicate-run", "duplicate-run"],
    ],
)
def test_comparison_requires_at_least_two_unique_run_ids(
    comparison_client: tuple[TestClient, ComparisonHarness],
    agent_run_ids: list[str],
) -> None:
    client, _ = comparison_client

    response = client.post(
        "/offer-comparisons",
        json={"agent_run_ids": agent_run_ids},
    )

    assert response.status_code == 422


def test_comparison_rejects_browser_supplied_economics(
    comparison_client: tuple[TestClient, ComparisonHarness],
) -> None:
    client, _ = comparison_client

    response = client.post(
        "/offer-comparisons",
        json={
            "agent_run_ids": ["run-a", "run-b"],
            "dealer_id": "browser-controlled-dealer",
            "claimed_otd": "1.00",
            "comparable": True,
            "recommended_agent_run_id": "run-a",
        },
    )

    assert response.status_code == 422


def test_comparison_rejects_an_unknown_authoritative_run(
    comparison_client: tuple[TestClient, ComparisonHarness],
) -> None:
    client, _ = comparison_client

    response = client.post(
        "/offer-comparisons",
        json={"agent_run_ids": ["unknown-run-a", "unknown-run-b"]},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "agent_run_not_found"


def test_canonical_runs_produce_a_read_only_evidence_backed_comparison(
    comparison_client: tuple[TestClient, ComparisonHarness],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, harness = comparison_client
    baytown_run = _create_run_at_latest_authoritative_state(
        client,
        "baytown-blue",
    )
    houston_run = _create_run_at_latest_authoritative_state(
        client,
        "houston-white",
    )
    katy_run = _create_run_at_latest_authoritative_state(client, "katy-blue")

    assert baytown_run["phase"] == "INTERACTION_COMPLETE"
    assert houston_run["phase"] == "INTERACTION_COMPLETE"
    assert katy_run["phase"] == "WAITING_FOR_APPROVAL"
    assert len(harness.messaging.calls) == 3
    assert len(harness.drafter.calls) == 1

    run_ids = [
        str(katy_run["id"]),
        str(houston_run["id"]),
        str(baytown_run["id"]),
    ]
    before_runs = {
        run_id: client.get(f"/agent-runs/{run_id}").json()
        for run_id in run_ids
    }
    messaging_calls_before = list(harness.messaging.calls)
    drafting_calls_before = list(harness.drafter.calls)

    async def unexpected_resume(
        self: AgentWorkflowService,
        run_id: str,
    ) -> object:
        del self, run_id
        raise AssertionError("Comparison must never resume an AgentRun.")

    monkeypatch.setattr(AgentWorkflowService, "resume", unexpected_resume)

    first_response = client.post(
        "/offer-comparisons",
        json={"agent_run_ids": run_ids},
    )
    second_response = client.post(
        "/offer-comparisons",
        json={"agent_run_ids": run_ids},
    )

    assert first_response.status_code == 200, first_response.text
    assert second_response.status_code == 200, second_response.text
    comparison = first_response.json()
    assert second_response.json() == comparison

    offers = comparison["offers"]
    assert [offer["dealer_id"] for offer in offers] == [
        "baytown",
        "houston",
        "katy",
    ]
    assert comparison["ranked_agent_run_ids"] == [
        baytown_run["id"],
        houston_run["id"],
    ]

    baytown, houston, katy = offers
    assert baytown["agent_run_id"] == baytown_run["id"]
    assert baytown["advertised_price"] == "37800"
    assert baytown["distance_miles"] == 34
    assert baytown["claimed_otd"] == "40315"
    assert baytown["comparable"] is True
    assert baytown["transparent"] is True
    assert baytown["reconciled"] is True
    assert baytown["comparison_status"] == "VERIFIED"
    assert baytown["eligible"] is True
    assert baytown["verified_rank"] == 1
    assert baytown["mandatory_addons"] == []
    assert baytown["sent_followup_count"] == 0
    assert baytown["run_phase"] == "INTERACTION_COMPLETE"
    assert baytown["analysis_status"] == "ANALYZED"
    assert baytown["inventory_provenance"] == {
        "source_type": "INVENTORY_LISTING",
        "listing_id": "baytown-blue",
        "source_provider": "fixture",
        "source_url": "https://example.test/inventory/baytown-blue",
    }
    assert baytown["claimed_otd_evidence_ids"] == ["ev-no-addons-otd"]

    assert houston["agent_run_id"] == houston_run["id"]
    assert houston["advertised_price"] == "37250"
    assert houston["distance_miles"] == 12
    assert houston["claimed_otd"] == "41780"
    assert houston["comparable"] is True
    assert houston["comparison_status"] == "VERIFIED"
    assert houston["eligible"] is True
    assert houston["verified_rank"] == 2
    assert houston["mandatory_addons"] == [
        {
            "name": "Ceramic Shield",
            "amount": "1299",
            "stated_mandatory": True,
            "evidence_id": "ev-addons-ceramic",
        },
        {
            "name": "SecureTrack theft recovery",
            "amount": "596",
            "stated_mandatory": True,
            "evidence_id": "ev-addons-theft",
        },
    ]
    assert houston["claimed_otd_evidence_ids"] == ["ev-addons-otd"]
    assert houston["inventory_provenance"] == {
        "source_type": "INVENTORY_LISTING",
        "listing_id": "houston-white",
        "source_provider": "fixture",
        "source_url": "https://example.test/inventory/houston-white",
    }

    assert katy["agent_run_id"] == katy_run["id"]
    assert katy["advertised_price"] == "39500"
    assert katy["distance_miles"] == 28
    assert katy["claimed_otd"] == "40250"
    assert katy["comparable"] is False
    assert katy["missing_for_comparison"] == [
        "vehicle_identity",
        "addon_status",
    ]
    assert katy["comparison_status"] == "INCOMPLETE"
    assert katy["eligible"] is False
    assert katy["verified_rank"] is None
    assert katy["sent_followup_count"] == 0
    assert katy["run_phase"] == "WAITING_FOR_APPROVAL"
    assert katy["analysis_status"] == "ANALYZED"
    assert any(
        "trade" in condition["description"].casefold()
        and "ev-trade-required" in condition["evidence_ids"]
        for condition in katy["conditions"]
    )
    assert katy["claimed_otd_evidence_ids"] == ["ev-trade-otd"]
    assert katy["inventory_provenance"] == {
        "source_type": "INVENTORY_LISTING",
        "listing_id": "katy-blue",
        "source_provider": "fixture",
        "source_url": "https://example.test/inventory/katy-blue",
    }

    evidence_by_id = {
        offer["dealer_id"]: {
            evidence["id"]: evidence for evidence in offer["evidence"]
        }
        for offer in offers
    }
    baytown_otd_evidence = evidence_by_id["baytown"]["ev-no-addons-otd"]
    assert baytown_otd_evidence["source_type"] == "DEALER_EMAIL"
    assert baytown_otd_evidence["field_name"] == "claimed_otd"
    assert "written cash OTD is $40,315" in baytown_otd_evidence["excerpt"]
    assert evidence_by_id["houston"]["ev-addons-ceramic"][
        "field_name"
    ] == "addons"
    assert evidence_by_id["houston"]["ev-addons-theft"][
        "field_name"
    ] == "addons"
    assert evidence_by_id["katy"]["ev-trade-required"][
        "field_name"
    ] == "trade_required"

    recommendation = comparison["recommendation"]
    assert recommendation["recommended_agent_run_id"] == baytown_run["id"]
    assert recommendation["recommended_dealer_id"] == "baytown"
    assert recommendation["recommended_otd"] == "40315"
    assert recommendation["next_best_verified_otd"] == "41780"
    assert recommendation["savings_vs_next_verified"] == "1465"
    assert recommendation["has_unresolved_alternatives"] is True
    explanation = " ".join(recommendation["explanation_facts"]).casefold()
    assert "baytown" in explanation
    assert "lowest verified" in explanation
    assert "katy" in explanation
    assert "incomplete" in explanation

    assert comparison["advertised_vs_verified"] == {
        "lowest_advertised_agent_run_id": houston_run["id"],
        "lowest_advertised_price": "37250",
        "lowest_advertised_verified_otd": "41780",
        "recommended_agent_run_id": baytown_run["id"],
        "recommended_advertised_price": "37800",
        "recommended_verified_otd": "40315",
        "advertised_price_difference": "550",
        "verified_otd_savings": "1465",
    }

    after_runs = {
        run_id: client.get(f"/agent-runs/{run_id}").json()
        for run_id in run_ids
    }
    assert after_runs == before_runs
    assert harness.messaging.calls == messaging_calls_before
    assert harness.drafter.calls == drafting_calls_before


def test_comparison_reads_analyzed_interaction_without_resuming_stale_run_projection(
    comparison_client: tuple[TestClient, ComparisonHarness],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, harness = comparison_client
    stale_response = client.post(
        "/agent-runs",
        json={"vehicle_id": "baytown-blue"},
    )
    assert stale_response.status_code == 201, stale_response.text
    stale_run = stale_response.json()
    sent_response = client.post(
        f"/outreach/proposals/{stale_run['initial_action_id']}/approve",
        json={},
    )
    assert sent_response.status_code == 200, sent_response.text
    analyzed_response = client.post(
        f"/outreach/proposals/{stale_run['initial_action_id']}/demo-response",
        json={},
    )
    assert analyzed_response.status_code == 200, analyzed_response.text
    assert analyzed_response.json()["analysis_status"] == "ANALYZED"

    unchanged_run = client.get(f"/agent-runs/{stale_run['id']}").json()
    assert unchanged_run["phase"] == "WAITING_FOR_APPROVAL"
    assert unchanged_run["interaction_id"] is None

    houston_run = _create_run_at_latest_authoritative_state(
        client,
        "houston-white",
    )
    messaging_calls_before = list(harness.messaging.calls)
    drafting_calls_before = list(harness.drafter.calls)

    async def unexpected_resume(
        self: AgentWorkflowService,
        run_id: str,
    ) -> object:
        del self, run_id
        raise AssertionError("Comparison must not repair a stale run projection.")

    monkeypatch.setattr(AgentWorkflowService, "resume", unexpected_resume)
    response = client.post(
        "/offer-comparisons",
        json={
            "agent_run_ids": [stale_run["id"], houston_run["id"]],
        },
    )

    assert response.status_code == 200, response.text
    baytown = next(
        offer for offer in response.json()["offers"]
        if offer["agent_run_id"] == stale_run["id"]
    )
    assert baytown["run_phase"] == "WAITING_FOR_APPROVAL"
    assert baytown["analysis_status"] == "ANALYZED"
    assert baytown["claimed_otd"] == "40315"
    assert baytown["comparable"] is True
    assert baytown["comparison_status"] == "VERIFIED"
    assert baytown["eligible"] is True
    assert response.json()["ranked_agent_run_ids"][0] == stale_run["id"]
    assert (
        response.json()["recommendation"]["recommended_agent_run_id"]
        == stale_run["id"]
    )
    assert client.get(f"/agent-runs/{stale_run['id']}").json() == unchanged_run
    assert harness.messaging.calls == messaging_calls_before
    assert harness.drafter.calls == drafting_calls_before
