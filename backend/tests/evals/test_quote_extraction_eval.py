import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.config import Settings
from app.domain.message import DealerMessage
from app.domain.quote import Incentive, MoneyItem, QuoteExtraction
from app.providers.quote_extraction import (
    EvidenceDraft,
    OpenAIQuoteExtractor,
    QuoteExtractorOutput,
)
from app.services.evidence_validation import EvidenceValidationError, validate_evidence


pytestmark = pytest.mark.eval
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RAW_CASES_PATH = (
    REPOSITORY_ROOT / "demo" / "dealer_messages" / "quote_analysis_cases.json"
)
EXPECTED_CASES_PATH = (
    REPOSITORY_ROOT / "demo" / "expected" / "quote_analysis_expected.json"
)
RAW_CASES = {
    value["id"]: value
    for value in json.loads(RAW_CASES_PATH.read_text(encoding="utf-8"))
}
EXPECTED_CASES = json.loads(EXPECTED_CASES_PATH.read_text(encoding="utf-8"))
SCALAR_FIELDS = (
    "vehicle_vin",
    "stock_number",
    "selling_price",
    "claimed_otd",
    "expiration",
    "explicit_no_addons_statement",
    "explicit_all_fees_included_statement",
)
STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "by",
        "for",
        "from",
        "has",
        "have",
        "is",
        "it",
        "of",
        "on",
        "or",
        "our",
        "that",
        "the",
        "this",
        "through",
        "to",
        "was",
        "we",
        "were",
        "with",
        "your",
    }
)
TOKEN_ALIASES = {
    "addons": "addon",
    "charges": "charge",
    "fees": "fee",
    "incentives": "incentive",
    "items": "item",
    "products": "product",
    "quotes": "quote",
    "quoted": "quote",
    "quoting": "quote",
    "taxes": "tax",
    "vin": "vehicle",
}
FIELD_LABELS = {
    "vehicle_vin": "vin",
    "stock_number": "stock number",
    "selling_price": "selling price",
    "claimed_otd": "claimed out the door total",
    "dealer_fees": "dealer fee",
    "government_fees": "government fee",
    "addons": "dealer addon",
    "incentives": "incentive",
    "financing_required": "financing required",
    "trade_required": "trade required",
    "explicit_no_addons_statement": "no dealer addons",
    "explicit_all_fees_included_statement": "all fees included",
}
POLARITY_FIELDS = {
    "financing_required",
    "trade_required",
    "explicit_no_addons_statement",
    "explicit_all_fees_included_statement",
}
NEGATION_TOKENS = {"cannot", "never", "no", "not", "without"}
QUESTION_CONCEPT_ANCHORS = (
    frozenset({"breakdown"}),
    frozenset({"out", "door", "total"}),
    frozenset({"tax", "title", "license"}),
    frozenset({"addon"}),
    frozenset({"eligibility"}),
    frozenset({"store", "visit"}),
    frozenset({"vehicle", "which"}),
    frozenset({"quote", "email"}),
    frozenset({"financing"}),
    frozenset({"trade"}),
)
QUESTION_VEHICLE_TOKENS = frozenset({"vehicle", "vehicles"})
QUESTION_SELECTION_TOKENS = frozenset(
    {"select", "selected", "selection", "which"}
)


def _tokens(value: str) -> set[str]:
    normalized = value.casefold().replace(",", "")
    normalized = normalized.replace("out-the-door", "out the door")
    normalized = normalized.replace("trade-in", "trade")
    normalized = normalized.replace("add-on", "addon")
    normalized = normalized.replace("line-item", "itemized")
    normalized = normalized.replace("itemization", "breakdown")
    normalized = normalized.replace("itemized", "breakdown")
    normalized = re.sub(r"\botd\b", "out the door total", normalized)
    normalized = re.sub(r"\bttl\b", "tax title license", normalized)
    normalized = re.sub(
        r"\brequir(?:e|es|ed|ing|ement|ements)\b", "require", normalized
    )
    normalized = re.sub(r"\binclud(?:e|es|ed|ing)\b", "include", normalized)
    normalized = re.sub(
        r"\b(?:expires?|expiring|expiration)\b", "expiration", normalized
    )
    tokens = re.findall(r"[a-z0-9]+", normalized)
    return {
        TOKEN_ALIASES.get(token, token)
        for token in tokens
        if token not in STOP_WORDS
    }


