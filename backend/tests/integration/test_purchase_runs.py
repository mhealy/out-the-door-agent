from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from app.agent.graph import AgentRunAdvancementFailedError, AgentWorkflowService
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
from app.domain.vehicle import VehicleListing
from app.main import app
from app.persistence.db import build_engine, create_schema, get_session
from app.persistence.models import (
    ApprovalRecordModel,
    DealerInteractionRecord,
    InboundDealerMessageRecord,
    ProposedActionRecord,
)
from app.providers.dealer_messages import FixtureDealerMessageProvider
from app.providers.inventory import FixtureInventoryProvider
from app.providers.messaging import MessagingProviderError
from app.providers.quote_extraction import QuoteExtractorOutput
from app.services.offer_comparison import OfferComparisonService


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

CANONICAL_VEHICLE_IDS = ["baytown-blue", "houston-white", "katy-blue"]
VALID_VEHICLE_IDS = [
    "baytown-blue",
    "houston-white",
    "katy-blue",
    "too-far",
    "baytown-extra",
]
PURCHASE_GOAL = "Compare written out-the-door offers for my selected vehicles."


class ExpectedFixtureExtractor:
    async def extract(self, message: DealerMessage) -> QuoteExtractorOutput:
        case_id = RAW_CASE_ID_BY_BODY[message.body]
        return EXPECTED_OUTPUT_BY_CASE_ID[case_id].model_copy(deep=True)


