from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.dependencies import (
    get_dealer_message_provider,
    get_messaging_provider,
    get_quote_extractor,
)
from app.domain.message import DealerMessage, DeliveryReceipt, OutboundDealerMessage
from app.main import app
from app.persistence.db import build_engine, create_schema, get_session
from app.providers.dealer_messages import FixtureDealerMessageProvider
from app.providers.messaging import MessagingProviderError
from app.providers.quote_extraction import (
    EvidenceDraft,
    QuoteExtractionError,
    QuoteExtractorOutput,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RAW_CASES = {
    value["id"]: value
    for value in json.loads(
        (
            REPOSITORY_ROOT / "demo/dealer_messages/quote_analysis_cases.json"
        ).read_text(encoding="utf-8")
    )
}
EXPECTED_OUTPUTS = {
    value["case_id"]: QuoteExtractorOutput.model_validate(
        {"extraction": value["extraction"], "evidence": value["evidence"]}
    )
    for value in json.loads(
        (
            REPOSITORY_ROOT / "demo/expected/quote_analysis_expected.json"
        ).read_text(encoding="utf-8")
    )
}
CASE_ID_BY_BODY = {
    value["body"]: case_id for case_id, value in RAW_CASES.items()
}


class RecordingMessagingProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[OutboundDealerMessage] = []
        self._fail = fail

    async def send(self, message: OutboundDealerMessage) -> DeliveryReceipt:
        self.calls.append(message)
        if self._fail:
            raise MessagingProviderError("fixture delivery was not confirmed")
        return DeliveryReceipt(
            action_id=message.action_id,
            provider="recording-fixture",
            external_message_id=f"recorded-{message.action_id}",
            sent_at=datetime(2026, 8, 19, 20, 0, tzinfo=timezone.utc),
        )


class ExpectedFixtureExtractor:
    def __init__(self) -> None:
        self.calls: list[DealerMessage] = []

    async def extract(self, message: DealerMessage) -> QuoteExtractorOutput:
        self.calls.append(message)
        case_id = CASE_ID_BY_BODY[message.body]
        return EXPECTED_OUTPUTS[case_id].model_copy(deep=True)


class InvalidEvidenceExtractor:
    def __init__(self) -> None:
        self.calls: list[DealerMessage] = []

    async def extract(self, message: DealerMessage) -> QuoteExtractorOutput:
        self.calls.append(message)
        return QuoteExtractorOutput(
            extraction={
                "claimed_otd": "1",
                "evidence_ids": ["fabricated"],
                "extraction_confidence": 0.99,
            },
            evidence=[
                EvidenceDraft(
                    id="fabricated",
                    field_name="claimed_otd",
                    excerpt="This excerpt does not occur in the dealer response.",
                )
            ],
        )


class WrongVinBaytownMessageProvider(FixtureDealerMessageProvider):
    async def get_message(self, message_id: str) -> DealerMessage:
        assert message_id == "msg-explicit-no-addons"
        # Both the response metadata and body identify another target. The persisted
        # association must still come only from the application-owned interaction.
        return await super().get_message("msg-wrong-vin")


class UnexpectedFixtureLookupProvider:
    async def list_messages(self) -> list[DealerMessage]:
        raise AssertionError("An idempotent release must use the persisted response.")

    async def get_message(self, message_id: str) -> DealerMessage:
        del message_id
        raise AssertionError("An idempotent release must use the persisted response.")


class BlockingFirstSuccessExtractor:
    """Hold the first extraction open so a simultaneous release can race it."""

    def __init__(self) -> None:
        self.calls: list[DealerMessage] = []
        self.first_started = Event()
        self.release_first = Event()
        self._lock = Lock()

    async def extract(self, message: DealerMessage) -> QuoteExtractorOutput:
        with self._lock:
            self.calls.append(message)
            call_number = len(self.calls)
        if call_number == 1:
            self.first_started.set()
            released = await asyncio.to_thread(self.release_first.wait, 5)
            assert released, "Timed out waiting to release the first extraction."
        case_id = CASE_ID_BY_BODY[message.body]
        return EXPECTED_OUTPUTS[case_id].model_copy(deep=True)


class StaleFailureRaceExtractor:
    """Let a reclaimed analysis succeed before the stale worker fails."""

    def __init__(self) -> None:
        self.calls: list[DealerMessage] = []
        self.first_started = Event()
        self.release_first = Event()
        self._lock = Lock()

    async def extract(self, message: DealerMessage) -> QuoteExtractorOutput:
        with self._lock:
            self.calls.append(message)
            call_number = len(self.calls)
        if call_number == 1:
            self.first_started.set()
            released = await asyncio.to_thread(self.release_first.wait, 5)
            assert released, "Timed out waiting to release the stale extraction."
            raise QuoteExtractionError("The stale extraction failed after its lease.")
        case_id = CASE_ID_BY_BODY[message.body]
        return EXPECTED_OUTPUTS[case_id].model_copy(deep=True)


@pytest.fixture
def interaction_client(
    tmp_path: Path,
) -> Iterator[
    tuple[
        TestClient,
        RecordingMessagingProvider,
        ExpectedFixtureExtractor,
        sessionmaker[Session],
    ]
]:
    engine = build_engine(f"sqlite:///{tmp_path / 'interaction-test.db'}")
    create_schema(engine)
    test_session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    messaging_provider = RecordingMessagingProvider()
    extractor = ExpectedFixtureExtractor()
    message_provider = FixtureDealerMessageProvider()

    def override_session() -> Iterator[Session]:
        with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_messaging_provider] = lambda: messaging_provider
    app.dependency_overrides[get_dealer_message_provider] = lambda: message_provider
    app.dependency_overrides[get_quote_extractor] = lambda: extractor
    try:
        with TestClient(app) as client:
            yield client, messaging_provider, extractor, test_session_factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _prepare(client: TestClient, vehicle_id: str = "baytown-blue") -> dict[str, object]:
    response = client.post("/outreach/proposals", json={"vehicle_id": vehicle_id})
    assert response.status_code == 201
    return response.json()


