from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.domain.approval import (
    ApprovalRecord,
    OutreachProposal,
    OutreachVehicleSnapshot,
    ProposedAction,
)
from app.domain.message import DeliveryReceipt
from app.domain.outreach_requirements import (
    OUTREACH_REQUIREMENT_LABELS_BY_ACTION_TYPE,
)
from app.domain.vehicle import VehicleListing
from app.persistence.models import (
    ApprovalRecordModel,
    DealerInteractionFollowupRecord,
    DealerInteractionFollowupStateRecord,
    DealerInteractionRecord,
    InboundDealerMessageRecord,
    OutboundDeliveryRecord,
    ProposedActionRecord,
)


class OutreachRecordNotFoundError(LookupError):
    """No persisted proposed action exists for the supplied identifier."""


class OutreachFollowupLimitReachedError(RuntimeError):
    """The interaction has no unreserved follow-up send round remaining."""


FOLLOWUP_LIMIT = 2


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


def _action_record(
    action: ProposedAction,
    vehicle: OutreachVehicleSnapshot,
) -> ProposedActionRecord:
    return ProposedActionRecord(
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
        vehicle_snapshot=vehicle.model_dump(mode="json"),
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
        self._session.add(_action_record(action, snapshot))
        self._session.commit()
        self._session.expire_all()

    def create_followup(
        self,
        action: ProposedAction,
        vehicle: OutreachVehicleSnapshot,
        interaction_id: str,
        source_message_id: str,
    ) -> None:
        """Persist a follow-up and its interaction link in one transaction."""

        if action.action_type != "SEND_FOLLOWUP":
            raise ValueError("Only SEND_FOLLOWUP actions can be linked as follow-ups.")

        interaction = self._session.get(DealerInteractionRecord, interaction_id)
        source_message = self._session.get(
            InboundDealerMessageRecord,
            source_message_id,
        )
        if interaction is None or source_message is None:
            raise OutreachRecordNotFoundError(interaction_id)
        if source_message.interaction_id != interaction_id:
            raise ValueError("The source message does not belong to the interaction.")
        if (
            action.dealer_id != interaction.dealer_id
            or action.vehicle_id != interaction.vehicle_id
            or vehicle.dealer_id != interaction.dealer_id
            or vehicle.id != interaction.vehicle_id
            or vehicle.model_dump(mode="json") != interaction.vehicle_snapshot
        ):
            raise ValueError("The follow-up target does not match the interaction.")

        now = datetime.now(timezone.utc)
        self._ensure_followup_state(interaction_id, created_at=now)
        available = self._session.execute(
            update(DealerInteractionFollowupStateRecord)
            .where(
                DealerInteractionFollowupStateRecord.interaction_id
                == interaction_id,
                DealerInteractionFollowupStateRecord.sent_count < FOLLOWUP_LIMIT,
            )
            .values(
                sent_count=DealerInteractionFollowupStateRecord.sent_count
            )
            .execution_options(synchronize_session=False)
        )
        if available.rowcount != 1:
            self._session.rollback()
            self._session.expire_all()
            raise OutreachFollowupLimitReachedError(interaction_id)

        self._session.add(_action_record(action, vehicle))
        self._session.add(
            DealerInteractionFollowupRecord(
                interaction_id=interaction_id,
                proposed_action_id=action.id,
                source_message_id=source_message_id,
                created_at=now,
            )
        )
        self._session.commit()
        self._session.expire_all()

    def get_action(self, action_id: str) -> ProposedActionRecord:
        record = self._session.get(ProposedActionRecord, action_id)
        if record is None:
            raise OutreachRecordNotFoundError(action_id)
        return record

    def get_sent_followup_count(self, interaction_id: str) -> int:
        state = self._session.get(
            DealerInteractionFollowupStateRecord,
            interaction_id,
        )
        return 0 if state is None else state.sent_count

    def get_followup_counts(self, interaction_id: str) -> tuple[int, int]:
        state = self._session.get(
            DealerInteractionFollowupStateRecord,
            interaction_id,
        )
        if state is None:
            return 0, 0
        return state.sent_count, state.reserved_count

    def followup_limit_reached(self, interaction_id: str) -> bool:
        return self.get_sent_followup_count(interaction_id) >= FOLLOWUP_LIMIT

    def claim_approval(self, action: ProposedActionRecord) -> bool:
        now = datetime.now(timezone.utc)
        snapshot = _action_from_record(action)
        followup_link = None
        if action.action_type == "SEND_FOLLOWUP":
            followup_link = self._session.scalar(
                select(DealerInteractionFollowupRecord).where(
                    DealerInteractionFollowupRecord.proposed_action_id
                    == action.id
                )
            )
            if followup_link is None:
                raise OutreachRecordNotFoundError(action.id)

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

        if followup_link is not None:
            reserved = self._session.execute(
                update(DealerInteractionFollowupStateRecord)
                .where(
                    DealerInteractionFollowupStateRecord.interaction_id
                    == followup_link.interaction_id,
                    (
                        DealerInteractionFollowupStateRecord.sent_count
                        + DealerInteractionFollowupStateRecord.reserved_count
                    )
                    < FOLLOWUP_LIMIT,
                )
                .values(
                    reserved_count=(
                        DealerInteractionFollowupStateRecord.reserved_count + 1
                    )
                )
                .execution_options(synchronize_session=False)
            )
            if reserved.rowcount != 1:
                interaction_id = followup_link.interaction_id
                self._session.rollback()
                self._session.expire_all()
                raise OutreachFollowupLimitReachedError(interaction_id)

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
        followup_link = None
        if action.action_type == "SEND_FOLLOWUP":
            followup_link = self._followup_link(action_id)

        now = datetime.now(timezone.utc)
        sent = self._session.execute(
            update(ProposedActionRecord)
            .where(
                ProposedActionRecord.id == action_id,
                ProposedActionRecord.status == "APPROVED",
            )
            .values(status="SENT", updated_at=now)
            .execution_options(synchronize_session=False)
        )
        if sent.rowcount != 1:
            self._session.rollback()
            self._session.expire_all()
            raise OutreachRecordNotFoundError(action_id)

        if followup_link is not None:
            counted = self._session.execute(
                update(DealerInteractionFollowupStateRecord)
                .where(
                    DealerInteractionFollowupStateRecord.interaction_id
                    == followup_link.interaction_id,
                    DealerInteractionFollowupStateRecord.reserved_count > 0,
                    DealerInteractionFollowupStateRecord.sent_count
                    < FOLLOWUP_LIMIT,
                )
                .values(
                    reserved_count=(
                        DealerInteractionFollowupStateRecord.reserved_count - 1
                    ),
                    sent_count=DealerInteractionFollowupStateRecord.sent_count + 1,
                )
                .execution_options(synchronize_session=False)
            )
            if counted.rowcount != 1:
                self._session.rollback()
                self._session.expire_all()
                raise OutreachRecordNotFoundError(action_id)

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
            interaction_id = str(uuid4())
            self._session.add_all(
                [
                    DealerInteractionRecord(
                        id=interaction_id,
                        initial_action_id=action_id,
                        dealer_id=action.dealer_id,
                        vehicle_id=action.vehicle_id,
                        vehicle_snapshot=dict(action.vehicle_snapshot),
                        created_at=receipt.sent_at,
                    ),
                    DealerInteractionFollowupStateRecord(
                        interaction_id=interaction_id,
                        sent_count=0,
                        reserved_count=0,
                        created_at=receipt.sent_at,
                    ),
                ]
            )
        self._session.commit()
        self._session.expire_all()

    def mark_send_failed(self, action_id: str) -> None:
        action = self.get_action(action_id)
        followup_link = None
        if action.action_type == "SEND_FOLLOWUP":
            followup_link = self._followup_link(action_id)

        failed = self._session.execute(
            update(ProposedActionRecord)
            .where(
                ProposedActionRecord.id == action_id,
                ProposedActionRecord.status == "APPROVED",
            )
            .values(
                status="SEND_FAILED",
                updated_at=datetime.now(timezone.utc),
            )
            .execution_options(synchronize_session=False)
        )
        if failed.rowcount != 1:
            self._session.rollback()
            self._session.expire_all()
            raise OutreachRecordNotFoundError(action_id)

        if followup_link is not None:
            released = self._session.execute(
                update(DealerInteractionFollowupStateRecord)
                .where(
                    DealerInteractionFollowupStateRecord.interaction_id
                    == followup_link.interaction_id,
                    DealerInteractionFollowupStateRecord.reserved_count > 0,
                )
                .values(
                    reserved_count=(
                        DealerInteractionFollowupStateRecord.reserved_count - 1
                    )
                )
                .execution_options(synchronize_session=False)
            )
            if released.rowcount != 1:
                self._session.rollback()
                self._session.expire_all()
                raise OutreachRecordNotFoundError(action_id)

        self._session.commit()
        self._session.expire_all()

    def get_proposal(self, action_id: str) -> OutreachProposal:
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
        requirement_labels = OUTREACH_REQUIREMENT_LABELS_BY_ACTION_TYPE[
            action.action_type
        ]
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

    def _ensure_followup_state(
        self,
        interaction_id: str,
        *,
        created_at: datetime,
    ) -> None:
        """Lazily backfill state for interactions created before this table existed."""

        self._session.execute(
            sqlite_insert(DealerInteractionFollowupStateRecord)
            .values(
                interaction_id=interaction_id,
                sent_count=0,
                reserved_count=0,
                created_at=created_at,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    DealerInteractionFollowupStateRecord.interaction_id
                ]
            )
        )

    def _followup_link(self, action_id: str) -> DealerInteractionFollowupRecord:
        link = self._session.scalar(
            select(DealerInteractionFollowupRecord).where(
                DealerInteractionFollowupRecord.proposed_action_id == action_id
            )
        )
        if link is None:
            raise OutreachRecordNotFoundError(action_id)
        return link
