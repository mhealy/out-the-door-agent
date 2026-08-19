from app.domain.message import DealerMessage
from app.domain.quote import (
    QuoteAnalysisResult,
    QuoteAssessmentContext,
)
from app.providers.dealer_messages import DealerMessageProvider
from app.providers.inventory import InventoryProvider
from app.providers.quote_extraction import QuoteExtractor
from app.services.evidence_validation import EvidenceValidationError, validate_evidence
from app.services.quote_assessment import assess_quote


class QuoteAnalysisService:
    def __init__(
        self,
        message_provider: DealerMessageProvider,
        quote_extractor: QuoteExtractor,
        inventory_provider: InventoryProvider,
    ) -> None:
        self._message_provider = message_provider
        self._quote_extractor = quote_extractor
        self._inventory_provider = inventory_provider

    async def list_fixture_messages(self) -> list[DealerMessage]:
        return await self._message_provider.list_messages()

    async def analyze(self, message_id: str) -> QuoteAnalysisResult:
        message = await self._message_provider.get_message(message_id)
        expected_vehicle = (
            await self._inventory_provider.get_by_id(message.vehicle_id)
            if message.vehicle_id is not None
            else None
        )
        assessment_context = QuoteAssessmentContext(
            expected_vehicle_id=message.vehicle_id,
            expected_vin=(
                expected_vehicle.vin if expected_vehicle is not None else None
            ),
            expected_stock_number=(
                expected_vehicle.stock_number
                if expected_vehicle is not None
                else None
            ),
        )
        return await self.analyze_message(message, assessment_context)

    async def analyze_message(
        self,
        message: DealerMessage,
        assessment_context: QuoteAssessmentContext,
    ) -> QuoteAnalysisResult:
        """Analyze a persisted message against application-owned identity context."""

        for attempt in range(2):
            output = await self._quote_extractor.extract(message)
            try:
                evidence = validate_evidence(message, output)
            except EvidenceValidationError:
                if attempt == 0:
                    continue
                raise
            return QuoteAnalysisResult(
                message=message,
                extraction=output.extraction,
                evidence=evidence,
                assessment=assess_quote(output.extraction, assessment_context),
            )
        raise AssertionError("Quote evidence retry loop exited unexpectedly.")
