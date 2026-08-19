from datetime import datetime, timezone

from app.domain.message import DealerMessage
from app.domain.vehicle import VehicleListing
from app.providers.quote_extraction import EvidenceDraft, QuoteExtractorOutput
from app.services.quote_analysis import QuoteAnalysisService


class StubInventoryProvider:
    async def get_by_id(self, vehicle_id: str) -> VehicleListing:
        return VehicleListing(
            id=vehicle_id,
            vin="EXPECTEDVIN0000001",
            stock_number="EXPECTED-STOCK",
            year=2025,
            make="Hyundai",
            model="Tucson Hybrid",
            trim="Limited",
            condition="new",
            dealer_id="dealer",
            dealer_name="Fixture dealer",
            source_url=f"https://example.test/{vehicle_id}",
            source_provider="fixture",
        )


async def test_incomplete_extraction_is_not_filled_by_deterministic_postprocessing() -> None:
    message = DealerMessage(
        id="plus-ttl",
        dealer_id="dealer",
        vehicle_id="vehicle",
        subject="Price plus TTL",
        body="The selling price is $37,450 plus TTL.",
        received_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
        source_provider="fixture",
    )

    class MessageProvider:
        async def list_messages(self) -> list[DealerMessage]:
            return [message]

        async def get_message(self, message_id: str) -> DealerMessage:
            assert message_id == message.id
            return message

    class Extractor:
        async def extract(self, source: DealerMessage) -> QuoteExtractorOutput:
            assert source is message
            return QuoteExtractorOutput(
                extraction={
                    "selling_price": "37450",
                    "claimed_otd": None,
                    "government_fees": [
                        {
                            "name": "Tax, title, and license",
                            "amount": None,
                            "stated_mandatory": None,
                            "evidence_id": "government-fees",
                        }
                    ],
                    "financing_required": None,
                    "trade_required": None,
                    "unresolved_questions": [],
                    "evidence_ids": ["selling", "government-fees"],
                    "extraction_confidence": 0.94,
                },
                evidence=[
                    EvidenceDraft(
                        id="selling",
                        field_name="selling_price",
                        excerpt="selling price is $37,450",
                    ),
                    EvidenceDraft(
                        id="government-fees",
                        field_name="government_fees",
                        excerpt="plus TTL",
                    ),
                ],
            )

    result = await QuoteAnalysisService(
        MessageProvider(),
        Extractor(),
        StubInventoryProvider(),
    ).analyze(message.id)

    assert result.extraction.selling_price is not None
    assert result.extraction.claimed_otd is None
    assert len(result.extraction.government_fees) == 1
    assert result.extraction.government_fees[0].amount is None
    assert result.extraction.government_fees[0].stated_mandatory is None
    assert result.extraction.addons == []
    assert result.extraction.financing_required is None
    assert result.extraction.trade_required is None
    assert result.extraction.unresolved_questions == []
    assert result.assessment.comparable is False
    assert result.assessment.missing_for_comparison == [
        "vehicle_identity",
        "claimed_otd",
        "addon_status",
        "financing_dependency",
        "trade_dependency",
    ]


async def test_invalid_evidence_is_retried_once_before_analysis_succeeds() -> None:
    message = DealerMessage(
        id="retry-evidence",
        dealer_id="dealer",
        vehicle_id="vehicle",
        subject="Quote",
        body="Selling price is $37,450.",
        received_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
        source_provider="fixture",
    )

    class MessageProvider:
        async def list_messages(self) -> list[DealerMessage]:
            return [message]

        async def get_message(self, message_id: str) -> DealerMessage:
            assert message_id == message.id
            return message

    class Extractor:
        calls = 0

        async def extract(self, _: DealerMessage) -> QuoteExtractorOutput:
            self.calls += 1
            excerpt = " " if self.calls == 1 else "Selling price is $37,450."
            return QuoteExtractorOutput(
                extraction={
                    "selling_price": "37450",
                    "evidence_ids": ["selling"],
                    "extraction_confidence": 0.9,
                },
                evidence=[
                    EvidenceDraft(
                        id="selling",
                        field_name="selling_price",
                        excerpt=excerpt,
                    )
                ],
            )

    extractor = Extractor()
    result = await QuoteAnalysisService(
        MessageProvider(),
        extractor,
        StubInventoryProvider(),
    ).analyze(message.id)

    assert result.extraction.selling_price is not None
    assert extractor.calls == 2
    assert result.assessment.comparable is False
