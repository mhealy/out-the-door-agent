from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import exists, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.persistence.models import (
    AgentRunRecord,
    PurchaseRun,
    PurchaseRunVehicleRecord,
)


class PurchaseRunNotFoundError(LookupError):
    """No durable purchase exists for the supplied identifier."""


class PurchaseChildNotFoundError(LookupError):
    """A vehicle is not selected in the supplied purchase."""


class PurchaseChildAlreadyLinkedError(RuntimeError):
    """A purchase vehicle is already associated with another AgentRun."""


class PurchaseChildRunMismatchError(ValueError):
    """The AgentRun belongs to a different vehicle."""


@dataclass(frozen=True)
class PurchaseRecord:
    id: str
    goal: str
    created_at: datetime


@dataclass(frozen=True)
class PurchaseVehicleLink:
    id: str
    purchase_run_id: str
    vehicle_id: str
    position: int
    agent_run_id: str | None
    last_creation_error: str | None
    created_at: datetime
    updated_at: datetime


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _purchase(record: PurchaseRun) -> PurchaseRecord:
    return PurchaseRecord(
        id=record.id,
        goal=record.goal,
        created_at=_utc(record.created_at),
    )


def _link(record: PurchaseRunVehicleRecord) -> PurchaseVehicleLink:
    return PurchaseVehicleLink(
        id=record.id,
        purchase_run_id=record.purchase_run_id,
        vehicle_id=record.vehicle_id,
        position=record.position,
        agent_run_id=record.agent_run_id,
        last_creation_error=record.last_creation_error,
        created_at=_utc(record.created_at),
        updated_at=_utc(record.updated_at),
    )


