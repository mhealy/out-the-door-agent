from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.agent.state import BuyerAgentState, GraphRoute
from app.domain.agent_run import AgentRun, RunPhase
from app.domain.approval import OutreachProposal
from app.domain.interaction import DealerInteraction
from app.persistence.agent_runs import AgentRunRepository, NewAgentEvent
from app.providers.dealer_contacts import (
    DealerContactNotFoundError,
    DealerContactResolver,
)
from app.providers.dealer_messages import DealerMessageProvider
from app.providers.followup_drafting import (
    FollowupDrafter,
    FollowupDrafterUnavailableError,
    FollowupDraftingError,
)
from app.providers.inventory import InventoryProvider
from app.providers.messaging import MessagingProvider
from app.providers.quote_extraction import QuoteExtractor
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
from app.services.outreach import (
    CandidateNotFoundError,
    OutreachProposalNotFoundError,
    OutreachService,
)
from app.services.outreach_interactions import (
    OutreachInteractionNotFoundError,
    OutreachInteractionService,
)


class AgentRunAdvancementFailedError(RuntimeError):
    """A durable run exists, but its create-time graph invocation failed."""

    def __init__(self, run_id: str) -> None:
        super().__init__(run_id)
        self.run_id = run_id


class AgentGraphContext:
    """Request-scoped application capabilities used by graph nodes."""

    def __init__(
        self,
        *,
        session: Session,
        inventory_provider: InventoryProvider,
        dealer_contact_resolver: DealerContactResolver,
        messaging_provider: MessagingProvider,
        message_provider: DealerMessageProvider,
        quote_extractor: QuoteExtractor,
        followup_drafter: FollowupDrafter,
    ) -> None:
        self.runs = AgentRunRepository(session)
        self.outreach = OutreachService(
            session=session,
            inventory_provider=inventory_provider,
            dealer_contact_resolver=dealer_contact_resolver,
            messaging_provider=messaging_provider,
        )
        self.interactions = OutreachInteractionService(
            session=session,
            message_provider=message_provider,
            quote_extractor=quote_extractor,
            inventory_provider=inventory_provider,
        )
        self.followups = FollowupService(
            session=session,
            dealer_contact_resolver=dealer_contact_resolver,
            drafter=followup_drafter,
        )


def _state_from_run(run: AgentRun, route: GraphRoute) -> BuyerAgentState:
    last_event = run.events[-1] if run.events else None
    return {
        "run_id": run.id,
        "phase": run.phase,
        "vehicle_id": run.vehicle_id,
        "initial_action_id": run.initial_action_id,
        "current_action_id": run.current_action_id,
        "interaction_id": run.interaction_id,
        "last_message_id": run.last_message_id,
        "last_event_type": last_event.event_type if last_event else None,
        "last_event_id": last_event.id if last_event else None,
        "error_code": run.error_code,
        "route": route,
    }


def _route(state: BuyerAgentState) -> GraphRoute:
    return state["route"]


def _response_analyzed_event(
    interaction: DealerInteraction,
) -> NewAgentEvent:
    message_id = interaction.analysis.message.id if interaction.analysis else None
    return NewAgentEvent(
        semantic_key=f"response-analyzed:{message_id}",
        event_type="RESPONSE_ANALYZED",
        message=(
            "Dealer response analyzed against deterministic quote policy."
        ),
        interaction_id=interaction.id,
        message_id=message_id,
    )


def _stale_event(
    action_id: str,
    interaction: DealerInteraction,
) -> NewAgentEvent:
    message_id = interaction.analysis.message.id if interaction.analysis else None
    return NewAgentEvent(
        semantic_key=f"followup-stale:{action_id}:{message_id}",
        event_type="FOLLOWUP_STALE",
        message=(
            "An earlier follow-up was superseded by a newer analyzed dealer "
            "response."
        ),
        action_id=action_id,
        interaction_id=interaction.id,
        message_id=message_id,
        metadata={"reason_code": "followup_source_changed"},
    )


