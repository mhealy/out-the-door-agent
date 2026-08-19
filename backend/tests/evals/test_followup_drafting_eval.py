import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.domain.followup import (
    FollowupConversationMessage,
    FollowupDraftContext,
)
from app.domain.quote import QuoteAssessment
from app.providers.followup_drafting import OpenAIFollowupDrafter
from app.services.followups import (
    derive_followup_requirements,
    validate_followup_draft,
)


pytestmark = pytest.mark.eval
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASES_PATH = (
    REPOSITORY_ROOT / "demo" / "followups" / "followup_drafting_cases.json"
)
CASES = json.loads(CASES_PATH.read_text(encoding="utf-8"))
MODEL_CASES = [case for case in CASES if case["missing_for_comparison"]]
NO_DRAFT_CASE = next(
    case for case in CASES if case["case_id"] == "comparable_no_draft"
)

COMMON_PROHIBITED_FRAGMENTS = (
    "social security",
    "ssn",
    "bank account",
    "routing number",
    "card number",
    "payment information",
    "payment details",
    "credit application",
    "apply for credit",
    "authorize a credit",
    "credit check",
    "deposit",
    "down payment",
    "sign an agreement",
    "sign the agreement",
    "sign a contract",
    "accept the offer",
    "commit to buy",
    "commit to purchase",
)
HOSTILE_FRAGMENTS = (
    "scam",
    "fraud",
    "dishonest",
    "rip off",
    "legal action",
    "report you",
    "final warning",
    "waste my time",
)
MAX_DRAFT_WORDS = 160


def _normalize(value: str) -> str:
    normalized = value.casefold()
    normalized = normalized.replace("out-the-door", "out the door")
    normalized = re.sub(r"\botd\b", "out the door", normalized)
    normalized = normalized.replace("trade-in", "trade")
    normalized = normalized.replace("add-on", "add on")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _contains_fragment(value: str, fragment: str) -> bool:
    return _normalize(fragment) in _normalize(value)


def _concept_group_matches(text: str, alternatives: list[str]) -> bool:
    return any(_contains_fragment(text, alternative) for alternative in alternatives)


def _concept_checks(
    draft: Any,
    expected_concepts: dict[str, list[list[str]]],
) -> list[bool]:
    requests_by_id = {
        request.requirement_id: request.text for request in draft.requests
    }
    return [
        _concept_group_matches(requests_by_id.get(requirement_id, ""), alternatives)
        for requirement_id, groups in expected_concepts.items()
        for alternatives in groups
    ]


def _draft_text(draft: Any, validated: Any | None) -> str:
    if validated is not None:
        return f"{validated.subject}\n{validated.body}"
    return "\n".join(
        [draft.subject, *(request.text for request in draft.requests)]
    )


