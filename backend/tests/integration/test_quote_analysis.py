from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.dependencies import (
    get_dealer_message_provider,
    get_inventory_provider,
    get_quote_extractor,
)
from app.domain.message import DealerMessage
from app.domain.vehicle import VehicleListing
from app.main import app
from app.providers.dealer_messages import DealerMessageNotFoundError
from app.providers.quote_extraction import (
    EvidenceDraft,
    QuoteExtractionError,
    QuoteExtractorOutput,
    UnavailableQuoteExtractor,
)


MESSAGE = DealerMessage(
    id="fixture-message",
    dealer_id="fixture-dealer",
    vehicle_id="fixture-vehicle",
    subject="Your written quote",
    body=(
        "Quote for VIN KM8JCDD10SU000001. Selling price: $37,800. "
        "Documentation fee: $225. Government taxes, title, and license: $2,290. "
        "There are no dealer-installed add-ons. Out-the-door total: $40,315. "
        "No financing or trade-in is required."
    ),
    received_at=datetime(2026, 8, 19, 17, 30, tzinfo=timezone.utc),
    source_provider="fixture",
)


class StubMessageProvider:
    async def list_messages(self) -> list[DealerMessage]:
        return [MESSAGE]

    async def get_message(self, message_id: str) -> DealerMessage:
        if message_id != MESSAGE.id:
            raise DealerMessageNotFoundError(message_id)
        return MESSAGE


class StubExtractor:
    async def extract(self, message: DealerMessage) -> QuoteExtractorOutput:
        assert message is MESSAGE
        return QuoteExtractorOutput(
            extraction={
                "vehicle_vin": "KM8JCDD10SU000001",
                "selling_price": "37800",
                "claimed_otd": "40315",
                "dealer_fees": [
                    {
                        "name": "Documentation fee",
                        "amount": "225",
                        "stated_mandatory": True,
                        "evidence_id": "fee",
                    }
                ],
                "government_fees": [
                    {
                        "name": "Government taxes, title, and license",
                        "amount": "2290",
                        "stated_mandatory": None,
                        "evidence_id": "government-fees",
                    }
                ],
                "financing_required": False,
                "trade_required": False,
                "explicit_no_addons_statement": True,
                "evidence_ids": [
                    "vin",
                    "selling",
                    "fee",
                    "government-fees",
                    "no-addons",
                    "otd",
                    "financing",
                    "trade",
                ],
                "extraction_confidence": 0.92,
            },
            evidence=[
                EvidenceDraft(
                    id="vin",
                    field_name="vehicle_vin",
                    excerpt="Quote for VIN KM8JCDD10SU000001.",
                ),
                EvidenceDraft(
                    id="selling",
                    field_name="selling_price",
                    excerpt="Selling price: $37,800.",
                ),
                EvidenceDraft(
                    id="fee",
                    field_name="dealer_fees",
                    excerpt="Documentation fee: $225.",
                ),
                EvidenceDraft(
                    id="government-fees",
                    field_name="government_fees",
                    excerpt="Government taxes, title, and license: $2,290.",
                ),
                EvidenceDraft(
                    id="no-addons",
                    field_name="explicit_no_addons_statement",
                    excerpt="There are no dealer-installed add-ons.",
                ),
                EvidenceDraft(
                    id="otd",
                    field_name="claimed_otd",
                    excerpt="Out-the-door total: $40,315.",
                ),
                EvidenceDraft(
                    id="financing",
                    field_name="financing_required",
                    excerpt="No financing or trade-in is required.",
                ),
                EvidenceDraft(
                    id="trade",
                    field_name="trade_required",
                    excerpt="No financing or trade-in is required.",
                ),
            ],
        )


class StubInventoryProvider:
    async def get_by_id(self, vehicle_id: str) -> VehicleListing | None:
        assert vehicle_id == MESSAGE.vehicle_id
        return VehicleListing(
            id=vehicle_id,
            vin="KM8JCDD10SU000001",
            stock_number="B1001",
            year=2025,
            make="Hyundai",
            model="Tucson Hybrid",
            trim="Limited",
            condition="new",
            dealer_id="fixture-dealer",
            dealer_name="Fixture dealer",
            source_url="https://example.test/fixture-vehicle",
            source_provider="fixture",
        )


