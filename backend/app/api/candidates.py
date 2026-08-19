from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.domain.criteria import CriteriaExtractionResult
from app.domain.vehicle import VehicleListing
from app.providers.criteria import FixtureCriteriaInterpreter
from app.providers.inventory import FixtureInventoryProvider
from app.services.inventory import filter_candidates, shortlist_candidates

router = APIRouter(prefix="/candidates", tags=["candidates"])


class CandidateSearchRequest(BaseModel):
    goal: str = Field(min_length=1)


class CandidateSearchResponse(BaseModel):
    interpretation: CriteriaExtractionResult
    candidates: list[VehicleListing]


@router.post("/search", response_model=CandidateSearchResponse)
async def search_candidates(request: CandidateSearchRequest) -> CandidateSearchResponse:
    interpretation = await FixtureCriteriaInterpreter().interpret(request.goal)
    inventory = await FixtureInventoryProvider().search(interpretation.criteria)
    qualified = filter_candidates(interpretation.criteria, inventory)
    candidates = shortlist_candidates(interpretation.criteria, qualified)
    return CandidateSearchResponse(
        interpretation=interpretation,
        candidates=candidates,
    )
