from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain.agent_run import AgentRun
from app.domain.comparison import (
    AdvertisedVsVerified,
    ComparedOffer,
    ComparisonResult,
    ComparisonStatus,
    InventoryProvenance,
    OfferCondition,
    OfferRecommendation,
)
from app.domain.interaction import DealerInteraction
from app.domain.quote import QuoteAnalysisResult
from app.domain.vehicle import VehicleListing
from app.persistence.agent_runs import AgentRunRepository
from app.persistence.interactions import (
    InteractionRecordNotFoundError,
    InteractionRepository,
)
from app.providers.inventory import InventoryProvider


class InvalidOfferComparisonError(ValueError):
    """The requested run references cannot form a comparison."""


class ComparisonVehicleNotFoundError(LookupError):
    """A persisted run references inventory unavailable from the provider."""


def _evidence_ids_for(
    analysis: QuoteAnalysisResult,
    field_name: str,
) -> list[str]:
    return [
        evidence.id
        for evidence in analysis.evidence
        if evidence.field_name == field_name
    ]


def _conditions(analysis: QuoteAnalysisResult | None) -> list[OfferCondition]:
    if analysis is None:
        return []

    extraction = analysis.extraction
    conditions: list[OfferCondition] = []
    if extraction.financing_required is not None:
        qualifier = "is" if extraction.financing_required else "is not"
        conditions.append(
            OfferCondition(
                description=(
                    f"Dealer financing {qualifier} required for the stated offer."
                ),
                evidence_ids=_evidence_ids_for(
                    analysis,
                    "financing_required",
                ),
            )
        )
    if extraction.trade_required is not None:
        qualifier = "is" if extraction.trade_required else "is not"
        conditions.append(
            OfferCondition(
                description=f"A trade-in {qualifier} required for the stated offer.",
                evidence_ids=_evidence_ids_for(analysis, "trade_required"),
            )
        )

    for incentive in extraction.incentives:
        if incentive.eligibility_condition:
            amount = (
                f" ({_money(incentive.amount)})"
                if incentive.amount is not None
                else ""
            )
            conditions.append(
                OfferCondition(
                    description=(
                        f"{incentive.name}{amount}: "
                        f"{incentive.eligibility_condition}."
                    ),
                    evidence_ids=[incentive.evidence_id],
                )
            )

    if extraction.expiration is not None:
        conditions.append(
            OfferCondition(
                description=(
                    "The dealer states that the quote expires at "
                    f"{extraction.expiration.isoformat()}."
                ),
                evidence_ids=_evidence_ids_for(analysis, "expiration"),
            )
        )

    unresolved_evidence = _evidence_ids_for(analysis, "unresolved_questions")
    for question in extraction.unresolved_questions:
        conditions.append(
            OfferCondition(
                description=question,
                evidence_ids=unresolved_evidence,
            )
        )
    return conditions


def _comparison_status(
    run: AgentRun,
    interaction: DealerInteraction | None,
    *,
    eligible: bool,
    comparable: bool | None,
) -> ComparisonStatus:
    if eligible:
        return "VERIFIED"
    if run.phase == "RUN_REJECTED":
        return "REJECTED"
    if run.phase in {"RUN_FAILED", "ANALYSIS_FAILED"}:
        return "FAILED"
    if interaction is not None and interaction.analysis_status == "ANALYSIS_FAILED":
        return "FAILED"
    if run.phase == "DELIVERY_UNCONFIRMED":
        return "BLOCKED"
    if (
        run.phase
        in {"INTERACTION_COMPLETE", "INTERACTION_INCOMPLETE_MAX_FOLLOWUPS"}
        or (interaction is not None and interaction.analysis is not None and not comparable)
    ):
        return "INCOMPLETE"
    return "IN_PROGRESS"


