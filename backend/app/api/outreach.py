from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.dependencies import (
    get_dealer_contact_resolver,
    get_dealer_message_provider,
    get_followup_drafter,
    get_inventory_provider,
    get_messaging_provider,
    get_quote_extractor,
)
from app.domain.approval import OutreachProposal
from app.domain.interaction import DealerInteraction
from app.persistence.db import get_session
from app.providers.dealer_contacts import (
    DealerContactNotFoundError,
    DealerContactResolver,
)
from app.providers.inventory import InventoryProvider
from app.providers.dealer_messages import (
    DealerMessageProvider,
    DemoResponseFixtureNotFoundError,
)
from app.providers.messaging import MessagingProvider
from app.providers.followup_drafting import (
    FollowupDrafter,
    FollowupDrafterUnavailableError,
    FollowupDraftingError,
)
from app.providers.quote_extraction import (
    QuoteExtractionError,
    QuoteExtractor,
    QuoteExtractorUnavailableError,
)
from app.services.evidence_validation import EvidenceValidationError
from app.services.outreach import (
    CandidateNotFoundError,
    OutreachActionAlreadyApprovedError,
    OutreachActionAlreadySentError,
    OutreachActionNotApprovableError,
    OutreachActionNotRejectableError,
    OutreachFollowupLimitReachedError,
    OutreachFollowupSourceChangedError,
    OutreachProposalNotFoundError,
    OutreachRetryRequiresNewProposalError,
    OutreachSendError,
    OutreachService,
)
from app.services.followups import (
    FollowupDraftValidationError,
    FollowupLimitReachedError,
    FollowupNotAvailableError,
    FollowupNotRequiredError,
    FollowupRecipientChangedError,
    FollowupService,
    FollowupSourceChangedError,
    FollowupSourceMessageBlockedError,
    UnsupportedFollowupRequirementError,
)
from app.services.outreach_interactions import (
    InteractionAnalysisFailedError,
    OutreachInteractionNotFoundError,
    OutreachInteractionService,
    OutreachResponseAnalysisInProgressError,
    OutreachResponseNotReleasableError,
)

router = APIRouter(prefix="/outreach/proposals", tags=["outreach"])


class PrepareOutreachRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_id: str = Field(min_length=1)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DemoResponseReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PrepareFollowupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _service(
    session: Session,
    inventory_provider: InventoryProvider,
    dealer_contact_resolver: DealerContactResolver,
    messaging_provider: MessagingProvider,
) -> OutreachService:
    return OutreachService(
        session=session,
        inventory_provider=inventory_provider,
        dealer_contact_resolver=dealer_contact_resolver,
        messaging_provider=messaging_provider,
    )


def _interaction_service(
    session: Session,
    message_provider: DealerMessageProvider,
    quote_extractor: QuoteExtractor,
    inventory_provider: InventoryProvider,
) -> OutreachInteractionService:
    return OutreachInteractionService(
        session=session,
        message_provider=message_provider,
        quote_extractor=quote_extractor,
        inventory_provider=inventory_provider,
    )


def _followup_service(
    session: Session,
    dealer_contact_resolver: DealerContactResolver,
    drafter: FollowupDrafter,
) -> FollowupService:
    return FollowupService(
        session=session,
        dealer_contact_resolver=dealer_contact_resolver,
        drafter=drafter,
    )


@router.post("", response_model=OutreachProposal, status_code=status.HTTP_201_CREATED)
async def prepare_outreach(
    request: PrepareOutreachRequest,
    session: Annotated[Session, Depends(get_session)],
    inventory_provider: Annotated[InventoryProvider, Depends(get_inventory_provider)],
    dealer_contact_resolver: Annotated[
        DealerContactResolver, Depends(get_dealer_contact_resolver)
    ],
    messaging_provider: Annotated[MessagingProvider, Depends(get_messaging_provider)],
) -> OutreachProposal:
    try:
        return await _service(
            session,
            inventory_provider,
            dealer_contact_resolver,
            messaging_provider,
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
    dealer_contact_resolver: Annotated[
        DealerContactResolver, Depends(get_dealer_contact_resolver)
    ],
    messaging_provider: Annotated[MessagingProvider, Depends(get_messaging_provider)],
) -> OutreachProposal:
    try:
        return _service(
            session,
            inventory_provider,
            dealer_contact_resolver,
            messaging_provider,
        ).get(action_id)
    except OutreachProposalNotFoundError as error:
        raise _proposal_not_found(error) from error


