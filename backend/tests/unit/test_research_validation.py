from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain.research import (
    ResearchFindingDraft,
    ResearchSource,
    ResearchTarget,
)
from app.services.research_validation import (
    ResearchFindingValidationError,
    validate_research_finding,
)


NOW = datetime(2026, 8, 19, 16, 0, tzinfo=timezone.utc)


def _target(**updates: object) -> ResearchTarget:
    value: dict[str, object] = {
        "target_id": "target-ceramic-v1",
        "purchase_run_id": "purchase-1",
        "agent_run_id": "run-houston",
        "interaction_id": "interaction-houston",
        "source_message_id": "message-houston-v1",
        "dealer_id": "houston",
        "dealer_name": "Houston Hyundai",
        "vehicle_id": "houston-white",
        "target_type": "MANDATORY_ADDON",
        "canonical_name": "Ceramic Shield",
        "dealer_stated_amount": "1299",
        "stated_mandatory": True,
        "source_evidence_ids": ["ev-addons-ceramic"],
    }
    value.update(updates)
    return ResearchTarget.model_validate(value)


def _source(source_id: str, **updates: object) -> ResearchSource:
    value: dict[str, object] = {
        "id": source_id,
        "url": f"https://example.test/research/{source_id}",
        "title": f"Source {source_id}",
        "publisher": "Fixture Research Publisher",
        "retrieved_at": NOW,
        "excerpt": f"Bounded provider excerpt for {source_id}.",
    }
    value.update(updates)
    return ResearchSource.model_validate(value)


def _draft(**updates: object) -> ResearchFindingDraft:
    value: dict[str, object] = {
        "target_id": "target-ceramic-v1",
        "target_name": "Ceramic Shield",
        "summary": (
            "Sources describe Ceramic Shield as a dealer-applied protection product; "
            "the exact scope of this dealer's package was not independently verified."
        ),
        "what_it_appears_to_include": ["Dealer-applied exterior protection"],
        "limitations": ["The dealer-specific package contract was not supplied."],
        "source_ids": ["vendor-ceramic", "independent-ceramic"],
        "support_status": "SUPPORTED",
    }
    value.update(updates)
    return ResearchFindingDraft.model_validate(value)


def test_validated_finding_preserves_target_and_provider_owned_sources() -> None:
    target = _target()
    sources = [_source("vendor-ceramic"), _source("independent-ceramic")]
    draft = _draft()

    finding = validate_research_finding(target, sources, draft)

    assert finding.target_id == target.target_id
    assert finding.target_name == target.canonical_name
    assert finding.summary == draft.summary
    assert finding.what_it_appears_to_include == draft.what_it_appears_to_include
    assert finding.limitations == draft.limitations
    assert finding.source_ids == draft.source_ids
    assert finding.support_status == "SUPPORTED"
    assert [source.model_dump() for source in finding.sources] == [
        source.model_dump() for source in sources
    ]


