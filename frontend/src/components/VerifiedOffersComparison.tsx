import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import type { AgentRunSnapshot, RunPhase } from "./AgentWorkflow";
import { EvidenceDrawer, type Evidence } from "./QuoteAnalysisWorkspace";

type ComparisonStatus =
  | "VERIFIED"
  | "INCOMPLETE"
  | "IN_PROGRESS"
  | "BLOCKED"
  | "FAILED"
  | "REJECTED";

type InventoryProvenance = {
  source_type: "INVENTORY_LISTING";
  listing_id?: string;
  source_provider: string;
  source_url: string;
};

type MandatoryAddon = {
  name: string;
  amount: string | null;
  stated_mandatory: boolean | null;
  evidence_id: string;
};

type OfferCondition = {
  description: string;
  evidence_ids: string[];
};

export type ComparedOffer = {
  agent_run_id: string;
  interaction_id?: string | null;
  vehicle_id?: string;
  dealer_id?: string;
  dealer_name: string;
  advertised_price: string | null;
  inventory_provenance: InventoryProvenance | null;
  distance_miles?: number | null;
  claimed_otd: string | null;
  comparable?: boolean | null;
  transparent?: boolean | null;
  reconciled?: boolean | null;
  missing_for_comparison?: string[];
  mandatory_addons: MandatoryAddon[];
  conditions: OfferCondition[];
  sent_followup_count?: number;
  run_phase: RunPhase;
  analysis_status?: string | null;
  evidence: Evidence[];
  claimed_otd_evidence_ids: string[];
  comparison_status: ComparisonStatus;
  eligible: boolean;
  verified_rank: number | null;
};

type ComparisonRecommendation = {
  recommended_agent_run_id: string;
  recommended_dealer_id: string;
  recommended_dealer_name: string;
  recommended_otd: string;
  next_best_verified_otd: string | null;
  savings_vs_next_verified: string | null;
  has_unresolved_alternatives: boolean;
  explanation_facts: string[];
};

type AdvertisedVsVerified = {
  lowest_advertised_agent_run_id: string | null;
  lowest_advertised_price: string | null;
  lowest_advertised_verified_otd: string | null;
  recommended_agent_run_id: string | null;
  recommended_advertised_price: string | null;
  recommended_verified_otd: string | null;
  advertised_price_difference: string | null;
  verified_otd_savings: string | null;
};

export type OfferComparisonResult = {
  offers: ComparedOffer[];
  ranked_agent_run_ids: string[];
  recommendation: ComparisonRecommendation | null;
  advertised_vs_verified: AdvertisedVsVerified;
};

type ApiErrorPayload = {
  detail?: string | { message?: string };
};

type StatusPresentation = {
  label: string;
  tone: "verified" | "incomplete" | "progress" | "blocked" | "failed" | "rejected";
};

const statusPresentations: Record<ComparisonStatus, StatusPresentation> = {
  VERIFIED: { label: "Verified", tone: "verified" },
  INCOMPLETE: { label: "Incomplete", tone: "incomplete" },
  IN_PROGRESS: { label: "In progress", tone: "progress" },
  BLOCKED: { label: "Blocked", tone: "blocked" },
  FAILED: { label: "Failed", tone: "failed" },
  REJECTED: { label: "Rejected", tone: "rejected" },
};

const currencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatMoney(value: string | null): string {
  if (value === null) return "—";
  const amount = Number(value);
  return Number.isFinite(amount) ? currencyFormatter.format(amount) : value;
}

function isPositiveMoney(value: string | null): boolean {
  if (value === null) return false;
  const amount = Number(value);
  return Number.isFinite(amount) && amount > 0;
}

function formatIdentifier(value: string): string {
  const words = value.replaceAll("_", " ").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

async function apiError(response: Response): Promise<Error> {
  const payload = (await response.json().catch(() => null)) as ApiErrorPayload | null;
  const detail = payload?.detail;
  const message = typeof detail === "string" ? detail : detail?.message;
  return new Error(message ?? "The verified-offer comparison could not be loaded.");
}

async function compareOffers(
  apiBaseUrl: string,
  runs: AgentRunSnapshot[],
): Promise<OfferComparisonResult> {
  const response = await fetch(`${apiBaseUrl}/offer-comparisons`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      agent_run_ids: runs.map((run) => run.run_id),
    }),
  });
  if (!response.ok) throw await apiError(response);
  return response.json() as Promise<OfferComparisonResult>;
}

