from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

import app.main as app_main
from app.agent.graph import AgentWorkflowService
from app.config import get_settings
from app.dependencies import (
    get_dealer_contact_resolver,
    get_dealer_message_provider,
    get_followup_drafter,
    get_inventory_provider,
    get_messaging_provider,
    get_quote_extractor,
    get_research_provider,
    get_research_synthesizer,
)
from app.persistence.db import build_engine, create_schema, get_session
from app.persistence.models import (
    ApprovalRecordModel,
    AgentEventRecord,
    AgentRunRecord,
    DealerInteractionRecord,
    InboundDealerMessageRecord,
    OutboundDeliveryRecord,
    ProposedActionRecord,
    PurchaseRun,
    PurchaseRunVehicleRecord,
)
from app.services.offer_comparison import OfferComparisonService
from app.services.outreach import OutreachService
from app.services.research import ResearchService


RAW_MARKER = "RAW_DEALER_BODY_AND_HIDDEN_REASONING_MUST_NOT_APPEAR"


@dataclass(frozen=True)
class ActivityApiHarness:
    client: TestClient
    engine: Engine
    session_factory: sessionmaker[Session]
    checkpoint_path: Path


def _forbidden_dependency() -> None:
    raise AssertionError("Purchase activity must not resolve provider dependencies.")


async def _forbidden_async_call(*_: object, **__: object) -> None:
    raise AssertionError("Purchase activity must not execute application capabilities.")


def _seed_activity(session_factory: sessionmaker[Session]) -> None:
    occurred_at = datetime(2026, 8, 20, 15, 14, tzinfo=timezone.utc)
    vehicle_snapshot = {
        "id": "baytown-blue",
        "year": 2025,
        "make": "Hyundai",
        "model": "Tucson Hybrid",
        "trim": "Limited",
        "vin": "KM8JCDD10SU000001",
        "stock_number": "B1001",
        "dealer_id": "baytown",
        "dealer_name": "Baytown Hyundai",
    }
    with session_factory() as session:
        session.add_all(
            [
                PurchaseRun(
                    id="purchase-api-activity",
                    goal="Compare the canonical written offers.",
                    status="CREATED",
                    created_at=occurred_at,
                ),
                AgentRunRecord(
                    id="run-api-baytown",
                    thread_id="thread-api-baytown",
                    vehicle_id="baytown-blue",
                    phase="INTERACTION_COMPLETE",
                    initial_action_id="action-api-baytown",
                    current_action_id="action-api-baytown",
                    interaction_id="interaction-api-baytown",
                    last_message_id="message-api-baytown",
                    created_at=occurred_at,
                    updated_at=occurred_at,
                ),
                PurchaseRunVehicleRecord(
                    id="link-api-baytown",
                    purchase_run_id="purchase-api-activity",
                    vehicle_id="baytown-blue",
                    position=0,
                    agent_run_id="run-api-baytown",
                    created_at=occurred_at,
                    updated_at=occurred_at,
                ),
                ProposedActionRecord(
                    id="action-api-baytown",
                    action_type="SEND_INITIAL_QUOTE_REQUEST",
                    dealer_id="baytown",
                    vehicle_id="baytown-blue",
                    recipient="quotes@baytown.example.test",
                    subject="Written quote request",
                    body="Exact safe outbound request.",
                    reason="Obtain a written quote.",
                    requested_information=["claimed_otd"],
                    requires_approval=True,
                    status="SENT",
                    vehicle_snapshot=vehicle_snapshot,
                    created_at=occurred_at,
                    updated_at=occurred_at,
                ),
                DealerInteractionRecord(
                    id="interaction-api-baytown",
                    initial_action_id="action-api-baytown",
                    dealer_id="baytown",
                    vehicle_id="baytown-blue",
                    vehicle_snapshot=vehicle_snapshot,
                    created_at=occurred_at,
                ),
                InboundDealerMessageRecord(
                    id="message-api-baytown",
                    interaction_id="interaction-api-baytown",
                    source_fixture_id="fixture-api-baytown",
                    dealer_id="baytown",
                    vehicle_id="baytown-blue",
                    subject="Dealer response",
                    body=RAW_MARKER,
                    received_at=occurred_at,
                    source_provider="test-fixture",
                    analysis_status="ANALYZED",
                    analysis_snapshot={"safe": "authoritative snapshot"},
                    analyzed_at=occurred_at,
                    created_at=occurred_at,
                ),
                AgentEventRecord(
                    id="event-api-baytown",
                    run_id="run-api-baytown",
                    semantic_key="response-analyzed:message-api-baytown",
                    event_type="RESPONSE_ANALYZED",
                    phase="INTERACTION_COMPLETE",
                    node="observe_authoritative_state",
                    action_id="action-api-baytown",
                    interaction_id="interaction-api-baytown",
                    message_id="message-api-baytown",
                    message="Dealer response analyzed against deterministic quote policy.",
                    event_metadata={
                        "raw_prompt": RAW_MARKER,
                        "hidden_reasoning": RAW_MARKER,
                    },
                    created_at=occurred_at,
                ),
            ]
        )
        session.commit()


