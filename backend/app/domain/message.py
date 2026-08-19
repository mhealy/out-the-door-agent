from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DealerMessage(BaseModel):
    """A normalized inbound written response from a dealer."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    dealer_id: str = Field(min_length=1)
    vehicle_id: str | None = None
    direction: Literal["INBOUND"] = "INBOUND"
    subject: str | None = None
    body: str = Field(min_length=1)
    received_at: datetime
    source_provider: str = Field(min_length=1)