def _semantic_recall(actual: str, expected: str) -> float:
    expected_tokens = _tokens(expected)
    if not expected_tokens:
        return float(actual.casefold().strip() == expected.casefold().strip())
    return len(_tokens(actual) & expected_tokens) / len(expected_tokens)


def _optional_text_matches(
    actual: str | None,
    expected: str | None,
    *,
    threshold: float,
) -> bool:
    if expected is None:
        return actual is None
    return actual is not None and _semantic_recall(actual, expected) >= threshold


def _money_item_matches(actual: MoneyItem, expected: MoneyItem) -> bool:
    return (
        actual.amount == expected.amount
        and actual.stated_mandatory == expected.stated_mandatory
        and _semantic_recall(actual.name, expected.name) >= 0.45
    )


def _money_items_match(
    actual: list[MoneyItem], expected: list[MoneyItem]
) -> bool:
    remaining = list(actual)
    for expected_item in expected:
        index = next(
            (
                index
                for index, actual_item in enumerate(remaining)
                if _money_item_matches(actual_item, expected_item)
            ),
            None,
        )
        if index is None:
            return False
        remaining.pop(index)
    return not remaining


def _incentive_matches(actual: Incentive, expected: Incentive) -> bool:
    return (
        actual.amount == expected.amount
        and actual.requires_financing == expected.requires_financing
        and actual.requires_trade == expected.requires_trade
        and _semantic_recall(actual.name, expected.name) >= 0.33
        and _optional_text_matches(
            actual.eligibility_condition,
            expected.eligibility_condition,
            threshold=0.3,
        )
    )


def _incentives_match(
    actual: list[Incentive], expected: list[Incentive]
) -> bool:
    remaining = list(actual)
    for expected_item in expected:
        index = next(
            (
                index
                for index, actual_item in enumerate(remaining)
                if _incentive_matches(actual_item, expected_item)
            ),
            None,
        )
        if index is None:
            return False
        remaining.pop(index)
    return not remaining


def _question_checks(
    actual: list[str], expected: list[str]
) -> tuple[list[bool], list[bool]]:
    if not actual and not expected:
        return [True], [True]
    expected_recall = [
        any(_question_concept_matches(item, concept) for item in actual)
        for concept in expected
    ]
    actual_precision = [
        any(_question_concept_matches(item, concept) for concept in expected)
        for item in actual
    ]
    return expected_recall, actual_precision


def _question_concept_matches(actual: str, expected: str) -> bool:
    actual_tokens = _tokens(actual)
    expected_tokens = _tokens(expected)
    if (
        actual_tokens & QUESTION_VEHICLE_TOKENS
        and expected_tokens & QUESTION_VEHICLE_TOKENS
        and actual_tokens & QUESTION_SELECTION_TOKENS
        and expected_tokens & QUESTION_SELECTION_TOKENS
    ):
        return True
    if any(
        anchor.issubset(actual_tokens) and anchor.issubset(expected_tokens)
        for anchor in QUESTION_CONCEPT_ANCHORS
    ):
        return True
    overlap = actual_tokens & expected_tokens
    shortest = min(len(actual_tokens), len(expected_tokens))
    return shortest > 0 and len(overlap) >= 2 and len(overlap) / shortest >= 0.4


