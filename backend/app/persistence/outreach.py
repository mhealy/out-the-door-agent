from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.approval import (
    ApprovalRecord,
    OutreachProposal,
    OutreachVehicleSnapshot,
    ProposedAction,
)
from app.domain.message import DeliveryReceipt
from app.domain.vehicle import VehicleListing
from app.persistence.models import (
    ApprovalRecordModel,
    DealerInteractionRecord,
    OutboundDeliveryRecord,
    ProposedActionRecord,
)


class OutreachRecordNotFoundError(LookupError):
    """No persisted proposed action exists for the supplied identifier."""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _action_from_record(record: ProposedActionRecord) -> ProposedAction:
    return ProposedAction(
        id=record.id,
        action_type=record.action_type,
        dealer_id=record.dealer_id,
        vehicle_id=record.vehicle_id,
        recipient=record.recipient,
        subject=record.subject,
        body=record.body,
        reason=record.reason,
        requested_information=list(record.requested_information),
        requires_approval=record.requires_approval,
    )


class OutreachRepository:
    """Focused SQLAlchemy persistence for the outbound approval boundary."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, action: ProposedAction, vehicle: VehicleListing) -> None:
        snapshot = OutreachVehicleSnapshot(
            id=vehicle.id,
            year=vehicle.year,
            make=vehicle.make,
            model=vehicle.model,
            trim=vehicle.trim,
            vin=vehicle.vin,
            stock_number=vehicle.stock_number,
            dealer_id=vehicle.dealer_id,
            dealer_name=vehicle.dealer_name,
        )
        self._session.add(
            ProposedActionRecord(
                id=action.id,
                action_type=action.action_type,
                dealer_id=action.dealer_id,
                vehicle_id=action.vehicle_id,
                recipient=action.recipient,
                subject=action.subject,
                body=action.body,
                reason=action.reason,
                requested_information=list(action.requested_information),
                requires_approval=action.requires_approval,
                status="PENDING_APPROVAL",
                vehicle_snapshot=snapshot.model_dump(mode="json"),
            )
        )
        self._session.commit()
        self._session.expire_all()

    def get_action(self, action_id: str) -> ProposedActionRecord:
        record = self._session.get(ProposedActionRecord, action_id)
        if record is None:
            raise OutreachRecordNotFoundError(action_id)
        return record

    def claim_approval(self, action: ProposedActionRecord) -> bool:
        now = datetime.now(timezone.utc)
        snapshot = _action_from_record(action)
        result = self._session.execute(
            update(ProposedActionRecord)
            .where(
                ProposedActionRecord.id == action.id,
                ProposedActionRecord.status == "PENDING_APPROVAL",
            )
            .values(status="APPROVED", updated_at=now)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            self._session.rollback()
            self._session.expire_all()
            return False

        self._session.add(
            ApprovalRecordModel(
                id=str(uuid4()),
                proposed_action_id=action.id,
                decision="APPROVED",
                decided_at=now,
                action_snapshot=snapshot.model_dump(mode="json"),
            )
        )
        self._session.commit()
        self._session.expire_all()
        return True

    def reject(self, action: ProposedActionRecord) -> bool:
        now = datetime.now(timezone.utc)
        snapshot = _action_from_record(action)
        result = self._session.execute(
            update(ProposedActionRecord)
            .where(
                ProposedActionRecord.id == action.id,
                ProposedActionRecord.status == "PENDING_APPROVAL",
            )
            .values(status="REJECTED", updated_at=now)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            self._session.rollback()
            self._session.expire_all()
            return False

        self._session.add(
            ApprovalRecordModel(
                id=str(uuid4()),
                proposed_action_id=action.id,
                decision="REJECTED",
                decided_at=now,
                action_snapshot=snapshot.model_dump(mode="json"),
            )
        )
        self._session.commit()
        self._session.expire_all()
        return True

    def get_approved_action(self, action_id: str) -> ProposedAction:
        approval = self._session.scalar(
            select(ApprovalRecordModel).where(
                ApprovalRecordModel.proposed_action_id == action_id,
                ApprovalRecordModel.decision == "APPROVED",
            )
        )
        if approval is None:
            raise OutreachRecordNotFoundError(action_id)
        return ProposedAction.model_validate(approval.action_snapshot)

    def mark_sent(self, action_id: str, receipt: DeliveryReceipt) -> None:
        action = self.get_action(action_id)
        action.status = "SENT"
        action.updated_at = datetime.now(timezone.utc)
        self._session.add(
            OutboundDeliveryRecord(
                id=str(uuid4()),
                proposed_action_id=action_id,
                provider=receipt.provider,
                external_message_id=receipt.external_message_id,
                sent_at=receipt.sent_at,
            )
        )
        if action.action_type == "SEND_INITIAL_QUOTE_REQUEST":
            self._session.add(
                DealerInteractionRecord(
                    id=str(uuid4()),
                    initial_action_id=action_id,
                    dealer_id=action.dealer_id,
                    vehicle_id=action.vehicle_id,
                    vehicle_snapshot=dict(action.vehicle_snapshot),
                    created_at=receipt.sent_at,
                )
            )
        self._session.commit()
        self._session.expire_all()

    def mark_send_failed(self, action_id: str) -> None:
        action = self.get_action(action_id)
        action.status = "SEND_FAILED"
        action.updated_at = datetime.now(timezone.utc)
        self._session.commit()
        self._session.expire_all()

    def get_proposal(
        self,
        action_id: str,
        requirement_labels: Mapping[str, str],
    ) -> OutreachProposal:
        action = self.get_action(action_id)
        approval_model = self._session.scalar(
            select(ApprovalRecordModel).where(
                ApprovalRecordModel.proposed_action_id == action_id
            )
        )
        delivery_model = self._session.scalar(
            select(OutboundDeliveryRecord).where(
                OutboundDeliveryRecord.proposed_action_id == action_id
            )
        )

        approval = None
        if approval_model is not None:
            approval = ApprovalRecord(
                decision=approval_model.decision,
                decided_at=_utc(approval_model.decided_at),
                action_snapshot=ProposedAction.model_validate(
                    approval_model.action_snapshot
                ),
            )

        delivery = None
        if delivery_model is not None:
            delivery = DeliveryReceipt(
                action_id=action_id,
                provider=delivery_model.provider,
                external_message_id=delivery_model.external_message_id,
                sent_at=_utc(delivery_model.sent_at),
            )

        requested_information = list(action.requested_information)
        return OutreachProposal(
            **_action_from_record(action).model_dump(),
            requested_information_labels=[
                requirement_labels[item]
                for item in requested_information
            ],
            status=action.status,
            vehicle=OutreachVehicleSnapshot.model_validate(action.vehicle_snapshot),
            created_at=_utc(action.created_at),
            approval=approval,
            delivery=delivery,
        )
