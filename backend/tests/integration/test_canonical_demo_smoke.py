from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app import main as app_main
from app.config import get_settings
from app.dependencies import (
    get_dealer_message_provider,
    get_followup_drafter,
    get_inventory_provider,
    get_messaging_provider,
    get_quote_extractor,
    get_research_provider,
    get_research_synthesizer,
)
from app.domain.followup import FollowupDraft, FollowupDraftContext, FollowupDraftRequest
from app.domain.message import DealerMessage, OutboundDealerMessage
from app.domain.research import ResearchFindingDraft, ResearchSource, ResearchTarget
from app.persistence.db import build_engine, create_schema, get_session
from app.providers.dealer_messages import FixtureDealerMessageProvider
from app.providers.inventory import FixtureInventoryProvider
from app.providers.messaging import FixtureMessagingProvider
from app.providers.quote_extraction import QuoteExtractorOutput
from app.providers.research import FixtureResearchProvider


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CANONICAL_GOAL = (
    "Find a new 2025 or 2026 Hyundai Tucson Hybrid Limited within 40 miles "
    "of Houston under $40,000. I require AWD. I care most about true "
    "out-the-door price."
)
CANONICAL_VEHICLE_IDS = ["baytown-blue", "houston-white", "katy-blue"]
INITIAL_REQUIREMENTS = [
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
]
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


class LabeledFixtureExtractor:
    """Replace only probabilistic extraction with committed labeled output."""

    async def extract(self, message: DealerMessage) -> QuoteExtractorOutput:
        case_id = RAW_CASE_ID_BY_BODY[message.body]
        return EXPECTED_OUTPUT_BY_CASE_ID[case_id].model_copy(deep=True)


class DeterministicFollowupDrafter:
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


class DeterministicResearchSynthesizer:
    def __init__(self) -> None:
        self.calls: list[tuple[ResearchTarget, list[ResearchSource]]] = []

    async def synthesize(
        self,
        *,
        target: ResearchTarget,
        sources: list[ResearchSource],
    ) -> ResearchFindingDraft:
        self.calls.append((target, list(sources)))
        return ResearchFindingDraft(
            target_id=target.target_id,
            target_name=target.canonical_name,
            summary=(
                f"The fixture sources provide bounded context for "
                f"{target.canonical_name}; they do not establish this dealer's "
                "exact package terms."
            ),
            what_it_appears_to_include=[
                "Product context described by the retrieved fixture sources."
            ],
            limitations=[
                "The sources do not verify the exact dealer-specific package."
            ],
            source_ids=[source.id for source in sources],
            support_status="SUPPORTED",
        )


@dataclass(frozen=True)
class CanonicalSmokeHarness:
    session_factory: sessionmaker[Session]
    messaging: FixtureMessagingProvider
    followup_drafter: DeterministicFollowupDrafter
    research_synthesizer: DeterministicResearchSynthesizer