@pytest.fixture
def activity_api_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[ActivityApiHarness]:
    application_path = tmp_path / "purchase-activity-api.db"
    checkpoint_path = tmp_path / "purchase-activity-checkpoint.db"
    checkpoint_path.write_bytes(b"checkpoint-must-remain-untouched")
    engine = build_engine(f"sqlite:///{application_path}")
    create_schema(engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    _seed_activity(session_factory)

    def override_session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    monkeypatch.setenv("OTD_LANGGRAPH_CHECKPOINT_PATH", str(checkpoint_path))
    get_settings.cache_clear()
    monkeypatch.setattr(app_main, "create_schema", lambda: None)
    monkeypatch.setattr(AgentWorkflowService, "create", _forbidden_async_call)
    monkeypatch.setattr(AgentWorkflowService, "resume", _forbidden_async_call)
    monkeypatch.setattr(OfferComparisonService, "compare", _forbidden_async_call)
    monkeypatch.setattr(OutreachService, "approve_and_send", _forbidden_async_call)
    monkeypatch.setattr(ResearchService, "investigate", _forbidden_async_call)
    app_main.app.dependency_overrides[get_session] = override_session
    for dependency in (
        get_inventory_provider,
        get_dealer_contact_resolver,
        get_messaging_provider,
        get_dealer_message_provider,
        get_quote_extractor,
        get_followup_drafter,
        get_research_provider,
        get_research_synthesizer,
    ):
        app_main.app.dependency_overrides[dependency] = _forbidden_dependency

    try:
        with TestClient(app_main.app) as client:
            yield ActivityApiHarness(
                client=client,
                engine=engine,
                session_factory=session_factory,
                checkpoint_path=checkpoint_path,
            )
    finally:
        app_main.app.dependency_overrides.clear()
        get_settings.cache_clear()
        engine.dispose()


def _row_counts(session_factory: sessionmaker[Session]) -> dict[str, int]:
    with session_factory() as session:
        return {
            "events": session.scalar(select(func.count(AgentEventRecord.id))) or 0,
            "actions": session.scalar(select(func.count(ProposedActionRecord.id))) or 0,
            "approvals": (
                session.scalar(select(func.count(ApprovalRecordModel.id))) or 0
            ),
            "deliveries": (
                session.scalar(select(func.count(OutboundDeliveryRecord.id))) or 0
            ),
            "messages": (
                session.scalar(select(func.count(InboundDealerMessageRecord.id))) or 0
            ),
        }


def test_activity_get_is_session_only_read_only_and_safely_whitelisted(
    activity_api_harness: ActivityApiHarness,
) -> None:
    statements: list[str] = []

    def record_statement(
        _: object,
        __: object,
        statement: str,
        ___: object,
        ____: object,
        _____: object,
    ) -> None:
        statements.append(statement.lstrip().partition(" ")[0].upper())

    before_counts = _row_counts(activity_api_harness.session_factory)
    before_checkpoint = activity_api_harness.checkpoint_path.read_bytes()
    event.listen(
        activity_api_harness.engine,
        "before_cursor_execute",
        record_statement,
    )
    try:
        response = activity_api_harness.client.get(
            "/purchase-runs/purchase-api-activity/activity"
        )
    finally:
        event.remove(
            activity_api_harness.engine,
            "before_cursor_execute",
            record_statement,
        )

    assert response.status_code == 200, response.text
    assert statements and set(statements) == {"SELECT"}
    assert _row_counts(activity_api_harness.session_factory) == before_counts
    assert activity_api_harness.checkpoint_path.read_bytes() == before_checkpoint

    payload = response.json()
    assert payload == [
        {
            "event_id": "event-api-baytown",
            "agent_run_id": "run-api-baytown",
            "vehicle_id": "baytown-blue",
            "dealer_id": "baytown",
            "dealer_name": "Baytown Hyundai",
            "event_type": "RESPONSE_ANALYZED",
            "message": (
                "Dealer response analyzed against deterministic quote policy."
            ),
            "occurred_at": "2026-08-20T15:14:00Z",
        }
    ]
    serialized = json.dumps(payload)
    assert RAW_MARKER not in serialized
    assert not ({"node", "phase", "metadata", "action_id", "message_id"} & payload[0].keys())


def test_activity_get_distinguishes_empty_purchase_and_unknown_purchase(
    activity_api_harness: ActivityApiHarness,
) -> None:
    with activity_api_harness.session_factory() as session:
        session.add(
            PurchaseRun(
                id="purchase-api-empty",
                goal="Compare selected offers.",
                status="CREATED",
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    empty = activity_api_harness.client.get(
        "/purchase-runs/purchase-api-empty/activity"
    )
    missing = activity_api_harness.client.get(
        "/purchase-runs/purchase-api-missing/activity"
    )

    assert empty.status_code == 200
    assert empty.json() == []
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "purchase_run_not_found"
