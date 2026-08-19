from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.message import DeliveryReceipt

ActionType = Literal["SEND_INITIAL_QUOTE_REQUEST", "SEND_FOLLOWUP"]
ActionStatus = Literal[
    "PENDING_APPROVAL",
    "APPROVED",
    "REJECTED",
    "SENT",
    "SEND_FAILED",
]
ApprovalDecision = Literal["APPROVED", "REJECTED"]


class ProposedAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    action_type: ActionType
    dealer_id: str
    vehicle_id: str
    recipient: str
    subject: str
    body: str
    reason: str
    requested_information: list[str] = Field(default_factory=list)
    requires_approval: Literal[True] = True


class OutreachVehicleSnapshot(BaseModel):
    """Candidate identity persisted when the proposal is prepared."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    year: int
    make: str
    model: str
    trim: str | None = None
    vin: str | None = None
    stock_number: str | None = None
    dealer_id: str
    dealer_name: str


class ApprovalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: ApprovalDecision
    decided_at: datetime
    action_snapshot: ProposedAction


class OutreachProposal(BaseModel):
    """Flat action resource with persisted approval and delivery state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    action_type: ActionType
    dealer_id: str
    vehicle_id: str
    recipient: str
    subject: str
    body: str
    reason: str
    requested_information: list[str]
    requested_information_labels: list[str]
    requires_approval: Literal[True]
    status: ActionStatus
    vehicle: OutreachVehicleSnapshot
    created_at: datetime
    approval: ApprovalRecord | None = None
    delivery: DeliveryReceipt | None = None
