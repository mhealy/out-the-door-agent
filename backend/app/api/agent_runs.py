from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
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
from app.domain.agent_run import AgentRun
from app.persistence.agent_runs import (
    AgentRunAlreadyAdvancingError,
    AgentRunExecutionLeaseLostError,
    AgentRunNotFoundError,
    AgentRunRepository,
)
from app.persistence.db import get_session
from app.providers.dealer_contacts import DealerContactResolver
from app.providers.dealer_messages import DealerMessageProvider
from app.providers.followup_drafting import FollowupDrafter
from app.providers.inventory import InventoryProvider
from app.providers.messaging import MessagingProvider
from app.providers.quote_extraction import QuoteExtractor
from app.services.outreach import CandidateNotFoundError


router = APIRouter(prefix="/agent-runs", tags=["agent-runs"])


class CreateAgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_id: str = Field(min_length=1)


class ResumeAgentRunRequest(BaseModel):
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
) -> AgentWorkflowService:
    return AgentWorkflowService(
        session=session,
        inventory_provider=inventory_provider,
        dealer_contact_resolver=dealer_contact_resolver,
        messaging_provider=messaging_provider,
        message_provider=message_provider,
        quote_extractor=quote_extractor,
        followup_drafter=followup_drafter,
        checkpoint_path=settings.langgraph_checkpoint_path,
    )


@router.post("", response_model=AgentRun, status_code=status.HTTP_201_CREATED)
async def create_agent_run(
    request: CreateAgentRunRequest,
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
) -> AgentRun:
    try:
        return await _service(
            session=session,
            inventory_provider=inventory_provider,
            dealer_contact_resolver=dealer_contact_resolver,
            messaging_provider=messaging_provider,
            message_provider=message_provider,
            quote_extractor=quote_extractor,
            followup_drafter=followup_drafter,
            settings=settings,
        ).create(request.vehicle_id)
    except CandidateNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "candidate_not_found",
                "message": "The selected inventory candidate was not found.",
            },
        ) from error


@router.get("/{run_id}", response_model=AgentRun)
def inspect_agent_run(
    run_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> AgentRun:
    try:
        return AgentRunRepository(session).get(run_id)
    except AgentRunNotFoundError as error:
        raise _not_found(error) from error


@router.post("/{run_id}/resume", response_model=AgentRun)
async def resume_agent_run(
    run_id: str,
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
    _: Annotated[ResumeAgentRunRequest | None, Body()] = None,
) -> AgentRun:
    try:
        return await _service(
            session=session,
            inventory_provider=inventory_provider,
            dealer_contact_resolver=dealer_contact_resolver,
            messaging_provider=messaging_provider,
            message_provider=message_provider,
            quote_extractor=quote_extractor,
            followup_drafter=followup_drafter,
            settings=settings,
        ).resume(run_id)
    except AgentRunNotFoundError as error:
        raise _not_found(error) from error
    except (
        AgentRunAlreadyAdvancingError,
        AgentRunExecutionLeaseLostError,
    ) as error:
        raise _already_advancing(error) from error


def _not_found(error: Exception) -> HTTPException:
    del error
    return HTTPException(
        status_code=404,
        detail={
            "code": "agent_run_not_found",
            "message": "The requested agent workflow was not found.",
        },
    )


def _already_advancing(error: Exception) -> HTTPException:
    del error
    return HTTPException(
        status_code=409,
        detail={
            "code": "agent_run_already_advancing",
            "message": "This workflow is already processing another resume request.",
        },
    )