@pytest.fixture
def canonical_smoke_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[CanonicalSmokeHarness]:
    application_database = tmp_path / "canonical-smoke.db"
    checkpoint_database = tmp_path / "canonical-smoke-checkpoints.db"
    engine = build_engine(f"sqlite:///{application_database.as_posix()}")
    create_schema(engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    inventory = FixtureInventoryProvider()
    dealer_messages = FixtureDealerMessageProvider()
    messaging = FixtureMessagingProvider()
    followup_drafter = DeterministicFollowupDrafter()
    research_synthesizer = DeterministicResearchSynthesizer()

    def override_session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    monkeypatch.setenv("OTD_DATABASE_URL", f"sqlite:///{application_database.as_posix()}")
    monkeypatch.setenv("OTD_LANGGRAPH_CHECKPOINT_PATH", str(checkpoint_database))
    get_settings.cache_clear()
    monkeypatch.setattr(app_main, "create_schema", lambda: None)
    app_main.app.dependency_overrides[get_session] = override_session
    app_main.app.dependency_overrides[get_inventory_provider] = lambda: inventory
    app_main.app.dependency_overrides[get_dealer_message_provider] = lambda: dealer_messages
    app_main.app.dependency_overrides[get_messaging_provider] = lambda: messaging
    app_main.app.dependency_overrides[get_quote_extractor] = LabeledFixtureExtractor
    app_main.app.dependency_overrides[get_followup_drafter] = lambda: followup_drafter
    app_main.app.dependency_overrides[get_research_provider] = FixtureResearchProvider
    app_main.app.dependency_overrides[get_research_synthesizer] = (
        lambda: research_synthesizer
    )
    try:
        yield CanonicalSmokeHarness(
            session_factory=session_factory,
            messaging=messaging,
            followup_drafter=followup_drafter,
            research_synthesizer=research_synthesizer,
        )
    finally:
        app_main.app.dependency_overrides.clear()
        get_settings.cache_clear()
        engine.dispose()


def _children_by_vehicle(workspace: dict[str, object]) -> dict[str, dict[str, object]]:
    children = workspace["children"]
    assert isinstance(children, list)
    return {str(child["vehicle"]["id"]): child for child in children}


def _offers_by_dealer(comparison: dict[str, object]) -> dict[str, dict[str, object]]:
    offers = comparison["offers"]
    assert isinstance(offers, list)
    return {str(offer["dealer_id"]): offer for offer in offers}


def _row_count(harness: CanonicalSmokeHarness, table_name: str) -> int:
    with harness.session_factory() as session:
        value = session.scalar(text(f"select count(*) from {table_name}"))
    assert value is not None
    return int(value)


def _resume(client: TestClient, run_id: str) -> dict[str, object]:
    response = client.post(f"/agent-runs/{run_id}/resume", json={})
    assert response.status_code == 200, response.text
    return response.json()


def test_canonical_demo_proves_the_complete_product_story(
    canonical_smoke_harness: CanonicalSmokeHarness,
) -> None:
    with TestClient(app_main.app) as client:
        search = client.post("/candidates/search", json={"goal": CANONICAL_GOAL})
        assert search.status_code == 200, search.text
        candidates = search.json()["candidates"]
        assert [candidate["id"] for candidate in candidates] == [
            "houston-white",
            "baytown-blue",
            "katy-blue",
        ]

        created = client.post(
            "/purchase-runs",
            json={
                "creation_id": str(uuid4()),
                "goal": CANONICAL_GOAL,
                "vehicle_ids": CANONICAL_VEHICLE_IDS,
            },
        )
        assert created.status_code == 201, created.text
        workspace = created.json()
        purchase_id = str(workspace["id"])
        children = _children_by_vehicle(workspace)

        assert canonical_smoke_harness.messaging.sent_messages == []
        assert _row_count(canonical_smoke_harness, "approvals") == 0
        assert _row_count(canonical_smoke_harness, "outbound_deliveries") == 0
        assert workspace["counts"]["quote_requests_prepared"] == 3
        assert workspace["counts"]["pending_approvals"] == 3

        proposals: dict[str, dict[str, object]] = {}
        for vehicle_id in CANONICAL_VEHICLE_IDS:
            run = children[vehicle_id]["agent_run"]
            assert isinstance(run, dict)
            response = client.get(f"/outreach/proposals/{run['initial_action_id']}")
            assert response.status_code == 200, response.text
            proposal = response.json()
            proposals[vehicle_id] = proposal
            assert proposal["action_type"] == "SEND_INITIAL_QUOTE_REQUEST"
            assert proposal["status"] == "PENDING_APPROVAL"
            assert proposal["requested_information"] == INITIAL_REQUIREMENTS
            assert proposal["recipient"].endswith(".example.test")
            assert proposal["body"].strip()

        for expected_send_count, vehicle_id in enumerate(
            CANONICAL_VEHICLE_IDS,
            start=1,
        ):
            proposal = proposals[vehicle_id]
            approved = client.post(
                f"/outreach/proposals/{proposal['id']}/approve",
                json={},
            )
            assert approved.status_code == 200, approved.text
            approved_proposal = approved.json()
            assert approved_proposal["status"] == "SENT"
            assert len(canonical_smoke_harness.messaging.sent_messages) == (
                expected_send_count
            )
            exact_snapshot = approved_proposal["approval"]["action_snapshot"]
            delivered = canonical_smoke_harness.messaging.sent_messages[-1]
            assert delivered == OutboundDealerMessage(
                action_id=exact_snapshot["id"],
                vehicle_id=exact_snapshot["vehicle_id"],
                dealer_id=exact_snapshot["dealer_id"],
                recipient=exact_snapshot["recipient"],
                subject=exact_snapshot["subject"],
                body=exact_snapshot["body"],
            )

            run = children[vehicle_id]["agent_run"]
            assert isinstance(run, dict)
            waiting = _resume(client, str(run["id"]))
            assert waiting["phase"] == "WAITING_FOR_EXTERNAL_RESPONSE"
            released = client.post(
                f"/outreach/proposals/{proposal['id']}/demo-response",
                json={},
            )
            assert released.status_code == 200, released.text
            interaction = released.json()
            assert interaction["analysis_status"] == "ANALYZED"
            assert interaction["messages"]
            assert interaction["messages"][-1]["body"] in RAW_CASE_ID_BY_BODY
            assert interaction["analysis"]["evidence"]
            _resume(client, str(run["id"]))

        current = client.get(f"/purchase-runs/{purchase_id}")
        assert current.status_code == 200, current.text
        workspace = current.json()
        children = _children_by_vehicle(workspace)
        comparison = workspace["comparison"]
        assert isinstance(comparison, dict)
        offers = _offers_by_dealer(comparison)

        assert workspace["counts"]["verified_offers"] == 2
        assert workspace["counts"]["incomplete_offers"] == 1
        assert workspace["counts"]["pending_approvals"] == 1
        assert children["baytown-blue"]["workflow_status"] == "OFFER_VERIFIED"
        assert children["houston-white"]["workflow_status"] == "OFFER_VERIFIED"
        assert children["katy-blue"]["workflow_status"] == "APPROVAL_REQUIRED"
        katy_run = children["katy-blue"]["agent_run"]
        assert isinstance(katy_run, dict)
        katy_followup = client.get(
            f"/outreach/proposals/{katy_run['current_action_id']}"
        )
        assert katy_followup.status_code == 200, katy_followup.text
        assert katy_followup.json()["action_type"] == "SEND_FOLLOWUP"
        assert katy_followup.json()["status"] == "PENDING_APPROVAL"
        assert katy_followup.json()["requested_information"] == [
            "vehicle_identity",
            "addon_status",
        ]

        assert offers["baytown"]["claimed_otd"] == "40315"
        assert offers["baytown"]["comparison_status"] == "VERIFIED"
        assert offers["baytown"]["verified_rank"] == 1
        assert offers["houston"]["claimed_otd"] == "41780"
        assert offers["houston"]["comparison_status"] == "VERIFIED"
        assert offers["houston"]["verified_rank"] == 2
        assert offers["katy"]["claimed_otd"] == "40250"
        assert offers["katy"]["comparison_status"] == "INCOMPLETE"
        assert offers["katy"]["eligible"] is False
        assert offers["katy"]["verified_rank"] is None
        assert offers["katy"]["missing_for_comparison"] == [
            "vehicle_identity",
            "addon_status",
        ]
        assert comparison["recommendation"]["recommended_dealer_id"] == "baytown"
        assert comparison["recommendation"]["recommended_otd"] == "40315"
        assert comparison["recommendation"]["has_unresolved_alternatives"] is True
        assert comparison["advertised_vs_verified"]["advertised_price_difference"] == "550"
        assert comparison["advertised_vs_verified"]["verified_otd_savings"] == "1465"

        winning_evidence_id = offers["baytown"]["claimed_otd_evidence_ids"][0]
        winning_evidence = next(
            evidence
            for evidence in offers["baytown"]["evidence"]
            if evidence["id"] == winning_evidence_id
        )
        assert winning_evidence["source_type"] == "DEALER_EMAIL"
        assert winning_evidence["field_name"] == "claimed_otd"
        assert "written cash OTD is $40,315" in winning_evidence["excerpt"]

        targets_response = client.get(f"/purchase-runs/{purchase_id}/research-targets")
        assert targets_response.status_code == 200, targets_response.text
        targets = targets_response.json()
        targets_by_name = {target["canonical_name"]: target for target in targets}
        assert set(targets_by_name) == {
            "Ceramic Shield",
            "SecureTrack theft recovery",
        }
        assert targets_by_name["Ceramic Shield"]["dealer_stated_amount"] == "1299"
        assert targets_by_name["SecureTrack theft recovery"]["dealer_stated_amount"] == "596"

        comparison_before_research = comparison
        sent_before_research = list(canonical_smoke_harness.messaging.sent_messages)
        target = targets_by_name["Ceramic Shield"]
        investigated = client.post(
            f"/purchase-runs/{purchase_id}/research-targets/"
            f"{target['target_id']}/investigate",
            json={},
        )
        assert investigated.status_code == 200, investigated.text
        investigation = investigated.json()["investigation"]
        assert investigation["status"] == "COMPLETED"
        assert investigation["finding"]["source_ids"] == [
            "ceramic-shield-vendor-overview",
            "ceramic-coating-independent-context",
        ]
        assert len(canonical_smoke_harness.research_synthesizer.calls) == 1

        after_research = client.get(f"/purchase-runs/{purchase_id}")
        assert after_research.status_code == 200, after_research.text
        assert after_research.json()["comparison"] == comparison_before_research
        assert canonical_smoke_harness.messaging.sent_messages == sent_before_research

        activity = client.get(f"/purchase-runs/{purchase_id}/activity")
        assert activity.status_code == 200, activity.text
        activity_items = activity.json()
        assert {item["agent_run_id"] for item in activity_items} == {
            str(children[vehicle_id]["agent_run"]["id"])
            for vehicle_id in CANONICAL_VEHICLE_IDS
        }
        assert any(
            item["event_type"] == "FOLLOWUP_PREPARED"
            and item["vehicle_id"] == "katy-blue"
            for item in activity_items
        )
        assert any(
            item["event_type"] == "INTERACTION_COMPLETE"
            and item["vehicle_id"] == "baytown-blue"
            for item in activity_items
        )
        assert len(canonical_smoke_harness.messaging.sent_messages) == 3
        assert len(canonical_smoke_harness.followup_drafter.calls) == 1