def project_offer(
    run: AgentRun,
    interaction: DealerInteraction | None,
    listing: VehicleListing,
) -> ComparedOffer:
    """Project authoritative run, analysis, and inventory facts without mutation."""

    analysis = (
        interaction.analysis
        if interaction is not None and interaction.analysis_status == "ANALYZED"
        else None
    )
    extraction = analysis.extraction if analysis is not None else None
    assessment = analysis.assessment if analysis is not None else None
    claimed_otd = extraction.claimed_otd if extraction is not None else None
    comparable = assessment.comparable if assessment is not None else None
    eligible = (
        run.phase == "INTERACTION_COMPLETE"
        and interaction is not None
        and interaction.analysis_status == "ANALYZED"
        and comparable is True
        and claimed_otd is not None
    )
    status = _comparison_status(
        run,
        interaction,
        eligible=eligible,
        comparable=comparable,
    )

    evidence = list(analysis.evidence) if analysis is not None else []
    mandatory_addons = (
        [
            addon.model_copy(deep=True)
            for addon in extraction.addons
            if addon.stated_mandatory is True
        ]
        if extraction is not None
        else []
    )
    return ComparedOffer(
        agent_run_id=run.run_id,
        interaction_id=interaction.id if interaction is not None else None,
        vehicle_id=listing.id,
        dealer_id=listing.dealer_id,
        dealer_name=listing.dealer_name,
        advertised_price=listing.advertised_price,
        distance_miles=listing.distance_miles,
        inventory_provenance=InventoryProvenance(
            listing_id=listing.id,
            source_provider=listing.source_provider,
            source_url=listing.source_url,
        ),
        claimed_otd=claimed_otd,
        comparable=comparable,
        transparent=assessment.transparent if assessment is not None else None,
        reconciled=assessment.reconciled if assessment is not None else None,
        missing_for_comparison=(
            list(assessment.missing_for_comparison)
            if assessment is not None
            else []
        ),
        mandatory_addons=mandatory_addons,
        conditions=_conditions(analysis),
        sent_followup_count=(
            interaction.sent_followup_count if interaction is not None else 0
        ),
        run_phase=run.phase,
        analysis_status=(
            interaction.analysis_status if interaction is not None else None
        ),
        evidence=evidence,
        claimed_otd_evidence_ids=(
            _evidence_ids_for(analysis, "claimed_otd")
            if analysis is not None
            else []
        ),
        comparison_status=status,
        eligible=eligible,
    )


def _eligible_sort_key(
    offer: ComparedOffer,
) -> tuple[Decimal, bool, float, bool, Decimal, str]:
    if offer.claimed_otd is None:
        raise ValueError("An eligible offer must have a written OTD.")
    return (
        offer.claimed_otd,
        offer.distance_miles is None,
        offer.distance_miles if offer.distance_miles is not None else 0,
        offer.advertised_price is None,
        offer.advertised_price or Decimal("0"),
        offer.agent_run_id,
    )


def _distance_sort_key(offer: ComparedOffer) -> tuple[bool, float]:
    return (
        offer.distance_miles is None,
        offer.distance_miles if offer.distance_miles is not None else 0,
    )


def _advertised_price_sort_key(offer: ComparedOffer) -> tuple[bool, Decimal]:
    return (
        offer.advertised_price is None,
        offer.advertised_price or Decimal("0"),
    )


def _money(value: Decimal) -> str:
    return f"${value:,.2f}"


def _lowest_advertised(offers: list[ComparedOffer]) -> ComparedOffer | None:
    known = [offer for offer in offers if offer.advertised_price is not None]
    if not known:
        return None
    return min(
        known,
        key=lambda offer: (offer.advertised_price, offer.agent_run_id),
    )


