from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.domain.criteria import CriteriaExtractionResult
from app.domain.vehicle import VehicleListing
from app.dependencies import get_criteria_interpreter, get_inventory_provider
from app.providers.criteria import CriteriaInterpreter, UnsupportedCriteriaError
from app.providers.inventory import InventoryProvider
from app.services.inventory import filter_candidates, shortlist_candidates

router = APIRouter(prefix="/candidates", tags=["candidates"])


class CandidateSearchRequest(BaseModel):
    goal: str = Field(min_length=1)


class CandidateSearchResponse(BaseModel):
    interpretation: CriteriaExtractionResult
    candidates: list[VehicleListing]


@router.post("/search", response_model=CandidateSearchResponse)
async def search_candidates(
    request: CandidateSearchRequest,
    interpreter: Annotated[CriteriaInterpreter, Depends(get_criteria_interpreter)],
    inventory_provider: Annotated[InventoryProvider, Depends(get_inventory_provider)],
) -> CandidateSearchResponse:
    try:
        interpretation = await interpreter.interpret(request.goal)
    except UnsupportedCriteriaError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "unsupported_fixture_criteria",
                "message": str(error),
            },
        ) from error
    inventory = await inventory_provider.search(interpretation.criteria)
    qualified = filter_candidates(interpretation.criteria, inventory)
    candidates = shortlist_candidates(interpretation.criteria, qualified)
    return CandidateSearchResponse(
        interpretation=interpretation,
        candidates=candidates,
    )
