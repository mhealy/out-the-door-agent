from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.orm import Session

from app.agent.graph import AgentRunAdvancementFailedError, AgentWorkflowService
from app.domain.agent_run import AgentRun
from app.domain.approval import OutreachProposal
from app.domain.comparison import ComparedOffer, ComparisonResult
from app.domain.interaction import DealerInteraction
from app.domain.purchase import (
    PurchaseAttentionItem,
    PurchaseChildSummary,
    PurchaseDecisionStatus,
    PurchaseStatusCounts,
    PurchaseWorkflowStatus,
    PurchaseWorkspace,
)
from app.domain.vehicle import VehicleListing
from app.persistence.agent_runs import AgentRunNotFoundError, AgentRunRepository
from app.persistence.interactions import (
    InteractionRecordNotFoundError,
    InteractionRepository,
)
from app.persistence.outreach import OutreachRecordNotFoundError, OutreachRepository
from app.persistence.purchases import (
    PurchaseRecord,
    PurchaseRunRepository,
    PurchaseVehicleLink,
)
from app.providers.inventory import InventoryProvider
from app.services.offer_comparison import OfferComparisonService
from app.services.outreach import CandidateNotFoundError


class InvalidPurchaseSelectionError(ValueError):
    """The purchase does not contain two to five unique vehicle IDs."""


class PurchaseChildWorkflow(Protocol):
    async def create(
        self,
        vehicle_id: str,
        *,
        run_id: str | None = None,
    ) -> AgentRun: ...

    def get(self, run_id: str) -> AgentRun: ...

    async def resume(self, run_id: str) -> AgentRun: ...


class PurchaseOfferComparer(Protocol):
    async def compare(self, agent_run_ids: list[str]) -> ComparisonResult: ...


@dataclass(frozen=True)
class PurchaseChildSource:
    selection_index: int
    vehicle: VehicleListing
    agent_run: AgentRun | None
    initial_action: OutreachProposal | None = None
    current_action: OutreachProposal | None = None
    interaction: DealerInteraction | None = None
    creation_error_code: str | None = None


def _workflow_status(
    source: PurchaseChildSource,
    offer: ComparedOffer | None,
) -> tuple[PurchaseWorkflowStatus, str | None, bool]:
    run = source.agent_run
    action = source.current_action
    interaction = source.interaction

    if run is None or run.phase == "STARTING":
        return "RECOVERY_REQUIRED", None, True

    if run.phase == "DELIVERY_UNCONFIRMED":
        return "DELIVERY_UNCONFIRMED", action.id if action else None, False
    if run.phase == "RUN_REJECTED":
        return "RUN_REJECTED", None, False
    if run.phase == "RUN_FAILED":
        return "RUN_FAILED", None, False

    if action is not None:
        if action.status == "PENDING_APPROVAL":
            return "APPROVAL_REQUIRED", action.id, True
        if action.status == "APPROVED":
            return "DELIVERY_UNCONFIRMED", action.id, False
        if action.status == "REJECTED":
            return "RUN_REJECTED", None, False
        if action.status == "SEND_FAILED":
            return "RUN_FAILED", None, False
        if action.status == "SENT" and action.delivery is None:
            return "DELIVERY_UNCONFIRMED", action.id, False
        if action.status == "SENT" and action.action_type == "SEND_FOLLOWUP":
            return "WAITING_FOR_DEALER", None, True

    if interaction is not None:
        if interaction.analysis_status == "ANALYSIS_FAILED":
            return "ANALYSIS_FAILED", None, False
        if interaction.analysis_status in {
            "RESPONSE_RECEIVED",
            "ANALYSIS_IN_PROGRESS",
        }:
            return "WAITING_FOR_ANALYSIS", None, True

    if offer is not None and offer.comparison_status == "VERIFIED":
        return "OFFER_VERIFIED", None, False

    if interaction is not None:
        if interaction.analysis_status == "AWAITING_RESPONSE":
            return "WAITING_FOR_DEALER", None, True
        if interaction.analysis_status == "ANALYZED":
            active = (
                run.phase != "INTERACTION_INCOMPLETE_MAX_FOLLOWUPS"
                and not interaction.followup_limit_reached
            )
            return "OFFER_INCOMPLETE", None, active

    if run.phase == "WAITING_FOR_ANALYSIS":
        return "WAITING_FOR_ANALYSIS", None, True
    if run.phase == "ANALYSIS_FAILED":
        return "ANALYSIS_FAILED", None, False
    if run.phase == "INTERACTION_INCOMPLETE_MAX_FOLLOWUPS":
        return "OFFER_INCOMPLETE", None, False
    if run.phase == "INTERACTION_COMPLETE":
        return "OFFER_INCOMPLETE", None, False
    return "WAITING_FOR_DEALER", None, True


