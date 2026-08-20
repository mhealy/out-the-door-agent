from typing import Literal, TypedDict

from app.domain.agent_run import RunPhase


GraphRoute = Literal[
    "prepare_initial_outreach",
    "observe_authoritative_state",
    "prepare_followup_if_needed",
    "end",
]


class BuyerAgentState(TypedDict, total=False):
    """Small checkpoint state; business objects remain in application SQLite."""

    run_id: str
    phase: RunPhase
    vehicle_id: str
    initial_action_id: str
    current_action_id: str | None
    interaction_id: str | None
    last_message_id: str | None
    last_event_type: str | None
    last_event_id: str | None
    error_code: str | None
    route: GraphRoute
