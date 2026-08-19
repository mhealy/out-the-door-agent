from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from time import sleep

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.dependencies import get_dealer_contact_resolver, get_messaging_provider
from app.domain.message import DeliveryReceipt, OutboundDealerMessage
from app.main import app
from app.persistence.db import build_engine, create_schema, get_session
from app.providers.messaging import MessagingProviderError


class RecordingMessagingProvider:
    def __init__(
        self,
        *,
        fail: bool = False,
        before_send: object | None = None,
    ) -> None:
        self.calls: list[OutboundDealerMessage] = []
        self._fail = fail
        self._before_send = before_send

    async def send(self, message: OutboundDealerMessage) -> DeliveryReceipt:
        self.calls.append(message)
        if callable(self._before_send):
            self._before_send(message)
        if self._fail:
            raise MessagingProviderError("sensitive provider details")
        return DeliveryReceipt(
            action_id=message.action_id,
            provider="recording-fixture",
            external_message_id=f"recorded-{message.action_id}",
            sent_at=datetime(2026, 8, 19, 20, 0, tzinfo=timezone.utc),
        )


class SlowRecordingMessagingProvider(RecordingMessagingProvider):
    async def send(self, message: OutboundDealerMessage) -> DeliveryReceipt:
        sleep(0.1)
        return await super().send(message)


class AlternateDealerContactResolver:
    def __init__(self, recipient: str) -> None:
        self.recipient = recipient
        self.calls: list[str] = []

    def resolve(self, dealer_id: str) -> str:
        self.calls.append(dealer_id)
        return self.recipient


@pytest.fixture
def outreach_client(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, RecordingMessagingProvider, sessionmaker[Session]]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'outreach-test.db'}")
    create_schema(engine)
    test_session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    provider = RecordingMessagingProvider()

    def override_session() -> Iterator[Session]:
        with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_messaging_provider] = lambda: provider
    try:
        with TestClient(app) as client:
            yield client, provider, test_session_factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _prepare(client: TestClient, vehicle_id: str = "baytown-blue") -> dict[str, object]:
    response = client.post("/outreach/proposals", json={"vehicle_id": vehicle_id})

    assert response.status_code == 201
    return response.json()


def test_prepare_inspect_and_approve_persist_exact_content_across_requests(
    outreach_client: tuple[
        TestClient, RecordingMessagingProvider, sessionmaker[Session]
    ],
) -> None:
    client, provider, session_factory = outreach_client

    prepared = _prepare(client)

    assert prepared["status"] == "PENDING_APPROVAL"
    assert prepared["requires_approval"] is True
    assert prepared["dealer_id"] == "baytown"
    assert prepared["vehicle_id"] == "baytown-blue"
    assert prepared["recipient"] == "quotes@baytown.example.test"
    assert prepared["approval"] is None
    assert prepared["delivery"] is None
    assert provider.calls == []

    inspected = client.get(f"/outreach/proposals/{prepared['id']}")

    assert inspected.status_code == 200
    assert inspected.json() == prepared
    assert provider.calls == []

    approved = client.post(f"/outreach/proposals/{prepared['id']}/approve", json={})

    assert approved.status_code == 200
    sent = approved.json()
    assert sent["status"] == "SENT"
    assert sent["approval"]["decision"] == "APPROVED"
    assert sent["delivery"]["external_message_id"] == f"recorded-{prepared['id']}"
    assert len(provider.calls) == 1
    delivered = provider.calls[0]
    assert isinstance(delivered, OutboundDealerMessage)
    assert delivered.action_id == prepared["id"]
    assert delivered.vehicle_id == prepared["vehicle_id"]
    assert delivered.dealer_id == prepared["dealer_id"]
    assert delivered.recipient == prepared["recipient"]
    assert delivered.subject == prepared["subject"]
    assert delivered.body == prepared["body"]
    assert sent["approval"]["action_snapshot"]["recipient"] == delivered.recipient
    assert sent["approval"]["action_snapshot"]["subject"] == delivered.subject
    assert sent["approval"]["action_snapshot"]["body"] == delivered.body
    assert sent["approval"]["action_snapshot"]["vehicle_id"] == delivered.vehicle_id

    with session_factory() as session:
        assert session.scalar(text("select count(*) from approvals")) == 1
        assert session.scalar(text("select count(*) from outbound_deliveries")) == 1

    inspected_after_send = client.get(f"/outreach/proposals/{prepared['id']}")
    assert inspected_after_send.status_code == 200
    assert inspected_after_send.json() == sent


