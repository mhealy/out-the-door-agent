import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AgentWorkflow, type AgentRun } from "./AgentWorkflow";
import type { OutreachCandidate } from "./OutreachApproval";
import {
  VerifiedOffersComparisonView,
  type OfferComparisonResult,
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
  detail?: string | { message?: string };
};

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

function countLabels(counts: PurchaseStatusCounts): string[] {
  return [
    `${counts.selected_vehicles} dealers selected`,
    `${counts.linked_children} dealer workflows linked`,
    `${counts.quote_requests_prepared} quote requests prepared`,
    `${counts.responses_analyzed} responses analyzed`,
    `${counts.verified_offers} verified offers`,
    `${counts.incomplete_offers} incomplete`,
    `${counts.pending_approvals} pending approval${counts.pending_approvals === 1 ? "" : "s"}`,
  ];
}

function PurchaseCounts({ counts }: { counts: PurchaseStatusCounts }) {
  return <ul aria-label="Purchase progress" className="purchase-counts">
    {countLabels(counts).map((label) => <li key={label}>{label}</li>)}
  </ul>;
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
        <p>{item.message}</p>
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
  const recovery = useMutation({
    mutationFn: () => recoverPurchase(apiBaseUrl, purchaseId),
    onSuccess: (recovered) => {
      queryClient.setQueryData(queryKey, recovered);
    },
    retry: false,
  });

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

    <PurchaseCounts counts={workspace.counts} />

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

    <AttentionItems items={workspace.attention_items} />

    {workspace.comparison && <VerifiedOffersComparisonView
      recommendationHeading={recommendationHeading}
      result={workspace.comparison}
    />}

    <DealerWorkflows
      apiBaseUrl={apiBaseUrl}
      children={workspace.children}
      onAuthoritativeChange={() => {
        void purchase.refetch();
      }}
    />
  </main>;
}
