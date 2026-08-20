from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.persistence.db import build_engine, create_schema
from app.persistence.models import (
    AgentEventRecord,
    AgentRunRecord,
    ProposedActionRecord,
    PurchaseRun,
    PurchaseRunVehicleRecord,
)
from app.persistence.purchases import PurchaseRunNotFoundError
from app.services.purchase_activity import PurchaseActivityService


def _add_child(
    session: Session,
    *,
    purchase_id: str,
    run_id: str,
    vehicle_id: str,
    position: int,
    dealer_id: str | None,
    dealer_name: str | None,
    created_at: datetime,
) -> AgentRunRecord:
    action_id = f"action-{run_id}"
    run = AgentRunRecord(
        id=run_id,
        thread_id=f"thread-{run_id}",
        vehicle_id=vehicle_id,
        phase="WAITING_FOR_APPROVAL",
        initial_action_id=action_id,
        current_action_id=action_id,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(run)
    session.add(
        PurchaseRunVehicleRecord(
            id=f"link-{run_id}",
            purchase_run_id=purchase_id,
            vehicle_id=vehicle_id,
            position=position,
            agent_run_id=run_id,
            created_at=created_at,
            updated_at=created_at,
        )
    )
    if dealer_id is not None and dealer_name is not None:
        session.add(
            ProposedActionRecord(
                id=action_id,
                action_type="SEND_INITIAL_QUOTE_REQUEST",
                dealer_id=dealer_id,
                vehicle_id=vehicle_id,
                recipient=f"quotes@{dealer_id}.example.test",
                subject="Written quote request",
                body="Safe exact request body.",
                reason="Obtain a complete written quote.",
                requested_information=["claimed_otd"],
                requires_approval=True,
                status="PENDING_APPROVAL",
                vehicle_snapshot={
                    "id": vehicle_id,
                    "year": 2025,
                    "make": "Hyundai",
                    "model": "Tucson Hybrid",
                    "trim": "Limited",
                    "vin": None,
                    "stock_number": None,
                    "dealer_id": dealer_id,
                    "dealer_name": dealer_name,
                },
                created_at=created_at,
                updated_at=created_at,
            )
        )
    return run


def _add_event(
    session: Session,
    *,
    event_id: str,
    run_id: str,
    event_type: str,
    message: str,
    occurred_at: datetime,
) -> None:
    session.add(
        AgentEventRecord(
            id=event_id,
            run_id=run_id,
            semantic_key=f"semantic-{event_id}",
            event_type=event_type,
            phase="WAITING_FOR_APPROVAL",
            node="internal_node_that_must_not_be_projected",
            action_id=f"private-action-{event_id}",
            interaction_id=None,
            message_id=None,
            message=message,
            event_metadata={"reason_code": "private-reason"},
            created_at=occurred_at,
        )
    )


@pytest.fixture
def activity_session(tmp_path: Path) -> Session:
    engine = build_engine(f"sqlite:///{tmp_path / 'activity.db'}")
    create_schema(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_merges_child_events_by_time_then_id_and_preserves_whitelisted_identity(
    activity_session: Session,
) -> None:
    occurred_at = datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc)
    activity_session.add(
        PurchaseRun(
            id="purchase-activity",
            goal="Compare the selected written offers.",
            status="CREATED",
            created_at=occurred_at,
        )
    )
    _add_child(
        activity_session,
        purchase_id="purchase-activity",
        run_id="run-baytown",
        vehicle_id="baytown-blue",
        position=0,
        dealer_id="baytown",
        dealer_name="Baytown Hyundai",
        created_at=occurred_at,
    )
    _add_child(
        activity_session,
        purchase_id="purchase-activity",
        run_id="run-houston",
        vehicle_id="houston-white",
        position=1,
        dealer_id=None,
        dealer_name=None,
        created_at=occurred_at,
    )
    _add_event(
        activity_session,
        event_id="event-b",
        run_id="run-houston",
        event_type="RUN_STARTED",
        message="Houston workflow started.",
        occurred_at=occurred_at,
    )
    _add_event(
        activity_session,
        event_id="event-z",
        run_id="run-baytown",
        event_type="OUTREACH_SENT",
        message="Baytown delivery was confirmed.",
        occurred_at=occurred_at + timedelta(seconds=1),
    )
    _add_event(
        activity_session,
        event_id="event-a",
        run_id="run-baytown",
        event_type="WAITING_FOR_APPROVAL",
        message="Baytown request awaits approval.",
        occurred_at=occurred_at,
    )
    activity_session.commit()

    items = PurchaseActivityService(activity_session).list("purchase-activity")

    assert [item.event_id for item in items] == ["event-a", "event-b", "event-z"]
    assert [item.agent_run_id for item in items] == [
        "run-baytown",
        "run-houston",
        "run-baytown",
    ]
    assert items[0].dealer_id == "baytown"
    assert items[0].dealer_name == "Baytown Hyundai"
    assert items[1].dealer_id is None
    assert items[1].dealer_name is None
    assert items[0].occurred_at == occurred_at
    assert set(items[0].model_dump()) == {
        "event_id",
        "agent_run_id",
        "vehicle_id",
        "dealer_id",
        "dealer_name",
        "event_type",
        "message",
        "occurred_at",
    }


def test_valid_empty_purchase_is_distinct_from_unknown_purchase(
    activity_session: Session,
) -> None:
    activity_session.add(
        PurchaseRun(
            id="purchase-empty",
            goal="Compare selected offers.",
            status="CREATED",
            created_at=datetime.now(timezone.utc),
        )
    )
    activity_session.commit()
    service = PurchaseActivityService(activity_session)

    assert service.list("purchase-empty") == []
    with pytest.raises(PurchaseRunNotFoundError):
        service.list("purchase-missing")
