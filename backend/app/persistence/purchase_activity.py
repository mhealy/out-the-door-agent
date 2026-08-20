from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.purchase import PurchaseActivityItem
from app.persistence.models import (
    AgentEventRecord,
    AgentRunRecord,
    ProposedActionRecord,
    PurchaseRunVehicleRecord,
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class PurchaseActivityRepository:
    """Project existing child AgentEvents without invoking application capabilities."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_purchase(self, purchase_id: str) -> list[PurchaseActivityItem]:
        rows = self._session.execute(
            select(
                AgentEventRecord.id,
                AgentEventRecord.run_id,
                PurchaseRunVehicleRecord.vehicle_id,
                ProposedActionRecord.dealer_id,
                ProposedActionRecord.vehicle_snapshot,
                AgentEventRecord.event_type,
                AgentEventRecord.message,
                AgentEventRecord.created_at,
            )
            .select_from(PurchaseRunVehicleRecord)
            .join(
                AgentRunRecord,
                AgentRunRecord.id == PurchaseRunVehicleRecord.agent_run_id,
            )
            .join(
                AgentEventRecord,
                AgentEventRecord.run_id == AgentRunRecord.id,
            )
            .outerjoin(
                ProposedActionRecord,
                ProposedActionRecord.id == AgentRunRecord.initial_action_id,
            )
            .where(PurchaseRunVehicleRecord.purchase_run_id == purchase_id)
            .order_by(AgentEventRecord.created_at, AgentEventRecord.id)
        )

        activity: list[PurchaseActivityItem] = []
        for (
            event_id,
            agent_run_id,
            vehicle_id,
            dealer_id,
            vehicle_snapshot,
            event_type,
            message,
            occurred_at,
        ) in rows:
            dealer_name = (
                vehicle_snapshot.get("dealer_name")
                if isinstance(vehicle_snapshot, dict)
                else None
            )
            activity.append(
                PurchaseActivityItem(
                    event_id=event_id,
                    agent_run_id=agent_run_id,
                    vehicle_id=vehicle_id,
                    dealer_id=dealer_id,
                    dealer_name=dealer_name,
                    event_type=event_type,
                    message=message,
                    occurred_at=_utc(occurred_at),
                )
            )
        return activity