def _confirmed_send_events(
    initial: OutreachProposal,
    current: OutreachProposal,
    interaction: DealerInteraction,
) -> list[NewAgentEvent]:
    proposals = [initial]
    if current.id != initial.id:
        proposals.append(current)

    events: list[NewAgentEvent] = []
    for proposal in proposals:
        if proposal.status != "SENT" or proposal.delivery is None:
            continue
        is_followup = proposal.action_type == "SEND_FOLLOWUP"
        events.append(
            NewAgentEvent(
                semantic_key=f"action-sent:{proposal.id}",
                event_type="FOLLOWUP_SENT" if is_followup else "OUTREACH_SENT",
                message=(
                    "Dealer follow-up delivery was confirmed."
                    if is_followup
                    else "Quote request delivery was confirmed."
                ),
                action_id=proposal.id,
                interaction_id=interaction.id,
            )
        )
    return events


def _followup_preparation_failed(
    context: AgentGraphContext,
    run: AgentRun,
    interaction: DealerInteraction,
    message_id: str | None,
    error: Exception,
) -> BuyerAgentState:
    failed = context.runs.transition(
        run.id,
        phase="RUN_FAILED",
        node="prepare_followup_if_needed",
        events=[
            NewAgentEvent(
                semantic_key=(
                    f"run-failed:followup:{message_id}:"
                    f"{type(error).__name__}"
                ),
                event_type="RUN_FAILED",
                message="The required dealer follow-up could not be prepared.",
                interaction_id=interaction.id,
                message_id=message_id,
                metadata={"reason_code": type(error).__name__},
            )
        ],
        interaction_id=interaction.id,
        last_message_id=message_id,
        error_code=type(error).__name__,
    )
    return _state_from_run(failed, "end")


def _stop_followup(
    context: AgentGraphContext,
    run: AgentRun,
    proposal: OutreachProposal,
    interaction: DealerInteraction,
    message_id: str | None,
    base_events: list[NewAgentEvent],
) -> BuyerAgentState:
    rejected = proposal.status == "REJECTED"
    terminal_phase: RunPhase = "RUN_REJECTED" if rejected else "RUN_FAILED"
    terminal_type = "RUN_REJECTED" if rejected else "RUN_FAILED"
    stopped = context.runs.transition(
        run.id,
        phase=terminal_phase,
        node="observe_authoritative_state",
        events=[
            *base_events,
            NewAgentEvent(
                semantic_key=f"{terminal_type.casefold()}:{proposal.id}",
                event_type=terminal_type,
                message=(
                    "The proposed dealer follow-up was rejected."
                    if rejected
                    else "Dealer follow-up delivery failed and was not retried."
                ),
                action_id=proposal.id,
                interaction_id=interaction.id,
                metadata={"reason_code": proposal.status.casefold()},
            ),
        ],
        current_action_id=proposal.id,
        interaction_id=interaction.id,
        last_message_id=message_id,
        error_code=None if rejected else "send_failed",
    )
    return _state_from_run(stopped, "end")