class PurchaseRunRepository:
    """Persist purchase identity and ordered child-run intentions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, *, goal: str, vehicle_ids: list[str]) -> PurchaseRecord:
        purchase_id = str(uuid4())
        now = datetime.now(timezone.utc)
        self._session.add(
            PurchaseRun(
                id=purchase_id,
                goal=goal,
                status="CREATED",
                created_at=now,
            )
        )
        self._session.add_all(
            [
                PurchaseRunVehicleRecord(
                    id=str(uuid4()),
                    purchase_run_id=purchase_id,
                    vehicle_id=vehicle_id,
                    position=position,
                    created_at=now,
                    updated_at=now,
                )
                for position, vehicle_id in enumerate(vehicle_ids)
            ]
        )
        self._session.commit()
        self._session.expire_all()
        return self.get(purchase_id)

    def get(self, purchase_id: str) -> PurchaseRecord:
        record = self._session.get(PurchaseRun, purchase_id)
        if record is None:
            raise PurchaseRunNotFoundError(purchase_id)
        return _purchase(record)

    def list_vehicle_links(self, purchase_id: str) -> list[PurchaseVehicleLink]:
        self.get(purchase_id)
        records = list(
            self._session.scalars(
                select(PurchaseRunVehicleRecord)
                .where(PurchaseRunVehicleRecord.purchase_run_id == purchase_id)
                .order_by(
                    PurchaseRunVehicleRecord.position,
                    PurchaseRunVehicleRecord.id,
                )
            )
        )
        return [_link(record) for record in records]

    def get_vehicle_link(
        self,
        purchase_id: str,
        vehicle_id: str,
    ) -> PurchaseVehicleLink:
        record = self._get_vehicle_record(purchase_id, vehicle_id)
        return _link(record)

    def attach_agent_run(
        self,
        purchase_id: str,
        vehicle_id: str,
        agent_run_id: str,
    ) -> PurchaseVehicleLink:
        record = self._get_vehicle_record(purchase_id, vehicle_id)
        run = self._session.get(AgentRunRecord, agent_run_id)
        if run is None or run.vehicle_id != vehicle_id:
            raise PurchaseChildRunMismatchError(agent_run_id)
        if record.agent_run_id is not None:
            if record.agent_run_id == agent_run_id:
                return _link(record)
            raise PurchaseChildAlreadyLinkedError(vehicle_id)

        now = datetime.now(timezone.utc)
        result = self._session.execute(
            update(PurchaseRunVehicleRecord)
            .where(
                PurchaseRunVehicleRecord.id == record.id,
                or_(
                    PurchaseRunVehicleRecord.agent_run_id.is_(None),
                    PurchaseRunVehicleRecord.agent_run_id == agent_run_id,
                ),
            )
            .values(
                agent_run_id=agent_run_id,
                last_creation_error=None,
                updated_at=now,
            )
        )
        try:
            self._session.commit()
        except IntegrityError as error:
            self._session.rollback()
            current = self._get_vehicle_record(purchase_id, vehicle_id)
            if current.agent_run_id == agent_run_id:
                return _link(current)
            raise PurchaseChildAlreadyLinkedError(vehicle_id) from error
        if result.rowcount != 1:
            self._session.rollback()
            current = self._get_vehicle_record(purchase_id, vehicle_id)
            if current.agent_run_id == agent_run_id:
                return _link(current)
            raise PurchaseChildAlreadyLinkedError(vehicle_id)
        self._session.expire_all()
        return self.get_vehicle_link(purchase_id, vehicle_id)

    def record_creation_error(
        self,
        purchase_id: str,
        vehicle_id: str,
        error_code: str,
    ) -> PurchaseVehicleLink:
        record = self._get_vehicle_record(purchase_id, vehicle_id)
        self._session.execute(
            update(PurchaseRunVehicleRecord)
            .where(PurchaseRunVehicleRecord.id == record.id)
            .values(
                last_creation_error=error_code,
                updated_at=datetime.now(timezone.utc),
            )
        )
        self._session.commit()
        self._session.expire_all()
        return self.get_vehicle_link(purchase_id, vehicle_id)

    def record_advancement_error_if_starting(
        self,
        purchase_id: str,
        vehicle_id: str,
        agent_run_id: str,
        error_code: str = "agent_run_advancement_failed",
    ) -> PurchaseVehicleLink:
        """Record a setup error only while the linked run is still unadvanced."""

        record = self._get_vehicle_record(purchase_id, vehicle_id)
        self._session.execute(
            update(PurchaseRunVehicleRecord)
            .where(
                PurchaseRunVehicleRecord.id == record.id,
                PurchaseRunVehicleRecord.agent_run_id == agent_run_id,
                exists(
                    select(AgentRunRecord.id).where(
                        AgentRunRecord.id == agent_run_id,
                        AgentRunRecord.phase == "STARTING",
                    )
                ),
            )
            .values(
                last_creation_error=error_code,
                updated_at=datetime.now(timezone.utc),
            )
        )
        self._session.commit()
        self._session.expire_all()
        return self.get_vehicle_link(purchase_id, vehicle_id)

    def clear_creation_error(
        self,
        purchase_id: str,
        vehicle_id: str,
    ) -> PurchaseVehicleLink:
        record = self._get_vehicle_record(purchase_id, vehicle_id)
        if record.last_creation_error is None:
            return _link(record)
        self._session.execute(
            update(PurchaseRunVehicleRecord)
            .where(PurchaseRunVehicleRecord.id == record.id)
            .values(
                last_creation_error=None,
                updated_at=datetime.now(timezone.utc),
            )
        )
        self._session.commit()
        self._session.expire_all()
        return self.get_vehicle_link(purchase_id, vehicle_id)

    def _get_vehicle_record(
        self,
        purchase_id: str,
        vehicle_id: str,
    ) -> PurchaseRunVehicleRecord:
        self.get(purchase_id)
        record = self._session.scalar(
            select(PurchaseRunVehicleRecord).where(
                PurchaseRunVehicleRecord.purchase_run_id == purchase_id,
                PurchaseRunVehicleRecord.vehicle_id == vehicle_id,
            )
        )
        if record is None:
            raise PurchaseChildNotFoundError(vehicle_id)
        return record