def test_injected_contact_resolver_owns_the_persisted_and_delivered_recipient(
    outreach_client: tuple[
        TestClient, RecordingMessagingProvider, sessionmaker[Session]
    ],
) -> None:
    client, provider, session_factory = outreach_client
    alternate_recipient = "quotes@alternate.example.test"
    resolver = AlternateDealerContactResolver(alternate_recipient)
    app.dependency_overrides[get_dealer_contact_resolver] = lambda: resolver

    prepared = _prepare(client)

    assert resolver.calls == ["baytown"]
    assert prepared["recipient"] == alternate_recipient
    with session_factory() as session:
        assert session.scalar(
            text("select recipient from proposed_actions where id = :action_id"),
            {"action_id": prepared["id"]},
        ) == alternate_recipient

    inspected = client.get(f"/outreach/proposals/{prepared['id']}")
    assert inspected.status_code == 200
    assert inspected.json()["recipient"] == alternate_recipient

    approved = client.post(f"/outreach/proposals/{prepared['id']}/approve", json={})

    assert approved.status_code == 200
    assert approved.json()["approval"]["action_snapshot"]["recipient"] == (
        alternate_recipient
    )
    assert len(provider.calls) == 1
    assert provider.calls[0].recipient == alternate_recipient
    assert resolver.calls == ["baytown"]


def test_approval_is_persisted_before_the_provider_side_effect(
    outreach_client: tuple[
        TestClient, RecordingMessagingProvider, sessionmaker[Session]
    ],
) -> None:
    client, original_provider, session_factory = outreach_client

    def assert_approval_already_committed(message: OutboundDealerMessage) -> None:
        with session_factory() as session:
            decision = session.scalar(
                text(
                    "select decision from approvals "
                    "where proposed_action_id = :action_id"
                ),
                {"action_id": message.action_id},
            )
            status = session.scalar(
                text(
                    "select status from proposed_actions "
                    "where id = :action_id"
                ),
                {"action_id": message.action_id},
            )
        assert decision == "APPROVED"
        assert status == "APPROVED"

    provider = RecordingMessagingProvider(before_send=assert_approval_already_committed)
    app.dependency_overrides[get_messaging_provider] = lambda: provider
    prepared = _prepare(client)

    response = client.post(f"/outreach/proposals/{prepared['id']}/approve", json={})

    assert response.status_code == 200
    assert response.json()["status"] == "SENT"
    assert len(provider.calls) == 1
    assert original_provider.calls == []


def test_reject_is_a_persisted_terminal_boundary_and_never_sends(
    outreach_client: tuple[
        TestClient, RecordingMessagingProvider, sessionmaker[Session]
    ],
) -> None:
    client, provider, _ = outreach_client
    prepared = _prepare(client, "houston-white")

    rejected = client.post(f"/outreach/proposals/{prepared['id']}/reject", json={})

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"
    assert rejected.json()["approval"]["decision"] == "REJECTED"
    assert rejected.json()["delivery"] is None
    assert provider.calls == []

    later_approve = client.post(
        f"/outreach/proposals/{prepared['id']}/approve", json={}
    )

    assert later_approve.status_code == 409
    assert later_approve.json()["detail"]["code"] == "outreach_action_not_approvable"
    assert provider.calls == []
    persisted = client.get(f"/outreach/proposals/{prepared['id']}").json()
    assert persisted["status"] == "REJECTED"
    assert persisted["approval"]["decision"] == "REJECTED"


def test_duplicate_approve_is_idempotent_and_never_redelivers(
    outreach_client: tuple[
        TestClient, RecordingMessagingProvider, sessionmaker[Session]
    ],
) -> None:
    client, provider, _ = outreach_client
    prepared = _prepare(client, "katy-blue")

    first = client.post(f"/outreach/proposals/{prepared['id']}/approve", json={})
    second = client.post(f"/outreach/proposals/{prepared['id']}/approve", json={})

    assert first.status_code == 200
    assert first.json()["status"] == "SENT"
    assert second.status_code in {200, 409}
    if second.status_code == 200:
        assert second.json() == first.json()
    else:
        assert second.json()["detail"]["code"] == "outreach_action_already_sent"
    assert len(provider.calls) == 1


def test_concurrent_approve_requests_have_only_one_provider_side_effect(
    outreach_client: tuple[
        TestClient, RecordingMessagingProvider, sessionmaker[Session]
    ],
) -> None:
    client, original_provider, _ = outreach_client
    provider = SlowRecordingMessagingProvider()
    app.dependency_overrides[get_messaging_provider] = lambda: provider
    prepared = _prepare(client, "katy-blue")
    start = Barrier(2)

    def approve() -> object:
        start.wait(timeout=2)
        return client.post(f"/outreach/proposals/{prepared['id']}/approve", json={})

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: approve(), range(2)))

    assert sorted(response.status_code for response in responses) in (
        [200, 200],
        [200, 409],
    )
    successful = [response for response in responses if response.status_code == 200]
    assert all(response.json()["status"] == "SENT" for response in successful)
    conflicts = [response for response in responses if response.status_code == 409]
    assert all(
        response.json()["detail"]["code"]
        in {"outreach_action_already_approved", "outreach_action_already_sent"}
        for response in conflicts
    )
    assert len(provider.calls) == 1
    assert original_provider.calls == []