def build_agent_graph(
    context: AgentGraphContext,
    checkpointer: AsyncSqliteSaver,
) -> Any:
    """Compile one coarse, capability-oriented dealer workflow graph."""

    async def load_run_context(state: BuyerAgentState) -> BuyerAgentState:
        run = context.runs.get(state["run_id"])
        try:
            context.outreach.get(run.initial_action_id)
        except OutreachProposalNotFoundError:
            route: GraphRoute = "prepare_initial_outreach"
        else:
            route = "observe_authoritative_state"
        return _state_from_run(run, route)

    async def prepare_initial_outreach(
        state: BuyerAgentState,
    ) -> BuyerAgentState:
        run = context.runs.get(state["run_id"])
        try:
            proposal = await context.outreach.prepare(
                run.vehicle_id,
                action_id=run.initial_action_id,
            )
        except (CandidateNotFoundError, DealerContactNotFoundError) as error:
            failed = context.runs.transition(
                run.id,
                phase="RUN_FAILED",
                node="prepare_initial_outreach",
                events=[
                    NewAgentEvent(
                        semantic_key=f"run-failed:initial:{type(error).__name__}",
                        event_type="RUN_FAILED",
                        message="The initial quote request could not be prepared.",
                        action_id=run.initial_action_id,
                        metadata={"reason_code": type(error).__name__},
                    )
                ],
                error_code=type(error).__name__,
            )
            return _state_from_run(failed, "end")

        waiting = context.runs.transition(
            run.id,
            phase="WAITING_FOR_APPROVAL",
            node="prepare_initial_outreach",
            events=[
                NewAgentEvent(
                    semantic_key=f"initial-outreach-prepared:{proposal.id}",
                    event_type="INITIAL_OUTREACH_PREPARED",
                    message="Quote request prepared for review.",
                    action_id=proposal.id,
                ),
                NewAgentEvent(
                    semantic_key=f"waiting-for-approval:{proposal.id}",
                    event_type="WAITING_FOR_APPROVAL",
                    message="Waiting for explicit approval before sending.",
                    action_id=proposal.id,
                ),
            ],
            current_action_id=proposal.id,
            error_code=None,
        )
        return _state_from_run(waiting, "end")

    async def observe_authoritative_state(
        state: BuyerAgentState,
    ) -> BuyerAgentState:
        run = context.runs.get(state["run_id"])
        try:
            initial = context.outreach.get(run.initial_action_id)
        except OutreachProposalNotFoundError:
            return _state_from_run(run, "prepare_initial_outreach")

        if initial.status != "SENT":
            return _observe_initial_action(context, run, initial)
        if initial.delivery is None:
            return _delivery_unconfirmed(context, run, initial)

        current = initial
        if run.current_action_id and run.current_action_id != initial.id:
            try:
                current = context.outreach.get(run.current_action_id)
            except OutreachProposalNotFoundError:
                current = initial

        try:
            interaction = context.interactions.get(initial.id)
        except OutreachInteractionNotFoundError:
            failed = context.runs.transition(
                run.id,
                phase="RUN_FAILED",
                node="observe_authoritative_state",
                events=[
                    NewAgentEvent(
                        semantic_key=f"run-failed:interaction-missing:{initial.id}",
                        event_type="RUN_FAILED",
                        message=(
                            "Confirmed outreach has no durable dealer interaction."
                        ),
                        action_id=initial.id,
                        metadata={"reason_code": "interaction_missing"},
                    )
                ],
                error_code="interaction_missing",
            )
            return _state_from_run(failed, "end")
        return _observe_interaction(context, run, initial, current, interaction)

    async def prepare_followup_if_needed(
        state: BuyerAgentState,
    ) -> BuyerAgentState:
        run = context.runs.get(state["run_id"])
        try:
            interaction = context.interactions.get(run.initial_action_id)
        except OutreachInteractionNotFoundError:
            return _state_from_run(run, "observe_authoritative_state")
        message_id = (
            interaction.analysis.message.id if interaction.analysis else None
        )
        try:
            proposal = await context.followups.prepare(run.initial_action_id)
        except (
            FollowupSourceChangedError,
            FollowupSourceMessageBlockedError,
            FollowupNotAvailableError,
        ):
            refreshed = context.runs.get(run.id)
            return _state_from_run(refreshed, "observe_authoritative_state")
        except FollowupNotRequiredError as error:
            refreshed_interaction = context.interactions.get(
                run.initial_action_id
            )
            refreshed_message_id = (
                refreshed_interaction.analysis.message.id
                if refreshed_interaction.analysis
                else None
            )
            if (
                refreshed_interaction.analysis_status != "ANALYZED"
                or refreshed_message_id != message_id
                or (
                    refreshed_interaction.analysis is not None
                    and refreshed_interaction.analysis.assessment.comparable
                )
            ):
                refreshed = context.runs.get(run.id)
                return _state_from_run(
                    refreshed,
                    "observe_authoritative_state",
                )
            return _followup_preparation_failed(
                context,
                run,
                interaction,
                message_id,
                error,
            )
        except FollowupLimitReachedError:
            exhausted = context.runs.transition(
                run.id,
                phase="INTERACTION_INCOMPLETE_MAX_FOLLOWUPS",
                node="prepare_followup_if_needed",
                events=[
                    NewAgentEvent(
                        semantic_key=f"max-followups:{interaction.id}:{message_id}",
                        event_type="MAX_FOLLOWUPS_REACHED",
                        message=(
                            "The offer remains incomplete after two confirmed "
                            "follow-ups."
                        ),
                        interaction_id=interaction.id,
                        message_id=message_id,
                    )
                ],
                interaction_id=interaction.id,
                last_message_id=message_id,
                error_code=None,
            )
            return _state_from_run(exhausted, "end")
        except (
            DealerContactNotFoundError,
            FollowupRecipientChangedError,
            UnsupportedFollowupRequirementError,
            FollowupDrafterUnavailableError,
            FollowupDraftingError,
            FollowupDraftValidationError,
        ) as error:
            return _followup_preparation_failed(
                context,
                run,
                interaction,
                message_id,
                error,
            )

        waiting = context.runs.transition(
            run.id,
            phase="WAITING_FOR_APPROVAL",
            node="prepare_followup_if_needed",
            events=[
                NewAgentEvent(
                    semantic_key=f"followup-prepared:{proposal.id}",
                    event_type="FOLLOWUP_PREPARED",
                    message="Dealer follow-up prepared for review.",
                    action_id=proposal.id,
                    interaction_id=interaction.id,
                    message_id=message_id,
                ),
                NewAgentEvent(
                    semantic_key=f"waiting-for-approval:{proposal.id}",
                    event_type="WAITING_FOR_APPROVAL",
                    message="Waiting for explicit approval before sending.",
                    action_id=proposal.id,
                    interaction_id=interaction.id,
                    message_id=message_id,
                ),
            ],
            current_action_id=proposal.id,
            interaction_id=interaction.id,
            last_message_id=message_id,
            error_code=None,
        )
        return _state_from_run(waiting, "end")

    builder = StateGraph(BuyerAgentState)
    builder.add_node("load_run_context", load_run_context)
    builder.add_node("prepare_initial_outreach", prepare_initial_outreach)
    builder.add_node("observe_authoritative_state", observe_authoritative_state)
    builder.add_node("prepare_followup_if_needed", prepare_followup_if_needed)
    builder.add_edge(START, "load_run_context")
    route_map = {
        "prepare_initial_outreach": "prepare_initial_outreach",
        "observe_authoritative_state": "observe_authoritative_state",
        "prepare_followup_if_needed": "prepare_followup_if_needed",
        "end": END,
    }
    builder.add_conditional_edges("load_run_context", _route, route_map)
    builder.add_conditional_edges("prepare_initial_outreach", _route, route_map)
    builder.add_conditional_edges(
        "observe_authoritative_state",
        _route,
        route_map,
    )
    builder.add_conditional_edges(
        "prepare_followup_if_needed",
        _route,
        route_map,
    )
    return builder.compile(checkpointer=checkpointer)


