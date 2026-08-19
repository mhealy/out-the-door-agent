from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.dependencies import get_inventory_provider, get_messaging_provider
from app.domain.approval import OutreachProposal
from app.persistence.db import get_session
from app.providers.inventory import InventoryProvider
from app.providers.messaging import (
    DealerContactNotFoundError,
    MessagingProvider,
)
from app.services.outreach import (
    CandidateNotFoundError,
    OutreachActionAlreadyApprovedError,
    OutreachActionAlreadySentError,
    OutreachActionNotApprovableError,
    OutreachActionNotRejectableError,
    OutreachProposalNotFoundError,
    OutreachRetryRequiresNewProposalError,
    OutreachSendError,
    OutreachService,
)

router = APIRouter(prefix="/outreach/proposals", tags=["outreach"])


class PrepareOutreachRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_id: str = Field(min_length=1)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _service(
    session: Session,
    inventory_provider: InventoryProvider,
    messaging_provider: MessagingProvider,
) -> OutreachService:
    return OutreachService(
        session=session,
        inventory_provider=inventory_provider,
        messaging_provider=messaging_provider,
    )


@router.post("", response_model=OutreachProposal, status_code=status.HTTP_201_CREATED)
async def prepare_outreach(
    request: PrepareOutreachRequest,
    session: Annotated[Session, Depends(get_session)],
    inventory_provider: Annotated[InventoryProvider, Depends(get_inventory_provider)],
    messaging_provider: Annotated[MessagingProvider, Depends(get_messaging_provider)],
) -> OutreachProposal:
    try:
        return await _service(
            session, inventory_provider, messaging_provider
        ).prepare(request.vehicle_id)
    except CandidateNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "candidate_not_found",
                "message": "The selected inventory candidate was not found.",
            },
        ) from error
    except DealerContactNotFoundError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "dealer_contact_not_found",
                "message": "No safe fixture contact is configured for this dealer.",
            },
        ) from error


@router.get("/{action_id}", response_model=OutreachProposal)
def inspect_outreach(
    action_id: str,
    session: Annotated[Session, Depends(get_session)],
    inventory_provider: Annotated[InventoryProvider, Depends(get_inventory_provider)],
    messaging_provider: Annotated[MessagingProvider, Depends(get_messaging_provider)],
) -> OutreachProposal:
    try:
        return _service(session, inventory_provider, messaging_provider).get(action_id)
    except OutreachProposalNotFoundError as error:
        raise _proposal_not_found(error) from error


@router.post("/{action_id}/approve", response_model=OutreachProposal)
async def approve_outreach(
    action_id: str,
    session: Annotated[Session, Depends(get_session)],
    inventory_provider: Annotated[InventoryProvider, Depends(get_inventory_provider)],
    messaging_provider: Annotated[MessagingProvider, Depends(get_messaging_provider)],
    _: Annotated[DecisionRequest | None, Body()] = None,
) -> OutreachProposal:
    try:
        return await _service(
            session, inventory_provider, messaging_provider
        ).approve_and_send(action_id)
    except OutreachProposalNotFoundError as error:
        raise _proposal_not_found(error) from error
    except OutreachActionAlreadyApprovedError as error:
        raise _conflict(
            "outreach_action_already_approved",
            "This dealer message has already been approved for delivery.",
            error,
        ) from error
    except OutreachActionAlreadySentError as error:
        raise _conflict(
            "outreach_action_already_sent",
            "This dealer message has already been sent.",
            error,
        ) from error
    except OutreachRetryRequiresNewProposalError as error:
        raise _conflict(
            "outreach_retry_requires_new_proposal",
            "Delivery was not confirmed. Review the prior attempt before preparing a new proposal.",
            error,
        ) from error
    except OutreachActionNotApprovableError as error:
        raise _conflict(
            "outreach_action_not_approvable",
            "This proposed action can no longer be approved.",
            error,
        ) from error
    except OutreachSendError as error:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "outreach_send_failed",
                "message": "The approved dealer message could not be sent.",
            },
        ) from error


@router.post("/{action_id}/reject", response_model=OutreachProposal)
def reject_outreach(
    action_id: str,
    session: Annotated[Session, Depends(get_session)],
    inventory_provider: Annotated[InventoryProvider, Depends(get_inventory_provider)],
    messaging_provider: Annotated[MessagingProvider, Depends(get_messaging_provider)],
    _: Annotated[DecisionRequest | None, Body()] = None,
) -> OutreachProposal:
    try:
        return _service(session, inventory_provider, messaging_provider).reject(action_id)
    except OutreachProposalNotFoundError as error:
        raise _proposal_not_found(error) from error
    except OutreachActionNotRejectableError as error:
        raise _conflict(
            "outreach_action_not_rejectable",
            "This proposed action can no longer be rejected.",
            error,
        ) from error


def _proposal_not_found(error: Exception) -> HTTPException:
    del error
    return HTTPException(
        status_code=404,
        detail={
            "code": "outreach_proposal_not_found",
            "message": "The requested outreach proposal was not found.",
        },
    )


def _conflict(code: str, message: str, error: Exception) -> HTTPException:
    del error
    return HTTPException(
        status_code=409,
        detail={"code": code, "message": message},
    )