def _send(client: TestClient, vehicle_id: str = "baytown-blue") -> dict[str, object]:
    prepared = _prepare(client, vehicle_id)
    response = client.post(f"/outreach/proposals/{prepared['id']}/approve", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "SENT"
    return response.json()


def _release(client: TestClient, action_id: str):
    return client.post(
        f"/outreach/proposals/{action_id}/demo-response",
        json={},
    )


def test_sent_proposal_has_durable_interaction_anchored_to_original_snapshot(
    interaction_client: tuple[
        TestClient,
        RecordingMessagingProvider,
        ExpectedFixtureExtractor,
        sessionmaker[Session],
    ],
) -> None:
    client, _, extractor, session_factory = interaction_client
    sent = _send(client)

    first = client.get(f"/outreach/proposals/{sent['id']}/interaction")
    second = client.get(f"/outreach/proposals/{sent['id']}/interaction")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    interaction = first.json()
    assert interaction["id"]
    assert interaction["initial_action_id"] == sent["id"]
    assert interaction["dealer_id"] == sent["dealer_id"] == "baytown"
    assert interaction["vehicle_id"] == sent["vehicle_id"] == "baytown-blue"
    assert interaction["vehicle"] == sent["vehicle"]
    assert interaction["vehicle"]["vin"] == "KM8JCDD10SU000001"
    assert interaction["vehicle"]["stock_number"] == "B1001"
    assert interaction["analysis_status"] == "AWAITING_RESPONSE"
    assert interaction["messages"] == []
    assert interaction["analysis"] is None
    assert interaction["analysis_error_code"] is None
    assert extractor.calls == []

    with session_factory() as session:
        assert session.scalar(text("select count(*) from dealer_interactions")) == 1
        assert (
            session.scalar(text("select count(*) from inbound_dealer_messages"))
            == 0
        )


@pytest.mark.parametrize(
    "proposal_status",
    ["PENDING_APPROVAL", "REJECTED", "APPROVED", "SEND_FAILED"],
)
def test_demo_response_requires_confirmed_sent_initial_action(
    interaction_client: tuple[
        TestClient,
        RecordingMessagingProvider,
        ExpectedFixtureExtractor,
        sessionmaker[Session],
    ],
    proposal_status: str,
) -> None:
    client, _, extractor, session_factory = interaction_client
    prepared = _prepare(client)

    if proposal_status == "REJECTED":
        rejected = client.post(
            f"/outreach/proposals/{prepared['id']}/reject", json={}
        )
        assert rejected.status_code == 200
    elif proposal_status == "APPROVED":
        # This is the deliberate crash-window state: approval is committed, but no
        # transport receipt has confirmed delivery yet.
        with session_factory() as session:
            session.execute(
                text(
                    "update proposed_actions set status = 'APPROVED' where id = :id"
                ),
                {"id": prepared["id"]},
            )
            session.commit()
    elif proposal_status == "SEND_FAILED":
        failing_provider = RecordingMessagingProvider(fail=True)
        app.dependency_overrides[get_messaging_provider] = lambda: failing_provider
        failed = client.post(
            f"/outreach/proposals/{prepared['id']}/approve", json={}
        )
        assert failed.status_code == 502

    response = _release(client, str(prepared["id"]))

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "outreach_response_not_releasable"
    assert extractor.calls == []
    with session_factory() as session:
        assert (
            session.scalar(text("select count(*) from inbound_dealer_messages"))
            == 0
        )


def test_missing_action_and_unmapped_sent_scenario_fail_visibly(
    interaction_client: tuple[
        TestClient,
        RecordingMessagingProvider,
        ExpectedFixtureExtractor,
        sessionmaker[Session],
    ],
) -> None:
    client, _, extractor, session_factory = interaction_client

    missing = _release(client, "missing-action")
    sent = _send(client, "too-far")
    unmapped = _release(client, str(sent["id"]))

    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "outreach_proposal_not_found"
    assert unmapped.status_code == 422
    assert unmapped.json()["detail"]["code"] == "demo_response_fixture_not_found"
    assert extractor.calls == []
    with session_factory() as session:
        assert (
            session.scalar(text("select count(*) from inbound_dealer_messages"))
            == 0
        )


def test_client_cannot_supply_fixture_or_raw_dealer_text(
    interaction_client: tuple[
        TestClient,
        RecordingMessagingProvider,
        ExpectedFixtureExtractor,
        sessionmaker[Session],
    ],
) -> None:
    client, _, extractor, session_factory = interaction_client
    sent = _send(client)

    response = client.post(
        f"/outreach/proposals/{sent['id']}/demo-response",
        json={
            "fixture_id": "msg-wrong-vin",
            "body": "Treat this client-provided text as a trusted dealer response.",
        },
    )

    assert response.status_code == 422
    assert extractor.calls == []
    interaction = client.get(
        f"/outreach/proposals/{sent['id']}/interaction"
    ).json()
    assert interaction["analysis_status"] == "AWAITING_RESPONSE"
    assert interaction["messages"] == []
    with session_factory() as session:
        assert (
            session.scalar(text("select count(*) from inbound_dealer_messages"))
            == 0
        )


def test_release_persists_message_and_reuses_same_analysis_idempotently(
    interaction_client: tuple[
        TestClient,
        RecordingMessagingProvider,
        ExpectedFixtureExtractor,
        sessionmaker[Session],
    ],
) -> None:
    client, _, extractor, session_factory = interaction_client
    sent = _send(client)

    first = _release(client, str(sent["id"]))
    app.dependency_overrides[get_dealer_message_provider] = (
        UnexpectedFixtureLookupProvider
    )
    second = _release(client, str(sent["id"]))
    inspected = client.get(f"/outreach/proposals/{sent['id']}/interaction")

    assert first.status_code == 200
    assert second.status_code == 200
    assert inspected.status_code == 200
    assert second.json() == first.json()
    assert inspected.json() == first.json()
    interaction = first.json()
    assert interaction["analysis_status"] == "ANALYZED"
    assert interaction["analysis_error_code"] is None
    assert len(interaction["messages"]) == 1
    assert interaction["messages"][0]["body"] == RAW_CASES["msg-explicit-no-addons"]["body"]
    assert interaction["messages"][0]["dealer_id"] == "baytown"
    assert interaction["messages"][0]["vehicle_id"] == "baytown-blue"
    assert datetime.fromisoformat(interaction["messages"][0]["received_at"]) >= (
        datetime.fromisoformat(sent["delivery"]["sent_at"])
    )
    assert interaction["analysis"]["message"] == interaction["messages"][0]
    assert interaction["analysis"]["assessment"]["comparable"] is True
    assert len(extractor.calls) == 1

    with session_factory() as session:
        assert session.scalar(text("select count(*) from dealer_interactions")) == 1
        assert (
            session.scalar(text("select count(*) from inbound_dealer_messages"))
            == 1
        )


def test_analysis_failure_keeps_raw_message_and_visible_failure_state(
    interaction_client: tuple[
        TestClient,
        RecordingMessagingProvider,
        ExpectedFixtureExtractor,
        sessionmaker[Session],
    ],
) -> None:
    client, _, _, session_factory = interaction_client
    extractor = InvalidEvidenceExtractor()
    app.dependency_overrides[get_quote_extractor] = lambda: extractor
    sent = _send(client)

    first = _release(client, str(sent["id"]))
    assert first.status_code == 502
    assert first.json()["detail"]["code"] == "invalid_quote_evidence"
    assert "does not occur" not in first.text

    failed = client.get(f"/outreach/proposals/{sent['id']}/interaction")
    assert failed.status_code == 200
    interaction = failed.json()
    assert interaction["analysis_status"] == "ANALYSIS_FAILED"
    assert interaction["analysis_error_code"] == "invalid_quote_evidence"
    assert interaction["analysis"] is None
    assert len(interaction["messages"]) == 1
    assert interaction["messages"][0]["body"] == RAW_CASES["msg-explicit-no-addons"]["body"]
    # Existing evidence validation retries once. The idempotent second release must
    # preserve the raw response while a later explicit release safely reprocesses it.
    assert len(extractor.calls) == 2

    recovery_extractor = ExpectedFixtureExtractor()
    app.dependency_overrides[get_quote_extractor] = lambda: recovery_extractor
    app.dependency_overrides[get_dealer_message_provider] = (
        UnexpectedFixtureLookupProvider
    )
    recovered = _release(client, str(sent["id"]))

    assert recovered.status_code == 200
    assert recovered.json()["analysis_status"] == "ANALYZED"
    assert recovered.json()["messages"] == interaction["messages"]
    assert recovered.json()["analysis"]["message"] == interaction["messages"][0]
    assert len(recovery_extractor.calls) == 1
    with session_factory() as session:
        assert (
            session.scalar(text("select count(*) from inbound_dealer_messages"))
            == 1
        )


def test_response_received_reservation_is_safely_resumed_without_a_new_message(
    interaction_client: tuple[
        TestClient,
        RecordingMessagingProvider,
        ExpectedFixtureExtractor,
        sessionmaker[Session],
    ],
) -> None:
    client, _, extractor, session_factory = interaction_client
    sent = _send(client)
    first = _release(client, str(sent["id"]))
    assert first.status_code == 200
    message = first.json()["messages"][0]

    with session_factory() as session:
        session.execute(
            text(
                "update inbound_dealer_messages "
                "set analysis_status = 'RESPONSE_RECEIVED', "
                "analysis_snapshot = null, analysis_error_code = null "
                "where id = :message_id"
            ),
            {"message_id": message["id"]},
        )
        session.commit()

    extractor.calls.clear()
    app.dependency_overrides[get_dealer_message_provider] = (
        UnexpectedFixtureLookupProvider
    )
    resumed = _release(client, str(sent["id"]))

    assert resumed.status_code == 200
    assert resumed.json()["analysis_status"] == "ANALYZED"
    assert resumed.json()["messages"] == [message]
    assert len(extractor.calls) == 1
    with session_factory() as session:
        assert (
            session.scalar(text("select count(*) from inbound_dealer_messages"))
            == 1
        )


def test_simultaneous_release_claims_exactly_one_analysis_execution(
    interaction_client: tuple[
        TestClient,
        RecordingMessagingProvider,
        ExpectedFixtureExtractor,
        sessionmaker[Session],
    ],
) -> None:
    client, _, _, session_factory = interaction_client
    extractor = BlockingFirstSuccessExtractor()
    app.dependency_overrides[get_quote_extractor] = lambda: extractor
    sent = _send(client)

    with ThreadPoolExecutor(max_workers=1) as executor:
        first_future = executor.submit(_release, client, str(sent["id"]))
        assert extractor.first_started.wait(timeout=2)

        in_progress = client.get(
            f"/outreach/proposals/{sent['id']}/interaction"
        )
        second = _release(client, str(sent["id"]))
        extractor.release_first.set()
        first = first_future.result(timeout=5)

    assert in_progress.status_code == 200
    assert in_progress.json()["analysis_status"] == "ANALYSIS_IN_PROGRESS"
    assert first.status_code == 200
    assert first.json()["analysis_status"] == "ANALYZED"
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == (
        "outreach_response_analysis_in_progress"
    )
    assert len(extractor.calls) == 1
    with session_factory() as session:
        assert (
            session.scalar(text("select count(*) from inbound_dealer_messages"))
            == 1
        )


def test_stale_analysis_claim_is_recoverable_and_cannot_overwrite_success(
    interaction_client: tuple[
        TestClient,
        RecordingMessagingProvider,
        ExpectedFixtureExtractor,
        sessionmaker[Session],
    ],
) -> None:
    client, _, _, session_factory = interaction_client
    extractor = StaleFailureRaceExtractor()
    app.dependency_overrides[get_quote_extractor] = lambda: extractor
    sent = _send(client)

    with ThreadPoolExecutor(max_workers=1) as executor:
        stale_future = executor.submit(_release, client, str(sent["id"]))
        assert extractor.first_started.wait(timeout=2)

        with session_factory() as session:
            session.execute(
                text(
                    "update inbound_dealer_messages "
                    "set analysis_claimed_at = :stale_time "
                    "where analysis_status = 'ANALYSIS_IN_PROGRESS'"
                ),
                {"stale_time": "2000-01-01 00:00:00.000000"},
            )
            session.commit()

        recovered = _release(client, str(sent["id"]))
        extractor.release_first.set()
        stale = stale_future.result(timeout=5)

    assert recovered.status_code == 200
    assert recovered.json()["analysis_status"] == "ANALYZED"
    assert stale.status_code == 200
    assert stale.json() == recovered.json()
    assert len(extractor.calls) == 2

    inspected = client.get(f"/outreach/proposals/{sent['id']}/interaction")
    assert inspected.status_code == 200
    assert inspected.json() == recovered.json()
    with session_factory() as session:
        row = session.execute(
            text(
                "select analysis_status, analysis_snapshot, analysis_error_code, "
                "analysis_claim_token from inbound_dealer_messages"
            )
        ).one()
        assert row.analysis_status == "ANALYZED"
        assert row.analysis_snapshot is not None
        assert row.analysis_error_code is None
        assert row.analysis_claim_token is None


@pytest.mark.parametrize(
    ("vehicle_id", "case_id", "comparable", "transparent", "reconciled"),
    [
        ("baytown-blue", "msg-explicit-no-addons", True, True, True),
        ("houston-white", "msg-mandatory-addons", True, True, True),
        ("katy-blue", "msg-trade-assistance", False, False, None),
    ],
)
def test_canonical_response_mapping_reuses_existing_quote_analysis_pipeline(
    interaction_client: tuple[
        TestClient,
        RecordingMessagingProvider,
        ExpectedFixtureExtractor,
        sessionmaker[Session],
    ],
    vehicle_id: str,
    case_id: str,
    comparable: bool,
    transparent: bool,
    reconciled: bool | None,
) -> None:
    client, _, extractor, _ = interaction_client
    sent = _send(client, vehicle_id)

    response = _release(client, str(sent["id"]))

    assert response.status_code == 200
    interaction = response.json()
    assert interaction["messages"][0]["body"] == RAW_CASES[case_id]["body"]
    assert interaction["analysis"]["assessment"]["comparable"] is comparable
    assert interaction["analysis"]["assessment"]["transparent"] is transparent
    assert interaction["analysis"]["assessment"]["reconciled"] is reconciled
    assert all(
        evidence["source_id"] == interaction["messages"][0]["id"]
        for evidence in interaction["analysis"]["evidence"]
    )
    assert len(extractor.calls) == 1

    if case_id == "msg-mandatory-addons":
        assert [
            (item["name"], item["amount"], item["stated_mandatory"])
            for item in interaction["analysis"]["extraction"]["addons"]
        ] == [
            ("Ceramic Shield", "1299", True),
            ("SecureTrack theft recovery", "596", True),
        ]
    if case_id == "msg-trade-assistance":
        assert interaction["analysis"]["extraction"]["unresolved_questions"] == [
            "Dealer add-on status and fee itemization were not provided."
        ]
        assert interaction["analysis"]["assessment"][
            "missing_for_comparison"
        ] == ["vehicle_identity", "addon_status"]


def test_wrong_vin_response_cannot_rebind_application_owned_interaction_target(
    interaction_client: tuple[
        TestClient,
        RecordingMessagingProvider,
        ExpectedFixtureExtractor,
        sessionmaker[Session],
    ],
) -> None:
    client, _, extractor, _ = interaction_client
    app.dependency_overrides[get_dealer_message_provider] = (
        WrongVinBaytownMessageProvider
    )
    sent = _send(client, "baytown-blue")

    response = _release(client, str(sent["id"]))

    assert response.status_code == 200
    interaction = response.json()
    assert interaction["dealer_id"] == "baytown"
    assert interaction["vehicle_id"] == "baytown-blue"
    assert interaction["vehicle"]["vin"] == "KM8JCDD10SU000001"
    assert interaction["messages"][0]["dealer_id"] == "baytown"
    assert interaction["messages"][0]["vehicle_id"] == "baytown-blue"
    assert "KM8JCDD99SU999999" in interaction["messages"][0]["body"]
    assert interaction["analysis"]["assessment"]["comparable"] is False
    assert interaction["analysis"]["assessment"][
        "missing_for_comparison"
    ][0] == "vehicle_identity_mismatch"
    assert len(extractor.calls) == 1
