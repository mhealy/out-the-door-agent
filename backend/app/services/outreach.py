from __future__ import annotations

from typing import Final
from uuid import uuid4

from sqlalchemy.orm import Session

from app.domain.approval import OutreachProposal, ProposedAction
from app.domain.message import OutboundDealerMessage
from app.domain.vehicle import VehicleListing
from app.persistence.models import ProposedActionRecord
from app.persistence.outreach import OutreachRecordNotFoundError, OutreachRepository
from app.providers.dealer_contacts import DealerContactResolver
from app.providers.inventory import InventoryProvider
from app.providers.messaging import MessagingProvider


INITIAL_QUOTE_REQUEST_REQUIREMENTS: Final[tuple[str, ...]] = (
    "vehicle_identity",
    "selling_price",
    "dealer_fees",
    "mandatory_addons",
    "government_charges",
    "out_the_door_total",
    "incentives_and_eligibility",
    "financing_requirement",
    "trade_in_requirement",
    "quote_expiration",
)

INITIAL_QUOTE_REQUEST_LABELS: Final[dict[str, str]] = {
    "vehicle_identity": "Exact VIN and/or stock number for the quoted vehicle",
    "selling_price": "Selling price before taxes and fees",
    "dealer_fees": "All dealer and documentation fees",
    "mandatory_addons": (
        "All mandatory dealer-installed products or add-ons and their amounts"
    ),
    "government_charges": "Taxes, title, license, and other government charges",
    "out_the_door_total": "Written out-the-door total",
    "incentives_and_eligibility": (
        "Every included incentive or rebate and its eligibility conditions"
    ),
    "financing_requirement": "Whether the quoted economics require dealer financing",
    "trade_in_requirement": "Whether the quoted economics require a trade-in",
    "quote_expiration": "Quote expiration or validity period, if applicable",
}


class CandidateNotFoundError(LookupError):
    """The selected normalized inventory candidate does not exist."""


class OutreachProposalNotFoundError(LookupError):
    """The requested proposed action does not exist."""


class OutreachActionNotApprovableError(RuntimeError):
    """The proposed action is in a terminal non-approvable state."""


class OutreachActionAlreadyApprovedError(RuntimeError):
    """Another request already claimed this proposal for delivery."""


class OutreachActionAlreadySentError(RuntimeError):
    """The approved action was already delivered."""


class OutreachRetryRequiresNewProposalError(RuntimeError):
    """A failed external attempt cannot be retried implicitly."""


class OutreachActionNotRejectableError(RuntimeError):
    """The proposed action is no longer pending a decision."""


class OutreachSendError(RuntimeError):
    """The approved content could not be delivered."""


def _vehicle_description(vehicle: VehicleListing) -> str:
    parts: list[str] = [str(vehicle.year), vehicle.make, vehicle.model]
    if vehicle.trim:
        parts.append(vehicle.trim)
    return " ".join(parts)


def compose_initial_quote_request(
    *,
    action_id: str,
    vehicle: VehicleListing,
    recipient: str,
) -> ProposedAction:
    """Compose code-owned initial outreach without probabilistic generation."""

    vehicle_description = _vehicle_description(vehicle)
    known_identity: list[str] = []
    if vehicle.vin:
        known_identity.append(f"VIN: {vehicle.vin}")
    if vehicle.stock_number:
        known_identity.append(f"Stock number: {vehicle.stock_number}")

    identity_block = ""
    if known_identity:
        identity_block = "\n" + "\n".join(f"- {item}" for item in known_identity)

    requested_items = "\n".join(
        f"- {INITIAL_QUOTE_REQUEST_LABELS[requirement_id]}"
        for requirement_id in INITIAL_QUOTE_REQUEST_REQUIREMENTS
    )
    body = (
        "Hello,\n\n"
        f"I am requesting a written quote for the {vehicle_description} at "
        f"{vehicle.dealer_name}.{identity_block}\n\n"
        "Please provide the following information in writing:\n"
        f"{requested_items}\n\n"
        "Thank you."
    )

    return ProposedAction(
        id=action_id,
        action_type="SEND_INITIAL_QUOTE_REQUEST",
        dealer_id=vehicle.dealer_id,
        vehicle_id=vehicle.id,
        recipient=recipient,
        subject=f"Written quote request — {vehicle_description}",
        body=body,
        reason=(
            "Obtain a complete written out-the-door quote for this selected vehicle."
        ),
        requested_information=list(INITIAL_QUOTE_REQUEST_REQUIREMENTS),
        requires_approval=True,
    )