@router.get("/{action_id}/interaction", response_model=DealerInteraction)
def inspect_interaction(
    action_id: str,
    session: Annotated[Session, Depends(get_session)],
    message_provider: Annotated[
        DealerMessageProvider, Depends(get_dealer_message_provider)
    ],
    quote_extractor: Annotated[QuoteExtractor, Depends(get_quote_extractor)],
    inventory_provider: Annotated[InventoryProvider, Depends(get_inventory_provider)],
) -> DealerInteraction:
    try:
        return _interaction_service(
            session,
            message_provider,
            quote_extractor,
            inventory_provider,
        ).get(action_id)
    except OutreachProposalNotFoundError as error:
        raise _proposal_not_found(error) from error
    except OutreachInteractionNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "outreach_interaction_not_found",
                "message": "The proposed action has no confirmed dealer interaction.",
            },
        ) from error


@router.post(
    "/{action_id}/followups",
    response_model=OutreachProposal,
    status_code=status.HTTP_201_CREATED,
)
async def prepare_followup(
    action_id: str,
    session: Annotated[Session, Depends(get_session)],
    dealer_contact_resolver: Annotated[
        DealerContactResolver, Depends(get_dealer_contact_resolver)
    ],
    drafter: Annotated[FollowupDrafter, Depends(get_followup_drafter)],
    _: Annotated[PrepareFollowupRequest | None, Body()] = None,
) -> OutreachProposal:
    try:
        return await _followup_service(
            session,
            dealer_contact_resolver,
            drafter,
        ).prepare(action_id)
    except OutreachProposalNotFoundError as error:
        raise _proposal_not_found(error) from error
    except DealerContactNotFoundError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "dealer_contact_not_found",
                "message": "No safe fixture contact is configured for this dealer.",
            },
        ) from error
    except FollowupNotAvailableError as error:
        raise _conflict(
            "followup_not_available",
            "A follow-up requires a latest analyzed response on this interaction.",
            error,
        ) from error
    except FollowupNotRequiredError as error:
        raise _conflict(
            "followup_not_required",
            "Deterministic comparison policy has no information left to request.",
            error,
        ) from error
    except FollowupLimitReachedError as error:
        raise _conflict(
            "followup_limit_reached",
            "This dealer interaction already has two confirmed sent follow-ups.",
            error,
        ) from error
    except FollowupSourceMessageBlockedError as error:
        raise _followup_source_conflict(error) from error
    except FollowupSourceChangedError as error:
        raise _conflict(
            "followup_source_changed",
            (
                "A newer dealer response became current while the follow-up "
                "was drafted. Refresh the interaction and prepare again."
            ),
            error,
        ) from error
    except FollowupRecipientChangedError as error:
        raise _conflict(
            "followup_recipient_changed",
            "The application-owned dealer contact changed; prepare a new interaction.",
            error,
        ) from error
    except UnsupportedFollowupRequirementError as error:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "invalid_followup_requirement_policy",
                "message": "The persisted assessment contains an unsupported gap.",
            },
        ) from error
    except FollowupDrafterUnavailableError as error:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "followup_drafter_unavailable",
                "message": "Follow-up drafting is not configured.",
            },
        ) from error
    except (FollowupDraftingError, FollowupDraftValidationError) as error:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "invalid_followup_draft",
                "message": (
                    "The model did not return a safe, requirement-complete follow-up."
                ),
            },
        ) from error


