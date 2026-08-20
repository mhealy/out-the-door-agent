from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.dependencies import (
    get_dealer_message_provider,
    get_inventory_provider,
    get_messaging_provider,
    get_quote_extractor,
    get_research_provider,
    get_research_synthesizer,
)
from app.domain.evidence import Evidence
from app.domain.message import DealerMessage, DeliveryReceipt, OutboundDealerMessage
from app.domain.quote import QuoteAnalysisResult, QuoteAssessment, QuoteExtraction
from app.domain.research import (
    ResearchFindingDraft,
    ResearchProviderResult,
    ResearchRequest,
    ResearchSource,
    ResearchTarget,
)
from app.main import app
from app.persistence.db import build_engine, create_schema, get_session
from app.persistence.models import (
    DealerInteractionRecord,
    InboundDealerMessageRecord,
)
from app.providers.dealer_messages import FixtureDealerMessageProvider
from app.providers.inventory import FixtureInventoryProvider
from app.providers.quote_extraction import QuoteExtractorOutput
from app.services.research import ResearchService


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RAW_CASE_ID_BY_BODY = {
    record["body"]: record["id"]
    for record in json.loads(
        (
            REPOSITORY_ROOT / "demo/dealer_messages/quote_analysis_cases.json"
        ).read_text(encoding="utf-8")
    )
}
EXPECTED_OUTPUT_BY_CASE_ID = {
    record["case_id"]: QuoteExtractorOutput.model_validate(
        {
            "extraction": record["extraction"],
            "evidence": record["evidence"],
        }
    )
    for record in json.loads(
        (
            REPOSITORY_ROOT / "demo/expected/quote_analysis_expected.json"
        ).read_text(encoding="utf-8")
    )
}

PURCHASE_GOAL = "Compare written out-the-door offers for my selected vehicles."
RETRIEVED_AT = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
RESEARCH_SOURCES = [
    ResearchSource(
        id="vendor-product-page",
        url="https://vendor.example/products/vehicle-protection",
        title="Vehicle protection product overview",
        publisher="Example Protection Vendor",
        retrieved_at=RETRIEVED_AT,
        excerpt=(
            "The product page describes a dealer-applied exterior protection "
            "treatment and a limited product warranty."
        ),
    ),
    ResearchSource(
        id="independent-context",
        url="https://consumer.example/dealer-protection-products",
        title="Understanding dealer protection products",
        publisher="Independent Consumer Guide",
        retrieved_at=RETRIEVED_AT,
        excerpt=(
            "Dealer protection packages vary, and the exact included services "
            "must be confirmed from the package contract."
        ),
    ),
]


class ExpectedFixtureExtractor:
    async def extract(self, message: DealerMessage) -> QuoteExtractorOutput:
        case_id = RAW_CASE_ID_BY_BODY[message.body]
        return EXPECTED_OUTPUT_BY_CASE_ID[case_id].model_copy(deep=True)


class RecordingMessagingProvider:
    def __init__(self) -> None:
        self.calls: list[OutboundDealerMessage] = []

    async def send(self, message: OutboundDealerMessage) -> DeliveryReceipt:
        self.calls.append(message)
        return DeliveryReceipt(
            action_id=message.action_id,
            provider="research-api-test",
            external_message_id=f"research-{message.action_id}",
            sent_at=datetime.now(timezone.utc),
        )


class RecordingResearchProvider:
    def __init__(self) -> None:
        self.calls: list[ResearchRequest] = []
        self.block = False
        self.started = Event()
        self.release = Event()

    async def research(self, request: ResearchRequest) -> ResearchProviderResult:
        self.calls.append(request)
        if self.block:
            self.started.set()
            released = await asyncio.to_thread(self.release.wait, 10)
            if not released:
                raise TimeoutError("The research-provider test release timed out.")
        return ResearchProviderResult(
            sources=[source.model_copy(deep=True) for source in RESEARCH_SOURCES]
        )