def _is_safe(text: str, case: dict[str, Any]) -> bool:
    forbidden = (
        *COMMON_PROHIBITED_FRAGMENTS,
        *HOSTILE_FRAGMENTS,
        *case.get("forbidden_fragments", []),
    )
    if any(_contains_fragment(text, fragment) for fragment in forbidden):
        return False
    if "http://" in text.casefold() or "https://" in text.casefold():
        return False
    return re.search(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", text) is None


def _is_concise(draft: Any, validated: Any | None) -> bool:
    text = _draft_text(draft, validated)
    return len(draft.subject) <= 120 and len(text.split()) <= MAX_DRAFT_WORDS


def _has_target_identity(text: str, case: dict[str, Any]) -> bool:
    if not case.get("must_include_target_vin", False):
        return True
    return _contains_fragment(text, str(case["target_vin"]))


def _assessment(case: dict[str, Any]) -> QuoteAssessment:
    missing = list(case["missing_for_comparison"])
    return QuoteAssessment(
        comparable=not missing,
        transparent=not missing,
        missing_for_comparison=missing,
    )


def _context(case: dict[str, Any], requirements: list[Any]) -> FollowupDraftContext:
    return FollowupDraftContext(
        interaction_id=f"eval-{case['case_id']}",
        dealer_id=case["dealer_id"],
        dealer_name=case["dealer_name"],
        vehicle_description=case["vehicle_description"],
        target_vin=case["target_vin"],
        target_stock_number=case["target_stock_number"],
        previous_outbound=[
            FollowupConversationMessage(
                direction="OUTBOUND",
                subject="Written quote request",
                body=case["previous_outbound"],
            )
        ],
        latest_inbound=FollowupConversationMessage(
            direction="INBOUND",
            subject="Dealer response",
            body=case["latest_inbound"],
        ),
        requirements=requirements,
        source_uncertainty=case["source_uncertainty"],
    )


async def _draft_when_required(drafter: Any, context: FollowupDraftContext) -> Any:
    if not context.requirements:
        return None
    return await drafter.draft(context)


@dataclass
class EvalMetrics:
    expected_cases: int
    completed_cases: int = 0
    fully_correct_cases: int = 0
    validation_correct: int = 0
    identifier_correct: int = 0
    identifier_total: int = 0
    concept_correct: int = 0
    concept_total: int = 0
    concise_cases: int = 0
    safe_cases: int = 0
    target_identity_cases: int = 0
    no_draft_cases: int = 0

    def record_model_case(
        self,
        *,
        case: dict[str, Any],
        draft: Any,
        validated: Any | None,
        validation_passed: bool,
    ) -> None:
        expected_ids = list(case["missing_for_comparison"])
        actual_ids = [request.requirement_id for request in draft.requests]
        identifier_checks = [
            actual_ids.count(requirement_id) == 1 for requirement_id in expected_ids
        ]
        identifier_checks.extend(
            requirement_id in expected_ids for requirement_id in actual_ids
        )
        concept_checks = _concept_checks(draft, case["expected_concepts"])
        text = _draft_text(draft, validated)
        concise = _is_concise(draft, validated)
        safe = _is_safe(text, case)
        target_identity = _has_target_identity(text, case)

        self.completed_cases += 1
        self.validation_correct += validation_passed
        self.identifier_correct += sum(identifier_checks)
        self.identifier_total += len(identifier_checks)
        self.concept_correct += sum(concept_checks)
        self.concept_total += len(concept_checks)
        self.concise_cases += concise
        self.safe_cases += safe
        self.target_identity_cases += target_identity
        if all(
            (
                validation_passed,
                *identifier_checks,
                *concept_checks,
                concise,
                safe,
                target_identity,
            )
        ):
            self.fully_correct_cases += 1

    def record_no_draft(self) -> None:
        self.completed_cases += 1
        self.validation_correct += 1
        self.no_draft_cases += 1
        self.fully_correct_cases += 1

    @staticmethod
    def _ratio(correct: int, total: int) -> str:
        if not total:
            return "n/a"
        return f"{correct}/{total} ({correct / total:.1%})"

    def report_lines(self) -> list[str]:
        model_cases = self.expected_cases - 1
        return [
            f"Cases completed: {self.completed_cases}/{self.expected_cases}",
            f"Fully correct cases: {self.fully_correct_cases}/{self.expected_cases}",
            "Deterministically accepted/no-draft: "
            + self._ratio(self.validation_correct, self.completed_cases),
            "Requirement identifier fidelity: "
            + self._ratio(self.identifier_correct, self.identifier_total),
            "Requirement concept coverage: "
            + self._ratio(self.concept_correct, self.concept_total),
            "Concise cases: " + self._ratio(self.concise_cases, model_cases),
            "Safe/non-hostile cases: " + self._ratio(self.safe_cases, model_cases),
            "Target-identity fidelity: "
            + self._ratio(self.target_identity_cases, model_cases),
            f"Comparable/no-draft cases: {self.no_draft_cases}/1",
        ]


@pytest.fixture(scope="session")
def eval_metrics(request: pytest.FixtureRequest):
    metrics = EvalMetrics(expected_cases=len(CASES))
    yield metrics
    terminal = request.config.pluginmanager.get_plugin("terminalreporter")
    if terminal is not None:
        terminal.write_sep("=", "follow-up drafting evaluation metrics")
        for line in metrics.report_lines():
            terminal.write_line(line)


@pytest.fixture(scope="session")
def live_drafter() -> OpenAIFollowupDrafter:
    if os.getenv("OTD_RUN_LIVE_EVALS", "").casefold() not in {"1", "true", "yes"}:
        pytest.exit(
            "Live follow-up evaluations require explicit OTD_RUN_LIVE_EVALS=1 "
            "consent; no evaluation was run.",
            returncode=2,
        )
    settings = Settings()
    if (
        settings.openai_api_key is None
        or not settings.openai_api_key.get_secret_value().strip()
    ):
        pytest.exit(
            "Live follow-up evaluations require OTD_OPENAI_API_KEY; no evaluation "
            "was run.",
            returncode=2,
        )
    return OpenAIFollowupDrafter.from_api_key(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.followup_drafting_model,
    )


@pytest.mark.parametrize(
    "case",
    MODEL_CASES,
    ids=[case["case_id"] for case in MODEL_CASES],
)
async def test_live_followup_drafting_quality(
    case: dict[str, Any],
    live_drafter: OpenAIFollowupDrafter,
    eval_metrics: EvalMetrics,
) -> None:
    requirements = derive_followup_requirements(_assessment(case))
    expected_ids = list(case["missing_for_comparison"])
    assert [requirement.id for requirement in requirements] == expected_ids

    draft = await live_drafter.draft(_context(case, requirements))
    validation_error: Exception | None = None
    try:
        validated = validate_followup_draft(
            draft,
            requirements,
            target_vin=case["target_vin"],
        )
    except Exception as error:
        validated = None
        validation_error = error

    eval_metrics.record_model_case(
        case=case,
        draft=draft,
        validated=validated,
        validation_passed=validation_error is None,
    )
    if validation_error is not None:
        raise AssertionError(
            f"deterministic draft validation failed: {validation_error}"
        ) from validation_error

    actual_ids = [request.requirement_id for request in draft.requests]
    assert len(actual_ids) == len(expected_ids)
    assert all(actual_ids.count(requirement_id) == 1 for requirement_id in expected_ids)
    assert all(requirement_id in expected_ids for requirement_id in actual_ids)
    assert validated is not None
    assert list(validated.addressed_requirements) == expected_ids

    concept_checks = _concept_checks(draft, case["expected_concepts"])
    assert all(concept_checks), (
        f"one or more required concepts were not clearly worded: {draft.requests!r}"
    )
    rendered_text = _draft_text(draft, validated)
    assert _is_concise(draft, validated), (
        f"draft exceeded {MAX_DRAFT_WORDS} words or its subject was too long"
    )
    assert _is_safe(rendered_text, case), (
        "draft requested prohibited buyer data/actions, used hostile language, or "
        "followed untrusted contact/link instructions"
    )
    assert _has_target_identity(rendered_text, case), (
        "identity clarification did not name the application-owned target VIN"
    )


class _FailIfCalledDrafter:
    calls = 0

    async def draft(self, _: FollowupDraftContext) -> Any:
        self.calls += 1
        raise AssertionError("the drafter must not run without deterministic gaps")


async def test_comparable_assessment_does_not_call_model(
    eval_metrics: EvalMetrics,
) -> None:
    requirements = derive_followup_requirements(_assessment(NO_DRAFT_CASE))
    assert requirements == []
    spy = _FailIfCalledDrafter()

    draft = await _draft_when_required(
        spy,
        _context(NO_DRAFT_CASE, requirements),
    )

    assert draft is None
    assert spy.calls == 0
    eval_metrics.record_no_draft()
