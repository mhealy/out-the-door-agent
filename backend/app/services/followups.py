from __future__ import annotations

import re
import unicodedata
from uuid import uuid4

from sqlalchemy.orm import Session

from app.domain.approval import OutreachProposal, ProposedAction
from app.domain.followup import (
    FollowupConversationMessage,
    FollowupDraft,
    FollowupDraftContext,
    FollowupRequirement,
    ValidatedFollowupDraft,
)
from app.domain.interaction import DealerInteraction
from app.domain.outreach_requirements import (
    FOLLOWUP_REQUIREMENT_LABELS,
    FOLLOWUP_SUBJECT_OPTIONS,
    FOLLOWUP_WORDING_OPTIONS,
)
from app.domain.quote import QuoteAssessment
from app.persistence.interactions import (
    InteractionRecordNotFoundError,
    InteractionRepository,
)
from app.persistence.outreach import (
    OutreachFollowupLimitReachedError,
    OutreachFollowupSourceBlockedError,
    OutreachFollowupSourceChangedError,
    OutreachRecordNotFoundError,
    OutreachRepository,
)
from app.providers.dealer_contacts import DealerContactResolver
from app.providers.followup_drafting import FollowupDrafter
from app.services.outreach import OutreachProposalNotFoundError
from app.services.quote_assessment import (
    ADDON_STATUS,
    CLAIMED_OTD,
    FINANCING_DEPENDENCY,
    MANDATORY_ADDON_AMOUNT,
    PRICING_CONDITION,
    TRADE_DEPENDENCY,
    VEHICLE_IDENTITY,
    VEHICLE_IDENTITY_MISMATCH,
)


FOLLOWUP_REQUIREMENT_ORDER = (
    VEHICLE_IDENTITY,
    VEHICLE_IDENTITY_MISMATCH,
    CLAIMED_OTD,
    ADDON_STATUS,
    MANDATORY_ADDON_AMOUNT,
    FINANCING_DEPENDENCY,
    TRADE_DEPENDENCY,
    PRICING_CONDITION,
)
FOLLOWUP_LIMIT = 2
FOLLOWUP_REASON = (
    "Clarify the deterministic comparison gaps in the latest written dealer quote."
)

MAX_SUBJECT_LENGTH = 160
MAX_REQUEST_LENGTH = 500
MAX_BODY_LENGTH = 2_000

_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", re.IGNORECASE)
_URL = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")
_VIN = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b", re.IGNORECASE)

_PROHIBITED_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bssn\b",
        r"\bsocial\s+security(?:\s+number)?\b",
        r"\bdate\s+of\s+birth\b",
        r"\bdriver'?s\s+licen[cs]e\b",
        r"\bpassport\b",
        r"\bbank\s+(?:account|details|information)\b",
        r"\brouting\s+number\b",
        r"\b(?:credit|debit)\s+card(?:\s+number|\s+details)?\b",
        r"\bpayment\s+(?:information|details|method)\b",
        r"\bcredit\s+application\b",
        r"\bapply\s+for\s+credit\b",
        r"\bauthori[sz]e\s+(?:a\s+)?credit\b",
        r"\bcredit\s+(?:check|pull|report)\b",
        r"\b(?:place|pay|charge|send|make|provide)\b.{0,35}\bdeposit\b",
        r"\bdown\s+payment\b",
        r"\b(?:sign|execute)\b.{0,40}\b(?:agreement|contract)\b",
        r"\baccept\b.{0,25}\b(?:offer|deal|terms)\b",
        r"\bcommit\b.{0,30}\b(?:buy|purchase|purchasing)\b",
        r"\b(?:reserve|hold)\b.{0,30}\bvehicle\b",
        r"\b(?:i|we|the\s+buyer)\s+(?:will|can)\s+(?:visit|come\s+in|call)\b",
        r"\b(?:book|schedule)\b.{0,30}\b(?:visit|appointment|call)\b",
        r"\bprovide\b.{0,45}\btrade(?:-in)?\s+(?:vin|details|documents?)\b",
        r"\b(?:competing|competitor)\s+offer\b",
        r"\bother\s+dealer\b",
        r"\b(?:beat|match)\b.{0,20}\bprice\b",
        r"\b(?:scam|fraud|dishonest|rip[ -]?off)\b",
        r"\b(?:legal\s+action|report\s+you|final\s+warning)\b",
    )
)


