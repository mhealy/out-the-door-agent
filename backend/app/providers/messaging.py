from datetime import datetime, timezone
from typing import Protocol

from app.domain.message import DeliveryReceipt, OutboundDealerMessage


FIXTURE_DEALER_CONTACTS: dict[str, str] = {
    "austin": "quotes@austin.example.test",
    "baytown": "quotes@baytown.example.test",
    "houston": "quotes@houston.example.test",
    "katy": "quotes@katy.example.test",
}


class DealerContactNotFoundError(LookupError):
    """No safe fixture recipient is configured for the requested dealer."""


class MessagingProviderError(RuntimeError):
    """A messaging transport could not confirm delivery."""


class MessagingProvider(Protocol):
    async def send(self, message: OutboundDealerMessage) -> DeliveryReceipt: ...


def resolve_fixture_dealer_contact(dealer_id: str) -> str:
    try:
        return FIXTURE_DEALER_CONTACTS[dealer_id]
    except KeyError as error:
        raise DealerContactNotFoundError(dealer_id) from error


class FixtureMessagingProvider:
    """Side-effect-free transport used by the demo and local development."""

    def __init__(self) -> None:
        self.sent_messages: list[OutboundDealerMessage] = []
        self._receipts: dict[str, DeliveryReceipt] = {}

    async def send(self, message: OutboundDealerMessage) -> DeliveryReceipt:
        existing = self._receipts.get(message.action_id)
        if existing is not None:
            return existing

        receipt = DeliveryReceipt(
            action_id=message.action_id,
            provider="fixture",
            external_message_id=f"fixture-{message.action_id}",
            sent_at=datetime.now(timezone.utc),
        )
        self.sent_messages.append(message)
        self._receipts[message.action_id] = receipt
        return receipt
