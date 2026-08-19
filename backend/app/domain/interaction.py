from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.domain.approval import OutreachProposal, OutreachVehicleSnapshot
from app.domain.message import DealerMessage
from app.domain.quote import QuoteAnalysisResult


InteractionAnalysisStatus = Literal[
    "AWAITING_RESPONSE",
    "RESPONSE_RECEIVED",
    "ANALYSIS_IN_PROGRESS",
    "ANALYZED",
    "ANALYSIS_FAILED",
]
LatestResponseFollowupStatus = Literal[
    "PENDING_APPROVAL",
    "APPROVED",
    "SENT",
]


class DealerInteraction(BaseModel):
    """Durable dealer/vehicle interaction anchored to an initial action."""

    model_config = ConfigDict(extra="forbid")

    id: str
    initial_action_id: str
    dealer_id: str
    vehicle_id: str
    vehicle: OutreachVehicleSnapshot
    created_at: datetime
    analysis_status: InteractionAnalysisStatus
    messages: list[DealerMessage] = Field(default_factory=list)
    followups: list[OutreachProposal] = Field(default_factory=list)
    sent_followup_count: int = Field(default=0, ge=0, le=2)
    followup_limit: Literal[2] = 2
    latest_response_followup_status: LatestResponseFollowupStatus | None = None
    analysis: QuoteAnalysisResult | None = None
    analysis_error_code: str | None = None

    @computed_field
    @property
    def followup_limit_reached(self) -> bool:
        return self.sent_followup_count >= self.followup_limit
