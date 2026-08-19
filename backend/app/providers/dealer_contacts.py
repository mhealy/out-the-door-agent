from typing import Protocol


FIXTURE_DEALER_CONTACTS: dict[str, str] = {
    "austin": "quotes@austin.example.test",
    "baytown": "quotes@baytown.example.test",
    "houston": "quotes@houston.example.test",
    "katy": "quotes@katy.example.test",
}


class DealerContactNotFoundError(LookupError):
    """No application-owned recipient is configured for the requested dealer."""


class DealerContactResolver(Protocol):
    def resolve(self, dealer_id: str) -> str: ...


class FixtureDealerContactResolver:
    """Resolve existing dealer IDs to safe, fictitious demo recipients."""

    def resolve(self, dealer_id: str) -> str:
        try:
            return FIXTURE_DEALER_CONTACTS[dealer_id]
        except KeyError as error:
            raise DealerContactNotFoundError(dealer_id) from error
