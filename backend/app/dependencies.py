from functools import lru_cache

from app.config import get_settings
from app.providers.dealer_messages import (
    DealerMessageProvider,
    FixtureDealerMessageProvider,
)
from app.providers.criteria import CriteriaInterpreter, FixtureCriteriaInterpreter
from app.providers.dealer_contacts import (
    DealerContactResolver,
    FixtureDealerContactResolver,
)
from app.providers.followup_drafting import (
    FollowupDrafter,
    OpenAIFollowupDrafter,
    UnavailableFollowupDrafter,
)
from app.providers.inventory import FixtureInventoryProvider, InventoryProvider
from app.providers.messaging import FixtureMessagingProvider, MessagingProvider
from app.providers.quote_extraction import (
    OpenAIQuoteExtractor,
    QuoteExtractor,
    UnavailableQuoteExtractor,
)
from app.providers.research import FixtureResearchProvider, ResearchProvider
from app.providers.research_synthesis import (
    OpenAIResearchSynthesizer,
    ResearchSynthesizer,
    UnavailableResearchSynthesizer,
)

_criteria_interpreter = FixtureCriteriaInterpreter()
_inventory_provider = FixtureInventoryProvider()
_dealer_message_provider = FixtureDealerMessageProvider()
_dealer_contact_resolver = FixtureDealerContactResolver()
_messaging_provider = FixtureMessagingProvider()
_research_provider = FixtureResearchProvider()


def get_criteria_interpreter() -> CriteriaInterpreter:
    return _criteria_interpreter


def get_inventory_provider() -> InventoryProvider:
    return _inventory_provider


def get_dealer_message_provider() -> DealerMessageProvider:
    return _dealer_message_provider


def get_dealer_contact_resolver() -> DealerContactResolver:
    return _dealer_contact_resolver


def get_messaging_provider() -> MessagingProvider:
    return _messaging_provider


def get_research_provider() -> ResearchProvider:
    return _research_provider


@lru_cache
def get_quote_extractor() -> QuoteExtractor:
    settings = get_settings()
    if (
        settings.openai_api_key is None
        or not settings.openai_api_key.get_secret_value().strip()
    ):
        return UnavailableQuoteExtractor("OTD_OPENAI_API_KEY is not configured.")
    return OpenAIQuoteExtractor.from_api_key(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.quote_extraction_model,
    )


@lru_cache
def get_followup_drafter() -> FollowupDrafter:
    settings = get_settings()
    if (
        settings.openai_api_key is None
        or not settings.openai_api_key.get_secret_value().strip()
    ):
        return UnavailableFollowupDrafter("OTD_OPENAI_API_KEY is not configured.")
    return OpenAIFollowupDrafter.from_api_key(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.followup_drafting_model,
    )


@lru_cache
def get_research_synthesizer() -> ResearchSynthesizer:
    settings = get_settings()
    if (
        settings.openai_api_key is None
        or not settings.openai_api_key.get_secret_value().strip()
    ):
        return UnavailableResearchSynthesizer(
            "OTD_OPENAI_API_KEY is not configured."
        )
    return OpenAIResearchSynthesizer.from_api_key(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.research_synthesis_model,
    )