class UnsupportedFollowupRequirementError(ValueError):
    """Persisted assessment contains a gap outside deterministic policy."""


class FollowupDraftValidationError(ValueError):
    """Draft wording failed deterministic structural or safety validation."""


class FollowupNotAvailableError(RuntimeError):
    """The interaction has no latest analyzed dealer response to clarify."""


class FollowupNotRequiredError(RuntimeError):
    """Deterministic comparison policy has no gaps to ask about."""


class FollowupLimitReachedError(RuntimeError):
    """Two confirmed follow-ups have already been sent for the interaction."""


class FollowupRecipientChangedError(RuntimeError):
    """The current resolver no longer matches the interaction's saved recipient."""


class FollowupSourceMessageBlockedError(RuntimeError):
    """The latest response already owns an active or sent follow-up."""

    def __init__(
        self,
        interaction_id: str,
        source_message_id: str,
        action_status: str,
    ) -> None:
        super().__init__(source_message_id)
        self.interaction_id = interaction_id
        self.source_message_id = source_message_id
        self.action_status = action_status


class FollowupSourceChangedError(RuntimeError):
    """A newer response became current while the follow-up was drafted."""


def derive_followup_requirements(
    assessment: QuoteAssessment,
) -> list[FollowupRequirement]:
    """Return the canonical comparison-only requirement set.

    Transparency gaps and source uncertainty are deliberately absent from this
    policy. Repeated comparison identifiers are normalized to one stable item;
    unknown identifiers fail closed instead of becoming model-owned policy.
    """

    supplied = assessment.missing_for_comparison
    unknown = sorted(set(supplied) - set(FOLLOWUP_REQUIREMENT_ORDER))
    if unknown:
        raise UnsupportedFollowupRequirementError(
            "unsupported follow-up requirement identifiers: " + ", ".join(unknown)
        )
    selected = set(supplied)
    return [
        FollowupRequirement(
            id=requirement_id,
            label=FOLLOWUP_REQUIREMENT_LABELS[requirement_id],
            wording_options=list(FOLLOWUP_WORDING_OPTIONS[requirement_id]),
        )
        for requirement_id in FOLLOWUP_REQUIREMENT_ORDER
        if requirement_id in selected
    ]