def test_question_matcher_accepts_equivalent_vehicle_selection_uncertainty() -> None:
    expected_case = next(
        case for case in EXPECTED_CASES if case["case_id"] == "msg-multiple-vehicles"
    )
    expected_question = expected_case["extraction"]["unresolved_questions"][0]
    actual_question = (
        "The response provides distinct terms for two vehicles, so the applicable "
        "VIN, stock number, selling price, and OTD are ambiguous until a vehicle "
        "is selected."
    )

    assert _question_checks([actual_question], [expected_question]) == (
        [True],
        [True],
    )


def _evidence_claim_text(
    extraction: QuoteExtraction, draft: EvidenceDraft
) -> str:
    field_name = draft.field_name
    label = FIELD_LABELS.get(field_name, "")
    if field_name in {
        "vehicle_vin",
        "stock_number",
        "selling_price",
        "claimed_otd",
    }:
        value = getattr(extraction, field_name)
        return f"{label} {value}" if value is not None else ""
    if field_name == "financing_required":
        value = extraction.financing_required
        return "" if value is None else f"{'no ' if not value else ''}{label}"
    if field_name == "trade_required":
        value = extraction.trade_required
        return "" if value is None else f"{'no ' if not value else ''}{label}"
    if field_name in {
        "explicit_no_addons_statement",
        "explicit_all_fees_included_statement",
    }:
        return label if getattr(extraction, field_name) else ""
    if field_name in {"dealer_fees", "government_fees", "addons", "incentives"}:
        parts = [label]
        for item in getattr(extraction, field_name):
            if item.evidence_id != draft.id:
                continue
            parts.append(item.name)
            if item.amount is not None:
                parts.append(str(item.amount))
            if isinstance(item, Incentive):
                if item.eligibility_condition:
                    parts.append(item.eligibility_condition)
                if item.requires_financing:
                    parts.append("financing required")
                if item.requires_trade:
                    parts.append("trade required")
        return " ".join(parts) if len(parts) > 1 else ""
    return ""


def _draft_supports_expected_claim(
    actual: EvidenceDraft,
    expected: EvidenceDraft,
    expected_extraction: QuoteExtraction,
) -> bool:
    if actual.field_name != expected.field_name:
        return False
    if expected.field_name == "unresolved_questions":
        return _question_concept_matches(actual.excerpt, expected.excerpt)
    claim_text = _evidence_claim_text(expected_extraction, expected)
    reference_text = claim_text or expected.excerpt
    if expected.field_name in POLARITY_FIELDS:
        actual_is_negated = bool(_tokens(actual.excerpt) & NEGATION_TOKENS)
        expected_is_negated = bool(_tokens(reference_text) & NEGATION_TOKENS)
        if actual_is_negated != expected_is_negated:
            return False
    threshold = 0.5 if claim_text else 0.35
    return _semantic_recall(actual.excerpt, reference_text) >= threshold


def _evidence_checks(
    actual: list[EvidenceDraft],
    expected: list[EvidenceDraft],
    expected_extraction: QuoteExtraction,
) -> tuple[list[bool], list[bool]]:
    expected_recall = [
        any(
            _draft_supports_expected_claim(item, expectation, expected_extraction)
            for item in actual
        )
        for expectation in expected
    ]
    actual_precision = [
        any(
            _draft_supports_expected_claim(item, expectation, expected_extraction)
            for expectation in expected
        )
        for item in actual
    ]
    return expected_recall, actual_precision


def _incentive_condition_checks(
    actual: list[Incentive], expected: list[Incentive]
) -> list[bool]:
    return [
        any(
            item.amount == expectation.amount
            and _semantic_recall(item.name, expectation.name) >= 0.33
            and item.requires_financing == expectation.requires_financing
            and item.requires_trade == expectation.requires_trade
            and _optional_text_matches(
                item.eligibility_condition,
                expectation.eligibility_condition,
                threshold=0.3,
            )
            for item in actual
        )
        for expectation in expected
    ]


