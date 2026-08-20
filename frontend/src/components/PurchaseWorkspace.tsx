import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AgentWorkflow, type AgentRun } from "./AgentWorkflow";
import type { OutreachCandidate } from "./OutreachApproval";
import {
  VerifiedOffersComparisonView,
  type OfferComparisonResult,
  type ResearchTargetView,
} from "./VerifiedOffersComparison";

type PurchaseSetupStatus = "READY" | "RECOVERY_REQUIRED";
type PurchaseDecisionStatus =
  | "GATHERING_OFFERS"
  | "COMPARISON_AVAILABLE"
  | "DECISION_READY";
type PurchaseWorkflowStatus =
  | "RECOVERY_REQUIRED"
  | "APPROVAL_REQUIRED"
  | "DELIVERY_UNCONFIRMED"
  | "WAITING_FOR_DEALER"
  | "WAITING_FOR_ANALYSIS"
  | "ANALYSIS_FAILED"
  | "OFFER_INCOMPLETE"
  | "OFFER_VERIFIED"
  | "RUN_FAILED"
  | "RUN_REJECTED";
type PurchaseAttentionCategory = Exclude<PurchaseWorkflowStatus, "OFFER_VERIFIED">;

export type PurchaseVehicle = OutreachCandidate & {
  condition: "new" | "used";
  mileage: number | null;
  advertised_price: string | null;
  msrp: string | null;
  exterior_color: string | null;
  interior_color: string | null;
  features: string[];
  latitude: number | null;
  longitude: number | null;
  distance_miles: number | null;
  source_url: string;
  source_provider: string;
};

type PurchaseStatusCounts = {
  selected_vehicles: number;
  linked_children: number;
  quote_requests_prepared: number;
  responses_analyzed: number;
  verified_offers: number;
  incomplete_offers: number;
  pending_approvals: number;
};

type PurchaseAttentionItem = {
  category: PurchaseAttentionCategory;
  vehicle_id: string;
  dealer_name: string;
  agent_run_id: string | null;
  action_id: string | null;
  message: string;
  requires_buyer_action: boolean;
};

type PurchaseActivityItem = {
  event_id: string;
  agent_run_id: string;
  vehicle_id: string;
  event_type: string;
  message: string;
  occurred_at: string;
};

type PurchaseChild = {
  vehicle: PurchaseVehicle;
  agent_run: AgentRun | null;
  workflow_status: PurchaseWorkflowStatus;
  comparison_status: string | null;
  action_id: string | null;
  creation_error_code: string | null;
  active_unresolved: boolean;
};

export type PurchaseWorkspaceModel = {
  id: string;
  goal: string;
  setup_status: PurchaseSetupStatus;
  selected_vehicle_ids: string[];
  children: PurchaseChild[];
  counts: PurchaseStatusCounts;
  attention_items: PurchaseAttentionItem[];
  comparison: OfferComparisonResult | null;
  decision_status: PurchaseDecisionStatus;
  created_at: string;
  updated_at: string;
};

type ApiErrorPayload = {
  detail?: string | { code?: string; message?: string };
};

class ResearchApiError extends Error {
  readonly code: string | null;
  readonly status: number;

  constructor(
    message: string,
    { code, status }: { code: string | null; status: number },
  ) {
    super(message);
    this.name = "ResearchApiError";
    this.code = code;
    this.status = status;
  }
}

const decisionLabels: Record<PurchaseDecisionStatus, string> = {
  GATHERING_OFFERS: "Gathering offers",
  COMPARISON_AVAILABLE: "Comparison available",
  DECISION_READY: "Decision ready",
};