class OutreachService:
    def __init__(
        self,
        *,
        session: Session,
        inventory_provider: InventoryProvider,
        dealer_contact_resolver: DealerContactResolver,
        messaging_provider: MessagingProvider,
    ) -> None:
        self._repository = OutreachRepository(session)
        self._inventory_provider = inventory_provider
        self._dealer_contact_resolver = dealer_contact_resolver
        self._messaging_provider = messaging_provider

    async def prepare(self, vehicle_id: str) -> OutreachProposal:
        vehicle = await self._inventory_provider.get_by_id(vehicle_id)
        if vehicle is None:
            raise CandidateNotFoundError(vehicle_id)

        recipient = self._dealer_contact_resolver.resolve(vehicle.dealer_id)
        action = compose_initial_quote_request(
            action_id=str(uuid4()),
            vehicle=vehicle,
            recipient=recipient,
        )
        self._repository.create(action, vehicle)
        return self._get_proposal(action.id)

    def get(self, action_id: str) -> OutreachProposal:
        return self._get_proposal(action_id)

    async def approve_and_send(self, action_id: str) -> OutreachProposal:
        action = self._get_action(action_id)
        claimed = self._repository.claim_approval(action)
        if not claimed:
            self._raise_approval_conflict(action_id)

        approved_action = self._repository.get_approved_action(action_id)
        outbound = OutboundDealerMessage(
            action_id=approved_action.id,
            vehicle_id=approved_action.vehicle_id,
            dealer_id=approved_action.dealer_id,
            recipient=approved_action.recipient,
            subject=approved_action.subject,
            body=approved_action.body,
        )

        try:
            receipt = await self._messaging_provider.send(outbound)
            if receipt.action_id != action_id:
                raise ValueError("Messaging provider returned a mismatched action ID.")
        except Exception as error:
            self._repository.mark_send_failed(action_id)
            raise OutreachSendError(action_id) from error

        self._repository.mark_sent(action_id, receipt)
        return self._get_proposal(action_id)

    def reject(self, action_id: str) -> OutreachProposal:
        action = self._get_action(action_id)
        if action.status == "REJECTED":
            return self._get_proposal(action_id)
        if not self._repository.reject(action):
            raise OutreachActionNotRejectableError(action_id)
        return self._get_proposal(action_id)

    def _raise_approval_conflict(self, action_id: str) -> None:
        status = self._get_action(action_id).status
        if status == "APPROVED":
            raise OutreachActionAlreadyApprovedError(action_id)
        if status == "SENT":
            raise OutreachActionAlreadySentError(action_id)
        if status == "SEND_FAILED":
            raise OutreachRetryRequiresNewProposalError(action_id)
        raise OutreachActionNotApprovableError(action_id)

    def _get_action(self, action_id: str) -> ProposedActionRecord:
        try:
            return self._repository.get_action(action_id)
        except OutreachRecordNotFoundError as error:
            raise OutreachProposalNotFoundError(action_id) from error

    def _get_proposal(self, action_id: str) -> OutreachProposal:
        try:
            return self._repository.get_proposal(
                action_id,
                INITIAL_QUOTE_REQUEST_LABELS,
            )
        except OutreachRecordNotFoundError as error:
            raise OutreachProposalNotFoundError(action_id) from error
