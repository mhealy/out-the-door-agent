from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.domain.agent_run import (
    AgentEvent,
    AgentEventMetadataValue,
    AgentEventType,
    AgentRun,
    RunPhase,
)
from app.persistence.models import AgentEventRecord, AgentRunRecord


class AgentRunNotFoundError(LookupError):
    """No durable agent run exists for the supplied identifier."""


class AgentRunAlreadyAdvancingError(RuntimeError):
    """Another request holds the durable execution lease for this run."""


class AgentRunExecutionLeaseLostError(RuntimeError):
    """The current request no longer owns the run execution lease."""


@dataclass(frozen=True)
class NewAgentEvent:
    semantic_key: str
    event_type: AgentEventType
    message: str
    action_id: str | None = None
    interaction_id: str | None = None
    message_id: str | None = None
    metadata: dict[str, AgentEventMetadataValue] = field(default_factory=dict)


_UNSET = object()
_EXECUTION_LEASE_TIMEOUT = timedelta(minutes=5)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _event_id(run_id: str, semantic_key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"out-the-door-agent:{run_id}:{semantic_key}"))


class AgentRunRepository:
    """Application-owned run identity, phase projection, and safe activity trace."""

    def __init__(
        self,
        session: Session,
        *,
        execution_token: str | None = None,
    ) -> None:
        self._session = session
        self._execution_token = execution_token

    def create(self, vehicle_id: str) -> AgentRun:
        now = datetime.now(timezone.utc)
        run_id = str(uuid4())
        thread_id = str(uuid4())
        initial_action_id = str(uuid4())
        started = NewAgentEvent(
            semantic_key="run-started",
            event_type="RUN_STARTED",
            message="Agent workflow started for the selected vehicle.",
        )
        started_id = _event_id(run_id, started.semantic_key)
        record = AgentRunRecord(
            id=run_id,
            thread_id=thread_id,
            vehicle_id=vehicle_id,
            phase="STARTING",
            initial_action_id=initial_action_id,
            current_action_id=initial_action_id,
            last_event_type=started.event_type,
            last_event_id=started_id,
            created_at=now,
            updated_at=now,
        )
        self._session.add(record)
        self._session.flush()
        self._insert_event(
            record,
            node="load_run_context",
            phase="STARTING",
            event=started,
            created_at=now,
        )
        self._session.commit()
        self._session.expire_all()
        return self.get(run_id)

    def get_record(self, run_id: str) -> AgentRunRecord:
        record = self._session.get(AgentRunRecord, run_id)
        if record is None:
            raise AgentRunNotFoundError(run_id)
        return record

    def get(self, run_id: str) -> AgentRun:
        record = self.get_record(run_id)
        events = list(
            self._session.scalars(
                select(AgentEventRecord)
                .where(AgentEventRecord.run_id == run_id)
                .order_by(AgentEventRecord.created_at, AgentEventRecord.id)
            )
        )
        return AgentRun(
            id=record.id,
            run_id=record.id,
            thread_id=record.thread_id,
            vehicle_id=record.vehicle_id,
            phase=record.phase,
            initial_action_id=record.initial_action_id,
            current_action_id=record.current_action_id,
            interaction_id=record.interaction_id,
            last_message_id=record.last_message_id,
            error_code=record.error_code,
            created_at=_utc(record.created_at),
            updated_at=_utc(record.updated_at),
            events=[self._event_from_record(event) for event in events],
        )

    def claim_execution(self, run_id: str) -> str:
        self.get_record(run_id)
        token = str(uuid4())
        claimed_at = datetime.now(timezone.utc)
        stale_before = claimed_at - _EXECUTION_LEASE_TIMEOUT
        result = self._session.execute(
            update(AgentRunRecord)
            .where(
                AgentRunRecord.id == run_id,
                or_(
                    AgentRunRecord.execution_token.is_(None),
                    AgentRunRecord.execution_claimed_at.is_(None),
                    AgentRunRecord.execution_claimed_at < stale_before,
                ),
            )
            .values(
                execution_token=token,
                execution_claimed_at=claimed_at,
            )
        )
        if result.rowcount != 1:
            self._session.rollback()
            raise AgentRunAlreadyAdvancingError(run_id)
        self._session.commit()
        self._session.expire_all()
        return token

    def release_execution(self, run_id: str, token: str) -> None:
        self._session.execute(
            update(AgentRunRecord)
            .where(
                AgentRunRecord.id == run_id,
                AgentRunRecord.execution_token == token,
            )
            .values(
                execution_token=None,
                execution_claimed_at=None,
            )
        )
        self._session.commit()
        self._session.expire_all()

    def transition(
        self,
        run_id: str,
        *,
        phase: RunPhase,
        node: str,
        events: list[NewAgentEvent],
        current_action_id: str | None | object = _UNSET,
        interaction_id: str | None | object = _UNSET,
        last_message_id: str | None | object = _UNSET,
        error_code: str | None | object = _UNSET,
    ) -> AgentRun:
        self.get_record(run_id)
        now = datetime.now(timezone.utc)
        values: dict[str, Any] = {
            "phase": phase,
            "updated_at": now,
        }
        if current_action_id is not _UNSET:
            values["current_action_id"] = current_action_id
        if interaction_id is not _UNSET:
            values["interaction_id"] = interaction_id
        if last_message_id is not _UNSET:
            values["last_message_id"] = last_message_id
        if error_code is not _UNSET:
            values["error_code"] = error_code
        if events:
            last = events[-1]
            values["last_event_type"] = last.event_type
            values["last_event_id"] = _event_id(run_id, last.semantic_key)

        statement = update(AgentRunRecord).where(AgentRunRecord.id == run_id)
        if self._execution_token is not None:
            statement = statement.where(
                AgentRunRecord.execution_token == self._execution_token
            )
        result = self._session.execute(statement.values(**values))
        if result.rowcount != 1:
            self._session.rollback()
            if self._execution_token is not None:
                raise AgentRunExecutionLeaseLostError(run_id)
            raise AgentRunNotFoundError(run_id)

        self._session.expire_all()
        record = self.get_record(run_id)
        for index, event in enumerate(events):
            self._insert_event(
                record,
                node=node,
                phase=phase,
                event=event,
                created_at=now + timedelta(microseconds=index),
            )
        self._session.commit()
        self._session.expire_all()
        return self.get(run_id)

    def _insert_event(
        self,
        run: AgentRunRecord,
        *,
        node: str,
        phase: str,
        event: NewAgentEvent,
        created_at: datetime,
    ) -> None:
        values: dict[str, Any] = {
            "id": _event_id(run.id, event.semantic_key),
            "run_id": run.id,
            "semantic_key": event.semantic_key,
            "event_type": event.event_type,
            "phase": phase,
            "node": node,
            "action_id": event.action_id,
            "interaction_id": event.interaction_id,
            "message_id": event.message_id,
            "message": event.message,
            "event_metadata": dict(event.metadata),
            "created_at": created_at,
        }
        self._session.execute(
            sqlite_insert(AgentEventRecord)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=["run_id", "semantic_key"]
            )
        )

    @staticmethod
    def _event_from_record(record: AgentEventRecord) -> AgentEvent:
        return AgentEvent(
            id=record.id,
            run_id=record.run_id,
            event_type=record.event_type,
            phase=record.phase,
            node=record.node,
            action_id=record.action_id,
            interaction_id=record.interaction_id,
            message_id=record.message_id,
            message=record.message,
            metadata=dict(record.event_metadata or {}),
            created_at=_utc(record.created_at),
        )
