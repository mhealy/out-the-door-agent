import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.domain.followup import (
    FollowupConversationMessage,
    FollowupDraft,
    FollowupDraftContext,
)
from app.domain.quote import QuoteAssessment
from app.providers.followup_drafting import (
    FollowupDrafterUnavailableError,
    FollowupDraftingError,
    OpenAIFollowupDrafter,
    UnavailableFollowupDrafter,
)
from app.services.followups import derive_followup_requirements


def _context() -> FollowupDraftContext:
    requirements = derive_followup_requirements(
        QuoteAssessment(
            comparable=False,
            transparent=False,
            missing_for_comparison=["claimed_otd"],
        )
    )
    return FollowupDraftContext(
        interaction_id="interaction-1",
        dealer_id="baytown",
        dealer_name="Baytown Hyundai",
        vehicle_description="2025 Hyundai Tucson Hybrid Limited",
        target_vin="KM8JCDD10SU000001",
        target_stock_number="B1001",
        previous_outbound=[
            FollowupConversationMessage(
                direction="OUTBOUND",
                subject="Written quote request",
                body="Please provide a complete written quote.",
            )
        ],
        latest_inbound=FollowupConversationMessage(
            direction="INBOUND",
            subject="Partial quote",
            body="The selling price is $37,800, but the final total is absent.",
        ),
        requirements=requirements,
        source_uncertainty=[],
    )


def _valid_output() -> dict[str, Any]:
    return {
        "subject": "Written quote clarification",
        "requests": [
            {
                "requirement_id": "claimed_otd",
                "text": "Please confirm the written out-the-door total.",
            }
        ],
    }


@pytest.mark.asyncio
async def test_openai_followup_drafter_uses_structured_output_without_tools() -> None:
    class FakeResponses:
        def __init__(self) -> None:
            self.kwargs: dict[str, Any] = {}

        async def parse(self, **kwargs: Any) -> Any:
            self.kwargs = kwargs
            return SimpleNamespace(
                status="completed",
                output_parsed=_valid_output(),
            )

    responses = FakeResponses()
    drafter = OpenAIFollowupDrafter(
        client=SimpleNamespace(responses=responses),
        model="test-model",
    )

    draft = await drafter.draft(_context())

    assert isinstance(draft, FollowupDraft)
    assert responses.kwargs["model"] == "test-model"
    assert responses.kwargs["text_format"] is FollowupDraft
    assert responses.kwargs["store"] is False
    assert "tools" not in responses.kwargs
    assert [message["role"] for message in responses.kwargs["input"]] == [
        "system",
        "user",
    ]
    supplied_context = json.loads(responses.kwargs["input"][1]["content"])
    assert supplied_context["requirements"][0]["id"] == "claimed_otd"
    assert supplied_context["requirements"][0]["wording_options"]
    assert "recipient" not in supplied_context


@pytest.mark.asyncio
async def test_openai_followup_drafter_retries_invalid_structured_output_once() -> None:
    class FakeResponses:
        def __init__(self) -> None:
            self.calls = 0

        async def parse(self, **_: Any) -> Any:
            self.calls += 1
            parsed = {"subject": "Quote clarification", "requests": []}
            if self.calls == 2:
                parsed = _valid_output()
            return SimpleNamespace(status="completed", output_parsed=parsed)

    responses = FakeResponses()
    drafter = OpenAIFollowupDrafter(
        client=SimpleNamespace(responses=responses),
        model="test-model",
    )

    draft = await drafter.draft(_context())

    assert responses.calls == 2
    assert draft.subject == "Written quote clarification"


@pytest.mark.asyncio
async def test_openai_followup_drafter_fails_after_two_invalid_outputs() -> None:
    class FakeResponses:
        def __init__(self) -> None:
            self.calls = 0

        async def parse(self, **_: Any) -> Any:
            self.calls += 1
            return SimpleNamespace(
                status="completed",
                output_parsed={"subject": "Quote clarification", "requests": []},
            )

    responses = FakeResponses()
    drafter = OpenAIFollowupDrafter(
        client=SimpleNamespace(responses=responses),
        model="test-model",
    )

    with pytest.raises(FollowupDraftingError, match="invalid structured"):
        await drafter.draft(_context())

    assert responses.calls == 2


@pytest.mark.asyncio
async def test_unavailable_followup_drafter_fails_visibly() -> None:
    with pytest.raises(FollowupDrafterUnavailableError, match="not configured"):
        await UnavailableFollowupDrafter("not configured").draft(_context())
