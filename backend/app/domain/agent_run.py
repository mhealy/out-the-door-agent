from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


RunPhase = Literal[
    "STARTING",
    "WAITING_FOR_APPROVAL",
    "WAITING_FOR_EXTERNAL_RESPONSE",
    "WAITING_FOR_ANALYSIS",
    "ANALYSIS_FAILED",
    "DELIVERY_UNCONFIRMED",
    "INTERACTION_COMPLETE",
    "INTERACTION_INCOMPLETE_MAX_FOLLOWUPS",
    "RUN_REJECTED",
    "RUN_FAILED",
]

AgentEventType = Literal[
    "RUN_STARTED",
    "INITIAL_OUTREACH_PREPARED",
    "WAITING_FOR_APPROVAL",
    "OUTREACH_SENT",
    "FOLLOWUP_SENT",
    "DELIVERY_UNCONFIRMED",
    "WAITING_FOR_EXTERNAL_RESPONSE",
    "WAITING_FOR_ANALYSIS",
    "ANALYSIS_FAILED",
    "RESPONSE_ANALYZED",
    "FOLLOWUP_PREPARED",
    "FOLLOWUP_STALE",
    "INTERACTION_COMPLETE",
    "MAX_FOLLOWUPS_REACHED",
    "RUN_REJECTED",
    "RUN_FAILED",
]

AgentEventMetadataValue = str | int | bool | None


class AgentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    run_id: str
    event_type: AgentEventType
    phase: str
    node: str
    action_id: str | None = None
    interaction_id: str | None = None
    message_id: str | None = None
    message: str
    created_at: datetime
    metadata: dict[str, AgentEventMetadataValue] = Field(default_factory=dict)


class AgentRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    run_id: str
    thread_id: str
    vehicle_id: str
    phase: RunPhase
    initial_action_id: str
    current_action_id: str | None = None
    interaction_id: str | None = None
    last_message_id: str | None = None
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime
    events: list[AgentEvent] = Field(default_factory=list)
