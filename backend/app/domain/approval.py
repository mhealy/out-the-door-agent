from typing import Literal

from pydantic import BaseModel, Field


class ProposedAction(BaseModel):
    id: str
    action_type: Literal["SEND_INITIAL_QUOTE_REQUEST", "SEND_FOLLOWUP"]
    dealer_id: str
    vehicle_id: str
    subject: str
    body: str
    reason: str
    requested_information: list[str] = Field(default_factory=list)
    requires_approval: bool = True
