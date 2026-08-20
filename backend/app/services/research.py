from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.research import (
    ResearchRequest,
    ResearchTarget,
    ResearchTargetView,
)
from app.persistence.agent_runs import AgentRunRepository
from app.persistence.interactions import (
    InteractionRecordNotFoundError,
    InteractionRepository,
)
from app.persistence.research import ResearchClaimLostError, ResearchRepository
from app.persistence.purchases import PurchaseRunRepository
from app.providers.research import ResearchProvider, ResearchProviderError
from app.providers.research_synthesis import (
    ResearchSynthesisError,
    ResearchSynthesizer,
    ResearchSynthesizerUnavailableError,
)
from app.services.research_policy import derive_research_targets
from app.services.research_validation import (
    ResearchFindingValidationError,
    validate_research_finding,
)


RESEARCH_VERSION = "research-v1"


class ResearchTargetChangedError(RuntimeError):
    """A browser target no longer reconstructs from current authoritative state."""


class ResearchInProgressError(RuntimeError):
    """Another request currently owns this target's bounded research execution."""


class ResearchExecutionError(RuntimeError):
    """Research failed visibly after its auditable record was preserved."""

    def __init__(self, error_code: str, *, unavailable: bool = False) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.unavailable = unavailable


class ResearchService:
    """Resolve current targets, acquire read-only evidence, validate, and persist."""

    def __init__(
        self,
        *,
        session: Session,
        provider: ResearchProvider,
        synthesizer: ResearchSynthesizer,
    ) -> None:
        self._session = session
        self._provider = provider
        self._synthesizer = synthesizer
        self._purchases = PurchaseRunRepository(session)
        self._runs = AgentRunRepository(session)
        self._interactions = InteractionRepository(session)
        self._research = ResearchRepository(session)

    def list_targets(self, purchase_id: str) -> list[ResearchTargetView]:
        return [self._view(target) for target in self._current_targets(purchase_id)]

    async def investigate(
        self,
        purchase_id: str,
        target_id: str,
    ) -> ResearchTargetView:
        target = self._current_target(purchase_id, target_id)
        claim = self._research.claim(target, RESEARCH_VERSION)
        if not claim.acquired:
            existing = self._research.investigation(target, RESEARCH_VERSION)
            if existing is not None and existing.status in {"COMPLETED", "FAILED"}:
                return self._view(target)
            raise ResearchInProgressError(target_id)

        claim_token = claim.claim_token
        if claim_token is None:
            raise AssertionError("An acquired research claim must have a token.")

        sources = []
        try:
            provider_result = await self._provider.research(
                ResearchRequest(
                    target_id=target.target_id,
                    target_type=target.target_type,
                    canonical_name=target.canonical_name,
                )
            )
            sources = list(provider_result.sources)
            self._require_still_current(target)
            self._research.save_sources(claim.record_id, claim_token, sources)

            finding = None
            for attempt in range(2):
                draft = await self._synthesizer.synthesize(
                    target=target,
                    sources=sources,
                )
                try:
                    finding = validate_research_finding(target, sources, draft)
                except ResearchFindingValidationError:
                    if attempt == 0:
                        continue
                    raise
                break
            if finding is None:
                raise AssertionError(
                    "Research finding validation exited without a result."
                )

            # This claim-owned conditional update is intentionally the first write
            # after source persistence. On SQLite it serializes the authority read
            # below with both newer analysis persistence and final completion.
            self._research.lock_for_completion(claim.record_id, claim_token)
            self._require_still_current(target)
            self._research.complete(claim.record_id, claim_token, finding)
        except ResearchTargetChangedError:
            self._fail_claim(
                claim.record_id,
                claim_token,
                "research_target_changed",
                target_id=target_id,
            )
            raise
        except ResearchSynthesizerUnavailableError as error:
            self._fail_claim(
                claim.record_id,
                claim_token,
                "research_synthesizer_unavailable",
                target_id=target_id,
            )
            raise ResearchExecutionError(
                "research_synthesizer_unavailable",
                unavailable=True,
            ) from error
        except ResearchProviderError as error:
            self._fail_claim(
                claim.record_id,
                claim_token,
                "research_provider_failed",
                target_id=target_id,
            )
            raise ResearchExecutionError("research_provider_failed") from error
        except ResearchSynthesisError as error:
            self._fail_claim(
                claim.record_id,
                claim_token,
                "research_synthesis_failed",
                target_id=target_id,
            )
            raise ResearchExecutionError("research_synthesis_failed") from error
        except ResearchFindingValidationError as error:
            self._fail_claim(
                claim.record_id,
                claim_token,
                "research_finding_invalid",
                target_id=target_id,
            )
            raise ResearchExecutionError("research_finding_invalid") from error
        except ResearchClaimLostError as error:
            raise ResearchInProgressError(target_id) from error

        return self._view(target)

    def _view(self, target: ResearchTarget) -> ResearchTargetView:
        investigation = self._research.investigation(
            target,
            RESEARCH_VERSION,
        )
        values = target.model_dump()
        values["recommended"] = (
            investigation is None or investigation.status == "FAILED"
        )
        return ResearchTargetView(**values, investigation=investigation)

    def _current_target(
        self,
        purchase_id: str,
        target_id: str,
    ) -> ResearchTarget:
        target = next(
            (
                target
                for target in self._current_targets(purchase_id)
                if target.target_id == target_id
            ),
            None,
        )
        if target is None:
            raise ResearchTargetChangedError(target_id)
        return target

    def _require_still_current(self, expected: ResearchTarget) -> None:
        self._session.expire_all()
        current = self._current_target(
            expected.purchase_run_id,
            expected.target_id,
        )
        if current != expected:
            raise ResearchTargetChangedError(expected.target_id)

    def _fail_claim(
        self,
        record_id: str,
        claim_token: str,
        error_code: str,
        *,
        target_id: str,
    ) -> None:
        try:
            self._research.fail(record_id, claim_token, error_code)
        except ResearchClaimLostError as error:
            raise ResearchInProgressError(target_id) from error

    def _current_targets(self, purchase_id: str) -> list[ResearchTarget]:
        # Require the purchase first so an unknown purchase is never confused with
        # an empty or stale target set.
        self._purchases.get(purchase_id)
        targets: list[ResearchTarget] = []
        for link in self._purchases.list_vehicle_links(purchase_id):
            if link.agent_run_id is None:
                continue
            run = self._runs.get(link.agent_run_id)
            try:
                interaction = self._interactions.get(run.initial_action_id)
            except InteractionRecordNotFoundError:
                continue
            targets.extend(
                derive_research_targets(
                    purchase_run_id=purchase_id,
                    agent_run_id=run.id,
                    interaction=interaction,
                )
            )
        return targets
