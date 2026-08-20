from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.approval import OutreachVehicleSnapshot
from app.domain.interaction import DealerInteraction
from app.domain.message import DealerMessage
from app.domain.quote import QuoteAnalysisResult
from app.persistence.models import (
    DealerInteractionFollowupRecord,
    DealerInteractionRecord,
    InboundDealerMessageRecord,
)
from app.persistence.outreach import OutreachRepository


class InteractionRecordNotFoundError(LookupError):
    """No durable interaction exists for the supplied initial action."""


ANALYSIS_CLAIM_LEASE = timedelta(minutes=5)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def dealer_message_from_record(record: InboundDealerMessageRecord) -> DealerMessage:
    return DealerMessage(
        id=record.id,
        dealer_id=record.dealer_id,
        vehicle_id=record.vehicle_id,
        subject=record.subject,
        body=record.body,
        received_at=_utc(record.received_at),
        source_provider=record.source_provider,
    )


class InteractionRepository:
    """Focused persistence for one initial outreach and its inbound messages."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_record(self, action_id: str) -> DealerInteractionRecord:
        interaction = self._session.scalar(
            select(DealerInteractionRecord).where(
                DealerInteractionRecord.initial_action_id == action_id
            )
        )
        if interaction is None:
            raise InteractionRecordNotFoundError(action_id)
        return interaction

    def reserve_message(
        self,
        interaction: DealerInteractionRecord,
        fixture_message: DealerMessage,
    ) -> tuple[InboundDealerMessageRecord, bool]:
        interaction_id = interaction.id
        fixture_id = fixture_message.id
        existing = self._message_for_fixture(interaction_id, fixture_id)
        if existing is not None:
            return existing, False

        record = InboundDealerMessageRecord(
            id=str(uuid4()),
            interaction_id=interaction_id,
            source_fixture_id=fixture_id,
            # Target association is application-owned; fixture content cannot rebind it.
            dealer_id=interaction.dealer_id,
            vehicle_id=interaction.vehicle_id,
            subject=fixture_message.subject,
            body=fixture_message.body,
            # This is the application receipt event, not the fixture author's
            # illustrative timestamp. Keep it UTC and never earlier than send.
            received_at=max(
                datetime.now(timezone.utc),
                _utc(interaction.created_at),
            ),
            source_provider=fixture_message.source_provider,
            analysis_status="RESPONSE_RECEIVED",
        )
        self._session.add(record)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            concurrent = self._message_for_fixture(interaction_id, fixture_id)
            if concurrent is None:
                raise
            return concurrent, False
        self._session.expire_all()
        persisted = self._session.get(InboundDealerMessageRecord, record.id)
        if persisted is None:
            raise InteractionRecordNotFoundError(record.id)
        return persisted, True

    def claim_analysis(
        self,
        message_id: str,
        *,
        claimed_at: datetime | None = None,
    ) -> str | None:
        """Atomically lease one message analysis to a single request."""

        claim_time = claimed_at or datetime.now(timezone.utc)
        stale_before = claim_time - ANALYSIS_CLAIM_LEASE
        claim_token = str(uuid4())
        result = self._session.execute(
            update(InboundDealerMessageRecord)
            .where(
                InboundDealerMessageRecord.id == message_id,
                or_(
                    InboundDealerMessageRecord.analysis_status.in_(
                        ("RESPONSE_RECEIVED", "ANALYSIS_FAILED")
                    ),
                    and_(
                        InboundDealerMessageRecord.analysis_status
                        == "ANALYSIS_IN_PROGRESS",
                        or_(
                            InboundDealerMessageRecord.analysis_claimed_at.is_(None),
                            InboundDealerMessageRecord.analysis_claimed_at
                            <= stale_before,
                        ),
                    ),
                ),
            )
            .values(
                analysis_status="ANALYSIS_IN_PROGRESS",
                analysis_snapshot=None,
                analysis_error_code=None,
                analysis_claim_token=claim_token,
                analysis_claimed_at=claim_time,
                analyzed_at=None,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            self._session.rollback()
            self._session.expire_all()
            return None
        self._session.commit()
        self._session.expire_all()
        return claim_token

    def record_analysis(
        self,
        message_id: str,
        analysis: QuoteAnalysisResult,
        claim_token: str,
    ) -> bool:
        snapshot = analysis.model_dump(mode="json", exclude={"message"})
        result = self._session.execute(
            update(InboundDealerMessageRecord)
            .where(
                InboundDealerMessageRecord.id == message_id,
                InboundDealerMessageRecord.analysis_status
                == "ANALYSIS_IN_PROGRESS",
                InboundDealerMessageRecord.analysis_claim_token == claim_token,
            )
            .values(
                analysis_status="ANALYZED",
                analysis_snapshot=snapshot,
                analysis_error_code=None,
                analysis_claim_token=None,
                analysis_claimed_at=None,
                analyzed_at=datetime.now(timezone.utc),
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            self._session.rollback()
            self._session.expire_all()
            return False
        self._session.commit()
        self._session.expire_all()
        return True

    def record_analysis_failure(
        self,
        message_id: str,
        error_code: str,
        claim_token: str,
    ) -> bool:
        result = self._session.execute(
            update(InboundDealerMessageRecord)
            .where(
                InboundDealerMessageRecord.id == message_id,
                InboundDealerMessageRecord.analysis_status
                == "ANALYSIS_IN_PROGRESS",
                InboundDealerMessageRecord.analysis_claim_token == claim_token,
            )
            .values(
                analysis_status="ANALYSIS_FAILED",
                analysis_snapshot=None,
                analysis_error_code=error_code,
                analysis_claim_token=None,
                analysis_claimed_at=None,
                analyzed_at=datetime.now(timezone.utc),
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            self._session.rollback()
            self._session.expire_all()
            return False
        self._session.commit()
        self._session.expire_all()
        return True

    def get(self, action_id: str) -> DealerInteraction:
        interaction = self.get_record(action_id)
        records = list(
            self._session.scalars(
                select(InboundDealerMessageRecord)
                .where(
                    InboundDealerMessageRecord.interaction_id == interaction.id
                )
                .order_by(
                    InboundDealerMessageRecord.created_at,
                    InboundDealerMessageRecord.id,
                )
            )
        )
        messages = [dealer_message_from_record(record) for record in records]
        followup_links = list(
            self._session.scalars(
                select(DealerInteractionFollowupRecord)
                .where(
                    DealerInteractionFollowupRecord.interaction_id
                    == interaction.id
                )
                .order_by(
                    DealerInteractionFollowupRecord.created_at,
                    DealerInteractionFollowupRecord.proposed_action_id,
                )
            )
        )
        outreach_repository = OutreachRepository(self._session)
        followups = [
            outreach_repository.get_proposal(link.proposed_action_id)
            for link in followup_links
        ]
        sent_followup_count = outreach_repository.get_sent_followup_count(
            interaction.id
        )

        analysis = None
        analysis_status = "AWAITING_RESPONSE"
        analysis_error_code = None
        latest_response_followup_status = None
        latest_response_followup_attempt_id = None
        latest_response_followup_attempt_status = None
        if records:
            latest_record = records[-1]
            latest_message = messages[-1]
            analysis_status = latest_record.analysis_status
            analysis_error_code = latest_record.analysis_error_code
            if latest_record.analysis_snapshot is not None:
                analysis = QuoteAnalysisResult.model_validate(
                    {
                        "message": latest_message.model_dump(mode="json"),
                        **latest_record.analysis_snapshot,
                    }
                )
            if (
                latest_record.analysis_status == "ANALYZED"
                and latest_record.analysis_snapshot is not None
            ):
                blocker = outreach_repository.get_source_followup_blocker(
                    interaction.id,
                    latest_record.id,
                )
                if blocker is not None:
                    latest_response_followup_status = blocker.status
                latest_attempt = (
                    outreach_repository.get_latest_source_followup_attempt(
                        interaction.id,
                        latest_record.id,
                    )
                )
                if latest_attempt is not None:
                    latest_response_followup_attempt_id = latest_attempt.id
                    latest_response_followup_attempt_status = latest_attempt.status

        return DealerInteraction(
            id=interaction.id,
            initial_action_id=interaction.initial_action_id,
            dealer_id=interaction.dealer_id,
            vehicle_id=interaction.vehicle_id,
            vehicle=OutreachVehicleSnapshot.model_validate(
                interaction.vehicle_snapshot
            ),
            created_at=_utc(interaction.created_at),
            analysis_status=analysis_status,
            messages=messages,
            followups=followups,
            sent_followup_count=sent_followup_count,
            latest_response_followup_status=latest_response_followup_status,
            latest_response_followup_attempt_id=(
                latest_response_followup_attempt_id
            ),
            latest_response_followup_attempt_status=(
                latest_response_followup_attempt_status
            ),
            analysis=analysis,
            analysis_error_code=analysis_error_code,
        )

    def _message_for_fixture(
        self,
        interaction_id: str,
        fixture_id: str,
    ) -> InboundDealerMessageRecord | None:
        return self._session.scalar(
            select(InboundDealerMessageRecord).where(
                InboundDealerMessageRecord.interaction_id == interaction_id,
                InboundDealerMessageRecord.source_fixture_id == fixture_id,
            )
        )
