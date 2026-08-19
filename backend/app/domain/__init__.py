"""Typed domain contracts for OutTheDoor."""

from app.domain.approval import ProposedAction
from app.domain.criteria import CriteriaExtractionResult, VehicleSearchCriteria
from app.domain.evidence import Evidence
from app.domain.message import DealerMessage
from app.domain.quote import (
    ComparisonResult,
    Incentive,
    InteractionMetrics,
    MoneyItem,
    QuoteAssessment,
    QuoteExtraction,
)
from app.domain.vehicle import VehicleListing

__all__ = [
    "ComparisonResult",
    "CriteriaExtractionResult",
    "DealerMessage",
    "Evidence",
    "Incentive",
    "InteractionMetrics",
    "MoneyItem",
    "ProposedAction",
    "QuoteAssessment",
    "QuoteExtraction",
    "VehicleListing",
    "VehicleSearchCriteria",
]
