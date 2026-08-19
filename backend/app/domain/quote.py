from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.evidence import Evidence
from app.domain.message import DealerMessage


class MoneyItem(BaseModel):
    name: str
    amount: Decimal | None = None
    stated_mandatory: bool | None = None
    evidence_id: str


class Incentive(BaseModel):
    name: str
    amount: Decimal | None = None
    eligibility_condition: str | None = None
    requires_financing: bool | None = None
    requires_trade: bool | None = None
    evidence_id: str


class QuoteExtraction(BaseModel):
    vehicle_vin: str | None = None
    stock_number: str | None = None
    selling_price: Decimal | None = None
    claimed_otd: Decimal | None = None
    dealer_fees: list[MoneyItem] = Field(default_factory=list)
    government_fees: list[MoneyItem] = Field(default_factory=list)
    addons: list[MoneyItem] = Field(default_factory=list)
    incentives: list[Incentive] = Field(default_factory=list)
    financing_required: bool | None = None
    trade_required: bool | None = None
    expiration: datetime | None = None
    explicit_no_addons_statement: bool = False
    explicit_all_fees_included_statement: bool = False
    unresolved_questions: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    extraction_confidence: float = Field(ge=0, le=1)


class QuoteAssessment(BaseModel):
    comparable: bool
    transparent: bool
    reconciled: bool | None = None
    missing_for_comparison: list[str] = Field(default_factory=list)
    missing_for_transparency: list[str] = Field(default_factory=list)
    reconciliation_difference: Decimal | None = None


class QuoteAssessmentContext(BaseModel):
    """Application-owned identity expected for the dealer response."""

    model_config = ConfigDict(extra="forbid")

    expected_vehicle_id: str | None = None
    expected_vin: str | None = None
    expected_stock_number: str | None = None


class QuoteAnalysisResult(BaseModel):
    """Evidence-validated extraction and deterministic assessment for one message."""

    message: DealerMessage
    extraction: QuoteExtraction
    evidence: list[Evidence]
    assessment: QuoteAssessment


class InteractionMetrics(BaseModel):
    first_response_seconds: int | None = Field(default=None, ge=0)
    outbound_message_count: int = Field(ge=0)
    inbound_message_count: int = Field(ge=0)
    followups_required: int = Field(ge=0)
    comparable_on_first_response: bool
    refused_written_quote: bool
    required_phone_call: bool
    required_store_visit: bool
    unresolved_questions: int = Field(ge=0)


class ComparisonResult(BaseModel):
    winner_quote_id: str
    ranked_quote_ids: list[str]
    savings_vs_next_best: Decimal | None = None
    savings_vs_lowest_advertised_candidate: Decimal | None = None
    material_tradeoffs: list[str] = Field(default_factory=list)
    unresolved_risks: list[str] = Field(default_factory=list)
