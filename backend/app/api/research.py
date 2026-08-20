from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.dependencies import get_research_provider, get_research_synthesizer
from app.domain.research import ResearchTargetView
from app.persistence.db import get_session
from app.persistence.purchases import PurchaseRunNotFoundError
from app.providers.research import ResearchProvider
from app.providers.research_synthesis import ResearchSynthesizer
from app.services.research import (
    ResearchExecutionError,
    ResearchInProgressError,
    ResearchService,
    ResearchTargetChangedError,
)


router = APIRouter(prefix="/purchase-runs", tags=["research"])


class InvestigateResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _service(
    *,
    session: Session,
    provider: ResearchProvider,
    synthesizer: ResearchSynthesizer,
) -> ResearchService:
    return ResearchService(
        session=session,
        provider=provider,
        synthesizer=synthesizer,
    )


@router.get(
    "/{purchase_id}/research-targets",
    response_model=list[ResearchTargetView],
)
def list_research_targets(
    purchase_id: str,
    session: Annotated[Session, Depends(get_session)],
    provider: Annotated[ResearchProvider, Depends(get_research_provider)],
    synthesizer: Annotated[
        ResearchSynthesizer,
        Depends(get_research_synthesizer),
    ],
) -> list[ResearchTargetView]:
    try:
        return _service(
            session=session,
            provider=provider,
            synthesizer=synthesizer,
        ).list_targets(purchase_id)
    except PurchaseRunNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "purchase_run_not_found",
                "message": "The requested purchase workspace was not found.",
            },
        ) from error


@router.post(
    "/{purchase_id}/research-targets/{target_id}/investigate",
    response_model=ResearchTargetView,
)
async def investigate_research_target(
    purchase_id: str,
    target_id: str,
    _: InvestigateResearchRequest,
    session: Annotated[Session, Depends(get_session)],
    provider: Annotated[ResearchProvider, Depends(get_research_provider)],
    synthesizer: Annotated[
        ResearchSynthesizer,
        Depends(get_research_synthesizer),
    ],
) -> ResearchTargetView:
    service = _service(
        session=session,
        provider=provider,
        synthesizer=synthesizer,
    )
    try:
        return await service.investigate(purchase_id, target_id)
    except PurchaseRunNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "purchase_run_not_found",
                "message": "The requested purchase workspace was not found.",
            },
        ) from error
    except ResearchTargetChangedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "research_target_changed",
                "message": (
                    "This research target is no longer current. Reload the purchase "
                    "workspace before investigating it."
                ),
            },
        ) from error
    except ResearchInProgressError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "research_in_progress",
                "message": "Research for this current target is already in progress.",
            },
        ) from error
    except ResearchExecutionError as error:
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
                if error.unavailable
                else status.HTTP_502_BAD_GATEWAY
            ),
            detail={
                "code": error.error_code,
                "message": (
                    "Research failed without changing the dealer quote or "
                    "comparison. Retrieved sources were preserved when available."
                ),
            },
        ) from error