function evidenceFor(offer: ComparedOffer, evidenceId: string): Evidence | null {
  return offer.evidence.find((evidence) => evidence.id === evidenceId) ?? null;
}

function EvidenceButton({
  evidence,
  label,
  onSelect,
}: {
  evidence: Evidence | null;
  label: string;
  onSelect: (evidence: Evidence) => void;
}) {
  if (!evidence) return null;
  return <button
    className="evidence-trigger"
    onClick={() => onSelect(evidence)}
    type="button"
  >
    {label}
  </button>;
}

function AdvertisedPrice({ offer }: { offer: ComparedOffer }) {
  const provenance = offer.inventory_provenance;
  return <div className="comparison-money-cell">
    <strong>{formatMoney(offer.advertised_price)}</strong>
    {provenance
      ? <a
        aria-label={`${offer.dealer_name} inventory listing`}
        href={provenance.source_url}
      >
        Inventory listing · {provenance.source_provider}
      </a>
      : <span className="muted">Inventory source unavailable</span>}
  </div>;
}

function WrittenOtd({
  offer,
  onSelectEvidence,
}: {
  offer: ComparedOffer;
  onSelectEvidence: (evidence: Evidence) => void;
}) {
  return <div className="comparison-money-cell">
    <strong>{formatMoney(offer.claimed_otd)}</strong>
    {offer.claimed_otd !== null && <span className="comparison-source-label">
      Dealer response
    </span>}
    {offer.claimed_otd_evidence_ids.map((evidenceId, index) => <EvidenceButton
      evidence={evidenceFor(offer, evidenceId)}
      key={`${offer.agent_run_id}:${evidenceId}`}
      label={offer.claimed_otd_evidence_ids.length === 1
        ? `View ${offer.dealer_name} written OTD evidence`
        : `View ${offer.dealer_name} written OTD evidence ${index + 1}`}
      onSelect={onSelectEvidence}
    />)}
    {!offer.eligible && <span className="comparison-ineligible">Not eligible</span>}
  </div>;
}

function OfferTerms({
  offer,
  onSelectEvidence,
}: {
  offer: ComparedOffer;
  onSelectEvidence: (evidence: Evidence) => void;
}) {
  const noAddonsEvidence = offer.evidence.find(
    (evidence) => evidence.field_name === "explicit_no_addons_statement",
  ) ?? null;

  return <div className="comparison-terms">
    {!offer.mandatory_addons.length && (offer.eligible
      ? <div className="comparison-term">
        <span>No mandatory dealer add-ons</span>
        <EvidenceButton
          evidence={noAddonsEvidence}
          label="View no-addons evidence"
          onSelect={onSelectEvidence}
        />
      </div>
      : <span className="muted">No verified mandatory-add-on conclusion</span>)}
    {offer.mandatory_addons.map((addon) => <div
      className="comparison-term"
      key={`${offer.agent_run_id}:${addon.evidence_id}:${addon.name}`}
    >
      <span><strong>{addon.name}</strong> · {formatMoney(addon.amount)}</span>
      <EvidenceButton
        evidence={evidenceFor(offer, addon.evidence_id)}
        label={`View ${addon.name} evidence`}
        onSelect={onSelectEvidence}
      />
    </div>)}
    {offer.conditions.map((condition, conditionIndex) => <div
      className="comparison-term comparison-condition"
      key={`${offer.agent_run_id}:condition:${conditionIndex}`}
    >
      <span>{condition.description}</span>
      {condition.evidence_ids.map((evidenceId, evidenceIndex) => <EvidenceButton
        evidence={evidenceFor(offer, evidenceId)}
        key={`${offer.agent_run_id}:condition:${conditionIndex}:${evidenceId}`}
        label={condition.evidence_ids.length === 1
          ? `View ${offer.dealer_name} condition evidence ${conditionIndex + 1}`
          : `View ${offer.dealer_name} condition ${conditionIndex + 1} evidence ${evidenceIndex + 1}`}
        onSelect={onSelectEvidence}
      />)}
    </div>)}
  </div>;
}

