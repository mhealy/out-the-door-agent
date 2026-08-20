from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


ResearchTargetType = Literal["MANDATORY_ADDON"]
ResearchSupportStatus = Literal["SUPPORTED", "MIXED", "INSUFFICIENT"]
ResearchExecutionStatus = Literal["IN_PROGRESS", "COMPLETED", "FAILED"]

MAX_RESEARCH_SOURCES = 8
MAX_RESEARCH_SUMMARY_LENGTH = 1_500
MAX_RESEARCH_LIST_ITEMS = 8
MAX_RESEARCH_ITEM_LENGTH = 400
MAX_RESEARCH_EXCERPT_LENGTH = 4_000

BoundedFindingItem = Annotated[
    str,
    Field(min_length=1, max_length=MAX_RESEARCH_ITEM_LENGTH),
]


class _ResearchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResearchTarget(_ResearchModel):
    target_id: str = Field(min_length=1, max_length=128)
    purchase_run_id: str = Field(min_length=1, max_length=128)
    agent_run_id: str = Field(min_length=1, max_length=128)
    interaction_id: str = Field(min_length=1, max_length=128)
    source_message_id: str = Field(min_length=1, max_length=128)
    dealer_id: str = Field(min_length=1, max_length=128)
    dealer_name: str = Field(min_length=1, max_length=300)
    vehicle_id: str = Field(min_length=1, max_length=128)
    target_type: ResearchTargetType = "MANDATORY_ADDON"
    canonical_name: str = Field(min_length=1, max_length=300)
    dealer_stated_amount: Decimal | None = None
    stated_mandatory: Literal[True] = True
    source_evidence_ids: list[str] = Field(min_length=1, max_length=16)
    recommended: bool = True

    @field_validator("source_evidence_ids")
    @classmethod
    def require_unique_evidence_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("Research target evidence IDs must not be blank.")
        if len(values) != len(set(values)):
            raise ValueError("Research target evidence IDs must be unique.")
        return values


class ResearchRequest(_ResearchModel):
    """The only bounded target information exposed to a retrieval provider."""

    target_id: str = Field(min_length=1, max_length=128)
    target_type: ResearchTargetType
    canonical_name: str = Field(min_length=1, max_length=300)


class ResearchSource(_ResearchModel):
    """Provider-owned, bounded external material; never model-invented metadata."""

    id: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2_000)
    title: str = Field(min_length=1, max_length=500)
    publisher: str | None = Field(default=None, max_length=300)
    retrieved_at: datetime
    excerpt: str = Field(min_length=1, max_length=MAX_RESEARCH_EXCERPT_LENGTH)

    @field_validator("id", "title", "excerpt")
    @classmethod
    def reject_blank_provenance_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Research source provenance fields must not be blank.")
        return value

    @field_validator("url")
    @classmethod
    def require_public_web_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Research source URLs must be absolute HTTP(S) URLs.")
        return value

    @field_validator("publisher")
    @classmethod
    def reject_blank_publisher(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Research source publishers must not be blank.")
        return value


class ResearchProviderResult(_ResearchModel):
    sources: list[ResearchSource] = Field(
        default_factory=list,
        max_length=MAX_RESEARCH_SOURCES,
    )

    @field_validator("sources")
    @classmethod
    def require_unique_source_ids(
        cls,
        values: list[ResearchSource],
    ) -> list[ResearchSource]:
        source_ids = [source.id for source in values]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Research provider source IDs must be unique.")
        return values


class ResearchFindingDraft(_ResearchModel):
    """Tool-free structured model output awaiting deterministic validation."""

    target_id: str = Field(min_length=1, max_length=128)
    target_name: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=MAX_RESEARCH_SUMMARY_LENGTH)
    what_it_appears_to_include: list[BoundedFindingItem] = Field(
        default_factory=list,
        max_length=MAX_RESEARCH_LIST_ITEMS,
    )
    limitations: list[BoundedFindingItem] = Field(
        default_factory=list,
        max_length=MAX_RESEARCH_LIST_ITEMS,
    )
    source_ids: list[str] = Field(
        default_factory=list,
        max_length=MAX_RESEARCH_SOURCES,
    )
    support_status: ResearchSupportStatus


class ResearchFinding(ResearchFindingDraft):
    """A synthesis accepted against an application-owned target and source set."""

    sources: list[ResearchSource] = Field(
        default_factory=list,
        max_length=MAX_RESEARCH_SOURCES,
    )


class ResearchInvestigation(_ResearchModel):
    id: str
    target_id: str
    status: ResearchExecutionStatus
    research_version: str
    finding: ResearchFinding | None = None
    sources: list[ResearchSource] = Field(default_factory=list)
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class ResearchTargetView(ResearchTarget):
    investigation: ResearchInvestigation | None = None
