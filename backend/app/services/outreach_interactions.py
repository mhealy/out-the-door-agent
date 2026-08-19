from sqlalchemy.orm import Session

from app.domain.approval import OutreachVehicleSnapshot
from app.domain.interaction import DealerInteraction
from app.domain.quote import QuoteAssessmentContext
from app.persistence.interactions import (
    InteractionRecordNotFoundError,
    InteractionRepository,
    dealer_message_from_record,
)
from app.persistence.outreach import OutreachRecordNotFoundError, OutreachRepository
from app.providers.dealer_messages import (
    DealerMessageProvider,
    FixtureDealerResponseProvider,
)
from app.providers.inventory import InventoryProvider
from app.providers.quote_extraction import (
    QuoteExtractionError,
    QuoteExtractor,
    QuoteExtractorUnavailableError,
)
from app.services.evidence_validation import EvidenceValidationError
from app.services.outreach import OutreachProposalNotFoundError
from app.services.quote_analysis import QuoteAnalysisService


class OutreachInteractionNotFoundError(LookupError):
    """A proposal has no durable dealer interaction."""


class OutreachResponseNotReleasableError(RuntimeError):
    """The initial action has no confirmed SENT delivery boundary."""


class OutreachResponseAnalysisInProgressError(RuntimeError):
    """Another request owns the durable analysis lease."""


class InteractionAnalysisFailedError(RuntimeError):
    """A newer analysis owner persisted the canonical failure."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


class OutreachInteractionService:
    def __init__(
        self,
        *,
        session: Session,
        message_provider: DealerMessageProvider,
        quote_extractor: QuoteExtractor,
        inventory_provider: InventoryProvider,
    ) -> None:
        self._outreach_repository = OutreachRepository(session)
        self._interaction_repository = InteractionRepository(session)
        self._response_provider = FixtureDealerResponseProvider(message_provider)
        self._quote_analysis = QuoteAnalysisService(
            message_provider,
            quote_extractor,
            inventory_provider,
        )

    def get(self, action_id: str) -> DealerInteraction:
        self._get_action(action_id)
        try:
            return self._interaction_repository.get(action_id)
        except InteractionRecordNotFoundError as error:
            raise OutreachInteractionNotFoundError(action_id) from error

    async def release_demo_response(self, action_id: str) -> DealerInteraction:
        action = self._get_action(action_id)
        if (
            action.action_type != "SEND_INITIAL_QUOTE_REQUEST"
            or action.status != "SENT"
        ):
            raise OutreachResponseNotReleasableError(action_id)

        try:
            interaction = self._interaction_repository.get_record(action_id)
        except InteractionRecordNotFoundError as error:
            raise OutreachResponseNotReleasableError(action_id) from error

        persisted = self._interaction_repository.get(action_id)
        if persisted.analysis_status == "ANALYZED":
            return persisted

        if persisted.messages:
            # A prior failure or interrupted analysis is safely retryable from the
            # application-owned raw message; never look the fixture up again.
            message = persisted.messages[-1]
        else:
            fixture_message = await self._response_provider.get_response(
                dealer_id=interaction.dealer_id,
                vehicle_id=interaction.vehicle_id,
            )
            message_record, created = self._interaction_repository.reserve_message(
                interaction,
                fixture_message,
            )
            if not created and message_record.analysis_status == "ANALYZED":
                return self._interaction_repository.get(action_id)
            message = dealer_message_from_record(message_record)
        vehicle = OutreachVehicleSnapshot.model_validate(
            interaction.vehicle_snapshot
        )
        context = QuoteAssessmentContext(
            expected_vehicle_id=interaction.vehicle_id,
            expected_vin=vehicle.vin,
            expected_stock_number=vehicle.stock_number,
        )

        claim_token = self._interaction_repository.claim_analysis(message.id)
        if claim_token is None:
            return self._canonical_result_or_raise_in_progress(action_id)

        try:
            analysis = await self._quote_analysis.analyze_message(message, context)
        except QuoteExtractorUnavailableError:
            recorded = self._interaction_repository.record_analysis_failure(
                message.id,
                "quote_extractor_unavailable",
                claim_token,
            )
            if recorded:
                raise
            return self._canonical_result_or_raise_in_progress(action_id)
        except QuoteExtractionError:
            recorded = self._interaction_repository.record_analysis_failure(
                message.id,
                "quote_extraction_failed",
                claim_token,
            )
            if recorded:
                raise
            return self._canonical_result_or_raise_in_progress(action_id)
        except EvidenceValidationError:
            recorded = self._interaction_repository.record_analysis_failure(
                message.id,
                "invalid_quote_evidence",
                claim_token,
            )
            if recorded:
                raise
            return self._canonical_result_or_raise_in_progress(action_id)

        recorded = self._interaction_repository.record_analysis(
            message.id,
            analysis,
            claim_token,
        )
        if recorded:
            return self._interaction_repository.get(action_id)
        return self._canonical_result_or_raise_in_progress(action_id)

    def _canonical_result_or_raise_in_progress(
        self,
        action_id: str,
    ) -> DealerInteraction:
        current = self._interaction_repository.get(action_id)
        if current.analysis_status == "ANALYZED":
            return current
        if current.analysis_status == "ANALYSIS_FAILED":
            raise InteractionAnalysisFailedError(
                current.analysis_error_code or "quote_extraction_failed"
            )
        raise OutreachResponseAnalysisInProgressError(action_id)

    def _get_action(self, action_id: str):
        try:
            return self._outreach_repository.get_action(action_id)
        except OutreachRecordNotFoundError as error:
            raise OutreachProposalNotFoundError(action_id) from error
