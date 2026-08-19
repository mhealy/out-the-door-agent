"""Typed domain contracts for OutTheDoor."""

from app.domain.approval import (
    ApprovalRecord,
    OutreachProposal,
    OutreachVehicleSnapshot,
    ProposedAction,
)
from app.domain.criteria import CriteriaExtractionResult, VehicleSearchCriteria
from app.domain.evidence import Evidence
from app.domain.followup import (
    FollowupConversationMessage,
    FollowupDraft,
    FollowupDraftContext,
    FollowupDraftRequest,
    FollowupRequirement,
    ValidatedFollowupDraft,
)
from app.domain.interaction import DealerInteraction
from app.domain.message import DealerMessage, DeliveryReceipt, OutboundDealerMessage
from app.domain.quote import (
    ComparisonResult,
    Incentive,
    InteractionMetrics,
    MoneyItem,
    QuoteAssessment,
    QuoteAssessmentContext,
    QuoteAnalysisResult,
    QuoteExtraction,
)
from app.domain.vehicle import VehicleListing

__all__ = [
    "ComparisonResult",
    "CriteriaExtractionResult",
    "DealerInteraction",
    "DealerMessage",
    "DeliveryReceipt",
    "Evidence",
    "FollowupConversationMessage",
    "FollowupDraft",
    "FollowupDraftContext",
    "FollowupDraftRequest",
    "FollowupRequirement",
    "Incentive",
    "InteractionMetrics",
    "MoneyItem",
    "OutboundDealerMessage",
    "OutreachProposal",
    "OutreachVehicleSnapshot",
    "ApprovalRecord",
    "ProposedAction",
    "QuoteAssessment",
    "QuoteAssessmentContext",
    "QuoteAnalysisResult",
    "QuoteExtraction",
    "VehicleListing",
    "VehicleSearchCriteria",
    "ValidatedFollowupDraft",
]