def _observe_initial_action(
    context: AgentGraphContext,
    run: AgentRun,
    proposal: OutreachProposal,
) -> BuyerAgentState:
    if proposal.status == "PENDING_APPROVAL":
        waiting = context.runs.transition(
            run.id,
            phase="WAITING_FOR_APPROVAL",
            node="observe_authoritative_state",
            events=[
                NewAgentEvent(
                    semantic_key=f"initial-outreach-prepared:{proposal.id}",
                    event_type="INITIAL_OUTREACH_PREPARED",
                    message="Quote request prepared for review.",
                    action_id=proposal.id,
                ),
                NewAgentEvent(
                    semantic_key=f"waiting-for-approval:{proposal.id}",
                    event_type="WAITING_FOR_APPROVAL",
                    message="Waiting for explicit approval before sending.",
                    action_id=proposal.id,
                ),
            ],
            current_action_id=proposal.id,
            error_code=None,
        )
        return _state_from_run(waiting, "end")
    if proposal.status == "APPROVED":
        return _delivery_unconfirmed(context, run, proposal)
    if proposal.status == "REJECTED":
        rejected = context.runs.transition(
            run.id,
            phase="RUN_REJECTED",
            node="observe_authoritative_state",
            events=[
                NewAgentEvent(
                    semantic_key=f"run-rejected:{proposal.id}",
                    event_type="RUN_REJECTED",
                    message="The proposed dealer message was rejected.",
                    action_id=proposal.id,
                )
            ],
            current_action_id=proposal.id,
            error_code=None,
        )
        return _state_from_run(rejected, "end")
    failed = context.runs.transition(
        run.id,
        phase="RUN_FAILED",
        node="observe_authoritative_state",
        events=[
            NewAgentEvent(
                semantic_key=f"run-failed:send:{proposal.id}",
                event_type="RUN_FAILED",
                message="Dealer-message delivery failed and was not retried.",
                action_id=proposal.id,
                metadata={"reason_code": "send_failed"},
            )
        ],
        current_action_id=proposal.id,
        error_code="send_failed",
    )
    return _state_from_run(failed, "end")


