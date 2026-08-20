from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.agent.graph import AgentWorkflowService
from app.config import Settings, get_settings
from app.dependencies import (
    get_dealer_contact_resolver,
    get_dealer_message_provider,
    get_followup_drafter,
    get_inventory_provider,
    get_messaging_provider,
    get_quote_extractor,
)
from app.domain.purchase import PurchaseWorkspace
from app.persistence.db import get_session
from app.persistence.purchases import (
    PurchaseCreationConflictError,
    PurchaseRunNotFoundError,
)
from app.providers.dealer_contacts import DealerContactResolver
from app.providers.dealer_messages import DealerMessageProvider
from app.providers.followup_drafting import FollowupDrafter
from app.providers.inventory import InventoryProvider
from app.providers.messaging import MessagingProvider
from app.providers.quote_extraction import QuoteExtractor
from app.services.offer_comparison import OfferComparisonService
from app.services.outreach import CandidateNotFoundError
from app.services.purchases import (
    InvalidPurchaseSelectionError,
    PurchaseWorkspaceService,
)


router = APIRouter(prefix="/purchase-runs", tags=["purchase-runs"])


class CreatePurchaseRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    creation_id: UUID
    goal: str = Field(min_length=1)
    vehicle_ids: list[str] = Field(min_length=2, max_length=5)

    @field_validator("goal")
    @classmethod
    def require_nonblank_goal(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("The purchase goal must not be blank.")
        return stripped

    @field_validator("vehicle_ids")
    @classmethod
    def require_unique_nonblank_vehicle_ids(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("Vehicle IDs must not be blank.")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Vehicle IDs must be unique within a purchase.")
        return normalized


class RecoverPurchaseRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _service(
    *,
    session: Session,
    inventory_provider: InventoryProvider,
    dealer_contact_resolver: DealerContactResolver,
    messaging_provider: MessagingProvider,
    message_provider: DealerMessageProvider,
    quote_extractor: QuoteExtractor,
    followup_drafter: FollowupDrafter,
    settings: Settings,
) -> PurchaseWorkspaceService:
    workflow = AgentWorkflowService(
        session=session,
        inventory_provider=inventory_provider,
        dealer_contact_resolver=dealer_contact_resolver,
        messaging_provider=messaging_provider,
        message_provider=message_provider,
        quote_extractor=quote_extractor,
        followup_drafter=followup_drafter,
        checkpoint_path=settings.langgraph_checkpoint_path,
    )
    return PurchaseWorkspaceService(
        session=session,
        inventory_provider=inventory_provider,
        workflow_service=workflow,
        comparison_service=OfferComparisonService(
            session=session,
            inventory_provider=inventory_provider,
        ),
    )


def _dependencies(
    *,
    session: Session,
    inventory_provider: InventoryProvider,
    dealer_contact_resolver: DealerContactResolver,
    messaging_provider: MessagingProvider,
    message_provider: DealerMessageProvider,
    quote_extractor: QuoteExtractor,
    followup_drafter: FollowupDrafter,
    settings: Settings,
) -> PurchaseWorkspaceService:
    return _service(
        session=session,
        inventory_provider=inventory_provider,
        dealer_contact_resolver=dealer_contact_resolver,
        messaging_provider=messaging_provider,
        message_provider=message_provider,
        quote_extractor=quote_extractor,
        followup_drafter=followup_drafter,
        settings=settings,
    )


@router.post("", response_model=PurchaseWorkspace, status_code=status.HTTP_201_CREATED)
async def create_purchase_run(
    request: CreatePurchaseRunRequest,
    session: Annotated[Session, Depends(get_session)],
    inventory_provider: Annotated[InventoryProvider, Depends(get_inventory_provider)],
    dealer_contact_resolver: Annotated[
        DealerContactResolver, Depends(get_dealer_contact_resolver)
    ],
    messaging_provider: Annotated[MessagingProvider, Depends(get_messaging_provider)],
    message_provider: Annotated[
        DealerMessageProvider, Depends(get_dealer_message_provider)
    ],
    quote_extractor: Annotated[QuoteExtractor, Depends(get_quote_extractor)],
    followup_drafter: Annotated[FollowupDrafter, Depends(get_followup_drafter)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PurchaseWorkspace:
    service = _dependencies(
        session=session,
        inventory_provider=inventory_provider,
        dealer_contact_resolver=dealer_contact_resolver,
        messaging_provider=messaging_provider,
        message_provider=message_provider,
        quote_extractor=quote_extractor,
        followup_drafter=followup_drafter,
        settings=settings,
    )
    try:
        return await service.create(
            creation_id=str(request.creation_id),
            goal=request.goal,
            vehicle_ids=request.vehicle_ids,
        )
    except PurchaseCreationConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "purchase_creation_conflict",
                "message": (
                    "This creation identity is already bound to a different "
                    "purchase intent."
                ),
            },
        ) from error
    except CandidateNotFoundError as error:
        raise _candidate_not_found(error) from error
    except InvalidPurchaseSelectionError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_purchase_selection",
                "message": str(error),
            },
        ) from error