_ATTENTION_MESSAGES: dict[PurchaseWorkflowStatus, str] = {
    "RECOVERY_REQUIRED": "workflow setup needs recovery.",
    "APPROVAL_REQUIRED": "has an exact dealer message awaiting approval.",
    "DELIVERY_UNCONFIRMED": "has an approved message with unconfirmed delivery.",
    "WAITING_FOR_DEALER": "is waiting for a dealer response.",
    "WAITING_FOR_ANALYSIS": "has a dealer response waiting for analysis.",
    "ANALYSIS_FAILED": "has a preserved response whose analysis failed.",
    "OFFER_INCOMPLETE": "has an incomplete offer with unresolved information.",
    "OFFER_VERIFIED": "has a verified offer.",
    "RUN_FAILED": "workflow failed without claiming success.",
    "RUN_REJECTED": "workflow stopped after the exact action was rejected.",
}


def derive_purchase_workspace(
    *,
    purchase_id: str,
    goal: str,
    children: list[PurchaseChildSource],
    comparison: ComparisonResult | None,
    created_at: datetime,
    updated_at: datetime,
) -> PurchaseWorkspace:
    """Derive a purchase read model without mutating workflow or economic state."""

    ordered_sources = sorted(
        children,
        key=lambda child: (child.selection_index, child.vehicle.id),
    )
    offer_by_run_id = {
        offer.agent_run_id: offer
        for offer in comparison.offers
    } if comparison is not None else {}

    summaries: list[PurchaseChildSummary] = []
    attention: list[PurchaseAttentionItem] = []
    for source in ordered_sources:
        run = source.agent_run
        offer = offer_by_run_id.get(run.id) if run is not None else None
        status, action_id, active = _workflow_status(source, offer)
        summary = PurchaseChildSummary(
            vehicle=source.vehicle,
            agent_run=run,
            workflow_status=status,
            comparison_status=(offer.comparison_status if offer is not None else None),
            action_id=action_id,
            creation_error_code=(
                source.creation_error_code if status == "RECOVERY_REQUIRED" else None
            ),
            active_unresolved=active,
        )
        summaries.append(summary)
        if status != "OFFER_VERIFIED":
            attention.append(
                PurchaseAttentionItem(
                    category=status,
                    vehicle_id=source.vehicle.id,
                    dealer_name=source.vehicle.dealer_name,
                    agent_run_id=run.id if run is not None else None,
                    action_id=action_id,
                    message=(
                        f"{source.vehicle.dealer_name} "
                        f"{_ATTENTION_MESSAGES[status]}"
                    ),
                    requires_buyer_action=status in {
                        "RECOVERY_REQUIRED",
                        "APPROVAL_REQUIRED",
                        "DELIVERY_UNCONFIRMED",
                        "ANALYSIS_FAILED",
                    },
                )
            )

    offers = comparison.offers if comparison is not None else []
    counts = PurchaseStatusCounts(
        selected_vehicles=len(ordered_sources),
        linked_children=sum(source.agent_run is not None for source in ordered_sources),
        quote_requests_prepared=sum(
            source.initial_action is not None for source in ordered_sources
        ),
        responses_analyzed=sum(
            source.interaction is not None
            and source.interaction.analysis_status == "ANALYZED"
            for source in ordered_sources
        ),
        verified_offers=sum(
            offer.comparison_status == "VERIFIED" and offer.eligible
            for offer in offers
        ),
        incomplete_offers=sum(
            offer.comparison_status == "INCOMPLETE" for offer in offers
        ),
        pending_approvals=sum(
            source.current_action is not None
            and source.current_action.status == "PENDING_APPROVAL"
            for source in ordered_sources
        ),
    )
    setup_status = (
        "RECOVERY_REQUIRED"
        if any(summary.workflow_status == "RECOVERY_REQUIRED" for summary in summaries)
        else "READY"
    )
    if counts.verified_offers == 0:
        decision_status: PurchaseDecisionStatus = "GATHERING_OFFERS"
    elif (
        counts.verified_offers < 2
        or setup_status == "RECOVERY_REQUIRED"
        or any(summary.active_unresolved for summary in summaries)
    ):
        decision_status = "COMPARISON_AVAILABLE"
    else:
        decision_status = "DECISION_READY"

    return PurchaseWorkspace(
        id=purchase_id,
        goal=goal,
        setup_status=setup_status,
        selected_vehicle_ids=[source.vehicle.id for source in ordered_sources],
        children=summaries,
        counts=counts,
        attention_items=attention,
        comparison=comparison,
        decision_status=decision_status,
        created_at=created_at,
        updated_at=updated_at,
    )


