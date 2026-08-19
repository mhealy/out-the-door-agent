from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class OutboundDealerMessage(BaseModel):
    """The immutable, already-approved payload handed to a transport provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str = Field(min_length=1)
    vehicle_id: str = Field(min_length=1)
    dealer_id: str = Field(min_length=1)
    recipient: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)


class DeliveryReceipt(BaseModel):
    """Successful delivery metadata returned by a messaging provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    external_message_id: str = Field(min_length=1)
    sent_at: datetime

    @field_validator("sent_at")
    @classmethod
    def normalize_sent_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("sent_at must be timezone-aware")
        return value.astimezone(timezone.utc)