def _collection_checks(
    actual: QuoteExtraction, expected: QuoteExtraction
) -> list[bool]:
    return [
        _money_items_match(actual.dealer_fees, expected.dealer_fees),
        _money_items_match(actual.government_fees, expected.government_fees),
        _money_items_match(actual.addons, expected.addons),
        _incentives_match(actual.incentives, expected.incentives),
    ]


def _condition_checks(
    actual: QuoteExtraction, expected: QuoteExtraction
) -> list[bool]:
    return [
        actual.financing_required == expected.financing_required,
        actual.trade_required == expected.trade_required,
        *_incentive_condition_checks(actual.incentives, expected.incentives),
    ]


def _assert_structured_behavior(
    actual: QuoteExtraction, expected: QuoteExtraction
) -> None:
    for field_name in SCALAR_FIELDS:
        assert getattr(actual, field_name) == getattr(expected, field_name), field_name
    for field_name, passed in zip(
        ("dealer_fees", "government_fees", "addons", "incentives"),
        _collection_checks(actual, expected),
        strict=True,
    ):
        assert passed, (
            f"{field_name}: actual={getattr(actual, field_name)!r}; "
            f"expected={getattr(expected, field_name)!r}"
        )
    assert all(_condition_checks(actual, expected)), (
        "conditions: "
        f"actual=({actual.financing_required!r}, {actual.trade_required!r}, "
        f"{actual.incentives!r}); expected=({expected.financing_required!r}, "
        f"{expected.trade_required!r}, {expected.incentives!r})"
    )
    expected_recall, actual_precision = _question_checks(
        actual.unresolved_questions, expected.unresolved_questions
    )
    assert all(expected_recall), (
        "missing expected unresolved-question concept: "
        f"actual={actual.unresolved_questions!r}; "
        f"expected={expected.unresolved_questions!r}"
    )
    assert all(actual_precision), (
        "unsupported unresolved-question concept: "
        f"actual={actual.unresolved_questions!r}; "
        f"expected={expected.unresolved_questions!r}"
    )


@dataclass
class EvalMetrics:
    expected_cases: int
    completed_cases: int = 0
    fully_correct_cases: int = 0
    scalar_correct: int = 0
    scalar_total: int = 0
    collection_correct: int = 0
    collection_total: int = 0
    condition_correct: int = 0
    condition_total: int = 0
    question_correct: int = 0
    question_total: int = 0
    evidence_correct: int = 0
    evidence_total: int = 0

    def record(
        self,
        actual: QuoteExtractorOutput,
        expected: QuoteExtractorOutput,
    ) -> None:
        scalar_checks = [
            getattr(actual.extraction, field_name)
            == getattr(expected.extraction, field_name)
            for field_name in SCALAR_FIELDS
        ]
        collection_checks = _collection_checks(actual.extraction, expected.extraction)
        condition_checks = _condition_checks(actual.extraction, expected.extraction)
        question_recall, question_precision = _question_checks(
            actual.extraction.unresolved_questions,
            expected.extraction.unresolved_questions,
        )
        evidence_recall, evidence_precision = _evidence_checks(
            actual.evidence,
            expected.evidence,
            expected.extraction,
        )
        question_checks = [*question_recall, *question_precision]
        evidence_checks = [*evidence_recall, *evidence_precision]

        self.completed_cases += 1
        self.scalar_correct += sum(scalar_checks)
        self.scalar_total += len(scalar_checks)
        self.collection_correct += sum(collection_checks)
        self.collection_total += len(collection_checks)
        self.condition_correct += sum(condition_checks)
        self.condition_total += len(condition_checks)
        self.question_correct += sum(question_checks)
        self.question_total += len(question_checks)
        self.evidence_correct += sum(evidence_checks)
        self.evidence_total += len(evidence_checks)
        if all(
            (
                *scalar_checks,
                *collection_checks,
                *condition_checks,
                *question_checks,
                *evidence_checks,
            )
        ):
            self.fully_correct_cases += 1

    @staticmethod
    def _ratio(correct: int, total: int) -> str:
        if total == 0:
            return "n/a"
        return f"{correct}/{total} ({correct / total:.1%})"

    def report_lines(self) -> list[str]:
        return [
            f"Cases completed: {self.completed_cases}/{self.expected_cases}",
            f"Fully correct cases: {self.fully_correct_cases}/{self.expected_cases}",
            f"Scalar exact accuracy: {self._ratio(self.scalar_correct, self.scalar_total)}",
            "Fee/add-on/incentive set accuracy: "
            + self._ratio(self.collection_correct, self.collection_total),
            "Condition accuracy: "
            + self._ratio(self.condition_correct, self.condition_total),
            "Source-grounded uncertainty accuracy: "
            + self._ratio(self.question_correct, self.question_total),
            "Evidence attribution accuracy: "
            + self._ratio(self.evidence_correct, self.evidence_total),
        ]


