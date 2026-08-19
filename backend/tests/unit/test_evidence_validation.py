from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.message import DealerMessage
from app.domain.quote import MoneyItem, QuoteExtraction
from app.providers.quote_extraction import EvidenceDraft, QuoteExtractorOutput
from app.services.evidence_validation import (
    EvidenceValidationError,
    validate_evidence,
)


CREATED_AT = datetime(2026, 8, 19, 18, 30, tzinfo=timezone.utc)


def dealer_message(body: str = "Selling price: $37,800. OTD total: $40,315.") -> DealerMessage:
    return DealerMessage(
        id="message-1",
        dealer_id="dealer-1",
        vehicle_id="vehicle-1",
        subject="Written quote",
        body=body,
        received_at=CREATED_AT,
        source_provider="fixture",
    )


def output(
    *,
    extraction: QuoteExtraction | None = None,
    evidence: list[EvidenceDraft] | None = None,
) -> QuoteExtractorOutput:
    return QuoteExtractorOutput(
        extraction=extraction
        or QuoteExtraction(
            selling_price="37800",
            claimed_otd="40315",
            evidence_ids=["selling", "otd"],
            extraction_confidence=0.9,
        ),
        evidence=evidence
        if evidence is not None
        else [
            EvidenceDraft(
                id="selling",
                field_name="selling_price",
                excerpt="Selling price: $37,800.",
            ),
            EvidenceDraft(
                id="otd",
                field_name="claimed_otd",
                excerpt="OTD total: $40,315.",
            ),
        ],
    )


def test_valid_evidence_excerpt_is_bound_to_trusted_message_metadata() -> None:
    result = validate_evidence(dealer_message(), output(), created_at=CREATED_AT)

    assert [item.id for item in result] == ["selling", "otd"]
    assert all(item.source_type == "DEALER_EMAIL" for item in result)
    assert all(item.source_id == "message-1" for item in result)
    assert all(item.created_at == CREATED_AT for item in result)


def test_decimal_values_remain_decimal_after_evidence_validation() -> None:
    extraction = output().extraction

    validate_evidence(dealer_message(), output(extraction=extraction))

    assert extraction.selling_price == Decimal("37800")
    assert extraction.claimed_otd == Decimal("40315")


@pytest.mark.parametrize(
    ("evidence", "match"),
    [
        (
            [
                EvidenceDraft(id="selling", field_name="selling_price", excerpt=""),
                EvidenceDraft(
                    id="otd",
                    field_name="claimed_otd",
                    excerpt="OTD total: $40,315.",
                ),
            ],
            "empty excerpt",
        ),
        (
            [
                EvidenceDraft(id="selling", field_name="selling_price", excerpt=" "),
                EvidenceDraft(
                    id="otd",
                    field_name="claimed_otd",
                    excerpt="OTD total: $40,315.",
                ),
            ],
            "empty excerpt",
        ),
        (
            [
                EvidenceDraft(
                    id="selling",
                    field_name="selling_price",
                    excerpt="Selling price: $37,000.",
                ),
                EvidenceDraft(
                    id="otd",
                    field_name="claimed_otd",
                    excerpt="OTD total: $40,315.",
                ),
            ],
            "does not occur",
        ),
    ],
)
def test_invalid_source_excerpt_is_rejected(
    evidence: list[EvidenceDraft], match: str
) -> None:
    with pytest.raises(EvidenceValidationError, match=match):
        validate_evidence(dealer_message(), output(evidence=evidence))


def test_unknown_referenced_evidence_id_is_rejected() -> None:
    extraction = QuoteExtraction(
        selling_price="37800",
        evidence_ids=["missing"],
        extraction_confidence=0.8,
    )

    with pytest.raises(EvidenceValidationError, match="unknown evidence ID"):
        validate_evidence(
            dealer_message(),
            output(
                extraction=extraction,
                evidence=[
                    EvidenceDraft(
                        id="selling",
                        field_name="selling_price",
                        excerpt="Selling price: $37,800.",
                    )
                ],
            ),
        )


def test_duplicate_evidence_ids_are_rejected_before_lookup() -> None:
    duplicate = EvidenceDraft(
        id="selling",
        field_name="selling_price",
        excerpt="Selling price: $37,800.",
    )
    extraction = QuoteExtraction(
        selling_price="37800",
        evidence_ids=["selling"],
        extraction_confidence=0.8,
    )

    with pytest.raises(EvidenceValidationError, match="duplicate evidence ID"):
        validate_evidence(
            dealer_message(),
            output(extraction=extraction, evidence=[duplicate, duplicate]),
        )


def test_material_scalar_requires_evidence_for_its_canonical_field() -> None:
    extraction = QuoteExtraction(
        selling_price="37800",
        evidence_ids=["wrong-field"],
        extraction_confidence=0.8,
    )

    with pytest.raises(EvidenceValidationError, match="selling_price"):
        validate_evidence(
            dealer_message(),
            output(
                extraction=extraction,
                evidence=[
                    EvidenceDraft(
                        id="wrong-field",
                        field_name="claimed_otd",
                        excerpt="Selling price: $37,800.",
                    )
                ],
            ),
        )