const workflowLabels: Record<PurchaseWorkflowStatus, string> = {
  RECOVERY_REQUIRED: "Workflow recovery required",
  APPROVAL_REQUIRED: "Approval required",
  DELIVERY_UNCONFIRMED: "Delivery unconfirmed",
  WAITING_FOR_DEALER: "Waiting for dealer",
  WAITING_FOR_ANALYSIS: "Waiting for analysis",
  ANALYSIS_FAILED: "Analysis failed",
  OFFER_INCOMPLETE: "Offer incomplete",
  OFFER_VERIFIED: "Offer verified",
  RUN_FAILED: "Workflow failed",
  RUN_REJECTED: "Workflow rejected",
};

const activityLabels: Record<string, string> = {
  RUN_STARTED: "Workflow started",
  INITIAL_OUTREACH_PREPARED: "Quote request prepared",
  WAITING_FOR_APPROVAL: "Exact action awaiting approval",
  OUTREACH_SENT: "Quote request delivery confirmed",
  FOLLOWUP_SENT: "Follow-up delivery confirmed",
  DELIVERY_UNCONFIRMED: "Delivery unconfirmed",
  WAITING_FOR_EXTERNAL_RESPONSE: "Waiting for dealer response",
  WAITING_FOR_ANALYSIS: "Dealer response awaiting analysis",
  ANALYSIS_FAILED: "Response analysis failed",
  RESPONSE_ANALYZED: "Dealer response analyzed",
  FOLLOWUP_PREPARED: "Clarification prepared",
  FOLLOWUP_STALE: "Earlier clarification superseded",
  INTERACTION_COMPLETE: "Offer verified",
  MAX_FOLLOWUPS_REACHED: "Clarification limit reached",
  RUN_REJECTED: "Workflow stopped",
  RUN_FAILED: "Workflow failed",
};

const purchaseCurrencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const purchaseActivityDateFormatter = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});
const recentActivityLimit = 8;

async function apiError(response: Response, fallback: string): Promise<Error> {
  const payload = (await response.json().catch(() => null)) as ApiErrorPayload | null;
  const detail = payload?.detail;
  const message = typeof detail === "string" ? detail : detail?.message;
  return new Error(message ?? fallback);
}

async function inspectPurchase(
  apiBaseUrl: string,
  purchaseId: string,
): Promise<PurchaseWorkspaceModel> {
  const response = await fetch(`${apiBaseUrl}/purchase-runs/${encodeURIComponent(purchaseId)}`);
  if (!response.ok) {
    throw await apiError(response, "The purchase workspace could not be loaded.");
  }
  return response.json() as Promise<PurchaseWorkspaceModel>;
}

async function inspectPurchaseActivity(
  apiBaseUrl: string,
  purchaseId: string,
): Promise<PurchaseActivityItem[]> {
  const response = await fetch(
    `${apiBaseUrl}/purchase-runs/${encodeURIComponent(purchaseId)}/activity`,
  );
  if (!response.ok) {
    throw await apiError(response, "Purchase activity could not be loaded.");
  }
  return response.json() as Promise<PurchaseActivityItem[]>;
}

