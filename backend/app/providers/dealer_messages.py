import json
from pathlib import Path
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict

from app.domain.message import DealerMessage


def _default_fixture_path() -> Path:
    relative_path = Path("demo/dealer_messages/quote_analysis_cases.json")
    for parent in Path(__file__).resolve().parents:
        candidate = parent / relative_path
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parents[3] / relative_path


DEFAULT_FIXTURE_PATH = _default_fixture_path()


class DealerMessageProvider(Protocol):
    async def list_messages(self) -> list[DealerMessage]: ...

    async def get_message(self, message_id: str) -> DealerMessage: ...


class DealerMessageNotFoundError(LookupError):
    """The requested normalized dealer message does not exist."""


class DemoResponseFixtureNotFoundError(LookupError):
    """No application-owned response fixture is mapped to the interaction."""


class _FixtureMessageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    dealer_id: str
    vehicle_id: str | None = None
    direction: str = "INBOUND"
    subject: str | None = None
    body: str
    received_at: str


class FixtureDealerMessageProvider:
    """Loads representative raw dealer responses through the provider boundary."""

    def __init__(self, fixture_path: Path = DEFAULT_FIXTURE_PATH) -> None:
        self._fixture_path = fixture_path
        self._messages: tuple[DealerMessage, ...] | None = None

    def _load(self) -> tuple[DealerMessage, ...]:
        if self._messages is None:
            records = json.loads(self._fixture_path.read_text(encoding="utf-8"))
            normalized = []
            for value in records:
                record = _FixtureMessageRecord.model_validate(value)
                normalized.append(
                    DealerMessage(
                        **record.model_dump(),
                        source_provider="fixture",
                    )
                )
            ids = [message.id for message in normalized]
            if len(ids) != len(set(ids)):
                raise ValueError("Dealer-message fixture IDs must be unique.")
            self._messages = tuple(normalized)
        return self._messages

    async def list_messages(self) -> list[DealerMessage]:
        return list(self._load())

    async def get_message(self, message_id: str) -> DealerMessage:
        for message in self._load():
            if message.id == message_id:
                return message
        raise DealerMessageNotFoundError(message_id)


DEMO_RESPONSE_FIXTURE_IDS: Final[dict[tuple[str, str], str]] = {
    ("baytown", "baytown-blue"): "msg-explicit-no-addons",
    ("houston", "houston-white"): "msg-mandatory-addons",
    ("katy", "katy-blue"): "msg-trade-assistance",
}


class DealerResponseProvider(Protocol):
    async def get_response(
        self,
        *,
        dealer_id: str,
        vehicle_id: str,
    ) -> DealerMessage: ...


class FixtureDealerResponseProvider:
    """Select canonical responses from an application-owned target mapping."""

    def __init__(self, message_provider: DealerMessageProvider) -> None:
        self._message_provider = message_provider

    async def get_response(
        self,
        *,
        dealer_id: str,
        vehicle_id: str,
    ) -> DealerMessage:
        try:
            fixture_id = DEMO_RESPONSE_FIXTURE_IDS[(dealer_id, vehicle_id)]
        except KeyError as error:
            raise DemoResponseFixtureNotFoundError(
                f"{dealer_id}/{vehicle_id}"
            ) from error

        try:
            return await self._message_provider.get_message(fixture_id)
        except DealerMessageNotFoundError as error:
            raise DemoResponseFixtureNotFoundError(fixture_id) from error