def _delivery_unconfirmed(
    context: AgentGraphContext,
    run: AgentRun,
    proposal: OutreachProposal,
    *,
    interaction_id: str | None = None,
    message_id: str | None = None,
    prior_events: list[NewAgentEvent] | None = None,
) -> BuyerAgentState:
    authoritative_interaction_id = interaction_id or run.interaction_id
    authoritative_message_id = message_id or run.last_message_id
    blocked = context.runs.transition(
        run.id,
        phase="DELIVERY_UNCONFIRMED",
        node="observe_authoritative_state",
        events=[
            *(prior_events or []),
            NewAgentEvent(
                semantic_key=f"delivery-unconfirmed:{proposal.id}",
                event_type="DELIVERY_UNCONFIRMED",
                message=(
                    "Approval was recorded, but dealer-message delivery is "
                    "unconfirmed."
                ),
                action_id=proposal.id,
                interaction_id=authoritative_interaction_id,
                message_id=authoritative_message_id,
                metadata={"reason_code": "delivery_unconfirmed"},
            )
        ],
        current_action_id=proposal.id,
        interaction_id=authoritative_interaction_id,
        last_message_id=authoritative_message_id,
        error_code="delivery_unconfirmed",
    )
    return _state_from_run(blocked, "end")


def _observe_interaction(
    context: AgentGraphContext,
    run: AgentRun,
    initial: OutreachProposal,
    current: OutreachProposal,
    interaction: DealerInteraction,
) -> BuyerAgentState:
    message_id = interaction.messages[-1].id if interaction.messages else None
    sent_events = _confirmed_send_events(initial, current, interaction)
    observed_events = list(sent_events)
    if interaction.analysis_status == "ANALYZED" and interaction.analysis:
        observed_events.append(_response_analyzed_event(interaction))

    ambiguous = next(
        (
            proposal
            for proposal in interaction.followups
            if proposal.status in {"APPROVED", "SENT"}
            and proposal.delivery is None
        ),
        None,
    )
    if ambiguous is not None:
        return _delivery_unconfirmed(
            context,
            run,
            ambiguous,
            interaction_id=interaction.id,
            message_id=message_id,
            prior_events=observed_events,
        )

    if interaction.analysis_status == "AWAITING_RESPONSE":
        last_confirmed = (
            current
            if current.status == "SENT" and current.delivery is not None
            else initial
        )
        waiting = context.runs.transition(
            run.id,
            phase="WAITING_FOR_EXTERNAL_RESPONSE",
            node="observe_authoritative_state",
            events=[
                *sent_events,
                NewAgentEvent(
                    semantic_key=f"waiting-for-response:{last_confirmed.id}",
                    event_type="WAITING_FOR_EXTERNAL_RESPONSE",
                    message="Waiting for a dealer response.",
                    action_id=last_confirmed.id,
                    interaction_id=interaction.id,
                ),
            ],
            current_action_id=last_confirmed.id,
            interaction_id=interaction.id,
            last_message_id=None,
            error_code=None,
        )
        return _state_from_run(waiting, "end")

    if interaction.analysis_status in {
        "RESPONSE_RECEIVED",
        "ANALYSIS_IN_PROGRESS",
    }:
        waiting = context.runs.transition(
            run.id,
            phase="WAITING_FOR_ANALYSIS",
            node="observe_authoritative_state",
            events=[
                *sent_events,
                NewAgentEvent(
                    semantic_key=f"waiting-for-analysis:{message_id}",
                    event_type="WAITING_FOR_ANALYSIS",
                    message="Dealer response is waiting for authoritative analysis.",
                    interaction_id=interaction.id,
                    message_id=message_id,
                )
            ],
            interaction_id=interaction.id,
            last_message_id=message_id,
            error_code=None,
        )
        return _state_from_run(waiting, "end")

    if interaction.analysis_status == "ANALYSIS_FAILED":
        error_code = interaction.analysis_error_code or "quote_extraction_failed"
        failed = context.runs.transition(
            run.id,
            phase="ANALYSIS_FAILED",
            node="observe_authoritative_state",
            events=[
                *sent_events,
                NewAgentEvent(
                    semantic_key=f"analysis-failed:{message_id}:{error_code}",
                    event_type="ANALYSIS_FAILED",
                    message=(
                        "Dealer response analysis failed; the raw response remains "
                        "available for an application-owned retry."
                    ),
                    interaction_id=interaction.id,
                    message_id=message_id,
                    metadata={"reason_code": error_code},
                )
            ],
            interaction_id=interaction.id,
            last_message_id=message_id,
            error_code=error_code,
        )
        return _state_from_run(failed, "end")

    if interaction.analysis is None:
        failed = context.runs.transition(
            run.id,
            phase="RUN_FAILED",
            node="observe_authoritative_state",
            events=[
                *sent_events,
                NewAgentEvent(
                    semantic_key=f"run-failed:analysis-missing:{message_id}",
                    event_type="RUN_FAILED",
                    message="Analyzed response has no persisted quote assessment.",
                    interaction_id=interaction.id,
                    message_id=message_id,
                    metadata={"reason_code": "analysis_snapshot_missing"},
                )
            ],
            interaction_id=interaction.id,
            last_message_id=message_id,
            error_code="analysis_snapshot_missing",
        )
        return _state_from_run(failed, "end")

    base_events = observed_events
    attempt_id = interaction.latest_response_followup_attempt_id
    attempt_status = interaction.latest_response_followup_attempt_status
    if (
        current.action_type == "SEND_FOLLOWUP"
        and current.status == "PENDING_APPROVAL"
        and current.id != attempt_id
    ):
        base_events.append(_stale_event(current.id, interaction))

    if interaction.analysis.assessment.comparable:
        completed = context.runs.transition(
            run.id,
            phase="INTERACTION_COMPLETE",
            node="observe_authoritative_state",
            events=[
                *base_events,
                NewAgentEvent(
                    semantic_key=f"interaction-complete:{interaction.id}:{message_id}",
                    event_type="INTERACTION_COMPLETE",
                    message="The dealer offer is comparable.",
                    interaction_id=interaction.id,
                    message_id=message_id,
                ),
            ],
            interaction_id=interaction.id,
            last_message_id=message_id,
            error_code=None,
        )
        return _state_from_run(completed, "end")

    if attempt_id is not None and attempt_status is not None:
        attempt = context.outreach.get(attempt_id)
        if attempt_status == "PENDING_APPROVAL":
            waiting = context.runs.transition(
                run.id,
                phase="WAITING_FOR_APPROVAL",
                node="observe_authoritative_state",
                events=[
                    *base_events,
                    NewAgentEvent(
                        semantic_key=f"followup-prepared:{attempt.id}",
                        event_type="FOLLOWUP_PREPARED",
                        message="Dealer follow-up prepared for review.",
                        action_id=attempt.id,
                        interaction_id=interaction.id,
                        message_id=message_id,
                    ),
                    NewAgentEvent(
                        semantic_key=f"waiting-for-approval:{attempt.id}",
                        event_type="WAITING_FOR_APPROVAL",
                        message="Waiting for explicit approval before sending.",
                        action_id=attempt.id,
                        interaction_id=interaction.id,
                        message_id=message_id,
                    ),
                ],
                current_action_id=attempt.id,
                interaction_id=interaction.id,
                last_message_id=message_id,
                error_code=None,
            )
            return _state_from_run(waiting, "end")
        if attempt_status == "APPROVED":
            return _delivery_unconfirmed(
                context,
                run,
                attempt,
                interaction_id=interaction.id,
                message_id=message_id,
                prior_events=base_events,
            )
        if attempt_status == "SENT":
            if attempt.delivery is None:
                return _delivery_unconfirmed(
                    context,
                    run,
                    attempt,
                    interaction_id=interaction.id,
                    message_id=message_id,
                    prior_events=base_events,
                )
            waiting = context.runs.transition(
                run.id,
                phase="WAITING_FOR_EXTERNAL_RESPONSE",
                node="observe_authoritative_state",
                events=[
                    *base_events,
                    NewAgentEvent(
                        semantic_key=f"action-sent:{attempt.id}",
                        event_type="FOLLOWUP_SENT",
                        message="Dealer follow-up delivery was confirmed.",
                        action_id=attempt.id,
                        interaction_id=interaction.id,
                        message_id=message_id,
                    ),
                    NewAgentEvent(
                        semantic_key=f"waiting-for-response:{attempt.id}",
                        event_type="WAITING_FOR_EXTERNAL_RESPONSE",
                        message="Waiting for a newer dealer response.",
                        action_id=attempt.id,
                        interaction_id=interaction.id,
                        message_id=message_id,
                    ),
                ],
                current_action_id=attempt.id,
                interaction_id=interaction.id,
                last_message_id=message_id,
                error_code=None,
            )
            return _state_from_run(waiting, "end")
        return _stop_followup(
            context,
            run,
            attempt,
            interaction,
            message_id,
            base_events,
        )

    if (
        current.action_type == "SEND_FOLLOWUP"
        and current.status in {"REJECTED", "SEND_FAILED"}
    ):
        return _stop_followup(
            context,
            run,
            current,
            interaction,
            message_id,
            base_events,
        )

    if interaction.followup_limit_reached:
        exhausted = context.runs.transition(
            run.id,
            phase="INTERACTION_INCOMPLETE_MAX_FOLLOWUPS",
            node="observe_authoritative_state",
            events=[
                *base_events,
                NewAgentEvent(
                    semantic_key=f"max-followups:{interaction.id}:{message_id}",
                    event_type="MAX_FOLLOWUPS_REACHED",
                    message=(
                        "The offer remains incomplete after two confirmed "
                        "follow-ups."
                    ),
                    interaction_id=interaction.id,
                    message_id=message_id,
                ),
            ],
            interaction_id=interaction.id,
            last_message_id=message_id,
            error_code=None,
        )
        return _state_from_run(exhausted, "end")

    observed = context.runs.transition(
        run.id,
        phase=run.phase,
        node="observe_authoritative_state",
        events=base_events,
        interaction_id=interaction.id,
        last_message_id=message_id,
        error_code=None,
    )
    return _state_from_run(observed, "prepare_followup_if_needed")


