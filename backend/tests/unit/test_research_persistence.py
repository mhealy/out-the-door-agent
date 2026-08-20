from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.domain.research import ResearchSource, ResearchTarget
from app.persistence.db import build_engine, create_schema
from app.persistence.research import ResearchRepository


RESEARCH_VERSION = "test-research-v1"
INITIAL_CLAIMED_AT = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _target() -> ResearchTarget:
    return ResearchTarget(
        target_id="target-ceramic-v1",
        purchase_run_id="purchase-1",
        agent_run_id="run-houston",
        interaction_id="interaction-houston",
        source_message_id="message-houston-v1",
        dealer_id="houston",
        dealer_name="Houston Hyundai",
        vehicle_id="houston-white",
        target_type="MANDATORY_ADDON",
        canonical_name="Ceramic Shield",
        dealer_stated_amount="1299",
        stated_mandatory=True,
        source_evidence_ids=["ev-addons-ceramic"],
    )


def _source(*, retrieved_at: datetime) -> ResearchSource:
    return ResearchSource(
        id="ceramic-source",
        url="https://example.test/research/ceramic-source",
        title="Ceramic coating context",
        publisher="Fixture Publisher",
        retrieved_at=retrieved_at,
        excerpt="The source describes a dealer-applied protection coating.",
    )


@pytest.fixture
def repository() -> Iterator[tuple[ResearchRepository, Session]]:
    engine = build_engine("sqlite:///:memory:")
    create_schema(engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    with session_factory() as session:
        yield ResearchRepository(session), session
    engine.dispose()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def test_source_timestamp_round_trip_preserves_non_utc_instant(
    repository: tuple[ResearchRepository, Session],
) -> None:
    research, _ = repository
    target = _target()
    claim = research.claim(
        target,
        RESEARCH_VERSION,
        claimed_at=INITIAL_CLAIMED_AT,
    )
    assert claim.claim_token is not None
    retrieved_at = datetime(
        2026,
        8,
        20,
        12,
        0,
        tzinfo=timezone(timedelta(hours=-5)),
    )

    research.save_sources(
        claim.record_id,
        claim.claim_token,
        [_source(retrieved_at=retrieved_at)],
    )
    investigation = research.investigation(target, RESEARCH_VERSION)

    assert investigation is not None
    assert investigation.sources[0].retrieved_at == retrieved_at.astimezone(
        timezone.utc
    )


def test_saving_sources_refreshes_the_persisted_claim_lease_without_sleeping(
    repository: tuple[ResearchRepository, Session],
) -> None:
    research, session = repository
    target = _target()
    claim = research.claim(
        target,
        RESEARCH_VERSION,
        claimed_at=INITIAL_CLAIMED_AT,
    )
    assert claim.claim_token is not None

    research.save_sources(
        claim.record_id,
        claim.claim_token,
        [_source(retrieved_at=datetime.now(timezone.utc))],
    )
    session.expire_all()
    record = research.get_record(target.target_id, RESEARCH_VERSION)

    assert record is not None
    assert record.claimed_at == record.updated_at
    assert _as_utc(record.claimed_at) > INITIAL_CLAIMED_AT