async function recoverPurchase(
  apiBaseUrl: string,
  purchaseId: string,
): Promise<PurchaseWorkspaceModel> {
  const response = await fetch(`${apiBaseUrl}/purchase-runs/${encodeURIComponent(purchaseId)}/recover`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  if (!response.ok) {
    throw await apiError(response, "The missing dealer workflows could not be recovered.");
  }
  return response.json() as Promise<PurchaseWorkspaceModel>;
}

async function inspectResearchTargets(
  apiBaseUrl: string,
  purchaseId: string,
): Promise<ResearchTargetView[]> {
  const response = await fetch(
    `${apiBaseUrl}/purchase-runs/${encodeURIComponent(purchaseId)}/research-targets`,
  );
  if (!response.ok) {
    throw await apiError(response, "Independent research targets could not be loaded.");
  }
  return response.json() as Promise<ResearchTargetView[]>;
}

async function investigateResearchTarget(
  apiBaseUrl: string,
  purchaseId: string,
  targetId: string,
): Promise<ResearchTargetView> {
  const response = await fetch(
    `${apiBaseUrl}/purchase-runs/${encodeURIComponent(purchaseId)}/research-targets/${encodeURIComponent(targetId)}/investigate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    },
  );
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as ApiErrorPayload | null;
    const detail = payload?.detail;
    const message = typeof detail === "string"
      ? detail
      : detail?.message ?? "Independent research could not be completed.";
    const code = typeof detail === "string" ? null : detail?.code ?? null;
    throw new ResearchApiError(message, {
      code,
      status: response.status,
    });
  }
  return response.json() as Promise<ResearchTargetView>;
}

function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

function formatPurchaseMoney(value: string): string {
  const amount = Number(value);
  return Number.isFinite(amount) ? purchaseCurrencyFormatter.format(amount) : value;
}

function formatActivityLabel(eventType: string): string {
  return activityLabels[eventType] ?? eventType
    .toLowerCase()
    .replaceAll("_", " ")
    .replace(/^./, (first) => first.toUpperCase());
}

function formatActivityDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : purchaseActivityDateFormatter.format(date);
}

function compareActivityItems(left: PurchaseActivityItem, right: PurchaseActivityItem): number {
  const leftTime = Date.parse(left.occurred_at);
  const rightTime = Date.parse(right.occurred_at);
  if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) {
    return leftTime - rightTime;
  }
  const timestampOrder = left.occurred_at.localeCompare(right.occurred_at);
  return timestampOrder || left.event_id.localeCompare(right.event_id);
}

function PurchaseDecisionSummary({ workspace }: { workspace: PurchaseWorkspaceModel }) {
  const buyerActions = workspace.attention_items.filter((item) => item.requires_buyer_action);
  const firstBuyerAction = buyerActions[0] ?? null;
  const recommendation = workspace.comparison?.recommendation ?? null;
  const counts = workspace.counts;

  return <section
    aria-labelledby="purchase-decision-summary-heading"
    className="purchase-decision-summary"
  >
    <div className="purchase-decision-summary-heading">
      <div>
        <p className="eyebrow">Decision snapshot</p>
        <h2 id="purchase-decision-summary-heading">Purchase decision summary</h2>
      </div>
      <p className="purchase-operation-progress">
        {plural(counts.linked_children, "workflow")} linked
        <span aria-hidden="true"> · </span>
        {plural(counts.quote_requests_prepared, "quote request")} prepared
        <span aria-hidden="true"> · </span>
        {plural(counts.responses_analyzed, "response")} analyzed
        <span aria-hidden="true"> · </span>
        {plural(counts.pending_approvals, "pending approval")}
      </p>
    </div>
    <ul aria-label="Decision totals" className="purchase-decision-stats">
      <li>{plural(counts.selected_vehicles, "dealer")} selected</li>
      <li>{plural(counts.verified_offers, "verified offer")}</li>
      <li>{plural(counts.incomplete_offers, "incomplete offer")}</li>
      <li>{plural(buyerActions.length, "buyer action")}</li>
    </ul>
    <div className="purchase-decision-callouts">
      <div className={firstBuyerAction ? "purchase-decision-callout-attention" : undefined}>
        <span className="purchase-decision-callout-label">BUYER ACTION</span>
        {firstBuyerAction
          ? <>
            <a href={`#purchase-child-${encodeURIComponent(firstBuyerAction.vehicle_id)}`}>
              {firstBuyerAction.message}
            </a>
            {buyerActions.length > 1 && <small>
              +{buyerActions.length - 1} more below
            </small>}
          </>
          : <strong>No buyer action required right now.</strong>}
      </div>
      <div>
        <span className="purchase-decision-callout-label">BEST VERIFIED OFFER SO FAR</span>
        {recommendation
          ? <>
            <strong>{recommendation.recommended_dealer_name}</strong>
            <span>{formatPurchaseMoney(recommendation.recommended_otd)}</span>
          </>
          : <>
            <strong>No verified offer yet.</strong>
            <span>Dealer workflows remain visible below.</span>
          </>}
      </div>
    </div>
  </section>;
}

function PurchaseActivity({
  children,
  error,
  isPending,
  items,
}: {
  children: PurchaseChild[];
  error: string | null;
  isPending: boolean;
  items: PurchaseActivityItem[];
}) {
  const [showAll, setShowAll] = useState(false);
  const dealerByVehicle = new Map(
    children.map((child) => [child.vehicle.id, child.vehicle.dealer_name]),
  );
  const chronologicalItems = [...items].sort(compareActivityItems);
  const isBounded = chronologicalItems.length > recentActivityLimit;
  const visibleItems = showAll || !isBounded
    ? chronologicalItems
    : chronologicalItems.slice(-recentActivityLimit);

  return <section className="purchase-activity" aria-labelledby="purchase-activity-heading">
    <div className="purchase-activity-heading">
      <div>
        <p className="eyebrow">Across every selected dealer</p>
        <h2 id="purchase-activity-heading">Purchase activity</h2>
      </div>
      {!!chronologicalItems.length && <span>
        {plural(chronologicalItems.length, "event")}
      </span>}
    </div>
    {isPending && <p className="purchase-activity-state" role="status">
      Loading purchase activity…
    </p>}
    {error && <p
      aria-label="Purchase activity unavailable"
      className="purchase-activity-state"
      role="status"
    >
      Purchase activity is temporarily unavailable. Current decision data remains visible.
    </p>}
    {!isPending && !error && !chronologicalItems.length && <p className="purchase-activity-state">
      No dealer workflow activity has been recorded yet.
    </p>}
    {!!visibleItems.length && <ol aria-label="Purchase activity" className="purchase-activity-list">
      {visibleItems.map((item) => <li key={item.event_id}>
        <time dateTime={item.occurred_at}>{formatActivityDate(item.occurred_at)}</time>
        <strong>{dealerByVehicle.get(item.vehicle_id) ?? "Selected dealer"}</strong>
        <span className="purchase-activity-event">{formatActivityLabel(item.event_type)}</span>
        <p>{item.message}</p>
      </li>)}
    </ol>}
    {isBounded && <button
      aria-expanded={showAll}
      className="secondary-button purchase-activity-toggle"
      onClick={() => setShowAll((current) => !current)}
      type="button"
    >
      {showAll
        ? `Show recent ${recentActivityLimit} events`
        : `Show all ${chronologicalItems.length} events`}
    </button>}
  </section>;
}

function AttentionItems({ items }: { items: PurchaseAttentionItem[] }) {
  return <section className="purchase-attention" aria-labelledby="purchase-attention-heading">
    <p className="eyebrow">Current workflow state</p>
    <h2 id="purchase-attention-heading">Needs your attention</h2>
    {!items.length && <p className="purchase-empty-state">No dealer workflow currently needs attention.</p>}
    {!!items.length && <ul>
      {items.map((item) => <li
        className={item.requires_buyer_action ? "purchase-attention-required" : undefined}
        key={`${item.category}:${item.vehicle_id}:${item.action_id ?? "none"}`}
      >
        <div>
          <strong>{item.dealer_name}</strong>
          <span>{workflowLabels[item.category]}</span>
        </div>
        <p>{item.requires_buyer_action ? <>Next step: {item.message}</> : item.message}</p>
        {item.agent_run_id && <a href={`#purchase-child-${encodeURIComponent(item.vehicle_id)}`}>
          View dealer workflow
        </a>}
      </li>)}
    </ul>}
  </section>;
}

function DealerWorkflows({
  apiBaseUrl,
  children,
  onAuthoritativeChange,
}: {
  apiBaseUrl: string;
  children: PurchaseChild[];
  onAuthoritativeChange: () => void;
}) {
  return <section className="purchase-dealer-workflows" aria-labelledby="dealer-workflows-heading">
    <p className="eyebrow">Dealer drill-down</p>
    <h2 id="dealer-workflows-heading">Dealer workflows</h2>
    <div className="purchase-dealer-grid">
      {children.map((child) => <article
        id={`purchase-child-${encodeURIComponent(child.vehicle.id)}`}
        key={child.vehicle.id}
      >
        <span className={`purchase-workflow-status purchase-workflow-status-${child.workflow_status.toLowerCase()}`}>
          {workflowLabels[child.workflow_status]}
        </span>
        {child.agent_run
          ? <AgentWorkflow
            apiBaseUrl={apiBaseUrl}
            authoritativeActionId={child.action_id}
            authorizationRequired={child.workflow_status === "APPROVAL_REQUIRED"}
            candidate={child.vehicle}
            initialRun={child.agent_run}
            onRunChange={onAuthoritativeChange}
          />
          : <div className="purchase-missing-workflow">
            <h3>{child.vehicle.dealer_name}</h3>
            <p>The selected vehicle remains durably attached to this purchase, but its dealer workflow still needs recovery.</p>
            {child.creation_error_code && <code>{child.creation_error_code}</code>}
          </div>}
      </article>)}
    </div>
  </section>;
}

export function PurchaseWorkspace({
  apiBaseUrl,
  purchaseId,
}: {
  apiBaseUrl: string;
  purchaseId: string;
}) {
  const queryClient = useQueryClient();
  const queryKey = ["purchase-run", apiBaseUrl, purchaseId] as const;
  const purchase = useQuery({
    queryKey,
    queryFn: () => inspectPurchase(apiBaseUrl, purchaseId),
    retry: false,
  });
  const activityQueryKey = ["purchase-activity", apiBaseUrl, purchaseId] as const;
  const activity = useQuery({
    queryKey: activityQueryKey,
    queryFn: () => inspectPurchaseActivity(apiBaseUrl, purchaseId),
    enabled: purchase.isSuccess,
    retry: false,
  });
  const researchQueryKey = [
    "purchase-research-targets",
    apiBaseUrl,
    purchaseId,
  ] as const;
  const hasDisplayedAddons = purchase.data?.comparison?.offers.some(
    (offer) => offer.mandatory_addons.length > 0,
  ) ?? false;
  const researchTargets = useQuery({
    queryKey: researchQueryKey,
    queryFn: () => inspectResearchTargets(apiBaseUrl, purchaseId),
    enabled: hasDisplayedAddons,
    retry: false,
  });
  const [researchErrors, setResearchErrors] = useState<Record<string, string>>({});
  const [researchNotice, setResearchNotice] = useState<string | null>(null);
  const pendingResearchTargetIdsRef = useRef(new Set<string>());
  const [pendingResearchTargetIds, setPendingResearchTargetIds] = useState<string[]>([]);
  const investigation = useMutation({
    mutationFn: (targetId: string) => (
      investigateResearchTarget(apiBaseUrl, purchaseId, targetId)
    ),
    onMutate: (targetId) => {
      setResearchNotice(null);
      setResearchErrors((current) => {
        if (!(targetId in current)) return current;
        const next = { ...current };
        delete next[targetId];
        return next;
      });
    },
    onSuccess: (updatedTarget) => {
      queryClient.setQueryData<ResearchTargetView[]>(researchQueryKey, (current) => (
        current?.map((target) => (
          target.target_id === updatedTarget.target_id ? updatedTarget : target
        )) ?? [updatedTarget]
      ));
    },
    onError: (error, targetId) => {
      if (
        error instanceof ResearchApiError
        && error.status === 409
        && error.code === "research_target_changed"
      ) {
        queryClient.setQueryData<ResearchTargetView[]>(researchQueryKey, []);
        setResearchNotice(error.message);
        void purchase.refetch();
        void researchTargets.refetch();
        return;
      }
      setResearchErrors((current) => ({
        ...current,
        [targetId]: error instanceof Error
          ? error.message
          : "Independent research could not be completed.",
      }));
      if (
        error instanceof ResearchApiError
        && error.status === 409
        && error.code === "research_in_progress"
      ) {
        void queryClient.invalidateQueries({
          queryKey: researchQueryKey,
          exact: true,
        });
      }
    },
    onSettled: (_data, _error, targetId) => {
      pendingResearchTargetIdsRef.current.delete(targetId);
      setPendingResearchTargetIds([...pendingResearchTargetIdsRef.current]);
    },
    retry: false,
  });
  const recovery = useMutation({
    mutationFn: () => recoverPurchase(apiBaseUrl, purchaseId),
    onSuccess: (recovered) => {
      queryClient.setQueryData(queryKey, recovered);
      void activity.refetch();
    },
    retry: false,
  });

  useEffect(() => {
    setResearchErrors({});
    setResearchNotice(null);
  }, [apiBaseUrl, purchaseId]);

  if (purchase.isPending) {
    return <main className="purchase-workspace">
      <p className="analysis-status" role="status">Loading durable purchase workspace…</p>
    </main>;
  }
  if (purchase.isError) {
    return <main className="purchase-workspace">
      <p className="error" role="alert">{purchase.error.message}</p>
    </main>;
  }

  const workspace = purchase.data;
  const recommendationHeading = workspace.decision_status === "COMPARISON_AVAILABLE"
    ? "Best verified offer so far"
    : "Best verified offer";

  return <main className="purchase-workspace">
    <header className="purchase-header">
      <div>
        <p className="eyebrow">Durable purchase workspace</p>
        <h1>Buying agent</h1>
        <p className="purchase-goal">{workspace.goal}</p>
      </div>
      <span className={`purchase-decision purchase-decision-${workspace.decision_status.toLowerCase()}`}>
        {decisionLabels[workspace.decision_status]}
      </span>
    </header>

    <PurchaseDecisionSummary workspace={workspace} />

    {workspace.setup_status === "RECOVERY_REQUIRED" && <section className="purchase-recovery">
      <div>
        <strong>Purchase setup needs recovery</strong>
        <p>The purchase and completed child links are safe. Retry only the missing dealer workflows.</p>
      </div>
      <button
        disabled={recovery.isPending}
        onClick={() => recovery.mutate()}
        type="button"
      >
        {recovery.isPending ? "Recovering…" : "Recover missing workflows"}
      </button>
    </section>}
    {recovery.isError && <p className="error" role="alert">{recovery.error.message}</p>}

    <PurchaseActivity
      children={workspace.children}
      error={activity.isError ? activity.error.message : null}
      isPending={activity.isPending}
      items={activity.data ?? []}
    />

    <AttentionItems items={workspace.attention_items} />

    {workspace.comparison && <VerifiedOffersComparisonView
      recommendationHeading={recommendationHeading}
      research={{
        targets: researchTargets.data ?? [],
        pendingTargetIds: pendingResearchTargetIds,
        errors: researchErrors,
        notice: researchNotice,
        loadError: researchTargets.isError
          ? researchTargets.error.message
          : null,
        onInvestigate: (targetId) => {
          if (pendingResearchTargetIdsRef.current.has(targetId)) return;
          pendingResearchTargetIdsRef.current.add(targetId);
          setPendingResearchTargetIds([...pendingResearchTargetIdsRef.current]);
          investigation.mutate(targetId);
        },
      }}
      result={workspace.comparison}
    />}

    <DealerWorkflows
      apiBaseUrl={apiBaseUrl}
      children={workspace.children}
      onAuthoritativeChange={() => {
        void purchase.refetch();
        void activity.refetch();
        void researchTargets.refetch();
      }}
    />
  </main>;
}