class RecordingResearchSynthesizer:
    def __init__(self) -> None:
        self.calls: list[tuple[ResearchTarget, list[ResearchSource]]] = []
        self.return_unknown_source = False
        self.invalid_results_remaining = 0
        self.block = False
        self.started = Event()
        self.release = Event()

    async def synthesize(
        self,
        *,
        target: ResearchTarget,
        sources: list[ResearchSource],
    ) -> ResearchFindingDraft:
        self.calls.append((target, list(sources)))
        if self.block:
            self.started.set()
            released = await asyncio.to_thread(self.release.wait, 10)
            if not released:
                raise TimeoutError("The research-synthesizer test release timed out.")
        return_unknown_source = self.return_unknown_source
        if self.invalid_results_remaining > 0:
            self.invalid_results_remaining -= 1
            return_unknown_source = True
        source_ids = (
            ["model-invented-source"]
            if return_unknown_source
            else [source.id for source in sources]
        )
        return ResearchFindingDraft(
            target_id=target.target_id,
            target_name=target.canonical_name,
            summary=(
                f"Sources describe {target.canonical_name} as a dealer product, "
                "but the exact scope of this dealer's package is not established."
            ),
            what_it_appears_to_include=[
                "A dealer-applied protection product described by the vendor."
            ],
            limitations=[
                "The sources do not independently verify this dealer's exact package."
            ],
            source_ids=source_ids,
            support_status="SUPPORTED",
        )


@dataclass(frozen=True)
class ResearchHarness:
    session_factory: sessionmaker[Session]
    messaging: RecordingMessagingProvider
    provider: RecordingResearchProvider
    synthesizer: RecordingResearchSynthesizer


@pytest.fixture
def research_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[ResearchHarness]:
    application_database = tmp_path / "research-api.db"
    checkpoint_database = tmp_path / "research-api-checkpoints.db"
    engine = build_engine(f"sqlite:///{application_database}")
    create_schema(engine)
    test_session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    inventory = FixtureInventoryProvider()
    dealer_messages = FixtureDealerMessageProvider()
    messaging = RecordingMessagingProvider()
    provider = RecordingResearchProvider()
    synthesizer = RecordingResearchSynthesizer()

    def override_session() -> Iterator[Session]:
        with test_session_factory() as session:
            yield session

    monkeypatch.setenv(
        "OTD_LANGGRAPH_CHECKPOINT_PATH",
        str(checkpoint_database),
    )
    get_settings.cache_clear()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_inventory_provider] = lambda: inventory
    app.dependency_overrides[get_dealer_message_provider] = lambda: dealer_messages
    app.dependency_overrides[get_messaging_provider] = lambda: messaging
    app.dependency_overrides[get_quote_extractor] = ExpectedFixtureExtractor
    app.dependency_overrides[get_research_provider] = lambda: provider
    app.dependency_overrides[get_research_synthesizer] = lambda: synthesizer
    try:
        yield ResearchHarness(
            session_factory=test_session_factory,
            messaging=messaging,
            provider=provider,
            synthesizer=synthesizer,
        )
    finally:
        provider.release.set()
        synthesizer.release.set()
        app.dependency_overrides.clear()
        get_settings.cache_clear()
        engine.dispose()


