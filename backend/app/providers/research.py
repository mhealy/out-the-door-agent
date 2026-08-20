from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from app.domain.research import (
    ResearchProviderResult,
    ResearchRequest,
    ResearchSource,
)
from app.services.research_policy import normalize_research_name


def _default_fixture_path() -> Path:
    relative_path = Path("demo/research/research_sources.json")
    for parent in Path(__file__).resolve().parents:
        candidate = parent / relative_path
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parents[3] / relative_path


DEFAULT_RESEARCH_FIXTURE_PATH = _default_fixture_path()


class ResearchProvider(Protocol):
    async def research(self, request: ResearchRequest) -> ResearchProviderResult: ...


class ResearchProviderError(RuntimeError):
    """Bounded source retrieval failed without fabricating substitute evidence."""


class _FixtureSourceSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical_name: str
    sources: list[ResearchSource]


class FixtureResearchProvider:
    """Deterministic source acquisition for the canonical offline demo."""

    def __init__(self, fixture_path: Path = DEFAULT_RESEARCH_FIXTURE_PATH) -> None:
        self._fixture_path = fixture_path
        self._source_sets: dict[str, _FixtureSourceSet] | None = None

    def _load(self) -> dict[str, _FixtureSourceSet]:
        if self._source_sets is not None:
            return self._source_sets
        try:
            raw = json.loads(self._fixture_path.read_text(encoding="utf-8"))
            source_sets = [_FixtureSourceSet.model_validate(value) for value in raw]
        except Exception as error:
            raise ResearchProviderError(
                "The fixture research source corpus is unavailable or invalid."
            ) from error
        by_name = {
            normalize_research_name(source_set.canonical_name): source_set
            for source_set in source_sets
        }
        if len(by_name) != len(source_sets):
            raise ResearchProviderError(
                "The fixture research source corpus contains duplicate targets."
            )
        self._source_sets = by_name
        return by_name

    async def research(self, request: ResearchRequest) -> ResearchProviderResult:
        source_set = self._load().get(normalize_research_name(request.canonical_name))
        if source_set is None:
            raise ResearchProviderError(
                "Research is unavailable because no bounded fixture source set was found."
            )
        return ResearchProviderResult(
            sources=[source.model_copy(deep=True) for source in source_set.sources]
        )