@router.post("/{action_id}/demo-response", response_model=DealerInteraction)
async def release_demo_response(
    action_id: str,
    session: Annotated[Session, Depends(get_session)],
    message_provider: Annotated[
        DealerMessageProvider, Depends(get_dealer_message_provider)
    ],
    quote_extractor: Annotated[QuoteExtractor, Depends(get_quote_extractor)],
    inventory_provider: Annotated[InventoryProvider, Depends(get_inventory_provider)],
    _: Annotated[DemoResponseReleaseRequest | None, Body()] = None,
) -> DealerInteraction:
    try:
        return await _interaction_service(
            session,
            message_provider,
            quote_extractor,
            inventory_provider,
        ).release_demo_response(action_id)
    except OutreachProposalNotFoundError as error:
        raise _proposal_not_found(error) from error
    except OutreachResponseNotReleasableError as error:
        raise _conflict(
            "outreach_response_not_releasable",
            "A dealer response can be released only after confirmed initial delivery.",
            error,
        ) from error
    except OutreachResponseAnalysisInProgressError as error:
        raise _conflict(
            "outreach_response_analysis_in_progress",
            (
                "This dealer response is already being analyzed. Inspect the "
                "interaction and retry later if needed."
            ),
            error,
        ) from error
    except DemoResponseFixtureNotFoundError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "demo_response_fixture_not_found",
                "message": (
                    "No deterministic dealer response fixture is configured for "
                    "this interaction."
                ),
            },
        ) from error
    except QuoteExtractorUnavailableError as error:
        raise _analysis_error("quote_extractor_unavailable", error) from error
    except QuoteExtractionError as error:
        raise _analysis_error("quote_extraction_failed", error) from error
    except EvidenceValidationError as error:
        raise _analysis_error("invalid_quote_evidence", error) from error
    except InteractionAnalysisFailedError as error:
        raise _analysis_error(error.error_code, error) from error


@router.post("/{action_id}/approve", response_model=OutreachProposal)
async def approve_outreach(
    action_id: str,
    session: Annotated[Session, Depends(get_session)],
    inventory_provider: Annotated[InventoryProvider, Depends(get_inventory_provider)],
    dealer_contact_resolver: Annotated[
        DealerContactResolver, Depends(get_dealer_contact_resolver)
    ],
    messaging_provider: Annotated[MessagingProvider, Depends(get_messaging_provider)],
    _: Annotated[DecisionRequest | None, Body()] = None,
) -> OutreachProposal:
    try:
        return await _service(
            session,
            inventory_provider,
            dealer_contact_resolver,
            messaging_provider,
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
    except OutreachFollowupLimitReachedError as error:
        raise _conflict(
            "followup_limit_reached",
            "This dealer interaction has no remaining confirmed follow-up slot.",
            error,
        ) from error
    except OutreachFollowupSourceChangedError as error:
        raise _conflict(
            "followup_source_changed",
            "A newer dealer response was analyzed. Prepare a new follow-up.",
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
    dealer_contact_resolver: Annotated[
        DealerContactResolver, Depends(get_dealer_contact_resolver)
    ],
    messaging_provider: Annotated[MessagingProvider, Depends(get_messaging_provider)],
    _: Annotated[DecisionRequest | None, Body()] = None,
) -> OutreachProposal:
    try:
        return _service(
            session,
            inventory_provider,
            dealer_contact_resolver,
            messaging_provider,
        ).reject(action_id)
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


def _followup_source_conflict(
    error: FollowupSourceMessageBlockedError,
) -> HTTPException:
    if error.action_status == "PENDING_APPROVAL":
        return _conflict(
            "followup_already_pending",
            "A follow-up for this dealer response is already awaiting approval.",
            error,
        )
    if error.action_status == "APPROVED":
        return _conflict(
            "followup_delivery_unconfirmed",
            "The approved follow-up has an unconfirmed delivery outcome.",
            error,
        )
    return _conflict(
        "followup_waiting_for_response",
        (
            "A follow-up for this response was sent. Wait for a newer "
            "dealer response before preparing another."
        ),
        error,
    )


def _analysis_error(code: str, error: Exception) -> HTTPException:
    del error
    if code == "quote_extractor_unavailable":
        return HTTPException(
            status_code=503,
            detail={
                "code": code,
                "message": (
                    "Quote extraction is not configured. Set the model API key "
                    "and retry."
                ),
            },
        )
    if code == "invalid_quote_evidence":
        return HTTPException(
            status_code=502,
            detail={
                "code": code,
                "message": (
                    "The extracted quote contained evidence that could not be "
                    "traced to the dealer response."
                ),
            },
        )
    return HTTPException(
        status_code=502,
        detail={
            "code": "quote_extraction_failed",
            "message": (
                "The dealer response could not be extracted into a structured quote."
            ),
        },
    )
