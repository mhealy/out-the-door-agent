from datetime import datetime, timezone

from app.domain.evidence import Evidence
from app.domain.message import DealerMessage
from app.domain.quote import QuoteExtraction
from app.providers.quote_extraction import EvidenceDraft, QuoteExtractorOutput


MATERIAL_SCALAR_FIELDS = (
    "vehicle_vin",
    "stock_number",
    "selling_price",
    "claimed_otd",
    "financing_required",
    "trade_required",
    "expiration",
)
EXPLICIT_STATEMENT_FIELDS = (
    "explicit_no_addons_statement",
    "explicit_all_fees_included_statement",
)
COLLECTION_FIELDS = (
    "dealer_fees",
    "government_fees",
    "addons",
    "incentives",
)
ALLOWED_EVIDENCE_FIELDS = frozenset(
    (
        *MATERIAL_SCALAR_FIELDS,
        *EXPLICIT_STATEMENT_FIELDS,
        *COLLECTION_FIELDS,
        "unresolved_questions",
    )
)


class EvidenceValidationError(ValueError):
    """Model-proposed evidence cannot be traced to the dealer source."""


def _referenced_item_ids(extraction: QuoteExtraction) -> list[tuple[str, str]]:
    references: list[tuple[str, str]] = []
    for field_name in COLLECTION_FIELDS:
        for item in getattr(extraction, field_name):
            references.append((item.evidence_id, field_name))
    return references


def _require_scalar_evidence(
    extraction: QuoteExtraction,
    evidence_by_field: dict[str, list[EvidenceDraft]],
) -> None:
    for field_name in MATERIAL_SCALAR_FIELDS:
        if getattr(extraction, field_name) is not None and not evidence_by_field.get(
            field_name
        ):
            raise EvidenceValidationError(
                f"Extracted field '{field_name}' has no matching evidence."
            )
    for field_name in EXPLICIT_STATEMENT_FIELDS:
        if getattr(extraction, field_name) and not evidence_by_field.get(field_name):
            raise EvidenceValidationError(
                f"Extracted field '{field_name}' has no matching evidence."
            )
    if extraction.unresolved_questions and not evidence_by_field.get(
        "unresolved_questions"
    ):
        raise EvidenceValidationError(
            "Extracted field 'unresolved_questions' has no matching evidence."
        )


def _associated_evidence_ids(
    extraction: QuoteExtraction,
    drafts: list[EvidenceDraft],
    item_references: list[tuple[str, str]],
) -> set[str]:
    populated_fields = {
        field_name
        for field_name in MATERIAL_SCALAR_FIELDS
        if getattr(extraction, field_name) is not None
    }
    populated_fields.update(
        field_name
        for field_name in EXPLICIT_STATEMENT_FIELDS
        if getattr(extraction, field_name)
    )
    if extraction.unresolved_questions:
        populated_fields.add("unresolved_questions")

    associated_ids = {
        draft.id for draft in drafts if draft.field_name in populated_fields
    }
    associated_ids.update(reference_id for reference_id, _ in item_references)
    return associated_ids


def validate_evidence(
    message: DealerMessage,
    output: QuoteExtractorOutput,
    *,
    created_at: datetime | None = None,
) -> list[Evidence]:
    """Validate model-local citations and bind trusted source metadata."""

    drafts = output.evidence
    draft_ids = [draft.id for draft in drafts]
    duplicate_ids = sorted(
        {draft_id for draft_id in draft_ids if draft_ids.count(draft_id) > 1}
    )
    if duplicate_ids:
        raise EvidenceValidationError(
            f"Model output contains duplicate evidence ID(s): {', '.join(duplicate_ids)}."
        )

    declared_ids = output.extraction.evidence_ids
    if len(declared_ids) != len(set(declared_ids)):
        raise EvidenceValidationError("Quote extraction contains duplicate evidence IDs.")

    known_ids = set(draft_ids)
    referenced_ids = set(declared_ids)
    item_references = _referenced_item_ids(output.extraction)
    referenced_ids.update(reference_id for reference_id, _ in item_references)
    unknown_ids = sorted(referenced_ids - known_ids)
    if unknown_ids:
        raise EvidenceValidationError(
            f"Quote extraction references unknown evidence ID(s): {', '.join(unknown_ids)}."
        )

    undeclared_ids = sorted(known_ids - set(declared_ids))
    if undeclared_ids:
        raise EvidenceValidationError(
            "Evidence records are missing from QuoteExtraction.evidence_ids: "
            + ", ".join(undeclared_ids)
            + "."
        )

    by_id = {draft.id: draft for draft in drafts}
    by_field: dict[str, list[EvidenceDraft]] = {}
    for draft in drafts:
        if not draft.excerpt.strip():
            raise EvidenceValidationError(
                f"Evidence '{draft.id}' has an empty excerpt."
            )
        if draft.excerpt not in message.body:
            raise EvidenceValidationError(
                f"Evidence '{draft.id}' excerpt does not occur in source message "
                f"'{message.id}'."
            )
        if draft.field_name not in ALLOWED_EVIDENCE_FIELDS:
            raise EvidenceValidationError(
                f"Evidence '{draft.id}' uses unsupported field '{draft.field_name}'."
            )
        by_field.setdefault(draft.field_name, []).append(draft)

    _require_scalar_evidence(output.extraction, by_field)
    for reference_id, expected_field in item_references:
        actual_field = by_id[reference_id].field_name
        if actual_field != expected_field:
            raise EvidenceValidationError(
                f"Evidence '{reference_id}' supports '{actual_field}', not "
                f"'{expected_field}'."
            )

    orphan_ids = sorted(
        known_ids
        - _associated_evidence_ids(output.extraction, drafts, item_references)
    )
    if orphan_ids:
        raise EvidenceValidationError(
            "Evidence record(s) are not associated with a populated extraction claim: "
            + ", ".join(orphan_ids)
            + "."
        )

    timestamp = created_at or datetime.now(timezone.utc)
    return [
        Evidence(
            id=draft.id,
            source_type="DEALER_EMAIL",
            source_id=message.id,
            field_name=draft.field_name,
            excerpt=draft.excerpt,
            created_at=timestamp,
        )
        for draft in drafts
    ]
