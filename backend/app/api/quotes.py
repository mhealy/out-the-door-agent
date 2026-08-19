from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.dependencies import (
    get_dealer_message_provider,
    get_inventory_provider,
    get_quote_extractor,
)
from app.domain.message import DealerMessage
from app.providers.dealer_messages import (
    DealerMessageNotFoundError,
    DealerMessageProvider,
)
from app.providers.inventory import InventoryProvider
from app.providers.quote_extraction import (
    QuoteExtractionError,
    QuoteExtractor,
    QuoteExtractorUnavailableError,
)
from app.services.evidence_validation import EvidenceValidationError
from app.services.quote_analysis import QuoteAnalysisResult, QuoteAnalysisService

router = APIRouter(prefix="/quotes", tags=["quotes"])


class QuoteAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1)


def _service(
    message_provider: DealerMessageProvider,
    quote_extractor: QuoteExtractor,
    inventory_provider: InventoryProvider,
) -> QuoteAnalysisService:
    return QuoteAnalysisService(
        message_provider,
        quote_extractor,
        inventory_provider,
    )


@router.get("/fixtures", response_model=list[DealerMessage])
async def list_quote_fixtures(
    message_provider: Annotated[
        DealerMessageProvider, Depends(get_dealer_message_provider)
    ],
) -> list[DealerMessage]:
    return await message_provider.list_messages()


@router.post("/analyze", response_model=QuoteAnalysisResult)
async def analyze_quote(
    request: QuoteAnalysisRequest,
    message_provider: Annotated[
        DealerMessageProvider, Depends(get_dealer_message_provider)
    ],
    quote_extractor: Annotated[QuoteExtractor, Depends(get_quote_extractor)],
    inventory_provider: Annotated[
        InventoryProvider, Depends(get_inventory_provider)
    ],
) -> QuoteAnalysisResult:
    try:
        return await _service(
            message_provider,
            quote_extractor,
            inventory_provider,
        ).analyze(request.message_id)
    except DealerMessageNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "dealer_message_not_found",
                "message": "The requested fixture dealer response was not found.",
            },
        ) from error
    except QuoteExtractorUnavailableError as error:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "quote_extractor_unavailable",
                "message": "Quote extraction is not configured. Set the model API key and retry.",
            },
        ) from error
    except QuoteExtractionError as error:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "quote_extraction_failed",
                "message": "The dealer response could not be extracted into a structured quote.",
            },
        ) from error
    except EvidenceValidationError as error:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "invalid_quote_evidence",
                "message": "The extracted quote contained evidence that could not be traced to the dealer response.",
            },
        ) from error