def _create_purchase(
    client: TestClient,
    vehicle_ids: list[str] | None = None,
) -> dict[str, object]:
    response = client.post(
        "/purchase-runs",
        json={
            "creation_id": str(uuid4()),
            "goal": PURCHASE_GOAL,
            "vehicle_ids": vehicle_ids or ["houston-white", "baytown-blue"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _children_by_vehicle(
    workspace: dict[str, object],
) -> dict[str, dict[str, object]]:
    children = workspace["children"]
    assert isinstance(children, list)
    return {str(child["vehicle"]["id"]): child for child in children}


def _release_current_quote(
    client: TestClient,
    child: dict[str, object],
) -> dict[str, object]:
    run = child["agent_run"]
    assert isinstance(run, dict)
    initial_action_id = str(run["initial_action_id"])
    approved = client.post(
        f"/outreach/proposals/{initial_action_id}/approve",
        json={},
    )
    assert approved.status_code == 200, approved.text
    released = client.post(
        f"/outreach/proposals/{initial_action_id}/demo-response",
        json={},
    )
    assert released.status_code == 200, released.text
    assert released.json()["analysis_status"] == "ANALYZED"
    return released.json()


def _purchase_with_current_houston_quote(
    client: TestClient,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    workspace = _create_purchase(client)
    houston_child = _children_by_vehicle(workspace)["houston-white"]
    interaction = _release_current_quote(client, houston_child)
    return workspace, houston_child, interaction


def _get_targets(client: TestClient, purchase_id: str) -> list[dict[str, object]]:
    response = client.get(f"/purchase-runs/{purchase_id}/research-targets")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload, list)
    return payload


def _targets_by_name(
    targets: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    return {str(target["canonical_name"]): target for target in targets}


def _count_rows(harness: ResearchHarness, table_name: str) -> int:
    with harness.session_factory() as session:
        count = session.scalar(text(f"select count(*) from {table_name}"))
    assert count is not None
    return int(count)


def _table_snapshot(
    harness: ResearchHarness,
    table_names: tuple[str, ...],
) -> dict[str, list[dict[str, object]]]:
    with harness.session_factory() as session:
        return {
            table_name: [
                dict(row)
                for row in session.execute(
                    text(f"select * from {table_name} order by rowid")
                ).mappings()
            ]
            for table_name in table_names
        }


def _stage_replacement_quote_without_addons(
    session: Session,
    initial_action_id: str,
) -> str:
    message_id = str(uuid4())
    now = datetime.now(timezone.utc) + timedelta(seconds=1)
    interaction = session.scalar(
        select(DealerInteractionRecord).where(
            DealerInteractionRecord.initial_action_id == initial_action_id
        )
    )
    assert interaction is not None
    message = DealerMessage(
        id=message_id,
        dealer_id=interaction.dealer_id,
        vehicle_id=interaction.vehicle_id,
        subject="Revised written quote",
        body="The revised quote removes all dealer add-ons.",
        received_at=now,
        source_provider="research-api-test",
    )
    analysis = QuoteAnalysisResult(
        message=message,
        extraction=QuoteExtraction(
            vehicle_vin="KM8JCDD11SU000002",
            stock_number="H2002",
            selling_price="37500",
            claimed_otd="39885",
            addons=[],
            financing_required=False,
            trade_required=False,
            explicit_no_addons_statement=True,
            explicit_all_fees_included_statement=True,
            evidence_ids=[],
            extraction_confidence=1,
        ),
        evidence=[],
        assessment=QuoteAssessment(
            comparable=True,
            transparent=False,
            reconciled=None,
            missing_for_comparison=[],
            missing_for_transparency=[
                "dealer_fee_detail",
                "government_fee_detail",
            ],
        ),
    )
    session.add(
        InboundDealerMessageRecord(
            id=message_id,
            interaction_id=interaction.id,
            source_fixture_id=f"replacement-{message_id}",
            dealer_id=interaction.dealer_id,
            vehicle_id=interaction.vehicle_id,
            subject=message.subject,
            body=message.body,
            received_at=now,
            source_provider=message.source_provider,
            analysis_status="ANALYZED",
            analysis_snapshot=analysis.model_dump(
                mode="json",
                exclude={"message"},
            ),
            analyzed_at=now,
            created_at=now,
        )
    )
    return message_id


def _replace_current_quote_without_addons(
    harness: ResearchHarness,
    initial_action_id: str,
) -> str:
    with harness.session_factory() as session:
        message_id = _stage_replacement_quote_without_addons(
            session,
            initial_action_id,
        )
        session.commit()
    return message_id


def test_targets_are_reconstructed_from_current_persisted_purchase_quote(
    research_harness: ResearchHarness,
) -> None:
    del research_harness
    with TestClient(app) as client:
        workspace, houston_child, interaction = _purchase_with_current_houston_quote(
            client
        )
        first = _get_targets(client, str(workspace["id"]))
        second = _get_targets(client, str(workspace["id"]))

    assert first == second
    targets = _targets_by_name(first)
    assert list(targets) == ["Ceramic Shield", "SecureTrack theft recovery"]
    run = houston_child["agent_run"]
    assert isinstance(run, dict)
    source_message = interaction["analysis"]["message"]
    assert isinstance(source_message, dict)

    expected = {
        "Ceramic Shield": ("1299", {"ev-addons-ceramic"}),
        "SecureTrack theft recovery": ("596", {"ev-addons-theft"}),
    }
    for name, target in targets.items():
        UUID(str(target["target_id"]))
        assert target["purchase_run_id"] == workspace["id"]
        assert target["agent_run_id"] == run["id"]
        assert target["interaction_id"] == interaction["id"]
        assert target["source_message_id"] == source_message["id"]
        assert target["vehicle_id"] == "houston-white"
        assert target["dealer_id"] == "houston"
        assert target["dealer_name"] == "Houston Hyundai"
        assert target["target_type"] == "MANDATORY_ADDON"
        assert target["dealer_stated_amount"] == expected[name][0]
        assert target["stated_mandatory"] is True
        assert set(target["source_evidence_ids"]) == expected[name][1]
        assert target["recommended"] is True
        assert target["investigation"] is None


def test_stale_or_forged_target_is_rejected_before_research_executes(
    research_harness: ResearchHarness,
) -> None:
    with TestClient(app) as client:
        workspace, houston_child, _ = _purchase_with_current_houston_quote(client)
        purchase_id = str(workspace["id"])
        target = _targets_by_name(_get_targets(client, purchase_id))["Ceramic Shield"]
        run = houston_child["agent_run"]
        assert isinstance(run, dict)
        _replace_current_quote_without_addons(
            research_harness,
            str(run["initial_action_id"]),
        )

        stale = client.post(
            f"/purchase-runs/{purchase_id}/research-targets/"
            f"{target['target_id']}/investigate",
            json={},
        )
        forged = client.post(
            f"/purchase-runs/{purchase_id}/research-targets/forged-target/investigate",
            json={},
        )

    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "research_target_changed"
    assert forged.status_code == 409
    assert forged.json()["detail"]["code"] == "research_target_changed"
    assert research_harness.provider.calls == []
    assert research_harness.synthesizer.calls == []


def test_browser_cannot_replace_authoritative_target_facts(
    research_harness: ResearchHarness,
) -> None:
    with TestClient(app) as client:
        workspace, _, _ = _purchase_with_current_houston_quote(client)
        purchase_id = str(workspace["id"])
        target = _targets_by_name(_get_targets(client, purchase_id))["Ceramic Shield"]
        messaging_calls = len(research_harness.messaging.calls)
        response = client.post(
            f"/purchase-runs/{purchase_id}/research-targets/"
            f"{target['target_id']}/investigate",
            json={
                "canonical_name": "Browser-controlled product",
                "dealer_stated_amount": "1.00",
                "dealer_id": "browser-controlled-dealer",
            },
        )

    assert response.status_code == 422
    assert research_harness.provider.calls == []
    assert research_harness.synthesizer.calls == []
    assert len(research_harness.messaging.calls) == messaging_calls


def test_investigation_persists_and_is_idempotent_across_request_recreation(
    research_harness: ResearchHarness,
) -> None:
    with TestClient(app) as client:
        workspace, _, _ = _purchase_with_current_houston_quote(client)
        purchase_id = str(workspace["id"])
        target = _targets_by_name(_get_targets(client, purchase_id))["Ceramic Shield"]
        first = client.post(
            f"/purchase-runs/{purchase_id}/research-targets/"
            f"{target['target_id']}/investigate",
            json={},
        )
        assert first.status_code == 200, first.text

    with TestClient(app) as recreated_client:
        reloaded = _targets_by_name(
            _get_targets(recreated_client, purchase_id)
        )["Ceramic Shield"]
        repeated = recreated_client.post(
            f"/purchase-runs/{purchase_id}/research-targets/"
            f"{target['target_id']}/investigate",
            json={},
        )

    assert repeated.status_code == 200, repeated.text
    assert first.json() == reloaded == repeated.json()
    assert repeated.json()["recommended"] is False
    investigation = repeated.json()["investigation"]
    assert investigation["status"] == "COMPLETED"
    assert investigation["finding"]["target_id"] == target["target_id"]
    assert investigation["finding"]["source_ids"] == [
        "vendor-product-page",
        "independent-context",
    ]
    sources = {source["id"]: source for source in investigation["sources"]}
    assert sources["vendor-product-page"]["url"] == RESEARCH_SOURCES[0].url
    assert sources["vendor-product-page"]["title"] == RESEARCH_SOURCES[0].title
    assert sources["vendor-product-page"]["publisher"] == RESEARCH_SOURCES[0].publisher
    assert sources["vendor-product-page"]["excerpt"] == RESEARCH_SOURCES[0].excerpt
    assert len(research_harness.provider.calls) == 1
    assert len(research_harness.synthesizer.calls) == 1
    assert research_harness.provider.calls[0].model_dump() == {
        "target_id": target["target_id"],
        "target_type": "MANDATORY_ADDON",
        "canonical_name": "Ceramic Shield",
    }
    assert _count_rows(research_harness, "research_findings") == 1
    assert _count_rows(research_harness, "research_sources") == 2


def test_invalid_synthesis_preserves_provider_sources_and_visible_failure(
    research_harness: ResearchHarness,
) -> None:
    research_harness.synthesizer.return_unknown_source = True
    with TestClient(app) as client:
        workspace, _, _ = _purchase_with_current_houston_quote(client)
        purchase_id = str(workspace["id"])
        target = _targets_by_name(_get_targets(client, purchase_id))["Ceramic Shield"]
        response = client.post(
            f"/purchase-runs/{purchase_id}/research-targets/"
            f"{target['target_id']}/investigate",
            json={},
        )
        reloaded = _targets_by_name(_get_targets(client, purchase_id))[
            "Ceramic Shield"
        ]

    assert response.status_code == 502
    investigation = reloaded["investigation"]
    assert reloaded["recommended"] is True
    assert investigation["status"] == "FAILED"
    assert investigation["finding"] is None
    assert investigation["error_code"]
    assert [source["id"] for source in investigation["sources"]] == [
        "vendor-product-page",
        "independent-context",
    ]
    assert len(research_harness.provider.calls) == 1
    assert len(research_harness.synthesizer.calls) == 2
    assert _count_rows(research_harness, "research_findings") == 1
    assert _count_rows(research_harness, "research_sources") == 2


def test_deterministic_validation_retries_synthesis_once_without_reretrieval(
    research_harness: ResearchHarness,
) -> None:
    research_harness.synthesizer.invalid_results_remaining = 1

    with TestClient(app) as client:
        workspace, _, _ = _purchase_with_current_houston_quote(client)
        purchase_id = str(workspace["id"])
        target = _targets_by_name(_get_targets(client, purchase_id))["Ceramic Shield"]
        response = client.post(
            f"/purchase-runs/{purchase_id}/research-targets/"
            f"{target['target_id']}/investigate",
            json={},
        )

    assert response.status_code == 200, response.text
    assert response.json()["investigation"]["status"] == "COMPLETED"
    assert len(research_harness.provider.calls) == 1
    assert len(research_harness.synthesizer.calls) == 2
    assert _count_rows(research_harness, "research_findings") == 1
    assert _count_rows(research_harness, "research_sources") == 2


def test_failed_investigation_is_reclaimed_once_and_completed_stays_idempotent(
    research_harness: ResearchHarness,
) -> None:
    research_harness.synthesizer.return_unknown_source = True
    with TestClient(app) as client:
        workspace, _, _ = _purchase_with_current_houston_quote(client)
        purchase_id = str(workspace["id"])
        target = _targets_by_name(_get_targets(client, purchase_id))["Ceramic Shield"]
        first = client.post(
            f"/purchase-runs/{purchase_id}/research-targets/"
            f"{target['target_id']}/investigate",
            json={},
        )

    assert first.status_code == 502
    assert first.json()["detail"]["code"] == "research_finding_invalid"

    research_harness.synthesizer.return_unknown_source = False
    research_harness.provider.block = True

    def retry_once():
        with TestClient(app) as retry_client:
            return retry_client.post(
                f"/purchase-runs/{purchase_id}/research-targets/"
                f"{target['target_id']}/investigate",
                json={},
            )

    with ThreadPoolExecutor(max_workers=1) as executor:
        retry_future = executor.submit(retry_once)
        assert research_harness.provider.started.wait(5)
        try:
            with TestClient(app) as concurrent_client:
                concurrent = concurrent_client.post(
                    f"/purchase-runs/{purchase_id}/research-targets/"
                    f"{target['target_id']}/investigate",
                    json={},
                )
        finally:
            research_harness.provider.release.set()
        retried = retry_future.result(timeout=10)

    with TestClient(app) as completed_client:
        repeated = completed_client.post(
            f"/purchase-runs/{purchase_id}/research-targets/"
            f"{target['target_id']}/investigate",
            json={},
        )

    assert concurrent.status_code == 409
    assert concurrent.json()["detail"]["code"] == "research_in_progress"
    assert retried.status_code == 200, retried.text
    assert retried.json()["investigation"]["status"] == "COMPLETED"
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == retried.json()
    assert len(research_harness.provider.calls) == 2
    assert len(research_harness.synthesizer.calls) == 3
    assert _count_rows(research_harness, "research_findings") == 1
    assert _count_rows(research_harness, "research_sources") == 2


def test_final_freshness_read_is_serialized_with_completion(
    research_harness: ResearchHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_freshness_finished = Event()
    freshness_call_lock = Lock()
    freshness_calls = 0
    original_require_current = ResearchService._require_still_current

    def observe_freshness(
        service: ResearchService,
        expected: ResearchTarget,
    ) -> None:
        nonlocal freshness_calls
        try:
            original_require_current(service, expected)
        finally:
            with freshness_call_lock:
                freshness_calls += 1
                call_number = freshness_calls
            if call_number == 2:
                final_freshness_finished.set()

    monkeypatch.setattr(
        ResearchService,
        "_require_still_current",
        observe_freshness,
    )
    research_harness.synthesizer.block = True

    with TestClient(app) as client:
        workspace, houston_child, _ = _purchase_with_current_houston_quote(client)
        purchase_id = str(workspace["id"])
        target = _targets_by_name(_get_targets(client, purchase_id))["Ceramic Shield"]
        run = houston_child["agent_run"]
        assert isinstance(run, dict)

    def investigate_once():
        with TestClient(app) as research_client:
            return research_client.post(
                f"/purchase-runs/{purchase_id}/research-targets/"
                f"{target['target_id']}/investigate",
                json={},
            )

    with ThreadPoolExecutor(max_workers=1) as executor:
        research_future = executor.submit(investigate_once)
        assert research_harness.synthesizer.started.wait(5)
        with research_harness.session_factory() as replacement_session:
            _stage_replacement_quote_without_addons(
                replacement_session,
                str(run["initial_action_id"]),
            )
            replacement_session.flush()
            research_harness.synthesizer.release.set()

            # The replacement owns SQLite's write lock but is not committed yet.
            # A correct completion path must wait for it before its final authority
            # read. A read-then-write path leaks through here and persists stale work.
            freshness_escaped_before_replacement_commit = (
                final_freshness_finished.wait(1)
            )
            replacement_session.commit()
        response = research_future.result(timeout=10)

    with TestClient(app) as current_client:
        current_targets = _get_targets(current_client, purchase_id)

    with research_harness.session_factory() as audit_session:
        audit = audit_session.execute(
            text("select status, error_code from research_findings")
        ).one()

    assert freshness_escaped_before_replacement_commit is False
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "research_target_changed"
    assert current_targets == []
    assert audit == ("FAILED", "research_target_changed")
    assert _count_rows(research_harness, "research_findings") == 1
    assert _count_rows(research_harness, "research_sources") == 2


def test_completed_old_finding_remains_auditable_but_is_not_current(
    research_harness: ResearchHarness,
) -> None:
    with TestClient(app) as client:
        workspace, houston_child, _ = _purchase_with_current_houston_quote(client)
        purchase_id = str(workspace["id"])
        target = _targets_by_name(_get_targets(client, purchase_id))["Ceramic Shield"]
        completed = client.post(
            f"/purchase-runs/{purchase_id}/research-targets/"
            f"{target['target_id']}/investigate",
            json={},
        )
        assert completed.status_code == 200, completed.text
        run = houston_child["agent_run"]
        assert isinstance(run, dict)
        _replace_current_quote_without_addons(
            research_harness,
            str(run["initial_action_id"]),
        )
        current_targets = _get_targets(client, purchase_id)

    assert current_targets == []
    assert _count_rows(research_harness, "research_findings") == 1
    assert _count_rows(research_harness, "research_sources") == 2


def test_concurrent_investigation_executes_provider_once(
    research_harness: ResearchHarness,
) -> None:
    with TestClient(app) as client:
        workspace, _, _ = _purchase_with_current_houston_quote(client)
        purchase_id = str(workspace["id"])
        target = _targets_by_name(_get_targets(client, purchase_id))["Ceramic Shield"]

    research_harness.provider.block = True

    def investigate_once():
        with TestClient(app) as concurrent_client:
            return concurrent_client.post(
                f"/purchase-runs/{purchase_id}/research-targets/"
                f"{target['target_id']}/investigate",
                json={},
            )

    with ThreadPoolExecutor(max_workers=1) as executor:
        first_future = executor.submit(investigate_once)
        assert research_harness.provider.started.wait(5)
        try:
            with TestClient(app) as second_client:
                concurrent = second_client.post(
                    f"/purchase-runs/{purchase_id}/research-targets/"
                    f"{target['target_id']}/investigate",
                    json={},
                )
        finally:
            research_harness.provider.release.set()
        first = first_future.result(timeout=10)

    assert first.status_code == 200, first.text
    assert concurrent.status_code == 409
    assert concurrent.json()["detail"]["code"] == "research_in_progress"
    assert len(research_harness.provider.calls) == 1
    assert len(research_harness.synthesizer.calls) == 1
    assert _count_rows(research_harness, "research_findings") == 1


def test_research_leaves_offer_comparison_and_messaging_exactly_unchanged(
    research_harness: ResearchHarness,
) -> None:
    with TestClient(app) as client:
        workspace = _create_purchase(client)
        children = _children_by_vehicle(workspace)
        _release_current_quote(client, children["houston-white"])
        _release_current_quote(client, children["baytown-blue"])

        before_response = client.get(f"/purchase-runs/{workspace['id']}")
        assert before_response.status_code == 200, before_response.text
        before = before_response.json()["comparison"]
        messaging_calls = list(research_harness.messaging.calls)

        target = _targets_by_name(
            _get_targets(client, str(workspace["id"]))
        )["Ceramic Shield"]
        protected_tables = (
            "purchase_runs",
            "purchase_run_vehicles",
            "agent_runs",
            "agent_events",
            "proposed_actions",
            "approvals",
            "outbound_deliveries",
            "dealer_interactions",
            "dealer_interaction_followups",
            "dealer_interaction_followup_states",
            "inbound_dealer_messages",
        )
        protected_before = _table_snapshot(
            research_harness,
            protected_tables,
        )
        investigated = client.post(
            f"/purchase-runs/{workspace['id']}/research-targets/"
            f"{target['target_id']}/investigate",
            json={},
        )
        assert investigated.status_code == 200, investigated.text

        after_response = client.get(f"/purchase-runs/{workspace['id']}")
        assert after_response.status_code == 200, after_response.text
        after = after_response.json()["comparison"]
        protected_after = _table_snapshot(
            research_harness,
            protected_tables,
        )

    assert before == after
    assert before["recommendation"]["recommended_dealer_id"] == "baytown"
    assert before["recommendation"]["recommended_otd"] == "40315"
    assert before["ranked_agent_run_ids"] == after["ranked_agent_run_ids"]
    assert protected_after == protected_before
    assert research_harness.messaging.calls == messaging_calls