def set_overrides(extractor: object) -> None:
    app.dependency_overrides[get_dealer_message_provider] = StubMessageProvider
    app.dependency_overrides[get_inventory_provider] = StubInventoryProvider
    app.dependency_overrides[get_quote_extractor] = lambda: extractor


def test_fixture_list_uses_message_provider_boundary() -> None:
    set_overrides(StubExtractor())
    try:
        with TestClient(app) as client:
            response = client.get("/quotes/fixtures")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == [MESSAGE.model_dump(mode="json")]


def test_quote_analysis_returns_raw_message_structured_quote_and_evidence() -> None:
    set_overrides(StubExtractor())
    try:
        with TestClient(app) as client:
            response = client.post(
                "/quotes/analyze", json={"message_id": MESSAGE.id}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"]["body"] == MESSAGE.body
    assert payload["extraction"]["selling_price"] == "37800"
    assert payload["extraction"]["claimed_otd"] == "40315"
    assert payload["extraction"]["dealer_fees"][0]["amount"] == "225"
    assert payload["evidence"][0]["source_id"] == MESSAGE.id
    assert payload["evidence"][0]["source_type"] == "DEALER_EMAIL"
    assert payload["assessment"] == {
        "comparable": True,
        "transparent": True,
        "reconciled": True,
        "missing_for_comparison": [],
        "missing_for_transparency": [],
        "reconciliation_difference": "0",
    }


def test_quote_analysis_rejects_client_supplied_extraction_facts() -> None:
    set_overrides(StubExtractor())
    try:
        with TestClient(app) as client:
            response = client.post(
                "/quotes/analyze",
                json={
                    "message_id": MESSAGE.id,
                    "extraction": {"claimed_otd": "1"},
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


def test_unknown_fixture_is_a_visible_not_found_error() -> None:
    set_overrides(StubExtractor())
    try:
        with TestClient(app) as client:
            response = client.post(
                "/quotes/analyze", json={"message_id": "unknown"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "dealer_message_not_found"


def test_model_provider_failure_is_visible_and_does_not_return_quote_data() -> None:
    class FailingExtractor:
        async def extract(self, _: DealerMessage) -> QuoteExtractorOutput:
            raise QuoteExtractionError("provider details must not leak")

    set_overrides(FailingExtractor())
    try:
        with TestClient(app) as client:
            response = client.post(
                "/quotes/analyze", json={"message_id": MESSAGE.id}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": "quote_extraction_failed",
        "message": "The dealer response could not be extracted into a structured quote.",
    }
    assert "extraction" not in response.json()
    assert "provider details" not in response.text


def test_missing_model_configuration_is_a_visible_service_error() -> None:
    set_overrides(UnavailableQuoteExtractor("test reason"))
    try:
        with TestClient(app) as client:
            response = client.post(
                "/quotes/analyze", json={"message_id": MESSAGE.id}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "quote_extractor_unavailable"
    assert "test reason" not in response.text


def test_untraceable_model_evidence_is_rejected_without_quote_data() -> None:
    class FabricatingExtractor:
        calls = 0

        async def extract(self, _: DealerMessage) -> QuoteExtractorOutput:
            self.calls += 1
            return QuoteExtractorOutput(
                extraction={
                    "claimed_otd": "1",
                    "evidence_ids": ["fabricated"],
                    "extraction_confidence": 0.99,
                },
                evidence=[
                    EvidenceDraft(
                        id="fabricated",
                        field_name="claimed_otd",
                        excerpt="This excerpt was never in the source.",
                    )
                ],
            )

    extractor = FabricatingExtractor()
    set_overrides(extractor)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/quotes/analyze", json={"message_id": MESSAGE.id}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "invalid_quote_evidence"
    assert "extraction" not in response.json()
    assert extractor.calls == 2