@router.get("/{purchase_id}", response_model=PurchaseWorkspace)
async def inspect_purchase_run(
    purchase_id: str,
    session: Annotated[Session, Depends(get_session)],
    inventory_provider: Annotated[InventoryProvider, Depends(get_inventory_provider)],
    dealer_contact_resolver: Annotated[
        DealerContactResolver, Depends(get_dealer_contact_resolver)
    ],
    messaging_provider: Annotated[MessagingProvider, Depends(get_messaging_provider)],
    message_provider: Annotated[
        DealerMessageProvider, Depends(get_dealer_message_provider)
    ],
    quote_extractor: Annotated[QuoteExtractor, Depends(get_quote_extractor)],
    followup_drafter: Annotated[FollowupDrafter, Depends(get_followup_drafter)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PurchaseWorkspace:
    try:
        return await _dependencies(
            session=session,
            inventory_provider=inventory_provider,
            dealer_contact_resolver=dealer_contact_resolver,
            messaging_provider=messaging_provider,
            message_provider=message_provider,
            quote_extractor=quote_extractor,
            followup_drafter=followup_drafter,
            settings=settings,
        ).get(purchase_id)
    except PurchaseRunNotFoundError as error:
        raise _purchase_not_found(error) from error
    except CandidateNotFoundError as error:
        raise _candidate_not_found(error) from error


@router.post("/{purchase_id}/recover", response_model=PurchaseWorkspace)
async def recover_purchase_run(
    purchase_id: str,
    session: Annotated[Session, Depends(get_session)],
    inventory_provider: Annotated[InventoryProvider, Depends(get_inventory_provider)],
    dealer_contact_resolver: Annotated[
        DealerContactResolver, Depends(get_dealer_contact_resolver)
    ],
    messaging_provider: Annotated[MessagingProvider, Depends(get_messaging_provider)],
    message_provider: Annotated[
        DealerMessageProvider, Depends(get_dealer_message_provider)
    ],
    quote_extractor: Annotated[QuoteExtractor, Depends(get_quote_extractor)],
    followup_drafter: Annotated[FollowupDrafter, Depends(get_followup_drafter)],
    settings: Annotated[Settings, Depends(get_settings)],
    _: Annotated[RecoverPurchaseRunRequest | None, Body()] = None,
) -> PurchaseWorkspace:
    try:
        return await _dependencies(
            session=session,
            inventory_provider=inventory_provider,
            dealer_contact_resolver=dealer_contact_resolver,
            messaging_provider=messaging_provider,
            message_provider=message_provider,
            quote_extractor=quote_extractor,
            followup_drafter=followup_drafter,
            settings=settings,
        ).recover(purchase_id)
    except PurchaseRunNotFoundError as error:
        raise _purchase_not_found(error) from error
    except CandidateNotFoundError as error:
        raise _candidate_not_found(error) from error


def _purchase_not_found(error: Exception) -> HTTPException:
    del error
    return HTTPException(
        status_code=404,
        detail={
            "code": "purchase_run_not_found",
            "message": "The requested purchase workspace was not found.",
        },
    )


def _candidate_not_found(error: Exception) -> HTTPException:
    del error
    return HTTPException(
        status_code=404,
        detail={
            "code": "candidate_not_found",
            "message": "A selected inventory candidate was not found.",
        },
    )
