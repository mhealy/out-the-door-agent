from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.domain.message import DeliveryReceipt, OutboundDealerMessage
from app.domain.vehicle import VehicleListing
from app.providers.messaging import (
    FIXTURE_DEALER_CONTACTS,
    DealerContactNotFoundError,
    FixtureMessagingProvider,
    resolve_fixture_dealer_contact,
)
from app.services.outreach import (
    INITIAL_QUOTE_REQUEST_LABELS,
    INITIAL_QUOTE_REQUEST_REQUIREMENTS,
    compose_initial_quote_request,
)


EXPECTED_REQUIREMENT_IDS = (
    "vehicle_identity",
    "selling_price",
    "dealer_fees",
    "mandatory_addons",
    "government_charges",
    "out_the_door_total",
    "incentives_and_eligibility",
    "financing_requirement",
    "trade_in_requirement",
    "quote_expiration",
)


def _requirement_id(requirement: object) -> str:
    value = getattr(requirement, "value", requirement)
    assert isinstance(value, str)
    return value


def _listing(**overrides: object) -> VehicleListing:
    values: dict[str, object] = {
        "id": "baytown-blue",
        "vin": "KM8JCDD10SU000001",
        "stock_number": "B1001",
        "year": 2025,
        "make": "Hyundai",
        "model": "Tucson Hybrid",
        "trim": "Limited",
        "condition": "new",
        "mileage": 8,
        "advertised_price": "37800",
        "msrp": "42150",
        "exterior_color": "Deep Sea Blue",
        "interior_color": "Gray",
        "features": ["AWD", "panoramic roof", "heated seats"],
        "dealer_id": "baytown",
        "dealer_name": "Baytown Hyundai",
        "distance_miles": 34,
        "source_url": "https://example.test/inventory/baytown-blue",
        "source_provider": "fixture",
    }
    values.update(overrides)
    return VehicleListing(**values)


def test_initial_quote_request_requirement_ids_are_complete_stable_and_unique() -> None:
    requirement_ids = tuple(
        _requirement_id(requirement)
        for requirement in INITIAL_QUOTE_REQUEST_REQUIREMENTS
    )

    assert requirement_ids == EXPECTED_REQUIREMENT_IDS
    assert len(requirement_ids) == len(set(requirement_ids))
    assert set(INITIAL_QUOTE_REQUEST_LABELS) == set(requirement_ids)
    assert all(INITIAL_QUOTE_REQUEST_LABELS[item].strip() for item in requirement_ids)


def test_initial_quote_request_composition_is_deterministic_and_complete() -> None:
    vehicle = _listing()
    recipient = "quotes@baytown.example.test"

    first = compose_initial_quote_request(
        action_id="proposal-1",
        vehicle=vehicle,
        recipient=recipient,
    )
    second = compose_initial_quote_request(
        action_id="proposal-1",
        vehicle=vehicle,
        recipient=recipient,
    )

    assert first == second
    assert first.action_type == "SEND_INITIAL_QUOTE_REQUEST"
    assert first.requires_approval is True
    assert first.vehicle_id == vehicle.id
    assert first.dealer_id == vehicle.dealer_id
    assert first.recipient == recipient
    assert first.requested_information == list(EXPECTED_REQUIREMENT_IDS)
    assert "2025 Hyundai Tucson Hybrid Limited" in first.subject
    assert "VIN: KM8JCDD10SU000001" in first.body
    assert "Stock number: B1001" in first.body
    for requirement_id in EXPECTED_REQUIREMENT_IDS:
        assert INITIAL_QUOTE_REQUEST_LABELS[requirement_id] in first.body


def test_initial_quote_request_does_not_fabricate_missing_vehicle_identity() -> None:
    action = compose_initial_quote_request(
        action_id="proposal-without-identifiers",
        vehicle=_listing(vin=None, stock_number=None),
        recipient="quotes@baytown.example.test",
    )

    assert "VIN:" not in action.body
    assert "Stock number:" not in action.body
    assert "None" not in action.subject
    assert "None" not in action.body
    assert "unknown" not in action.body.casefold()
    assert "vehicle_identity" in action.requested_information


def test_initial_quote_request_does_not_request_privileged_buyer_actions() -> None:
    action = compose_initial_quote_request(
        action_id="proposal-safe-content",
        vehicle=_listing(),
        recipient="quotes@baytown.example.test",
    )
    normalized = " ".join(action.body.casefold().split())

    prohibited_requests = (
        "provide your ssn",
        "provide a social security number",
        "provide payment information",
        "authorize a credit check",
        "complete a credit application",
        "place a deposit",
        "make a payment",
        "sign a purchase agreement",
        "commit to purchase",
    )
    assert all(phrase not in normalized for phrase in prohibited_requests)


def test_fixture_contacts_are_central_complete_and_clearly_fictitious() -> None:
    assert set(FIXTURE_DEALER_CONTACTS) == {"austin", "baytown", "houston", "katy"}
    assert resolve_fixture_dealer_contact("baytown") == "quotes@baytown.example.test"
    assert all(
        recipient.endswith(".example.test")
        for recipient in FIXTURE_DEALER_CONTACTS.values()
    )


def test_unknown_fixture_dealer_contact_fails_visibly() -> None:
    with pytest.raises(DealerContactNotFoundError, match="unknown-dealer"):
        resolve_fixture_dealer_contact("unknown-dealer")


async def test_fixture_messaging_provider_uses_typed_transport_and_is_inspectable() -> None:
    provider = FixtureMessagingProvider()
    action = compose_initial_quote_request(
        action_id="proposal-fixture-send",
        vehicle=_listing(),
        recipient=resolve_fixture_dealer_contact("baytown"),
    )
    message = OutboundDealerMessage(
        action_id=action.id,
        vehicle_id=action.vehicle_id,
        dealer_id=action.dealer_id,
        recipient=action.recipient,
        subject=action.subject,
        body=action.body,
    )

    receipt = await provider.send(message)

    assert receipt.action_id == action.id
    assert receipt.provider == "fixture"
    assert receipt.external_message_id == "fixture-proposal-fixture-send"
    assert provider.sent_messages == [message]
    assert provider.sent_messages[0].recipient.endswith(".example.test")


def test_delivery_receipt_normalizes_aware_timestamps_and_rejects_naive_values() -> None:
    receipt = DeliveryReceipt(
        action_id="proposal-offset-receipt",
        provider="fixture",
        external_message_id="fixture-offset-receipt",
        sent_at=datetime(
            2026,
            8,
            19,
            15,
            tzinfo=timezone(timedelta(hours=-5)),
        ),
    )

    assert receipt.sent_at == datetime(2026, 8, 19, 20, tzinfo=timezone.utc)

    with pytest.raises(ValidationError, match="timezone-aware"):
        DeliveryReceipt(
            action_id="proposal-naive-receipt",
            provider="fixture",
            external_message_id="fixture-naive-receipt",
            sent_at=datetime(2026, 8, 19, 15),
        )