@pytest.mark.parametrize(
    ("updates", "match"),
    [
        ({"target_id": "browser-target"}, "target"),
        ({"target_name": "A different dealer product"}, "target"),
    ],
)
def test_model_cannot_replace_application_owned_target_identity(
    updates: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(ResearchFindingValidationError, match=match):
        validate_research_finding(
            _target(),
            [_source("vendor-ceramic"), _source("independent-ceramic")],
            _draft(**updates),
        )


def test_unknown_source_reference_is_rejected() -> None:
    with pytest.raises(ResearchFindingValidationError, match="unknown"):
        validate_research_finding(
            _target(),
            [_source("vendor-ceramic")],
            _draft(source_ids=["vendor-ceramic", "invented-source"]),
        )


def test_duplicate_source_references_are_rejected() -> None:
    with pytest.raises(ResearchFindingValidationError, match="duplicate"):
        validate_research_finding(
            _target(),
            [_source("vendor-ceramic")],
            _draft(source_ids=["vendor-ceramic", "vendor-ceramic"]),
        )


def test_duplicate_provider_source_ids_are_rejected_before_lookup() -> None:
    with pytest.raises(ResearchFindingValidationError, match="duplicate"):
        validate_research_finding(
            _target(),
            [_source("vendor-ceramic"), _source("vendor-ceramic")],
            _draft(source_ids=["vendor-ceramic"]),
        )


@pytest.mark.parametrize("support_status", ["SUPPORTED", "MIXED"])
def test_supported_or_mixed_finding_requires_at_least_one_cited_source(
    support_status: str,
) -> None:
    with pytest.raises(ResearchFindingValidationError, match="source"):
        validate_research_finding(
            _target(),
            [],
            _draft(source_ids=[], support_status=support_status),
        )


def test_insufficient_finding_may_truthfully_have_no_external_source() -> None:
    draft = _draft(
        summary="No legitimate external corroboration was retrieved.",
        what_it_appears_to_include=[],
        limitations=["The available sources were insufficient."],
        source_ids=[],
        support_status="INSUFFICIENT",
    )

    finding = validate_research_finding(_target(), [], draft)

    assert finding.support_status == "INSUFFICIENT"
    assert finding.source_ids == []
    assert finding.sources == []


@pytest.mark.parametrize(
    "draft",
    [
        ResearchFindingDraft.model_construct(
            target_id="target-ceramic-v1",
            target_name="Ceramic Shield",
            summary="x" * 50_000,
            what_it_appears_to_include=[],
            limitations=[],
            source_ids=[],
            support_status="INSUFFICIENT",
        ),
        ResearchFindingDraft.model_construct(
            target_id="target-ceramic-v1",
            target_name="Ceramic Shield",
            summary="Bounded summary.",
            what_it_appears_to_include=["item"] * 100,
            limitations=[],
            source_ids=[],
            support_status="INSUFFICIENT",
        ),
        ResearchFindingDraft.model_construct(
            target_id="target-ceramic-v1",
            target_name="Ceramic Shield",
            summary="   ",
            what_it_appears_to_include=[],
            limitations=[],
            source_ids=[],
            support_status="INSUFFICIENT",
        ),
    ],
)
def test_deterministic_validator_rechecks_bounds_even_for_constructed_models(
    draft: ResearchFindingDraft,
) -> None:
    with pytest.raises(ResearchFindingValidationError, match="bound|summary|size"):
        validate_research_finding(_target(), [], draft)


def test_model_schema_cannot_carry_prohibited_judgments_or_source_metadata() -> None:
    base = _draft().model_dump()

    for field, value in (
        ("is_scam", False),
        ("fair_price", "100"),
        ("dealer_trust_score", 0.9),
        ("should_buy", True),
        ("replacement_market_value", "50"),
        ("sources", [_source("fabricated").model_dump(mode="json")]),
    ):
        with pytest.raises(ValidationError):
            ResearchFindingDraft.model_validate({**base, field: value})


def test_provider_metadata_cannot_be_replaced_by_model_output() -> None:
    provider_source = _source(
        "vendor-ceramic",
        url="https://provider.example.test/ceramic",
        title="Provider-owned title",
        publisher="Provider-owned publisher",
        excerpt="Provider-owned bounded excerpt.",
    )
    draft = _draft(source_ids=[provider_source.id])

    finding = validate_research_finding(_target(), [provider_source], draft)

    assert finding.sources == [provider_source]
    assert finding.sources[0].url == provider_source.url
    assert finding.sources[0].title == "Provider-owned title"
    assert finding.sources[0].publisher == "Provider-owned publisher"
    assert finding.sources[0].excerpt == "Provider-owned bounded excerpt."


def test_research_contracts_forbid_browser_supplied_economics_and_unknown_fields() -> None:
    target = _target().model_dump(mode="json")
    with pytest.raises(ValidationError):
        ResearchTarget.model_validate({**target, "claimed_otd": "1.00"})

    with pytest.raises(ValidationError):
        ResearchTarget.model_validate(
            {**target, "source_evidence_ids": ["ev-addons-ceramic"] * 2}
        )


def test_research_source_requires_bounded_http_provenance() -> None:
    source = _source("source").model_dump(mode="json")

    for updates in (
        {"id": "   "},
        {"url": "file:///tmp/not-public"},
        {"title": ""},
        {"title": "   "},
        {"publisher": ""},
        {"excerpt": ""},
        {"excerpt": "   "},
        {"excerpt": "x" * 100_000},
        {"unexpected": "model supplied"},
    ):
        with pytest.raises(ValidationError):
            ResearchSource.model_validate({**source, **updates})