function OfferStatus({ offer }: { offer: ComparedOffer }) {
  const presentation = statusPresentations[offer.comparison_status];
  return <div className="comparison-status-cell">
    <span className={`comparison-status comparison-status-${presentation.tone}`}>
      {presentation.label}
    </span>
    {offer.verified_rank !== null && <span>Verified rank #{offer.verified_rank}</span>}
    <span>{formatIdentifier(offer.run_phase)}</span>
  </div>;
}

function Recommendation({
  heading,
  result,
}: {
  heading: string;
  result: OfferComparisonResult;
}) {
  const recommendation = result.recommendation;
  if (!recommendation) {
    return <section className="comparison-recommendation comparison-recommendation-empty">
      <p className="eyebrow">Recommendation</p>
      <h3>No verified offer yet</h3>
      <p>Included dealer workflows remain visible, but none currently meets the authoritative comparison policy.</p>
    </section>;
  }

  const advertised = result.advertised_vs_verified;
  const lowestAdvertised = result.offers.find(
    (offer) => offer.agent_run_id === advertised.lowest_advertised_agent_run_id,
  );
  const recommended = result.offers.find(
    (offer) => offer.agent_run_id === recommendation.recommended_agent_run_id,
  );
  const hasAdvertisedReversal = (
    lowestAdvertised
    && recommended
    && lowestAdvertised.agent_run_id !== recommended.agent_run_id
    && isPositiveMoney(advertised.advertised_price_difference)
    && isPositiveMoney(advertised.verified_otd_savings)
  );

  return <section className="comparison-recommendation">
    <p className="eyebrow">Recommendation</p>
    <h3>{heading}</h3>
    <div className="comparison-winner">
      <strong>{recommendation.recommended_dealer_name}</strong>
      <span>{formatMoney(recommendation.recommended_otd)} written OTD</span>
    </div>
    {lowestAdvertised && recommended && <div
      aria-label="Advertised versus verified"
      className="comparison-price-story"
      role="group"
    >
      <div>
        <span className="comparison-price-story-label">Lowest advertised listing</span>
        <strong>{`${lowestAdvertised.dealer_name} — ${formatMoney(advertised.lowest_advertised_price)}`}</strong>
        <small>{lowestAdvertised.eligible
          ? "Eligible verified offer"
          : `${statusPresentations[lowestAdvertised.comparison_status].label}; not eligible to win`}</small>
      </div>
      <div>
        <span className="comparison-price-story-label">Best verified transaction cost</span>
        <strong>{`${recommended.dealer_name} — ${formatMoney(recommendation.recommended_otd)} written OTD`}</strong>
        <small>Ranked from authoritative dealer-response economics</small>
      </div>
    </div>}
    {!!recommendation.explanation_facts.length && <ul>
      {recommendation.explanation_facts.map((fact, index) => <li key={`${index}:${fact}`}>
        {fact}
      </li>)}
    </ul>}
    {hasAdvertisedReversal && <p className="advertised-reversal">
      <strong>{lowestAdvertised.dealer_name}</strong> looked {formatMoney(advertised.advertised_price_difference)} cheaper in inventory,
      but <strong>{recommended.dealer_name}</strong> saves {formatMoney(advertised.verified_otd_savings)} on verified written OTD.
    </p>}
    {recommendation.has_unresolved_alternatives && <p className="comparison-caveat">
      Unresolved alternatives remain. This is the best verified offer, not a guarantee that every incomplete offer is more expensive.
    </p>}
  </section>;
}

function VerifiedOffersPresentation({
  error,
  isPending,
  recommendationHeading,
  result,
}: {
  error?: string;
  isPending?: boolean;
  recommendationHeading: string;
  result?: OfferComparisonResult;
}) {
  const [selectedEvidence, setSelectedEvidence] = useState<{
    agentRunId: string;
    evidenceId: string;
    sourceId: string;
  } | null>(null);
  const selectedOffer = selectedEvidence && result
    ? result.offers.find(
      (offer) => offer.agent_run_id === selectedEvidence.agentRunId,
    ) ?? null
    : null;
  const currentEvidence = selectedEvidence && selectedOffer
    ? selectedOffer.evidence.find(
      (evidence) => (
        evidence.id === selectedEvidence.evidenceId
        && evidence.source_id === selectedEvidence.sourceId
      ),
    ) ?? null
    : null;
  useEffect(() => {
    if (selectedEvidence && result && !currentEvidence) {
      setSelectedEvidence(null);
    }
  }, [currentEvidence, result, selectedEvidence]);

  return <section className="verified-offers" aria-labelledby="verified-offers-heading">
    <p className="eyebrow">Cross-dealer decision</p>
    <h2 id="verified-offers-heading">Verified offers</h2>
    <p className="section-summary">
      Advertised inventory prices and dealer-written out-the-door totals are separate facts. Only offers that satisfy authoritative comparison policy can win.
    </p>

    {isPending && <p className="analysis-status" role="status">
      Loading current authoritative dealer-run results…
    </p>}
    {error && <p className="error" role="alert">
      {error}
    </p>}

    {result && <>
      <div className="comparison-table-scroll">
        <table aria-label="Verified dealer offers" className="comparison-table">
          <thead>
            <tr>
              <th scope="col">Dealer</th>
              <th scope="col">Advertised price — inventory listing</th>
              <th scope="col">Written OTD — dealer response</th>
              <th scope="col">Mandatory add-ons and conditions</th>
              <th scope="col">Status</th>
              <th scope="col">Follow-ups</th>
              <th scope="col">Distance</th>
            </tr>
          </thead>
          <tbody>
            {result.offers.map((offer) => <tr
              className={`comparison-row comparison-row-${statusPresentations[offer.comparison_status].tone}`}
              key={offer.agent_run_id}
            >
              <th scope="row">{offer.dealer_name}</th>
              <td><AdvertisedPrice offer={offer} /></td>
              <td><WrittenOtd
                offer={offer}
                onSelectEvidence={(evidence) => setSelectedEvidence({
                  agentRunId: offer.agent_run_id,
                  evidenceId: evidence.id,
                  sourceId: evidence.source_id,
                })}
              /></td>
              <td><OfferTerms
                offer={offer}
                onSelectEvidence={(evidence) => setSelectedEvidence({
                  agentRunId: offer.agent_run_id,
                  evidenceId: evidence.id,
                  sourceId: evidence.source_id,
                })}
              /></td>
              <td><OfferStatus offer={offer} /></td>
              <td>{offer.sent_followup_count ?? 0}</td>
              <td>{offer.distance_miles === null || offer.distance_miles === undefined
                ? "—"
                : `${offer.distance_miles.toLocaleString()} mi`}</td>
            </tr>)}
          </tbody>
        </table>
      </div>
      <Recommendation heading={recommendationHeading} result={result} />
    </>}

    {currentEvidence && <EvidenceDrawer
      evidence={currentEvidence}
      key={`${selectedEvidence?.agentRunId}:${currentEvidence.source_id}:${currentEvidence.id}`}
      onClose={() => setSelectedEvidence(null)}
    />}
  </section>;
}

export function VerifiedOffersComparisonView({
  recommendationHeading = "Best verified offer",
  result,
}: {
  recommendationHeading?: string;
  result: OfferComparisonResult;
}) {
  return <VerifiedOffersPresentation
    recommendationHeading={recommendationHeading}
    result={result}
  />;
}

export function VerifiedOffersComparison({
  apiBaseUrl,
  runs,
}: {
  apiBaseUrl: string;
  runs: AgentRunSnapshot[];
}) {
  const comparison = useQuery({
    queryKey: [
      "offer-comparison",
      apiBaseUrl,
      runs.map((run) => ({ run_id: run.run_id, updated_at: run.updated_at })),
    ],
    queryFn: () => compareOffers(apiBaseUrl, runs),
    enabled: runs.length >= 2,
    retry: false,
  });

  if (runs.length < 2) return null;

  return <VerifiedOffersPresentation
    error={comparison.isError ? comparison.error.message : undefined}
    isPending={comparison.isPending}
    recommendationHeading="Best verified offer"
    result={comparison.data}
  />;
}
