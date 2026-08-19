from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PurchaseRun(Base):
    """Minimal persisted run record; workflow state arrives in a later phase."""

    __tablename__ = "purchase_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    goal: Mapped[str] = mapped_column(Text())
    status: Mapped[str] = mapped_column(String(32), default="CREATED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ProposedActionRecord(Base):
    __tablename__ = "proposed_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action_type: Mapped[str] = mapped_column(String(48))
    dealer_id: Mapped[str] = mapped_column(String(128))
    vehicle_id: Mapped[str] = mapped_column(String(128))
    recipient: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(Text())
    body: Mapped[str] = mapped_column(Text())
    reason: Mapped[str] = mapped_column(Text())
    requested_information: Mapped[list[str]] = mapped_column(JSON())
    requires_approval: Mapped[bool] = mapped_column(Boolean(), default=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING_APPROVAL")
    vehicle_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ApprovalRecordModel(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    proposed_action_id: Mapped[str] = mapped_column(
        ForeignKey("proposed_actions.id"), unique=True, index=True
    )
    decision: Mapped[str] = mapped_column(String(16))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    action_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON())


class OutboundDeliveryRecord(Base):
    __tablename__ = "outbound_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    proposed_action_id: Mapped[str] = mapped_column(
        ForeignKey("proposed_actions.id"), unique=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(128))
    external_message_id: Mapped[str] = mapped_column(String(512))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DealerInteractionRecord(Base):
    __tablename__ = "dealer_interactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    initial_action_id: Mapped[str] = mapped_column(
        ForeignKey("proposed_actions.id"), unique=True, index=True
    )
    dealer_id: Mapped[str] = mapped_column(String(128))
    vehicle_id: Mapped[str] = mapped_column(String(128))
    vehicle_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class InboundDealerMessageRecord(Base):
    __tablename__ = "inbound_dealer_messages"
    __table_args__ = (
        UniqueConstraint(
            "interaction_id",
            "source_fixture_id",
            name="uq_inbound_message_interaction_fixture",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    interaction_id: Mapped[str] = mapped_column(
        ForeignKey("dealer_interactions.id"), index=True
    )
    source_fixture_id: Mapped[str] = mapped_column(String(128))
    dealer_id: Mapped[str] = mapped_column(String(128))
    vehicle_id: Mapped[str] = mapped_column(String(128))
    subject: Mapped[str | None] = mapped_column(Text(), nullable=True)
    body: Mapped[str] = mapped_column(Text())
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_provider: Mapped[str] = mapped_column(String(128))
    analysis_status: Mapped[str] = mapped_column(
        String(32), default="RESPONSE_RECEIVED"
    )
    analysis_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(), nullable=True
    )
    analysis_error_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    analysis_claim_token: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    analysis_claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    analyzed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
