from __future__ import annotations

import json
import unicodedata
from collections import defaultdict
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from app.domain.interaction import DealerInteraction
from app.domain.quote import MoneyItem
from app.domain.research import ResearchTarget
from app.services.quote_assessment import MANDATORY_ADDON_AMOUNT


MATERIAL_ADDON_THRESHOLD = Decimal("500")


def normalize_research_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split()).casefold()


def _canonical_display_name(items: list[MoneyItem]) -> str:
    names = {
        " ".join(unicodedata.normalize("NFKC", item.name).split())
        for item in items
    }
    return min(names, key=lambda value: (value.casefold(), value))


def _amount_identity(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalized = value.normalize()
    return format(normalized, "f")


def _target_id(
    *,
    purchase_run_id: str,
    agent_run_id: str,
    interaction: DealerInteraction,
    source_message_id: str,
    normalized_name: str,
    amount: Decimal | None,
    evidence_ids: list[str],
) -> str:
    identity = {
        "purchase_run_id": purchase_run_id,
        "agent_run_id": agent_run_id,
        "interaction_id": interaction.id,
        "source_message_id": source_message_id,
        "dealer_id": interaction.dealer_id,
        "vehicle_id": interaction.vehicle_id,
        "target_type": "MANDATORY_ADDON",
        "normalized_name": normalized_name,
        "dealer_stated_amount": _amount_identity(amount),
        "stated_mandatory": True,
        "source_evidence_ids": evidence_ids,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return str(uuid5(NAMESPACE_URL, f"out-the-door-agent:research-target:{encoded}"))


def derive_research_targets(
    *,
    purchase_run_id: str,
    agent_run_id: str,
    interaction: DealerInteraction,
) -> list[ResearchTarget]:
    """Derive narrow, versioned targets from the current validated quote only."""

    if interaction.analysis_status != "ANALYZED" or interaction.analysis is None:
        return []

    analysis = interaction.analysis
    source_message_id = analysis.message.id
    evidence_ids = {
        evidence.id
        for evidence in analysis.evidence
        if evidence.field_name == "addons"
        and evidence.source_id == source_message_id
    }
    amount_unknown_is_material = (
        MANDATORY_ADDON_AMOUNT
        in analysis.assessment.missing_for_comparison
    )

    grouped: dict[tuple[str, str | None], list[MoneyItem]] = defaultdict(list)
    for addon in analysis.extraction.addons:
        normalized_name = normalize_research_name(addon.name)
        if (
            addon.stated_mandatory is not True
            or not normalized_name
            or addon.evidence_id not in evidence_ids
            or (
                addon.amount is not None
                and addon.amount < MATERIAL_ADDON_THRESHOLD
            )
            or (addon.amount is None and not amount_unknown_is_material)
        ):
            continue
        grouped[(normalized_name, _amount_identity(addon.amount))].append(addon)

    targets: list[ResearchTarget] = []
    for (normalized_name, _), items in grouped.items():
        evidence = sorted({item.evidence_id for item in items})
        amount = items[0].amount
        targets.append(
            ResearchTarget(
                target_id=_target_id(
                    purchase_run_id=purchase_run_id,
                    agent_run_id=agent_run_id,
                    interaction=interaction,
                    source_message_id=source_message_id,
                    normalized_name=normalized_name,
                    amount=amount,
                    evidence_ids=evidence,
                ),
                purchase_run_id=purchase_run_id,
                agent_run_id=agent_run_id,
                interaction_id=interaction.id,
                source_message_id=source_message_id,
                dealer_id=interaction.dealer_id,
                dealer_name=interaction.vehicle.dealer_name,
                vehicle_id=interaction.vehicle_id,
                canonical_name=_canonical_display_name(items),
                dealer_stated_amount=amount,
                source_evidence_ids=evidence,
            )
        )
    return sorted(
        targets,
        key=lambda target: (
            normalize_research_name(target.canonical_name),
            target.dealer_stated_amount is None,
            target.dealer_stated_amount or Decimal("0"),
            target.target_id,
        ),
    )
