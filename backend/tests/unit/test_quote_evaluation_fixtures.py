import json
from pathlib import Path

from app.domain.message import DealerMessage
from app.providers.quote_extraction import QuoteExtractorOutput
from app.services.evidence_validation import validate_evidence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RAW_CASES_PATH = (
    REPOSITORY_ROOT / "demo" / "dealer_messages" / "quote_analysis_cases.json"
)
EXPECTED_CASES_PATH = (
    REPOSITORY_ROOT / "demo" / "expected" / "quote_analysis_expected.json"
)


def test_labeled_quote_dataset_is_broad_typed_and_source_traceable() -> None:
    raw_values = json.loads(RAW_CASES_PATH.read_text(encoding="utf-8"))
    expected_values = json.loads(EXPECTED_CASES_PATH.read_text(encoding="utf-8"))
    messages = {
        value["id"]: DealerMessage(**value, source_provider="fixture")
        for value in raw_values
    }

    assert len(messages) >= 13
    assert len(expected_values) == len(messages)
    assert {
        "msg-fully-itemized",
        "msg-otd-without-itemization",
        "msg-plus-ttl",
        "msg-financing-rebate",
        "msg-trade-assistance",
        "msg-military-incentive",
        "msg-college-incentive",
        "msg-mandatory-addons",
        "msg-explicit-no-addons",
        "msg-inconsistent-math",
        "msg-wrong-vin",
        "msg-multiple-vehicles",
        "msg-expiring-quote",
        "msg-refusal-store-visit",
        "msg-prompt-injection",
    }.issubset(messages)

    for value in expected_values:
        case_id = value["case_id"]
        output = QuoteExtractorOutput.model_validate(
            {
                "extraction": value["extraction"],
                "evidence": value["evidence"],
            }
        )
        evidence = validate_evidence(messages[case_id], output)
        assert {item.id for item in evidence} == set(output.extraction.evidence_ids)


def test_plus_ttl_label_does_not_invent_complete_quote_terms() -> None:
    expected_values = json.loads(EXPECTED_CASES_PATH.read_text(encoding="utf-8"))
    value = next(
        item for item in expected_values if item["case_id"] == "msg-plus-ttl"
    )
    extraction = QuoteExtractorOutput.model_validate(
        {"extraction": value["extraction"], "evidence": value["evidence"]}
    ).extraction

    assert extraction.selling_price is not None
    assert extraction.claimed_otd is None
    assert extraction.addons == []
    assert extraction.financing_required is None
    assert extraction.trade_required is None
