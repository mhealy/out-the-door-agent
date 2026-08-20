from __future__ import annotations

from pydantic import ValidationError

from app.domain.research import (
    ResearchFinding,
    ResearchFindingDraft,
    ResearchSource,
    ResearchTarget,
)


class ResearchFindingValidationError(ValueError):
    """Structured synthesis is not valid for the supplied target/source set."""


def validate_research_finding(
    target: ResearchTarget,
    sources: list[ResearchSource],
    draft: ResearchFindingDraft,
) -> ResearchFinding:
    """Bind provider provenance after deterministic identity/reference checks."""

    try:
        # Re-parse even validated-looking instances: tests and provider adapters can
        # hand us values created through model_construct, which bypasses constraints.
        checked = ResearchFindingDraft.model_validate(draft.model_dump())
    except ValidationError as error:
        raise ResearchFindingValidationError(
            "The research finding violates deterministic size bounds."
        ) from error

    if not checked.summary.strip():
        raise ResearchFindingValidationError(
            "The research finding summary must not be blank."
        )
    if any(
        not item.strip()
        for item in (
            *checked.what_it_appears_to_include,
            *checked.limitations,
        )
    ):
        raise ResearchFindingValidationError(
            "Research finding list items must not be blank."
        )

    if (
        checked.target_id != target.target_id
        or checked.target_name != target.canonical_name
    ):
        raise ResearchFindingValidationError(
            "The research finding target does not match application authority."
        )

    provider_ids = [source.id for source in sources]
    if len(provider_ids) != len(set(provider_ids)):
        raise ResearchFindingValidationError(
            "The provider returned duplicate research source IDs."
        )
    if len(checked.source_ids) != len(set(checked.source_ids)):
        raise ResearchFindingValidationError(
            "The research finding contains duplicate source references."
        )
    unknown = sorted(set(checked.source_ids) - set(provider_ids))
    if unknown:
        raise ResearchFindingValidationError(
            "The research finding cites unknown source IDs: " + ", ".join(unknown)
        )
    if checked.support_status in {"SUPPORTED", "MIXED"} and not checked.source_ids:
        raise ResearchFindingValidationError(
            "A supported or mixed research finding must cite a supplied source."
        )

    sources_by_id = {source.id: source for source in sources}
    cited_sources = [sources_by_id[source_id] for source_id in checked.source_ids]
    return ResearchFinding(
        **checked.model_dump(),
        sources=cited_sources,
    )