def validate_followup_draft(
    draft: FollowupDraft,
    requirements: list[FollowupRequirement],
    *,
    target_vin: str | None = None,
    target_stock_number: str | None = None,
) -> ValidatedFollowupDraft:
    """Validate exact requirement coverage and render the final immutable body."""

    required_ids = [requirement.id for requirement in requirements]
    if len(required_ids) != len(set(required_ids)):
        raise FollowupDraftValidationError(
            "The application requirement set contains duplicate identifiers."
        )
    supplied_ids = [request.requirement_id for request in draft.requests]
    duplicates = sorted(
        requirement_id
        for requirement_id in set(supplied_ids)
        if supplied_ids.count(requirement_id) > 1
    )
    if duplicates:
        raise FollowupDraftValidationError(
            "The draft contains duplicate requirement identifiers: "
            + ", ".join(duplicates)
        )
    missing = [item for item in required_ids if item not in supplied_ids]
    if missing:
        raise FollowupDraftValidationError(
            "The draft is missing required comparison gaps: " + ", ".join(missing)
        )
    extras = [item for item in supplied_ids if item not in required_ids]
    if extras:
        raise FollowupDraftValidationError(
            "The draft contains unknown or extra requirements: " + ", ".join(extras)
        )

    subject = draft.subject.strip()
    if not subject:
        raise FollowupDraftValidationError("The follow-up subject cannot be empty.")
    if len(subject) > MAX_SUBJECT_LENGTH:
        raise FollowupDraftValidationError("The follow-up subject exceeds its length limit.")
    if subject not in FOLLOWUP_SUBJECT_OPTIONS:
        raise FollowupDraftValidationError(
            "The follow-up subject is not approved code-owned wording."
        )
    _validate_safe_wording(subject, target_vin=target_vin)

    requests_by_id = {
        request.requirement_id: request.text.strip() for request in draft.requests
    }
    requirements_by_id = {
        requirement.id: requirement for requirement in requirements
    }
    ordered_requests: list[str] = []
    for requirement_id in required_ids:
        text = requests_by_id[requirement_id]
        if not text:
            raise FollowupDraftValidationError(
                f"The request wording for {requirement_id} cannot be empty."
            )
        if len(text) > MAX_REQUEST_LENGTH:
            raise FollowupDraftValidationError(
                f"The request wording for {requirement_id} exceeds its length limit."
            )
        _validate_safe_wording(text, target_vin=target_vin)
        if text not in requirements_by_id[requirement_id].wording_options:
            raise FollowupDraftValidationError(
                f"The request wording for {requirement_id} is not an approved "
                "code-owned option."
            )
        rendered_text = _render_target_identity(
            text,
            requirement_id=requirement_id,
            target_vin=target_vin,
            target_stock_number=target_stock_number,
        )
        _validate_safe_wording(rendered_text, target_vin=target_vin)
        ordered_requests.append(rendered_text)

    bullets = "\n".join(f"- {text}" for text in ordered_requests)
    body = (
        "Thanks for the quote. To compare it accurately, could you please confirm:\n\n"
        f"{bullets}\n\n"
        "Thank you."
    )
    if len(body) > MAX_BODY_LENGTH:
        raise FollowupDraftValidationError("The rendered follow-up body is too long.")
    return ValidatedFollowupDraft(
        subject=subject,
        body=body,
        addressed_requirements=required_ids,
    )


def _render_target_identity(
    text: str,
    *,
    requirement_id: str,
    target_vin: str | None,
    target_stock_number: str | None,
) -> str:
    if requirement_id not in {VEHICLE_IDENTITY, VEHICLE_IDENTITY_MISMATCH}:
        return text
    target = None
    if target_vin:
        target = f"VIN {target_vin}"
    elif target_stock_number:
        target = f"stock number {target_stock_number}"
    if target is None:
        return text
    return f"For {target}, {text[0].lower()}{text[1:]}"


def _validate_safe_wording(value: str, *, target_vin: str | None) -> None:
    normalized = unicodedata.normalize("NFKC", value)
    if _EMAIL.search(normalized) or _URL.search(normalized) or _PHONE.search(normalized):
        raise FollowupDraftValidationError(
            "The draft contains prohibited contact or redirection information."
        )
    if any(pattern.search(normalized) for pattern in _PROHIBITED_PATTERNS):
        raise FollowupDraftValidationError(
            "The draft contains a prohibited buyer data or action request."
        )

    normalized_target = target_vin.strip().casefold() if target_vin else None
    mentioned_vins = {match.group(0).casefold() for match in _VIN.finditer(normalized)}
    if mentioned_vins and (
        normalized_target is None or mentioned_vins != {normalized_target}
    ):
        raise FollowupDraftValidationError(
            "The draft mentions a VIN other than the application-owned target vehicle."
        )


def _vehicle_description(interaction: DealerInteraction) -> str:
    vehicle = interaction.vehicle
    return " ".join(
        str(value)
        for value in (vehicle.year, vehicle.make, vehicle.model, vehicle.trim)
        if value is not None and str(value).strip()
    )