def _reserved_child_run_id(purchase_id: str, vehicle_id: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"out-the-door-agent:purchase:{purchase_id}:vehicle:{vehicle_id}",
        )
    )


def _error_code(error: Exception) -> str:
    name = type(error).__name__
    return "".join(
        (f"_{character.casefold()}" if character.isupper() else character)
        for character in name
    ).lstrip("_")


class PurchaseWorkspaceService:
    """Coordinate durable child setup and derive the current purchase workspace."""

    def __init__(
        self,
        *,
        session: Session,
        inventory_provider: InventoryProvider,
        workflow_service: PurchaseChildWorkflow,
        comparison_service: PurchaseOfferComparer,
    ) -> None:
        self._session = session
        self._inventory = inventory_provider
        self._workflow = workflow_service
        self._comparison = comparison_service
        self._purchases = PurchaseRunRepository(session)

    async def create(
        self,
        *,
        creation_id: str,
        goal: str,
        vehicle_ids: list[str],
    ) -> PurchaseWorkspace:
        goal = goal.strip()
        vehicle_ids = [vehicle_id.strip() for vehicle_id in vehicle_ids]
        self._validate_selection(vehicle_ids)
        purchase = self._purchases.find_existing_creation(
            creation_id,
            goal=goal,
            vehicle_ids=vehicle_ids,
        )
        if purchase is None:
            for vehicle_id in vehicle_ids:
                if await self._inventory.get_by_id(vehicle_id) is None:
                    raise CandidateNotFoundError(vehicle_id)
            purchase = self._purchases.create(
                creation_id=creation_id,
                goal=goal,
                vehicle_ids=vehicle_ids,
            )
        await self._recover_setup(purchase)
        return await self.get(purchase.id)

    async def get(self, purchase_id: str) -> PurchaseWorkspace:
        purchase = self._purchases.get(purchase_id)
        links = self._purchases.list_vehicle_links(purchase_id)
        run_repository = AgentRunRepository(self._session)
        outreach = OutreachRepository(self._session)
        interactions = InteractionRepository(self._session)

        vehicles: list[VehicleListing] = []
        runs: list[AgentRun | None] = []
        for link in links:
            vehicle = await self._inventory.get_by_id(link.vehicle_id)
            if vehicle is None:
                raise CandidateNotFoundError(link.vehicle_id)
            vehicles.append(vehicle)
            runs.append(
                run_repository.get(link.agent_run_id)
                if link.agent_run_id is not None
                else None
            )

        linked_ids = [run.id for run in runs if run is not None]
        comparison = (
            await self._comparison.compare(linked_ids)
            if linked_ids
            else None
        )

        child_sources: list[PurchaseChildSource] = []
        for link, vehicle, run in zip(links, vehicles, runs, strict=True):
            initial_action = None
            current_action = None
            interaction = None
            if run is not None:
                try:
                    initial_action = outreach.get_proposal(run.initial_action_id)
                except OutreachRecordNotFoundError:
                    initial_action = None
                try:
                    interaction = interactions.get(run.initial_action_id)
                except InteractionRecordNotFoundError:
                    interaction = None

                current_action_id = self._authoritative_action_id(
                    run,
                    interaction,
                )
                if current_action_id is not None:
                    try:
                        current_action = outreach.get_proposal(current_action_id)
                    except OutreachRecordNotFoundError:
                        current_action = initial_action
            child_sources.append(
                PurchaseChildSource(
                    selection_index=link.position,
                    vehicle=vehicle,
                    agent_run=run,
                    initial_action=initial_action,
                    current_action=current_action,
                    interaction=interaction,
                    creation_error_code=link.last_creation_error,
                )
            )

        updated_at = max(
            [
                purchase.created_at,
                *(link.updated_at for link in links),
                *(run.updated_at for run in runs if run is not None),
            ]
        )
        return derive_purchase_workspace(
            purchase_id=purchase.id,
            goal=purchase.goal,
            children=child_sources,
            comparison=comparison,
            created_at=purchase.created_at,
            updated_at=updated_at,
        )

    async def recover(self, purchase_id: str) -> PurchaseWorkspace:
        purchase = self._purchases.get(purchase_id)
        await self._recover_setup(purchase)
        return await self.get(purchase_id)

    async def _recover_setup(self, purchase: PurchaseRecord) -> None:
        for link in self._purchases.list_vehicle_links(purchase.id):
            if link.agent_run_id is None:
                await self._create_missing_child(purchase, link)
                continue

            try:
                run = self._workflow.get(link.agent_run_id)
            except AgentRunNotFoundError as error:
                self._purchases.record_creation_error(
                    purchase.id,
                    link.vehicle_id,
                    _error_code(error),
                )
                continue
            if run.phase != "STARTING":
                self._purchases.clear_creation_error(
                    purchase.id,
                    link.vehicle_id,
                )
                continue
            try:
                resumed = await self._workflow.resume(run.id)
            except Exception as error:
                self._purchases.record_advancement_error_if_starting(
                    purchase.id,
                    link.vehicle_id,
                    run.id,
                    _error_code(error),
                )
            else:
                if resumed.phase == "STARTING":
                    self._purchases.record_advancement_error_if_starting(
                        purchase.id,
                        link.vehicle_id,
                        resumed.id,
                        "agent_run_advancement_failed",
                    )
                else:
                    self._purchases.clear_creation_error(
                        purchase.id,
                        link.vehicle_id,
                    )

    async def _create_missing_child(
        self,
        purchase: PurchaseRecord,
        link: PurchaseVehicleLink,
    ) -> None:
        reserved_id = _reserved_child_run_id(purchase.id, link.vehicle_id)
        try:
            run = await self._workflow.create(
                link.vehicle_id,
                run_id=reserved_id,
            )
        except AgentRunAdvancementFailedError as error:
            try:
                run = self._workflow.get(error.run_id)
                self._purchases.attach_agent_run(
                    purchase.id,
                    link.vehicle_id,
                    run.id,
                )
            except Exception as adoption_error:
                self._purchases.record_creation_error(
                    purchase.id,
                    link.vehicle_id,
                    _error_code(adoption_error),
                )
                return
            if run.phase == "STARTING":
                self._purchases.record_advancement_error_if_starting(
                    purchase.id,
                    link.vehicle_id,
                    run.id,
                    "agent_run_advancement_failed",
                )
            else:
                self._purchases.clear_creation_error(
                    purchase.id,
                    link.vehicle_id,
                )
            return
        except Exception as error:
            self._purchases.record_creation_error(
                purchase.id,
                link.vehicle_id,
                _error_code(error),
            )
            return

        self._purchases.attach_agent_run(
            purchase.id,
            link.vehicle_id,
            run.id,
        )
        if run.phase == "STARTING":
            self._purchases.record_advancement_error_if_starting(
                purchase.id,
                link.vehicle_id,
                run.id,
                "agent_run_advancement_failed",
            )
        else:
            self._purchases.clear_creation_error(
                purchase.id,
                link.vehicle_id,
            )

    @staticmethod
    def _authoritative_action_id(
        run: AgentRun,
        interaction: DealerInteraction | None,
    ) -> str | None:
        if interaction is not None:
            if interaction.latest_response_followup_attempt_id is not None:
                return interaction.latest_response_followup_attempt_id
            return run.initial_action_id
        return run.current_action_id or run.initial_action_id

    @staticmethod
    def _validate_selection(vehicle_ids: list[str]) -> None:
        if (
            len(vehicle_ids) < 2
            or len(vehicle_ids) > 5
            or len(vehicle_ids) != len(set(vehicle_ids))
            or any(not vehicle_id.strip() for vehicle_id in vehicle_ids)
        ):
            raise InvalidPurchaseSelectionError(
                "A purchase requires two to five unique vehicle IDs."
            )


def build_purchase_workspace_service(
    *,
    session: Session,
    inventory_provider: InventoryProvider,
    workflow_service: AgentWorkflowService,
) -> PurchaseWorkspaceService:
    return PurchaseWorkspaceService(
        session=session,
        inventory_provider=inventory_provider,
        workflow_service=workflow_service,
        comparison_service=OfferComparisonService(
            session=session,
            inventory_provider=inventory_provider,
        ),
    )
