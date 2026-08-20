from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PurchaseRun(Base):
    """Durable identity for one coordinated set of dealer workflows."""

    __tablename__ = "purchase_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    goal: Mapped[str] = mapped_column(Text())
    status: Mapped[str] = mapped_column(String(32), default="CREATED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class PurchaseRunVehicleRecord(Base):
    """Selected-vehicle intent and its nullable durable child-run association."""

    __tablename__ = "purchase_run_vehicles"
    __table_args__ = (
        UniqueConstraint(
            "purchase_run_id",
            "vehicle_id",
            name="uq_purchase_run_vehicle",
        ),
        UniqueConstraint(
            "purchase_run_id",
            "position",
            name="uq_purchase_run_vehicle_position",
        ),
        UniqueConstraint(
            "agent_run_id",
            name="uq_purchase_run_vehicle_agent_run",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    purchase_run_id: Mapped[str] = mapped_column(
        ForeignKey("purchase_runs.id"), index=True
    )
    vehicle_id: Mapped[str] = mapped_column(String(128), index=True)
    position: Mapped[int] = mapped_column(Integer())
    agent_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_runs.id"), nullable=True
    )
    last_creation_error: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AgentRunRecord(Base):
    """Durable identity and current orchestration projection for one interaction."""

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    vehicle_id: Mapped[str] = mapped_column(String(128), index=True)
    phase: Mapped[str] = mapped_column(String(64))
    initial_action_id: Mapped[str] = mapped_column(String(36))
    current_action_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    interaction_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_event_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    execution_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    execution_claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class AgentEventRecord(Base):
    """User-safe, semantically idempotent workflow activity."""

    __tablename__ = "agent_events"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "semantic_key",
            name="uq_agent_event_run_semantic_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.id"), index=True
    )
    semantic_key: Mapped[str] = mapped_column(String(512))
    event_type: Mapped[str] = mapped_column(String(64))
    phase: Mapped[str] = mapped_column(String(64))
    node: Mapped[str] = mapped_column(String(64))
    action_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    interaction_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    message: Mapped[str] = mapped_column(Text())
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON(),
        default=dict,
    )
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


class DealerInteractionFollowupRecord(Base):
    """Link one immutable follow-up proposal to its existing interaction."""

    __tablename__ = "dealer_interaction_followups"

    proposed_action_id: Mapped[str] = mapped_column(
        ForeignKey("proposed_actions.id"), primary_key=True
    )
    interaction_id: Mapped[str] = mapped_column(
        ForeignKey("dealer_interactions.id"), index=True
    )
    source_message_id: Mapped[str] = mapped_column(
        ForeignKey("inbound_dealer_messages.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class DealerInteractionFollowupStateRecord(Base):
    """Atomic sent/reserved round accounting for one dealer interaction."""

    __tablename__ = "dealer_interaction_followup_states"
    __table_args__ = (
        CheckConstraint("sent_count >= 0", name="ck_followup_state_sent_nonnegative"),
        CheckConstraint(
            "reserved_count >= 0",
            name="ck_followup_state_reserved_nonnegative",
        ),
        CheckConstraint(
            "sent_count + reserved_count <= 2",
            name="ck_followup_state_round_limit",
        ),
    )

    interaction_id: Mapped[str] = mapped_column(
        ForeignKey("dealer_interactions.id"), primary_key=True
    )
    sent_count: Mapped[int] = mapped_column(Integer(), default=0)
    reserved_count: Mapped[int] = mapped_column(Integer(), default=0)
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