class AgentWorkflowService:
    """Run or explicitly reinvoke one durable LangGraph dealer interaction."""

    def __init__(
        self,
        *,
        session: Session,
        inventory_provider: InventoryProvider,
        dealer_contact_resolver: DealerContactResolver,
        messaging_provider: MessagingProvider,
        message_provider: DealerMessageProvider,
        quote_extractor: QuoteExtractor,
        followup_drafter: FollowupDrafter,
        checkpoint_path: Path,
    ) -> None:
        self._session = session
        self._inventory_provider = inventory_provider
        self._context = AgentGraphContext(
            session=session,
            inventory_provider=inventory_provider,
            dealer_contact_resolver=dealer_contact_resolver,
            messaging_provider=messaging_provider,
            message_provider=message_provider,
            quote_extractor=quote_extractor,
            followup_drafter=followup_drafter,
        )
        self._checkpoint_path = checkpoint_path

    async def create(self, vehicle_id: str) -> AgentRun:
        vehicle = await self._inventory_provider.get_by_id(vehicle_id)
        if vehicle is None:
            raise CandidateNotFoundError(vehicle_id)
        run = AgentRunRepository(self._session).create(vehicle_id)
        try:
            return await self._advance(run)
        except Exception as error:
            raise AgentRunAdvancementFailedError(run.id) from error

    def get(self, run_id: str) -> AgentRun:
        return AgentRunRepository(self._session).get(run_id)

    async def resume(self, run_id: str) -> AgentRun:
        run = AgentRunRepository(self._session).get(run_id)
        return await self._advance(run)

    async def _advance(self, run: AgentRun) -> AgentRun:
        repository = AgentRunRepository(self._session)
        execution_token = repository.claim_execution(run.id)
        self._context.runs = AgentRunRepository(
            self._session,
            execution_token=execution_token,
        )
        try:
            checkpoint_path = self._checkpoint_path
            if str(checkpoint_path) != ":memory:":
                checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            async with AsyncSqliteSaver.from_conn_string(
                str(checkpoint_path)
            ) as checkpointer:
                await checkpointer.setup()
                graph = build_agent_graph(self._context, checkpointer)
                await graph.ainvoke(
                    {"run_id": run.id},
                    {"configurable": {"thread_id": run.thread_id}},
                )
            return self._context.runs.get(run.id)
        finally:
            self._session.rollback()
            repository.release_execution(run.id, execution_token)
