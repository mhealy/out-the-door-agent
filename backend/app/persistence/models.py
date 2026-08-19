from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
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
