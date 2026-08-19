from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _StrictFrozenModel(BaseModel):
    """Immutable input/output contract used by the follow-up drafting seam."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


class FollowupRequirement(_StrictFrozenModel):
    """A code-owned requirement that the wording provider must address."""

    id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=500)
    wording_options: list[str] = Field(min_length=1, max_length=4)


class FollowupDraftRequest(_StrictFrozenModel):
    """Model wording for exactly one deterministic requirement identifier."""

    requirement_id: str = Field(min_length=1, max_length=100)
    # This is untrusted provider output. A broad transport bound prevents an
    # unbounded payload while the deterministic validator owns the tighter
    # nonempty/concise wording policy.
    text: str = Field(max_length=20_000)


class FollowupDraft(_StrictFrozenModel):
    """Untrusted structured wording returned by a follow-up drafter."""

    subject: str = Field(max_length=20_000)
    requests: list[FollowupDraftRequest] = Field(min_length=1, max_length=20)


class ValidatedFollowupDraft(_StrictFrozenModel):
    """Application-validated wording ready to become an immutable proposal."""

    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=10_000)
    addressed_requirements: list[str] = Field(min_length=1, max_length=20)


class FollowupConversationMessage(_StrictFrozenModel):
    """Read-only conversation context supplied to the wording provider."""

    direction: Literal["OUTBOUND", "INBOUND"]
    subject: str | None = Field(default=None, max_length=500)
    body: str = Field(min_length=1, max_length=50_000)


class FollowupDraftContext(_StrictFrozenModel):
    """The complete, application-owned context for one bounded drafting call."""

    interaction_id: str = Field(min_length=1, max_length=200)
    dealer_id: str = Field(min_length=1, max_length=200)
    dealer_name: str = Field(min_length=1, max_length=500)
    vehicle_description: str = Field(min_length=1, max_length=1_000)
    target_vin: str | None = Field(default=None, min_length=1, max_length=100)
    target_stock_number: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )
    previous_outbound: list[FollowupConversationMessage] = Field(
        default_factory=list,
        max_length=20,
    )
    latest_inbound: FollowupConversationMessage
    requirements: list[FollowupRequirement] = Field(max_length=20)
    source_uncertainty: list[str] = Field(default_factory=list, max_length=20)