def test_unknown_candidate_and_missing_actions_fail_visibly_without_sending(
    outreach_client: tuple[
        TestClient, RecordingMessagingProvider, sessionmaker[Session]
    ],
) -> None:
    client, provider, _ = outreach_client

    unknown_candidate = client.post(
        "/outreach/proposals", json={"vehicle_id": "missing-candidate"}
    )
    missing_inspect = client.get("/outreach/proposals/missing-action")
    missing_approve = client.post(
        "/outreach/proposals/missing-action/approve", json={}
    )
    missing_reject = client.post(
        "/outreach/proposals/missing-action/reject", json={}
    )

    assert unknown_candidate.status_code == 404
    assert unknown_candidate.json()["detail"]["code"] == "candidate_not_found"
    for response in (missing_inspect, missing_approve, missing_reject):
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "outreach_proposal_not_found"
    assert provider.calls == []


@pytest.mark.parametrize(
    "path,payload",
    [
        (
            "/outreach/proposals",
            {
                "vehicle_id": "baytown-blue",
                "recipient": "attacker@example.test",
                "subject": "Client-controlled subject",
                "body": "Send arbitrary client content",
            },
        ),
        (
            "/outreach/proposals/{action_id}/approve",
            {
                "recipient": "attacker@example.test",
                "subject": "Client-controlled subject",
                "body": "Replace the server-owned approved content",
            },
        ),
    ],
)
def test_client_cannot_substitute_recipient_or_body_at_prepare_or_send_time(
    outreach_client: tuple[
        TestClient, RecordingMessagingProvider, sessionmaker[Session]
    ],
    path: str,
    payload: dict[str, str],
) -> None:
    client, provider, _ = outreach_client
    prepared = _prepare(client)
    target = path.format(action_id=prepared["id"])

    response = client.post(target, json=payload)

    assert response.status_code == 422
    assert provider.calls == []
    persisted = client.get(f"/outreach/proposals/{prepared['id']}").json()
    assert persisted["status"] == "PENDING_APPROVAL"


def test_provider_failure_is_visible_persisted_and_not_reported_as_sent(
    outreach_client: tuple[
        TestClient, RecordingMessagingProvider, sessionmaker[Session]
    ],
) -> None:
    client, original_provider, _ = outreach_client
    provider = RecordingMessagingProvider(fail=True)
    app.dependency_overrides[get_messaging_provider] = lambda: provider
    prepared = _prepare(client)

    failed = client.post(f"/outreach/proposals/{prepared['id']}/approve", json={})

    assert failed.status_code == 502
    assert failed.json()["detail"] == {
        "code": "outreach_send_failed",
        "message": "The approved dealer message could not be sent.",
    }
    assert "sensitive provider details" not in failed.text
    assert len(provider.calls) == 1
    assert original_provider.calls == []

    persisted = client.get(f"/outreach/proposals/{prepared['id']}")
    assert persisted.status_code == 200
    assert persisted.json()["status"] == "SEND_FAILED"
    assert persisted.json()["approval"]["decision"] == "APPROVED"
    assert persisted.json()["delivery"] is None

    retry = client.post(f"/outreach/proposals/{prepared['id']}/approve", json={})
    assert retry.status_code == 409
    assert retry.json()["detail"]["code"] == "outreach_retry_requires_new_proposal"
    assert len(provider.calls) == 1


def test_provider_receipt_offset_round_trips_as_the_correct_utc_instant(
    outreach_client: tuple[
        TestClient, RecordingMessagingProvider, sessionmaker[Session]
    ],
) -> None:
    client, original_provider, _ = outreach_client

    class OffsetReceiptProvider(RecordingMessagingProvider):
        async def send(self, message: OutboundDealerMessage) -> DeliveryReceipt:
            self.calls.append(message)
            return DeliveryReceipt(
                action_id=message.action_id,
                provider="offset-fixture",
                external_message_id=f"offset-{message.action_id}",
                sent_at=datetime(
                    2026,
                    8,
                    19,
                    15,
                    tzinfo=timezone(timedelta(hours=-5)),
                ),
            )

    provider = OffsetReceiptProvider()
    app.dependency_overrides[get_messaging_provider] = lambda: provider
    prepared = _prepare(client)

    sent = client.post(f"/outreach/proposals/{prepared['id']}/approve", json={})

    assert sent.status_code == 200
    assert sent.json()["delivery"]["sent_at"] == "2026-08-19T20:00:00Z"
    assert len(provider.calls) == 1
    assert original_provider.calls == []