def test_nested_money_item_reference_must_exist_and_match_its_field() -> None:
    extraction = QuoteExtraction(
        dealer_fees=[
            MoneyItem(
                name="Documentation fee",
                amount="225",
                stated_mandatory=True,
                evidence_id="fee",
            )
        ],
        evidence_ids=["fee"],
        extraction_confidence=0.9,
    )
    message = dealer_message("Documentation fee: $225.")

    result = validate_evidence(
        message,
        output(
            extraction=extraction,
            evidence=[
                EvidenceDraft(
                    id="fee",
                    field_name="dealer_fees",
                    excerpt="Documentation fee: $225.",
                )
            ],
        ),
    )

    assert result[0].field_name == "dealer_fees"


def test_multiple_fields_may_use_the_same_exact_source_excerpt() -> None:
    message = dealer_message("No financing or trade-in is required.")
    extraction = QuoteExtraction(
        financing_required=False,
        trade_required=False,
        evidence_ids=["financing", "trade"],
        extraction_confidence=0.9,
    )
    shared_excerpt = "No financing or trade-in is required."

    result = validate_evidence(
        message,
        output(
            extraction=extraction,
            evidence=[
                EvidenceDraft(
                    id="financing",
                    field_name="financing_required",
                    excerpt=shared_excerpt,
                ),
                EvidenceDraft(
                    id="trade",
                    field_name="trade_required",
                    excerpt=shared_excerpt,
                ),
            ],
        ),
    )

    assert [item.excerpt for item in result] == [shared_excerpt, shared_excerpt]


def test_source_grounded_unresolved_question_with_valid_evidence_is_accepted() -> None:
    message = dealer_message("We cannot provide a written OTD quote by email.")
    extraction = QuoteExtraction(
        unresolved_questions=["The dealer declined to provide a written OTD quote."],
        evidence_ids=["unresolved"],
        extraction_confidence=0.8,
    )

    result = validate_evidence(
        message,
        output(
            extraction=extraction,
            evidence=[
                EvidenceDraft(
                    id="unresolved",
                    field_name="unresolved_questions",
                    excerpt="We cannot provide a written OTD quote by email.",
                )
            ],
        ),
    )

    assert result[0].field_name == "unresolved_questions"


def test_unresolved_question_without_evidence_is_rejected() -> None:
    extraction = QuoteExtraction(
        unresolved_questions=["The dealer declined to provide a written OTD quote."],
        extraction_confidence=0.8,
    )

    with pytest.raises(EvidenceValidationError, match="unresolved_questions"):
        validate_evidence(
            dealer_message("We cannot provide a written OTD quote by email."),
            output(extraction=extraction, evidence=[]),
        )


def test_unresolved_question_evidence_absent_from_source_is_rejected() -> None:
    extraction = QuoteExtraction(
        unresolved_questions=["The dealer declined to provide a written OTD quote."],
        evidence_ids=["unresolved"],
        extraction_confidence=0.8,
    )

    with pytest.raises(EvidenceValidationError, match="does not occur"):
        validate_evidence(
            dealer_message("Please visit our store."),
            output(
                extraction=extraction,
                evidence=[
                    EvidenceDraft(
                        id="unresolved",
                        field_name="unresolved_questions",
                        excerpt="We cannot provide a written OTD quote by email.",
                    )
                ],
            ),
        )


def test_unresolved_question_evidence_requires_its_canonical_field() -> None:
    extraction = QuoteExtraction(
        unresolved_questions=["The dealer declined to provide a written OTD quote."],
        evidence_ids=["unresolved"],
        extraction_confidence=0.8,
    )

    with pytest.raises(EvidenceValidationError, match="unresolved_questions"):
        validate_evidence(
            dealer_message("We cannot provide a written OTD quote by email."),
            output(
                extraction=extraction,
                evidence=[
                    EvidenceDraft(
                        id="unresolved",
                        field_name="claimed_otd",
                        excerpt="We cannot provide a written OTD quote by email.",
                    )
                ],
            ),
        )


def test_evidence_not_associated_with_a_populated_claim_is_rejected() -> None:
    message = dealer_message("Selling price: $37,800. Friendly dealership.")
    extraction = QuoteExtraction(
        selling_price="37800",
        evidence_ids=["selling", "orphan"],
        extraction_confidence=0.8,
    )

    with pytest.raises(EvidenceValidationError, match="not associated"):
        validate_evidence(
            message,
            output(
                extraction=extraction,
                evidence=[
                    EvidenceDraft(
                        id="selling",
                        field_name="selling_price",
                        excerpt="Selling price: $37,800.",
                    ),
                    EvidenceDraft(
                        id="orphan",
                        field_name="claimed_otd",
                        excerpt="Friendly dealership.",
                    ),
                ],
            ),
        )


def test_unreferenced_evidence_for_a_populated_collection_is_rejected() -> None:
    message = dealer_message(
        "Documentation fee: $225. Another dealer-fee sentence appears here."
    )
    extraction = QuoteExtraction(
        dealer_fees=[
            MoneyItem(
                name="Documentation fee",
                amount="225",
                stated_mandatory=None,
                evidence_id="used",
            )
        ],
        evidence_ids=["used", "orphan"],
        extraction_confidence=0.8,
    )

    with pytest.raises(EvidenceValidationError, match="orphan"):
        validate_evidence(
            message,
            output(
                extraction=extraction,
                evidence=[
                    EvidenceDraft(
                        id="used",
                        field_name="dealer_fees",
                        excerpt="Documentation fee: $225.",
                    ),
                    EvidenceDraft(
                        id="orphan",
                        field_name="dealer_fees",
                        excerpt="Another dealer-fee sentence appears here.",
                    ),
                ],
            ),
        )