class FollowupService:
    """Prepare immutable follow-up proposals from persisted deterministic gaps."""

    def __init__(
        self,
        *,
        session: Session,
        dealer_contact_resolver: DealerContactResolver,
        drafter: FollowupDrafter,
    ) -> None:
        self._outreach_repository = OutreachRepository(session)
        self._interaction_repository = InteractionRepository(session)
        self._dealer_contact_resolver = dealer_contact_resolver
        self._drafter = drafter

    async def prepare(self, initial_action_id: str) -> OutreachProposal:
        try:
            initial_action = self._outreach_repository.get_action(initial_action_id)
        except OutreachRecordNotFoundError as error:
            raise OutreachProposalNotFoundError(initial_action_id) from error
        if (
            initial_action.action_type != "SEND_INITIAL_QUOTE_REQUEST"
            or initial_action.status != "SENT"
        ):
            raise FollowupNotAvailableError(initial_action_id)

        try:
            interaction = self._interaction_repository.get(initial_action_id)
        except InteractionRecordNotFoundError as error:
            raise FollowupNotAvailableError(initial_action_id) from error
        if interaction.analysis_status != "ANALYZED" or interaction.analysis is None:
            raise FollowupNotAvailableError(initial_action_id)
        if interaction.followup_limit_reached:
            raise FollowupLimitReachedError(interaction.id)

        latest_message = interaction.analysis.message
        if interaction.latest_response_followup_status is not None:
            raise FollowupSourceMessageBlockedError(
                interaction.id,
                latest_message.id,
                interaction.latest_response_followup_status,
            )

        requirements = derive_followup_requirements(
            interaction.analysis.assessment
        )
        if not requirements:
            raise FollowupNotRequiredError(interaction.id)

        resolved_recipient = self._dealer_contact_resolver.resolve(
            interaction.dealer_id
        )
        if resolved_recipient != initial_action.recipient:
            raise FollowupRecipientChangedError(interaction.id)

        previous_outbound = [
            FollowupConversationMessage(
                direction="OUTBOUND",
                subject=initial_action.subject,
                body=initial_action.body,
            ),
            *[
                FollowupConversationMessage(
                    direction="OUTBOUND",
                    subject=proposal.subject,
                    body=proposal.body,
                )
                for proposal in interaction.followups
                if proposal.status == "SENT"
            ],
        ]
        context = FollowupDraftContext(
            interaction_id=interaction.id,
            dealer_id=interaction.dealer_id,
            dealer_name=interaction.vehicle.dealer_name,
            vehicle_description=_vehicle_description(interaction),
            target_vin=interaction.vehicle.vin,
            target_stock_number=interaction.vehicle.stock_number,
            previous_outbound=previous_outbound,
            latest_inbound=FollowupConversationMessage(
                direction="INBOUND",
                subject=latest_message.subject,
                body=latest_message.body,
            ),
            requirements=requirements,
            source_uncertainty=list(
                interaction.analysis.extraction.unresolved_questions
            ),
        )
        draft = await self._drafter.draft(context)
        validated = validate_followup_draft(
            draft,
            requirements,
            target_vin=interaction.vehicle.vin,
            target_stock_number=interaction.vehicle.stock_number,
        )
        action = ProposedAction(
            id=str(uuid4()),
            action_type="SEND_FOLLOWUP",
            dealer_id=interaction.dealer_id,
            vehicle_id=interaction.vehicle_id,
            recipient=initial_action.recipient,
            subject=validated.subject,
            body=validated.body,
            reason=FOLLOWUP_REASON,
            requested_information=list(validated.addressed_requirements),
            requires_approval=True,
        )
        try:
            self._outreach_repository.create_followup(
                action,
                interaction.vehicle,
                interaction_id=interaction.id,
                source_message_id=latest_message.id,
            )
        except OutreachFollowupLimitReachedError as error:
            raise FollowupLimitReachedError(interaction.id) from error
        except OutreachFollowupSourceBlockedError as error:
            raise FollowupSourceMessageBlockedError(
                interaction.id,
                error.source_message_id,
                error.action_status,
            ) from error
        except OutreachFollowupSourceChangedError as error:
            raise FollowupSourceChangedError(interaction.id) from error
        return self._outreach_repository.get_proposal(action.id)
