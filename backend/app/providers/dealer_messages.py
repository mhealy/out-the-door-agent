import json
from pathlib import Path
from typing import Protocol

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
