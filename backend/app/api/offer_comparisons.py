from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.dependencies import get_inventory_provider
from app.domain.comparison import ComparisonResult
from app.persistence.agent_runs import AgentRunNotFoundError
from app.persistence.db import get_session
from app.providers.inventory import InventoryProvider
from app.services.offer_comparison import (
    ComparisonVehicleNotFoundError,
    OfferComparisonService,
)


router = APIRouter(prefix="/offer-comparisons", tags=["offer-comparisons"])


class OfferComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_run_ids: list[str] = Field(min_length=2)

    @field_validator("agent_run_ids")
    @classmethod
    def require_unique_nonempty_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("AgentRun IDs must not be blank.")
        if len(values) != len(set(values)):
            raise ValueError("AgentRun IDs must be unique.")
        return values


@router.post("", response_model=ComparisonResult)
async def compare_offers(
    request: OfferComparisonRequest,
    session: Annotated[Session, Depends(get_session)],
    inventory_provider: Annotated[
        InventoryProvider,
        Depends(get_inventory_provider),
    ],
) -> ComparisonResult:
    try:
        return await OfferComparisonService(
            session=session,
            inventory_provider=inventory_provider,
        ).compare(request.agent_run_ids)
    except AgentRunNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "agent_run_not_found",
                "message": "The requested agent workflow was not found.",
            },
        ) from error
    except ComparisonVehicleNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "candidate_not_found",
                "message": "Inventory for an included workflow was not found.",
            },
        ) from error
