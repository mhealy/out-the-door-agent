from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.research import (
    ResearchFinding,
    ResearchFindingDraft,
    ResearchInvestigation,
    ResearchSource,
    ResearchTarget,
)
from app.persistence.models import ResearchFindingRecord, ResearchSourceRecord


RESEARCH_CLAIM_LEASE = timedelta(minutes=5)


class ResearchRecordNotFoundError(LookupError):
    """No persisted research execution matches the supplied identity."""


class ResearchClaimLostError(RuntimeError):
    """The caller no longer owns the persisted research execution lease."""


@dataclass(frozen=True)
class ResearchClaim:
    record_id: str
    claim_token: str | None
    status: str

    @property
    def acquired(self) -> bool:
        return self.claim_token is not None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _amount(value: object | None) -> str | None:
    return None if value is None else str(value)


class ResearchRepository:
    """Focused SQLite persistence and single-execution claim for research cost."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_record(
        self,
        target_id: str,
        research_version: str,
    ) -> ResearchFindingRecord | None:
        return self._session.scalar(
            select(ResearchFindingRecord).where(
                ResearchFindingRecord.target_id == target_id,
                ResearchFindingRecord.research_version == research_version,
            )
        )

    def claim(
        self,
        target: ResearchTarget,
        research_version: str,
        *,
        claimed_at: datetime | None = None,
    ) -> ResearchClaim:
        now = claimed_at or datetime.now(timezone.utc)
        token = str(uuid4())
        record = ResearchFindingRecord(
            id=str(uuid4()),
            target_id=target.target_id,
            purchase_run_id=target.purchase_run_id,
            agent_run_id=target.agent_run_id,
            interaction_id=target.interaction_id,
            source_message_id=target.source_message_id,
            dealer_id=target.dealer_id,
            dealer_name=target.dealer_name,
            vehicle_id=target.vehicle_id,
            target_type=target.target_type,
            canonical_name=target.canonical_name,
            dealer_stated_amount=_amount(target.dealer_stated_amount),
            stated_mandatory=target.stated_mandatory,
            source_evidence_ids=list(target.source_evidence_ids),
            research_version=research_version,
            status="IN_PROGRESS",
            claim_token=token,
            claimed_at=now,
            created_at=now,
            updated_at=now,
        )
        self._session.add(record)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            current = self.get_record(target.target_id, research_version)
            if current is None:
                raise
            if current.status == "COMPLETED":
                return ResearchClaim(current.id, None, current.status)
            if current.status == "FAILED":
                reclaimed = self._session.execute(
                    update(ResearchFindingRecord)
                    .where(
                        ResearchFindingRecord.id == current.id,
                        ResearchFindingRecord.status == "FAILED",
                    )
                    .values(
                        status="IN_PROGRESS",
                        finding_snapshot=None,
                        error_code=None,
                        claim_token=token,
                        claimed_at=now,
                        updated_at=now,
                    )
                    .execution_options(synchronize_session=False)
                )
                if reclaimed.rowcount != 1:
                    self._session.rollback()
                    self._session.expire_all()
                    current = self.get_record(target.target_id, research_version)
                    if current is None:
                        raise ResearchRecordNotFoundError(target.target_id)
                    return ResearchClaim(current.id, None, current.status)
                self._session.commit()
                self._session.expire_all()
                return ResearchClaim(current.id, token, "IN_PROGRESS")
            if current.status != "IN_PROGRESS":
                return ResearchClaim(current.id, None, current.status)

            stale_before = now - RESEARCH_CLAIM_LEASE
            claimed = self._session.execute(
                update(ResearchFindingRecord)
                .where(
                    ResearchFindingRecord.id == current.id,
                    ResearchFindingRecord.status == "IN_PROGRESS",
                    or_(
                        ResearchFindingRecord.claimed_at.is_(None),
                        ResearchFindingRecord.claimed_at <= stale_before,
                    ),
                )
                .values(
                    claim_token=token,
                    claimed_at=now,
                    finding_snapshot=None,
                    error_code=None,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            if claimed.rowcount != 1:
                self._session.rollback()
                self._session.expire_all()
                current = self.get_record(target.target_id, research_version)
                if current is None:
                    raise ResearchRecordNotFoundError(target.target_id)
                return ResearchClaim(current.id, None, current.status)
            self._session.execute(
                delete(ResearchSourceRecord).where(
                    ResearchSourceRecord.finding_id == current.id
                )
            )
            self._session.commit()
            self._session.expire_all()
            return ResearchClaim(current.id, token, "IN_PROGRESS")
        self._session.expire_all()
        return ResearchClaim(record.id, token, "IN_PROGRESS")

    def save_sources(
        self,
        record_id: str,
        claim_token: str,
        sources: list[ResearchSource],
    ) -> None:
        record = self._claimed_record(record_id, claim_token)
        saved_at = datetime.now(timezone.utc)
        self._session.execute(
            delete(ResearchSourceRecord).where(
                ResearchSourceRecord.finding_id == record_id
            )
        )
        self._session.add_all(
            [
                ResearchSourceRecord(
                    id=str(uuid4()),
                    finding_id=record_id,
                    provider_source_id=source.id,
                    position=position,
                    url=source.url,
                    title=source.title,
                    publisher=source.publisher,
                    retrieved_at=_utc(source.retrieved_at),
                    excerpt=source.excerpt,
                )
                for position, source in enumerate(sources)
            ]
        )
        record.claimed_at = saved_at
        record.updated_at = saved_at
        self._session.commit()
        self._session.expire_all()

    def complete(
        self,
        record_id: str,
        claim_token: str,
        finding: ResearchFinding,
    ) -> None:
        snapshot = ResearchFindingDraft.model_validate(
            finding.model_dump(exclude={"sources"})
        ).model_dump(mode="json")
        completed_at = datetime.now(timezone.utc)
        result = self._session.execute(
            update(ResearchFindingRecord)
            .where(
                ResearchFindingRecord.id == record_id,
                ResearchFindingRecord.status == "IN_PROGRESS",
                ResearchFindingRecord.claim_token == claim_token,
            )
            .values(
                status="COMPLETED",
                finding_snapshot=snapshot,
                error_code=None,
                claim_token=None,
                claimed_at=None,
                updated_at=completed_at,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            self._session.rollback()
            self._session.expire_all()
            raise ResearchClaimLostError(record_id)
        self._session.commit()
        self._session.expire_all()

    def lock_for_completion(
        self,
        record_id: str,
        claim_token: str,
    ) -> None:
        """Acquire SQLite's write lock before the final authority read.

        This intentionally does not commit. The caller must reread authoritative
        quote state and then complete or fail the claim in this same transaction.
        """

        now = datetime.now(timezone.utc)
        result = self._session.execute(
            update(ResearchFindingRecord)
            .where(
                ResearchFindingRecord.id == record_id,
                ResearchFindingRecord.status == "IN_PROGRESS",
                ResearchFindingRecord.claim_token == claim_token,
            )
            .values(
                claimed_at=now,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            self._session.rollback()
            self._session.expire_all()
            raise ResearchClaimLostError(record_id)

    def fail(
        self,
        record_id: str,
        claim_token: str,
        error_code: str,
    ) -> None:
        failed_at = datetime.now(timezone.utc)
        result = self._session.execute(
            update(ResearchFindingRecord)
            .where(
                ResearchFindingRecord.id == record_id,
                ResearchFindingRecord.status == "IN_PROGRESS",
                ResearchFindingRecord.claim_token == claim_token,
            )
            .values(
                status="FAILED",
                finding_snapshot=None,
                error_code=error_code,
                claim_token=None,
                claimed_at=None,
                updated_at=failed_at,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            self._session.rollback()
            self._session.expire_all()
            raise ResearchClaimLostError(record_id)
        self._session.commit()
        self._session.expire_all()

    def investigation(
        self,
        target: ResearchTarget,
        research_version: str,
    ) -> ResearchInvestigation | None:
        record = self.get_record(target.target_id, research_version)
        if record is None:
            return None
        if not self._matches_target(record, target):
            raise ResearchRecordNotFoundError(target.target_id)
        sources = self._sources(record.id)
        finding = None
        if record.finding_snapshot is not None:
            content = ResearchFindingDraft.model_validate(record.finding_snapshot)
            cited = {source.id: source for source in sources}
            finding = ResearchFinding(
                **content.model_dump(),
                sources=[cited[source_id] for source_id in content.source_ids],
            )
        return ResearchInvestigation(
            id=record.id,
            target_id=record.target_id,
            status=record.status,
            research_version=record.research_version,
            finding=finding,
            sources=sources,
            error_code=record.error_code,
            created_at=_utc(record.created_at),
            updated_at=_utc(record.updated_at),
        )

    def _claimed_record(
        self,
        record_id: str,
        claim_token: str,
    ) -> ResearchFindingRecord:
        record = self._session.scalar(
            select(ResearchFindingRecord).where(
                ResearchFindingRecord.id == record_id,
                ResearchFindingRecord.status == "IN_PROGRESS",
                ResearchFindingRecord.claim_token == claim_token,
            )
        )
        if record is None:
            raise ResearchClaimLostError(record_id)
        return record

    def _sources(self, finding_id: str) -> list[ResearchSource]:
        records = list(
            self._session.scalars(
                select(ResearchSourceRecord)
                .where(ResearchSourceRecord.finding_id == finding_id)
                .order_by(
                    ResearchSourceRecord.position,
                    ResearchSourceRecord.provider_source_id,
                )
            )
        )
        return [
            ResearchSource(
                id=record.provider_source_id,
                url=record.url,
                title=record.title,
                publisher=record.publisher,
                retrieved_at=_utc(record.retrieved_at),
                excerpt=record.excerpt,
            )
            for record in records
        ]

    @staticmethod
    def _matches_target(
        record: ResearchFindingRecord,
        target: ResearchTarget,
    ) -> bool:
        return (
            record.purchase_run_id == target.purchase_run_id
            and record.agent_run_id == target.agent_run_id
            and record.interaction_id == target.interaction_id
            and record.source_message_id == target.source_message_id
            and record.dealer_id == target.dealer_id
            and record.dealer_name == target.dealer_name
            and record.vehicle_id == target.vehicle_id
            and record.target_type == target.target_type
            and record.canonical_name == target.canonical_name
            and record.dealer_stated_amount == _amount(target.dealer_stated_amount)
            and record.stated_mandatory == target.stated_mandatory
            and record.source_evidence_ids == target.source_evidence_ids
        )