class RecordingMessagingProvider:
    def __init__(self) -> None:
        self.calls: list[OutboundDealerMessage] = []
        self.fail = False

    async def send(self, message: OutboundDealerMessage) -> DeliveryReceipt:
        self.calls.append(message)
        if self.fail:
            raise MessagingProviderError("fixture delivery was not confirmed")
        return DeliveryReceipt(
            action_id=message.action_id,
            provider="purchase-run-test",
            external_message_id=f"purchase-{message.action_id}",
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


class ExtendedFixtureInventoryProvider:
    """Keep the canonical fixtures and add one valid fifth selection."""

    def __init__(self) -> None:
        listings = FixtureInventoryProvider._listings()
        baytown = next(item for item in listings if item.id == "baytown-blue")
        extra = baytown.model_copy(
            update={
                "id": "baytown-extra",
                "vin": "KM8JCDD10SU000099",
                "stock_number": "B1099",
                "exterior_color": "Silver",
                "source_url": "https://example.test/inventory/baytown-extra",
            }
        )
        self._listings_by_id = {item.id: item for item in [*listings, extra]}

    async def search(self, criteria: object) -> list[VehicleListing]:
        del criteria
        return list(self._listings_by_id.values())

    async def get_by_id(self, vehicle_id: str) -> VehicleListing | None:
        return self._listings_by_id.get(vehicle_id)


@dataclass(frozen=True)
class PurchaseHarness:
    session_factory: sessionmaker[Session]
    messaging: RecordingMessagingProvider
    drafter: RecordingFollowupDrafter
    application_database: Path
    checkpoint_database: Path


@pytest.fixture
def purchase_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[PurchaseHarness]:
    application_database = tmp_path / "purchase-runs.db"
    checkpoint_database = tmp_path / "purchase-run-checkpoints.db"
    engine = build_engine(f"sqlite:///{application_database}")
    create_schema(engine)
    test_session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    messaging = RecordingMessagingProvider()
    drafter = RecordingFollowupDrafter()
    inventory = ExtendedFixtureInventoryProvider()
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
        yield PurchaseHarness(
            session_factory=test_session_factory,
            messaging=messaging,
            drafter=drafter,
            application_database=application_database,
            checkpoint_database=checkpoint_database,
        )
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
        engine.dispose()


def _count_rows(harness: PurchaseHarness, table_name: str) -> int:
    with harness.session_factory() as session:
        count = session.scalar(text(f"select count(*) from {table_name}"))
    assert count is not None
    return int(count)


def _purchase_links(harness: PurchaseHarness) -> list[dict[str, object]]:
    with harness.session_factory() as session:
        rows = session.execute(
            text(
                "select purchase_run_id, vehicle_id, agent_run_id "
                "from purchase_run_vehicles order by vehicle_id"
            )
        ).mappings()
        return [dict(row) for row in rows]


def _create_purchase(
    client: TestClient,
    vehicle_ids: list[str] | None = None,
) -> dict[str, object]:
    response = client.post(
        "/purchase-runs",
        json={
            "goal": PURCHASE_GOAL,
            "vehicle_ids": vehicle_ids or CANONICAL_VEHICLE_IDS,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _children_by_vehicle(workspace: dict[str, object]) -> dict[str, dict[str, object]]:
    children = workspace["children"]
    assert isinstance(children, list)
    return {str(child["vehicle"]["id"]): child for child in children}


def _attention_by_vehicle(
    workspace: dict[str, object],
) -> dict[str, dict[str, object]]:
    attention = workspace["attention_items"]
    assert isinstance(attention, list)
    return {str(item["vehicle_id"]): item for item in attention}


def _approve(client: TestClient, action_id: str):
    return client.post(f"/outreach/proposals/{action_id}/approve", json={})


def _reject(client: TestClient, action_id: str):
    return client.post(f"/outreach/proposals/{action_id}/reject", json={})


def _resume(client: TestClient, run_id: str) -> dict[str, object]:
    response = client.post(f"/agent-runs/{run_id}/resume", json={})
    assert response.status_code == 200, response.text
    return response.json()


def _release(client: TestClient, initial_action_id: str) -> dict[str, object]:
    response = client.post(
        f"/outreach/proposals/{initial_action_id}/demo-response",
        json={},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _advance_child_through_current_fixture(
    client: TestClient,
    child: dict[str, object],
) -> dict[str, object]:
    agent_run = child["agent_run"]
    assert isinstance(agent_run, dict)
    initial_action_id = str(agent_run["initial_action_id"])
    sent = _approve(client, initial_action_id)
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "SENT"
    waiting = _resume(client, str(agent_run["id"]))
    assert waiting["phase"] == "WAITING_FOR_EXTERNAL_RESPONSE"
    released = _release(client, initial_action_id)
    assert released["analysis_status"] == "ANALYZED"
    return _resume(client, str(agent_run["id"]))


def _force_approved_without_delivery(
    harness: PurchaseHarness,
    action_id: str,
) -> None:
    now = datetime.now(timezone.utc)
    with harness.session_factory() as session:
        action = session.get(ProposedActionRecord, action_id)
        assert action is not None
        action.status = "APPROVED"
        action.updated_at = now
        session.add(
            ApprovalRecordModel(
                id=str(uuid4()),
                proposed_action_id=action.id,
                decision="APPROVED",
                decided_at=now,
                action_snapshot={
                    "id": action.id,
                    "action_type": action.action_type,
                    "dealer_id": action.dealer_id,
                    "vehicle_id": action.vehicle_id,
                    "recipient": action.recipient,
                    "subject": action.subject,
                    "body": action.body,
                    "reason": action.reason,
                    "requested_information": list(action.requested_information),
                    "requires_approval": True,
                },
            )
        )
        session.commit()


def _persist_analysis_state(
    harness: PurchaseHarness,
    initial_action_id: str,
    *,
    analysis_status: str,
    error_code: str | None = None,
) -> str:
    with harness.session_factory() as session:
        interaction = session.scalar(
            select(DealerInteractionRecord).where(
                DealerInteractionRecord.initial_action_id == initial_action_id
            )
        )
        assert interaction is not None
        message_id = str(uuid4())
        session.add(
            InboundDealerMessageRecord(
                id=message_id,
                interaction_id=interaction.id,
                source_fixture_id=f"forced-{message_id}",
                dealer_id=interaction.dealer_id,
                vehicle_id=interaction.vehicle_id,
                subject="Forced integration-test analysis state",
                body="A durable raw dealer response remains available.",
                received_at=datetime.now(timezone.utc),
                source_provider="purchase-run-test",
                analysis_status=analysis_status,
                analysis_error_code=error_code,
            )
        )
        session.commit()
    return message_id


@pytest.mark.parametrize(
    "payload",
    [
        {"goal": PURCHASE_GOAL, "vehicle_ids": ["baytown-blue"]},
        {
            "goal": PURCHASE_GOAL,
            "vehicle_ids": [
                "baytown-blue",
                "houston-white",
                "katy-blue",
                "too-far",
                "baytown-extra",
                "sixth-vehicle",
            ],
        },
        {
            "goal": PURCHASE_GOAL,
            "vehicle_ids": ["baytown-blue", "baytown-blue"],
        },
        {
            "goal": PURCHASE_GOAL,
            "vehicle_ids": ["baytown-blue", "houston-white"],
            "dealer_id": "browser-controlled-dealer",
            "claimed_otd": "1.00",
            "phase": "INTERACTION_COMPLETE",
            "recommended_agent_run_id": "forged-run",
        },
    ],
)
def test_purchase_creation_rejects_invalid_or_forged_intent(
    purchase_harness: PurchaseHarness,
    payload: dict[str, object],
) -> None:
    with TestClient(app) as client:
        response = client.post("/purchase-runs", json=payload)

    assert response.status_code == 422
    assert _count_rows(purchase_harness, "purchase_runs") == 0
    assert _count_rows(purchase_harness, "agent_runs") == 0
    assert purchase_harness.messaging.calls == []


def test_purchase_creation_rejects_unknown_inventory_before_persisting(
    purchase_harness: PurchaseHarness,
) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/purchase-runs",
            json={
                "goal": PURCHASE_GOAL,
                "vehicle_ids": ["baytown-blue", "unknown-vehicle"],
            },
        )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "candidate_not_found"
    assert _count_rows(purchase_harness, "purchase_runs") == 0
    assert _count_rows(purchase_harness, "agent_runs") == 0
    assert purchase_harness.messaging.calls == []


@pytest.mark.parametrize("vehicle_count", [2, 3, 4, 5])
def test_valid_purchase_creation_persists_one_safe_child_per_vehicle_without_sending(
    purchase_harness: PurchaseHarness,
    vehicle_count: int,
) -> None:
    selected = VALID_VEHICLE_IDS[:vehicle_count]

    with TestClient(app) as client:
        workspace = _create_purchase(client, selected)

    assert workspace["goal"] == PURCHASE_GOAL
    assert workspace["setup_status"] == "READY"
    assert workspace["decision_status"] == "GATHERING_OFFERS"
    assert workspace["selected_vehicle_ids"] == selected
    assert workspace["counts"] == {
        "selected_vehicles": vehicle_count,
        "linked_children": vehicle_count,
        "quote_requests_prepared": vehicle_count,
        "responses_analyzed": 0,
        "verified_offers": 0,
        "incomplete_offers": 0,
        "pending_approvals": vehicle_count,
    }

    children = _children_by_vehicle(workspace)
    assert set(children) == set(selected)
    run_ids: set[str] = set()
    for vehicle_id, child in children.items():
        run = child["agent_run"]
        assert isinstance(run, dict)
        assert run["vehicle_id"] == vehicle_id
        assert run["phase"] == "WAITING_FOR_APPROVAL"
        assert child["workflow_status"] == "APPROVAL_REQUIRED"
        assert child["comparison_status"] == "IN_PROGRESS"
        assert child["creation_error_code"] is None
        assert child["active_unresolved"] is True
        run_ids.add(str(run["id"]))
    assert len(run_ids) == vehicle_count

    attention = _attention_by_vehicle(workspace)
    assert set(attention) == set(selected)
    for vehicle_id, item in attention.items():
        run = children[vehicle_id]["agent_run"]
        assert isinstance(run, dict)
        assert item["category"] == "APPROVAL_REQUIRED"
        assert item["agent_run_id"] == run["id"]
        assert item["action_id"] == run["current_action_id"]
        assert item["requires_buyer_action"] is True

    links = _purchase_links(purchase_harness)
    assert len(links) == vehicle_count
    assert {str(link["vehicle_id"]) for link in links} == set(selected)
    assert {str(link["agent_run_id"]) for link in links} == run_ids
    assert {str(link["purchase_run_id"]) for link in links} == {workspace["id"]}
    assert _count_rows(purchase_harness, "purchase_runs") == 1
    assert _count_rows(purchase_harness, "agent_runs") == vehicle_count
    assert _count_rows(purchase_harness, "proposed_actions") == vehicle_count
    assert _count_rows(purchase_harness, "approvals") == 0
    assert _count_rows(purchase_harness, "outbound_deliveries") == 0
    assert purchase_harness.messaging.calls == []


def test_purchase_and_child_links_survive_request_service_recreation(
    purchase_harness: PurchaseHarness,
) -> None:
    with TestClient(app) as first_client:
        created = _create_purchase(first_client)
    created_children = _children_by_vehicle(created)
    created_ids = {
        vehicle_id: str(child["agent_run"]["id"])
        for vehicle_id, child in created_children.items()
    }

    with TestClient(app) as recreated_client:
        response = recreated_client.get(f"/purchase-runs/{created['id']}")

    assert response.status_code == 200, response.text
    reloaded = response.json()
    assert reloaded["id"] == created["id"]
    assert reloaded["selected_vehicle_ids"] == CANONICAL_VEHICLE_IDS
    assert {
        vehicle_id: str(child["agent_run"]["id"])
        for vehicle_id, child in _children_by_vehicle(reloaded).items()
    } == created_ids
    assert _count_rows(purchase_harness, "purchase_runs") == 1
    assert _count_rows(purchase_harness, "purchase_run_vehicles") == 3
    assert _count_rows(purchase_harness, "agent_runs") == 3
    assert purchase_harness.messaging.calls == []


def test_partial_creation_remains_inspectable_and_recovery_creates_only_missing_child(
    purchase_harness: PurchaseHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_create = AgentWorkflowService.create
    create_calls: list[str] = []
    fail_katy = True

    async def fail_one_child(
        self: AgentWorkflowService,
        vehicle_id: str,
        *args: object,
        **kwargs: object,
    ):
        nonlocal fail_katy
        create_calls.append(vehicle_id)
        if vehicle_id == "katy-blue" and fail_katy:
            fail_katy = False
            raise RuntimeError("injected child creation failure")
        return await original_create(self, vehicle_id, *args, **kwargs)

    monkeypatch.setattr(AgentWorkflowService, "create", fail_one_child)

    with TestClient(app) as client:
        partial = _create_purchase(client)
        partial_children = _children_by_vehicle(partial)
        stable_ids = {
            vehicle_id: str(partial_children[vehicle_id]["agent_run"]["id"])
            for vehicle_id in ["baytown-blue", "houston-white"]
        }

        assert partial["setup_status"] == "RECOVERY_REQUIRED"
        assert partial["counts"]["linked_children"] == 2
        assert partial["counts"]["quote_requests_prepared"] == 2
        assert partial_children["katy-blue"]["agent_run"] is None
        assert partial_children["katy-blue"]["workflow_status"] == "RECOVERY_REQUIRED"
        assert partial_children["katy-blue"]["creation_error_code"]
        assert _attention_by_vehicle(partial)["katy-blue"]["category"] == (
            "RECOVERY_REQUIRED"
        )

        inspected = client.get(f"/purchase-runs/{partial['id']}")
        assert inspected.status_code == 200, inspected.text
        assert inspected.json()["setup_status"] == "RECOVERY_REQUIRED"

        recovered_response = client.post(
            f"/purchase-runs/{partial['id']}/recover",
            json={},
        )
        assert recovered_response.status_code == 200, recovered_response.text
        recovered = recovered_response.json()
        repeated_response = client.post(
            f"/purchase-runs/{partial['id']}/recover",
            json={},
        )
        assert repeated_response.status_code == 200, repeated_response.text
        repeated = repeated_response.json()

    assert recovered["setup_status"] == "READY"
    assert recovered["counts"]["linked_children"] == 3
    recovered_children = _children_by_vehicle(recovered)
    assert {
        vehicle_id: str(recovered_children[vehicle_id]["agent_run"]["id"])
        for vehicle_id in stable_ids
    } == stable_ids
    assert recovered_children["katy-blue"]["agent_run"] is not None
    assert recovered_children["katy-blue"]["creation_error_code"] is None
    assert {
        vehicle_id: str(child["agent_run"]["id"])
        for vehicle_id, child in _children_by_vehicle(repeated).items()
    } == {
        vehicle_id: str(child["agent_run"]["id"])
        for vehicle_id, child in recovered_children.items()
    }
    assert Counter(create_calls) == Counter(
        {
            "baytown-blue": 1,
            "houston-white": 1,
            "katy-blue": 2,
        }
    )
    assert _count_rows(purchase_harness, "agent_runs") == 3
    assert _count_rows(purchase_harness, "purchase_run_vehicles") == 3
    assert purchase_harness.messaging.calls == []


def test_recoverable_committed_child_run_is_adopted_and_never_recreated(
    purchase_harness: PurchaseHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_create = AgentWorkflowService.create
    create_calls: list[str] = []
    committed_katy_id: str | None = None

    async def fail_after_katy_commit(
        self: AgentWorkflowService,
        vehicle_id: str,
        *args: object,
        **kwargs: object,
    ):
        nonlocal committed_katy_id
        create_calls.append(vehicle_id)
        run = await original_create(self, vehicle_id, *args, **kwargs)
        if vehicle_id == "katy-blue" and committed_katy_id is None:
            committed_katy_id = run.id
            raise AgentRunAdvancementFailedError(run.id)
        return run

    monkeypatch.setattr(AgentWorkflowService, "create", fail_after_katy_commit)

    with TestClient(app) as client:
        workspace = _create_purchase(client)
        recovered = client.post(
            f"/purchase-runs/{workspace['id']}/recover",
            json={},
        )

    assert recovered.status_code == 200, recovered.text
    assert committed_katy_id is not None
    assert workspace["setup_status"] == "READY"
    katy = _children_by_vehicle(workspace)["katy-blue"]
    assert katy["agent_run"]["id"] == committed_katy_id
    assert Counter(create_calls) == Counter(
        {
            "baytown-blue": 1,
            "houston-white": 1,
            "katy-blue": 1,
        }
    )
    assert _count_rows(purchase_harness, "agent_runs") == 3
    assert _count_rows(purchase_harness, "purchase_run_vehicles") == 3
    assert purchase_harness.messaging.calls == []


def test_recovery_reuses_reserved_identity_after_child_commit_before_link(
    purchase_harness: PurchaseHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_create = AgentWorkflowService.create
    committed_katy_id: str | None = None
    create_calls: list[str] = []

    async def lose_result_after_commit(
        self: AgentWorkflowService,
        vehicle_id: str,
        *args: object,
        **kwargs: object,
    ):
        nonlocal committed_katy_id
        create_calls.append(vehicle_id)
        run = await original_create(self, vehicle_id, *args, **kwargs)
        if vehicle_id == "katy-blue" and committed_katy_id is None:
            committed_katy_id = run.id
            raise RuntimeError("injected result loss before purchase link")
        return run

    monkeypatch.setattr(AgentWorkflowService, "create", lose_result_after_commit)

    with TestClient(app) as client:
        partial = _create_purchase(client)
        assert partial["setup_status"] == "RECOVERY_REQUIRED"
        assert _children_by_vehicle(partial)["katy-blue"]["agent_run"] is None
        assert _count_rows(purchase_harness, "agent_runs") == 3

        recovered_response = client.post(
            f"/purchase-runs/{partial['id']}/recover",
            json={},
        )

    assert recovered_response.status_code == 200, recovered_response.text
    recovered = recovered_response.json()
    assert recovered["setup_status"] == "READY"
    assert committed_katy_id is not None
    assert (
        _children_by_vehicle(recovered)["katy-blue"]["agent_run"]["id"]
        == committed_katy_id
    )
    assert Counter(create_calls)["katy-blue"] == 2
    assert _count_rows(purchase_harness, "agent_runs") == 3
    assert _count_rows(purchase_harness, "proposed_actions") == 3
    assert _count_rows(purchase_harness, "purchase_run_vehicles") == 3
    with purchase_harness.session_factory() as session:
        katy_event_counts = session.execute(
            text(
                "select count(*), count(distinct semantic_key) "
                "from agent_events where run_id = :run_id"
            ),
            {"run_id": committed_katy_id},
        ).one()
    assert tuple(katy_event_counts) == (3, 3)
    assert purchase_harness.messaging.calls == []


def test_concurrent_recovery_converges_on_one_child_identity_without_stale_error(
    purchase_harness: PurchaseHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_create = AgentWorkflowService.create
    fail_katy = True

    async def leave_katy_missing(
        self: AgentWorkflowService,
        vehicle_id: str,
        *args: object,
        **kwargs: object,
    ):
        nonlocal fail_katy
        if vehicle_id == "katy-blue" and fail_katy:
            fail_katy = False
            raise RuntimeError("injected missing child")
        return await original_create(self, vehicle_id, *args, **kwargs)

    monkeypatch.setattr(AgentWorkflowService, "create", leave_katy_missing)
    with TestClient(app) as client:
        partial = _create_purchase(client)
    assert partial["setup_status"] == "RECOVERY_REQUIRED"

    simultaneous_katy_calls = Barrier(2)

    async def concurrent_create(
        self: AgentWorkflowService,
        vehicle_id: str,
        *args: object,
        **kwargs: object,
    ):
        if vehicle_id == "katy-blue":
            simultaneous_katy_calls.wait(timeout=10)
        return await original_create(self, vehicle_id, *args, **kwargs)

    monkeypatch.setattr(AgentWorkflowService, "create", concurrent_create)

    def recover() -> tuple[int, dict[str, object]]:
        with TestClient(app) as client:
            response = client.post(
                f"/purchase-runs/{partial['id']}/recover",
                json={},
            )
        return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: recover(), range(2)))

    assert [status_code for status_code, _ in outcomes] == [200, 200]
    with TestClient(app) as client:
        final_response = client.get(f"/purchase-runs/{partial['id']}")
    assert final_response.status_code == 200, final_response.text
    final = final_response.json()
    assert final["setup_status"] == "READY"
    assert _children_by_vehicle(final)["katy-blue"]["creation_error_code"] is None
    assert _count_rows(purchase_harness, "agent_runs") == 3
    assert _count_rows(purchase_harness, "proposed_actions") == 3
    assert _count_rows(purchase_harness, "approvals") == 0
    assert _count_rows(purchase_harness, "outbound_deliveries") == 0
    assert purchase_harness.messaging.calls == []


def test_purchase_workspace_reuses_offer_comparison_without_resuming_children(
    purchase_harness: PurchaseHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_compare = OfferComparisonService.compare
    comparison_calls: list[tuple[str, ...]] = []

    async def recording_compare(
        self: OfferComparisonService,
        agent_run_ids: list[str],
    ):
        comparison_calls.append(tuple(agent_run_ids))
        return await original_compare(self, agent_run_ids)

    async def unexpected_resume(self: AgentWorkflowService, run_id: str):
        del self, run_id
        raise AssertionError("A purchase read must never resume a child graph.")

    monkeypatch.setattr(OfferComparisonService, "compare", recording_compare)
    monkeypatch.setattr(AgentWorkflowService, "resume", unexpected_resume)

    with TestClient(app) as client:
        created = _create_purchase(client)
        response = client.get(f"/purchase-runs/{created['id']}")

    assert response.status_code == 200, response.text
    child_ids = {
        str(child["agent_run"]["id"])
        for child in _children_by_vehicle(created).values()
    }
    assert comparison_calls
    assert set(comparison_calls[-1]) == child_ids
    assert len(comparison_calls[-1]) == len(child_ids)
    assert purchase_harness.messaging.calls == []


def test_new_authoritative_analysis_verifies_economics_despite_stale_child_phase(
    purchase_harness: PurchaseHarness,
) -> None:
    with TestClient(app) as client:
        created = _create_purchase(
            client,
            ["baytown-blue", "houston-white"],
        )
        children = _children_by_vehicle(created)
        baytown_run = children["baytown-blue"]["agent_run"]
        assert isinstance(baytown_run, dict)

        sent = _approve(client, str(baytown_run["initial_action_id"]))
        assert sent.status_code == 200, sent.text
        released = _release(client, str(baytown_run["initial_action_id"]))
        assert released["analysis_status"] == "ANALYZED"

        stale = client.get(f"/agent-runs/{baytown_run['id']}")
        assert stale.status_code == 200
        assert stale.json()["phase"] == "WAITING_FOR_APPROVAL"
        workspace_response = client.get(f"/purchase-runs/{created['id']}")

    assert workspace_response.status_code == 200, workspace_response.text
    workspace = workspace_response.json()
    baytown = _children_by_vehicle(workspace)["baytown-blue"]
    assert baytown["agent_run"]["phase"] == "WAITING_FOR_APPROVAL"
    assert baytown["workflow_status"] == "OFFER_VERIFIED"
    assert baytown["comparison_status"] == "VERIFIED"
    assert baytown["active_unresolved"] is False
    assert workspace["counts"]["responses_analyzed"] == 1
    assert workspace["counts"]["verified_offers"] == 1
    assert workspace["counts"]["pending_approvals"] == 1
    assert workspace["decision_status"] == "COMPARISON_AVAILABLE"
    assert "baytown-blue" not in _attention_by_vehicle(workspace)
    offer = next(
        item
        for item in workspace["comparison"]["offers"]
        if item["vehicle_id"] == "baytown-blue"
    )
    assert offer["claimed_otd"] == "40315"
    assert offer["eligible"] is True


def test_partial_purchase_projects_one_linked_verified_offer(
    purchase_harness: PurchaseHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_create = AgentWorkflowService.create

    async def fail_second_child(
        self: AgentWorkflowService,
        vehicle_id: str,
        *args: object,
        **kwargs: object,
    ):
        if vehicle_id == "houston-white":
            raise RuntimeError("injected child creation failure")
        return await original_create(self, vehicle_id, *args, **kwargs)

    monkeypatch.setattr(AgentWorkflowService, "create", fail_second_child)

    with TestClient(app) as client:
        created = _create_purchase(
            client,
            ["baytown-blue", "houston-white"],
        )
        baytown_run = _children_by_vehicle(created)["baytown-blue"]["agent_run"]
        assert isinstance(baytown_run, dict)

        sent = _approve(client, str(baytown_run["initial_action_id"]))
        assert sent.status_code == 200, sent.text
        released = _release(client, str(baytown_run["initial_action_id"]))
        assert released["analysis_status"] == "ANALYZED"

        response = client.get(f"/purchase-runs/{created['id']}")

    assert response.status_code == 200, response.text
    workspace = response.json()
    assert workspace["setup_status"] == "RECOVERY_REQUIRED"
    assert workspace["counts"]["linked_children"] == 1
    assert workspace["counts"]["verified_offers"] == 1
    assert workspace["decision_status"] == "COMPARISON_AVAILABLE"
    recommendation = workspace["comparison"]["recommendation"]
    assert recommendation["recommended_agent_run_id"] == baytown_run["id"]


def test_workspace_attention_uses_authoritative_action_and_interaction_states(
    purchase_harness: PurchaseHarness,
) -> None:
    selected = VALID_VEHICLE_IDS
    with TestClient(app) as client:
        created = _create_purchase(client, selected)
        children = _children_by_vehicle(created)

        houston = children["houston-white"]["agent_run"]
        assert isinstance(houston, dict)
        sent = _approve(client, str(houston["initial_action_id"]))
        assert sent.status_code == 200, sent.text
        assert _resume(client, str(houston["id"]))["phase"] == (
            "WAITING_FOR_EXTERNAL_RESPONSE"
        )

        katy = children["katy-blue"]["agent_run"]
        assert isinstance(katy, dict)
        sent = _approve(client, str(katy["initial_action_id"]))
        assert sent.status_code == 200, sent.text
        _persist_analysis_state(
            purchase_harness,
            str(katy["initial_action_id"]),
            analysis_status="ANALYSIS_FAILED",
            error_code="quote_extraction_failed",
        )
        assert _resume(client, str(katy["id"]))["phase"] == "ANALYSIS_FAILED"

        unconfirmed = children["too-far"]["agent_run"]
        assert isinstance(unconfirmed, dict)
        _force_approved_without_delivery(
            purchase_harness,
            str(unconfirmed["initial_action_id"]),
        )
        assert _resume(client, str(unconfirmed["id"]))["phase"] == (
            "DELIVERY_UNCONFIRMED"
        )

        rejected = children["baytown-extra"]["agent_run"]
        assert isinstance(rejected, dict)
        rejected_response = _reject(client, str(rejected["initial_action_id"]))
        assert rejected_response.status_code == 200, rejected_response.text
        assert _resume(client, str(rejected["id"]))["phase"] == "RUN_REJECTED"

        workspace_response = client.get(f"/purchase-runs/{created['id']}")

    assert workspace_response.status_code == 200, workspace_response.text
    workspace = workspace_response.json()
    projected = _children_by_vehicle(workspace)
    assert {
        vehicle_id: projected[vehicle_id]["workflow_status"]
        for vehicle_id in selected
    } == {
        "baytown-blue": "APPROVAL_REQUIRED",
        "houston-white": "WAITING_FOR_DEALER",
        "katy-blue": "ANALYSIS_FAILED",
        "too-far": "DELIVERY_UNCONFIRMED",
        "baytown-extra": "RUN_REJECTED",
    }
    assert projected["katy-blue"]["comparison_status"] == "FAILED"
    assert projected["too-far"]["comparison_status"] == "BLOCKED"
    assert projected["baytown-extra"]["comparison_status"] == "REJECTED"

    attention = _attention_by_vehicle(workspace)
    assert {vehicle_id: item["category"] for vehicle_id, item in attention.items()} == {
        "baytown-blue": "APPROVAL_REQUIRED",
        "houston-white": "WAITING_FOR_DEALER",
        "katy-blue": "ANALYSIS_FAILED",
        "too-far": "DELIVERY_UNCONFIRMED",
        "baytown-extra": "RUN_REJECTED",
    }
    assert attention["baytown-blue"]["action_id"] == projected["baytown-blue"][
        "agent_run"
    ]["initial_action_id"]
    assert attention["too-far"]["action_id"] == projected["too-far"][
        "agent_run"
    ]["initial_action_id"]
    assert attention["houston-white"]["action_id"] is None
    assert attention["katy-blue"]["action_id"] is None
    assert attention["baytown-extra"]["action_id"] is None
    assert workspace["counts"]["pending_approvals"] == 1
    assert workspace["decision_status"] == "GATHERING_OFFERS"


def test_send_failure_is_reported_as_truthful_child_failure(
    purchase_harness: PurchaseHarness,
) -> None:
    with TestClient(app) as client:
        created = _create_purchase(
            client,
            ["baytown-blue", "houston-white"],
        )
        baytown = _children_by_vehicle(created)["baytown-blue"]["agent_run"]
        assert isinstance(baytown, dict)
        purchase_harness.messaging.fail = True
        failed = _approve(client, str(baytown["initial_action_id"]))
        purchase_harness.messaging.fail = False
        assert failed.status_code == 502, failed.text
        assert _resume(client, str(baytown["id"]))["phase"] == "RUN_FAILED"
        workspace_response = client.get(f"/purchase-runs/{created['id']}")

    assert workspace_response.status_code == 200, workspace_response.text
    workspace = workspace_response.json()
    child = _children_by_vehicle(workspace)["baytown-blue"]
    assert child["workflow_status"] == "RUN_FAILED"
    assert child["comparison_status"] == "FAILED"
    assert child["active_unresolved"] is False
    attention = _attention_by_vehicle(workspace)["baytown-blue"]
    assert attention["category"] == "RUN_FAILED"
    assert attention["action_id"] is None


def test_canonical_workspace_reuses_comparison_and_updates_decision_deterministically(
    purchase_harness: PurchaseHarness,
) -> None:
    with TestClient(app) as client:
        created = _create_purchase(client)
        original_children = _children_by_vehicle(created)
        latest_runs = {
            vehicle_id: _advance_child_through_current_fixture(client, child)
            for vehicle_id, child in original_children.items()
        }
        assert latest_runs["baytown-blue"]["phase"] == "INTERACTION_COMPLETE"
        assert latest_runs["houston-white"]["phase"] == "INTERACTION_COMPLETE"
        assert latest_runs["katy-blue"]["phase"] == "WAITING_FOR_APPROVAL"

        comparison_response = client.get(f"/purchase-runs/{created['id']}")
        assert comparison_response.status_code == 200, comparison_response.text
        comparison_available = comparison_response.json()

        katy_action_id = str(latest_runs["katy-blue"]["current_action_id"])
        rejected = _reject(client, katy_action_id)
        assert rejected.status_code == 200, rejected.text
        assert _resume(
            client,
            str(latest_runs["katy-blue"]["id"]),
        )["phase"] == "RUN_REJECTED"
        ready_response = client.get(f"/purchase-runs/{created['id']}")

    assert comparison_available["setup_status"] == "READY"
    assert comparison_available["decision_status"] == "COMPARISON_AVAILABLE"
    assert comparison_available["counts"] == {
        "selected_vehicles": 3,
        "linked_children": 3,
        "quote_requests_prepared": 3,
        "responses_analyzed": 3,
        "verified_offers": 2,
        "incomplete_offers": 1,
        "pending_approvals": 1,
    }
    canonical_children = _children_by_vehicle(comparison_available)
    assert canonical_children["baytown-blue"]["workflow_status"] == "OFFER_VERIFIED"
    assert canonical_children["houston-white"]["workflow_status"] == "OFFER_VERIFIED"
    assert canonical_children["katy-blue"]["workflow_status"] == "APPROVAL_REQUIRED"
    assert canonical_children["katy-blue"]["comparison_status"] == "INCOMPLETE"
    assert canonical_children["katy-blue"]["active_unresolved"] is True
    canonical_attention = _attention_by_vehicle(comparison_available)
    assert list(canonical_attention) == ["katy-blue"]
    assert canonical_attention["katy-blue"]["category"] == "APPROVAL_REQUIRED"
    assert canonical_attention["katy-blue"]["action_id"] == katy_action_id

    comparison = comparison_available["comparison"]
    baytown_run_id = canonical_children["baytown-blue"]["agent_run"]["id"]
    houston_run_id = canonical_children["houston-white"]["agent_run"]["id"]
    assert comparison["ranked_agent_run_ids"] == [baytown_run_id, houston_run_id]
    assert comparison["recommendation"] == {
        **comparison["recommendation"],
        "recommended_agent_run_id": baytown_run_id,
        "recommended_dealer_id": "baytown",
        "recommended_dealer_name": "Baytown Hyundai",
        "recommended_otd": "40315",
        "next_best_verified_otd": "41780",
        "savings_vs_next_verified": "1465",
        "has_unresolved_alternatives": True,
    }
    assert comparison["advertised_vs_verified"]["advertised_price_difference"] == "550"
    assert comparison["advertised_vs_verified"]["verified_otd_savings"] == "1465"

    assert ready_response.status_code == 200, ready_response.text
    ready = ready_response.json()
    assert ready["decision_status"] == "DECISION_READY"
    assert ready["counts"]["verified_offers"] == 2
    assert ready["counts"]["pending_approvals"] == 0
    assert _children_by_vehicle(ready)["katy-blue"]["workflow_status"] == (
        "RUN_REJECTED"
    )
    assert _attention_by_vehicle(ready)["katy-blue"]["category"] == "RUN_REJECTED"
    assert ready["comparison"]["recommendation"][
        "has_unresolved_alternatives"
    ] is False
    assert len(purchase_harness.messaging.calls) == 3
    assert len(purchase_harness.drafter.calls) == 1