def _advertised_vs_verified(
    offers: list[ComparedOffer],
    winner: ComparedOffer | None,
) -> AdvertisedVsVerified:
    lowest_advertised = _lowest_advertised(offers)
    lowest_verified_otd = (
        lowest_advertised.claimed_otd
        if lowest_advertised is not None and lowest_advertised.eligible
        else None
    )
    raw_advertised_difference = (
        winner.advertised_price - lowest_advertised.advertised_price
        if (
            winner is not None
            and winner.advertised_price is not None
            and lowest_advertised is not None
            and lowest_advertised.advertised_price is not None
        )
        else None
    )
    raw_verified_savings = (
        lowest_verified_otd - winner.claimed_otd
        if (
            winner is not None
            and winner.claimed_otd is not None
            and lowest_verified_otd is not None
        )
        else None
    )
    return AdvertisedVsVerified(
        lowest_advertised_agent_run_id=(
            lowest_advertised.agent_run_id
            if lowest_advertised is not None
            else None
        ),
        lowest_advertised_price=(
            lowest_advertised.advertised_price
            if lowest_advertised is not None
            else None
        ),
        lowest_advertised_verified_otd=lowest_verified_otd,
        recommended_agent_run_id=(winner.agent_run_id if winner is not None else None),
        recommended_advertised_price=(
            winner.advertised_price if winner is not None else None
        ),
        recommended_verified_otd=(
            winner.claimed_otd if winner is not None else None
        ),
        advertised_price_difference=raw_advertised_difference,
        verified_otd_savings=raw_verified_savings,
    )


def _otd_tie_fact(winner: ComparedOffer, next_best: ComparedOffer) -> str:
    if winner.claimed_otd is None:
        raise ValueError("A ranked winner must have a written OTD.")

    prefix = (
        f"The verified written OTD totals are tied at "
        f"{_money(winner.claimed_otd)}; {winner.dealer_name} ranks first"
    )
    if _distance_sort_key(winner) != _distance_sort_key(next_best):
        return f"{prefix} because it has the shorter known distance."
    if _advertised_price_sort_key(winner) != _advertised_price_sort_key(next_best):
        return f"{prefix} because it has the lower known advertised price."
    return (
        f"{prefix} only because the stable AgentRun identifier provides the final "
        "deterministic ordering."
    )


def _is_unresolved_alternative(offer: ComparedOffer) -> bool:
    if offer.run_phase in {"RUN_FAILED", "RUN_REJECTED"}:
        return False
    return (
        offer.comparison_status in {"INCOMPLETE", "IN_PROGRESS", "BLOCKED"}
        or offer.run_phase == "ANALYSIS_FAILED"
        or offer.analysis_status == "ANALYSIS_FAILED"
    )


