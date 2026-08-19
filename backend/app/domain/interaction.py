from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.approval import OutreachVehicleSnapshot
from app.domain.message import DealerMessage
from app.domain.quote import QuoteAnalysisResult


InteractionAnalysisStatus = Literal[
    "AWAITING_RESPONSE",
    "RESPONSE_RECEIVED",
    "ANALYSIS_IN_PROGRESS",
    "ANALYZED",
    "ANALYSIS_FAILED",
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
    analysis: QuoteAnalysisResult | None = None
    analysis_error_code: str | None = None