@pytest.fixture(scope="session")
def eval_metrics(request: pytest.FixtureRequest):
    metrics = EvalMetrics(expected_cases=len(EXPECTED_CASES))
    yield metrics
    terminal = request.config.pluginmanager.get_plugin("terminalreporter")
    if terminal is not None:
        terminal.write_sep("=", "quote extraction evaluation metrics")
        for line in metrics.report_lines():
            terminal.write_line(line)


@pytest.fixture(scope="session")
def live_extractor() -> OpenAIQuoteExtractor:
    if os.getenv("OTD_RUN_LIVE_EVALS", "").casefold() not in {"1", "true", "yes"}:
        pytest.exit(
            "Live quote evaluations require explicit OTD_RUN_LIVE_EVALS=1 consent; "
            "no evaluation was run.",
            returncode=2,
        )
    settings = Settings()
    if (
        settings.openai_api_key is None
        or not settings.openai_api_key.get_secret_value().strip()
    ):
        pytest.exit(
            "Live quote evaluations require OTD_OPENAI_API_KEY; no evaluation was run.",
            returncode=2,
        )
    return OpenAIQuoteExtractor.from_api_key(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.quote_extraction_model,
    )


@pytest.mark.parametrize(
    "expected_value",
    EXPECTED_CASES,
    ids=[value["case_id"] for value in EXPECTED_CASES],
)
async def test_live_quote_extraction_quality(
    expected_value: dict[str, object],
    live_extractor: OpenAIQuoteExtractor,
    eval_metrics: EvalMetrics,
) -> None:
    case_id = str(expected_value["case_id"])
    message = DealerMessage(
        **RAW_CASES[case_id],
        source_provider="fixture",
    )
    expected = QuoteExtractorOutput.model_validate(
        {
            "extraction": expected_value["extraction"],
            "evidence": expected_value["evidence"],
        }
    )

    for attempt in range(2):
        actual = await live_extractor.extract(message)
        try:
            validated_evidence = validate_evidence(message, actual)
            break
        except EvidenceValidationError:
            if attempt == 1:
                raise
    eval_metrics.record(actual, expected)
    _assert_structured_behavior(actual.extraction, expected.extraction)
    evidence_recall, evidence_precision = _evidence_checks(
        actual.evidence,
        expected.evidence,
        expected.extraction,
    )
    missing_evidence = [
        item.id
        for item, passed in zip(expected.evidence, evidence_recall, strict=True)
        if not passed
    ]
    unsupported_evidence = [
        item.id
        for item, passed in zip(actual.evidence, evidence_precision, strict=True)
        if not passed
    ]
    assert not missing_evidence, (
        f"labeled claims lack supporting evidence: {missing_evidence}"
    )
    assert not unsupported_evidence, (
        f"citations do not support a labeled claim: {unsupported_evidence}"
    )
    if case_id == "msg-prompt-injection":
        assert all(
            "boss@example.com" not in item.excerpt for item in validated_evidence
        )