def _recommendation(
    ranked: list[ComparedOffer],
    unresolved: list[ComparedOffer],
    advertised: AdvertisedVsVerified,
) -> OfferRecommendation | None:
    if not ranked:
        return None

    winner = ranked[0]
    if winner.claimed_otd is None:
        raise ValueError("A ranked winner must have a written OTD.")
    next_best = ranked[1] if len(ranked) > 1 else None
    next_otd = next_best.claimed_otd if next_best is not None else None
    savings = next_otd - winner.claimed_otd if next_otd is not None else None
    if next_best is None:
        facts = [
            (
                f"{winner.dealer_name} is currently the only verified written "
                f"offer at {_money(winner.claimed_otd)}."
            ),
            "No second verified offer is currently available.",
        ]
    elif savings == 0:
        facts = [
            (
                f"{winner.dealer_name} shares the lowest verified written OTD at "
                f"{_money(winner.claimed_otd)}."
            ),
            _otd_tie_fact(winner, next_best),
        ]
    else:
        facts = [
            (
                f"{winner.dealer_name} is the lowest verified written OTD at "
                f"{_money(winner.claimed_otd)}."
            ),
            (
                f"That is {_money(savings)} below {next_best.dealer_name}'s "
                "verified written OTD."
            ),
        ]

    lowest_advertised = next(
        (
            offer
            for offer in (*ranked, *unresolved)
            if offer.agent_run_id == advertised.lowest_advertised_agent_run_id
        ),
        None,
    )
    if (
        lowest_advertised is not None
        and lowest_advertised.agent_run_id != winner.agent_run_id
        and advertised.advertised_price_difference is not None
        and advertised.advertised_price_difference > 0
        and advertised.verified_otd_savings is not None
        and advertised.verified_otd_savings > 0
    ):
        facts.append(
            (
                f"{lowest_advertised.dealer_name} looked "
                f"{_money(advertised.advertised_price_difference)} cheaper "
                f"online, but {winner.dealer_name} has the lower verified "
                "transaction cost."
            )
        )

    for offer in unresolved:
        status = offer.comparison_status.casefold().replace("_", " ")
        if offer.claimed_otd is not None:
            facts.append(
                (
                    f"{offer.dealer_name} has a stated "
                    f"{_money(offer.claimed_otd)} OTD but remains {status} and "
                    "is not rankable."
                )
            )
        else:
            facts.append(
                f"{offer.dealer_name} remains {status} and is not rankable."
            )

    return OfferRecommendation(
        recommended_agent_run_id=winner.agent_run_id,
        recommended_dealer_id=winner.dealer_id,
        recommended_dealer_name=winner.dealer_name,
        recommended_otd=winner.claimed_otd,
        next_best_verified_otd=next_otd,
        savings_vs_next_verified=savings,
        has_unresolved_alternatives=any(
            _is_unresolved_alternative(offer) for offer in unresolved
        ),
        explanation_facts=facts,
    )


def build_comparison(offers: list[ComparedOffer]) -> ComparisonResult:
    """Rank verified offers and retain every non-rankable alternative."""

    eligible = sorted(
        (offer for offer in offers if offer.eligible),
        key=_eligible_sort_key,
    )
    ranked = [
        offer.model_copy(update={"verified_rank": index})
        for index, offer in enumerate(eligible, start=1)
    ]
    unresolved = sorted(
        (
            offer.model_copy(update={"verified_rank": None})
            for offer in offers
            if not offer.eligible
        ),
        key=lambda offer: offer.agent_run_id,
    )
    ordered = [*ranked, *unresolved]
    winner = ranked[0] if ranked else None
    advertised = _advertised_vs_verified(ordered, winner)
    return ComparisonResult(
        offers=ordered,
        ranked_agent_run_ids=[offer.agent_run_id for offer in ranked],
        recommendation=_recommendation(ranked, unresolved, advertised),
        advertised_vs_verified=advertised,
    )


class OfferComparisonService:
    """Load existing authoritative records and derive a comparison read model."""

    def __init__(
        self,
        *,
        session: Session,
        inventory_provider: InventoryProvider,
    ) -> None:
        self._runs = AgentRunRepository(session)
        self._interactions = InteractionRepository(session)
        self._inventory = inventory_provider

    async def compare(self, agent_run_ids: list[str]) -> ComparisonResult:
        if len(agent_run_ids) < 2 or len(agent_run_ids) != len(set(agent_run_ids)):
            raise InvalidOfferComparisonError(
                "At least two unique AgentRun IDs are required."
            )

        # Resolve every stable run reference before loading any other facts so an
        # unknown ID fails the request at the authority boundary.
        runs = [self._runs.get(run_id) for run_id in agent_run_ids]

        offers: list[ComparedOffer] = []
        for run in runs:
            listing = await self._inventory.get_by_id(run.vehicle_id)
            if listing is None:
                raise ComparisonVehicleNotFoundError(run.vehicle_id)

            # The interaction can be newer than the AgentRun phase projection.
            # Read it through the immutable initial-action relationship without
            # resuming or repairing the run.
            try:
                interaction = self._interactions.get(run.initial_action_id)
            except InteractionRecordNotFoundError:
                interaction = None
            offers.append(project_offer(run, interaction, listing))
        return build_comparison(offers)
