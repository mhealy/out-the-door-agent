from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.agent_run import RunPhase
from app.domain.evidence import Evidence
from app.domain.interaction import InteractionAnalysisStatus
from app.domain.quote import MoneyItem


ComparisonStatus = Literal[
    "VERIFIED",
    "INCOMPLETE",
    "IN_PROGRESS",
    "BLOCKED",
    "FAILED",
    "REJECTED",
]


class _ComparisonModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InventoryProvenance(_ComparisonModel):
    source_type: Literal["INVENTORY_LISTING"] = "INVENTORY_LISTING"
    listing_id: str
    source_provider: str
    source_url: str


class OfferCondition(_ComparisonModel):
    description: str
    evidence_ids: list[str] = Field(default_factory=list)


class ComparedOffer(_ComparisonModel):
    agent_run_id: str
    interaction_id: str | None = None
    vehicle_id: str
    dealer_id: str
    dealer_name: str

    advertised_price: Decimal | None = None
    distance_miles: float | None = None
    inventory_provenance: InventoryProvenance

    claimed_otd: Decimal | None = None
    comparable: bool | None = None
    transparent: bool | None = None
    reconciled: bool | None = None
    missing_for_comparison: list[str] = Field(default_factory=list)

    mandatory_addons: list[MoneyItem] = Field(default_factory=list)
    conditions: list[OfferCondition] = Field(default_factory=list)
    sent_followup_count: int = Field(default=0, ge=0)

    run_phase: RunPhase
    analysis_status: InteractionAnalysisStatus | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    claimed_otd_evidence_ids: list[str] = Field(default_factory=list)

    comparison_status: ComparisonStatus
    eligible: bool
    verified_rank: int | None = Field(default=None, ge=1)


class OfferRecommendation(_ComparisonModel):
    recommended_agent_run_id: str
    recommended_dealer_id: str
    recommended_dealer_name: str
    recommended_otd: Decimal
    next_best_verified_otd: Decimal | None = None
    savings_vs_next_verified: Decimal | None = None
    has_unresolved_alternatives: bool
    explanation_facts: list[str] = Field(default_factory=list)


class AdvertisedVsVerified(_ComparisonModel):
    lowest_advertised_agent_run_id: str | None = None
    lowest_advertised_price: Decimal | None = None
    lowest_advertised_verified_otd: Decimal | None = None

    recommended_agent_run_id: str | None = None
    recommended_advertised_price: Decimal | None = None
    recommended_verified_otd: Decimal | None = None

    advertised_price_difference: Decimal | None = None
    verified_otd_savings: Decimal | None = None


class ComparisonResult(_ComparisonModel):
    offers: list[ComparedOffer]
    ranked_agent_run_ids: list[str]
    recommendation: OfferRecommendation | None = None
    advertised_vs_verified: AdvertisedVsVerified
