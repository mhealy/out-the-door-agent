from pydantic import BaseModel

from app.domain.evidence import Evidence
from app.domain.message import DealerMessage
from app.domain.quote import QuoteExtraction
from app.providers.dealer_messages import DealerMessageProvider
from app.providers.quote_extraction import QuoteExtractor
from app.services.evidence_validation import EvidenceValidationError, validate_evidence


class QuoteAnalysisResult(BaseModel):
    message: DealerMessage
    extraction: QuoteExtraction
    evidence: list[Evidence]


class QuoteAnalysisService:
    def __init__(
        self,
        message_provider: DealerMessageProvider,
        quote_extractor: QuoteExtractor,
    ) -> None:
        self._message_provider = message_provider
        self._quote_extractor = quote_extractor

    async def list_fixture_messages(self) -> list[DealerMessage]:
        return await self._message_provider.list_messages()

    async def analyze(self, message_id: str) -> QuoteAnalysisResult:
        message = await self._message_provider.get_message(message_id)
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
            )
        raise AssertionError("Quote evidence retry loop exited unexpectedly.")
