from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.agent_run import AgentEventType, AgentRun
from app.domain.comparison import ComparisonResult, ComparisonStatus
from app.domain.vehicle import VehicleListing


PurchaseSetupStatus = Literal["READY", "RECOVERY_REQUIRED"]
PurchaseDecisionStatus = Literal[
    "GATHERING_OFFERS",
    "COMPARISON_AVAILABLE",
    "DECISION_READY",
]
PurchaseWorkflowStatus = Literal[
    "RECOVERY_REQUIRED",
    "APPROVAL_REQUIRED",
    "DELIVERY_UNCONFIRMED",
    "WAITING_FOR_DEALER",
    "WAITING_FOR_ANALYSIS",
    "ANALYSIS_FAILED",
    "OFFER_INCOMPLETE",
    "OFFER_VERIFIED",
    "RUN_FAILED",
    "RUN_REJECTED",
]
PurchaseAttentionCategory = Literal[
    "RECOVERY_REQUIRED",
    "APPROVAL_REQUIRED",
    "DELIVERY_UNCONFIRMED",
    "WAITING_FOR_DEALER",
    "WAITING_FOR_ANALYSIS",
    "ANALYSIS_FAILED",
    "OFFER_INCOMPLETE",
    "RUN_FAILED",
    "RUN_REJECTED",
]


class _PurchaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PurchaseStatusCounts(_PurchaseModel):
    selected_vehicles: int = Field(ge=0)
    linked_children: int = Field(ge=0)
    quote_requests_prepared: int = Field(ge=0)
    responses_analyzed: int = Field(ge=0)
    verified_offers: int = Field(ge=0)
    incomplete_offers: int = Field(ge=0)
    pending_approvals: int = Field(ge=0)


class PurchaseAttentionItem(_PurchaseModel):
    category: PurchaseAttentionCategory
    vehicle_id: str
    dealer_name: str
    agent_run_id: str | None = None
    action_id: str | None = None
    message: str
    requires_buyer_action: bool


class PurchaseChildSummary(_PurchaseModel):
    vehicle: VehicleListing
    agent_run: AgentRun | None = None
    workflow_status: PurchaseWorkflowStatus
    comparison_status: ComparisonStatus | None = None
    action_id: str | None = None
    creation_error_code: str | None = None
    active_unresolved: bool


class PurchaseActivityItem(_PurchaseModel):
    """Historical child-workflow observation; never authoritative current state."""

    event_id: str
    agent_run_id: str
    vehicle_id: str
    dealer_id: str | None = None
    dealer_name: str | None = None
    event_type: AgentEventType
    message: str
    occurred_at: datetime


class PurchaseWorkspace(_PurchaseModel):
    id: str
    goal: str
    setup_status: PurchaseSetupStatus
    selected_vehicle_ids: list[str]
    children: list[PurchaseChildSummary]
    counts: PurchaseStatusCounts
    attention_items: list[PurchaseAttentionItem]
    comparison: ComparisonResult | None = None
    decision_status: PurchaseDecisionStatus
    created_at: datetime
    updated_at: datetime
