import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import type { OutreachCandidate } from "./components/OutreachApproval";
import {
  PurchaseWorkspace,
  type PurchaseWorkspaceModel,
} from "./components/PurchaseWorkspace";
import { QuoteAnalysisWorkspace } from "./components/QuoteAnalysisWorkspace";

type Criteria = {
  make: string;
  model: string;
  hard_constraints: string[];
  soft_preferences: string[];
};
type Interpretation = {
  criteria: Criteria;
  assumptions: string[];
  unresolved_ambiguities: string[];
};
type Candidate = OutreachCandidate & {
  advertised_price: string | null;
  exterior_color: string | null;
  distance_miles: number | null;
  features: string[];
};
type SearchResult = { interpretation: Interpretation; candidates: Candidate[] };
type ApiErrorPayload = { detail?: string | { message?: string } };

const exampleGoal = "Find a new 2025 or 2026 Hyundai Tucson Hybrid Limited within 40 miles of Houston under $40,000. I prefer blue and require AWD.";
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function responseError(response: Response, fallback: string): Promise<Error> {
  const payload = (await response.json().catch(() => null)) as ApiErrorPayload | null;
  const detail = payload?.detail;
  const message = typeof detail === "string" ? detail : detail?.message;
  return new Error(message ?? fallback);
}

async function search(goal: string): Promise<SearchResult> {
  const response = await fetch(`${apiBaseUrl}/candidates/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ goal }),
  });
  if (!response.ok) {
    throw await responseError(response, "The inventory search could not be completed.");
  }
  return response.json() as Promise<SearchResult>;
}

async function createPurchase(
  goal: string,
  vehicleIds: string[],
): Promise<PurchaseWorkspaceModel> {
  const response = await fetch(`${apiBaseUrl}/purchase-runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ goal, vehicle_ids: vehicleIds }),
  });
  if (!response.ok) {
    throw await responseError(response, "The purchase workspace could not be created.");
  }
  return response.json() as Promise<PurchaseWorkspaceModel>;
}

function purchaseIdFromLocation(): string | null {
  const purchaseId = new URLSearchParams(window.location.search).get("purchase")?.trim();
  return purchaseId || null;
}

function showPurchaseInUrl(purchaseId: string) {
  const url = new URL(window.location.href);
  url.searchParams.set("purchase", purchaseId);
  window.history.pushState({}, "", `${url.pathname}${url.search}${url.hash}`);
}

function PurchaseGoalForm({
  goal,
  isPending,
  onGoalChange,
  onSubmit,
}: {
  goal: string;
  isPending: boolean;
  onGoalChange: (goal: string) => void;
  onSubmit: (event: FormEvent) => void;
}) {
  return <form onSubmit={onSubmit}>
    <label htmlFor="goal">Purchase goal</label>
    <textarea id="goal" value={goal} onChange={(event) => onGoalChange(event.target.value)} />
    <button disabled={isPending || !goal.trim()}>
      {isPending ? "Searching…" : "Search inventory"}
    </button>
  </form>;
}

function InterpretedCriteria({ interpretation }: { interpretation: Interpretation }) {
  const { criteria } = interpretation;
  return <div className="criteria">
    <p className="eyebrow">Interpreted criteria</p>
    <h2>{criteria.make} {criteria.model}</h2>
    <ul>{criteria.hard_constraints.map((item) => <li key={item}>{item}</li>)}</ul>
    {!!criteria.soft_preferences.length && <p>
      <strong>Preferences:</strong> {criteria.soft_preferences.join(", ")}
    </p>}
    {!!interpretation.assumptions.length && <p>
      <strong>Assumptions:</strong> {interpretation.assumptions.join(" ")}
    </p>}
    {!!interpretation.unresolved_ambiguities.length && <p>
      <strong>Needs clarification:</strong> {interpretation.unresolved_ambiguities.join(" ")}
    </p>}
  </div>;
}

function CandidateCard({
  candidate,
  disabled,
  onSelectionChange,
  selected,
}: {
  candidate: Candidate;
  disabled: boolean;
  onSelectionChange: (candidateId: string, selected: boolean) => void;
  selected: boolean;
}) {
  return <article className={selected ? "candidate-selected" : undefined}>
    <div className="candidate-selection-heading">
      <p className="eyebrow">{candidate.dealer_name} · {candidate.distance_miles} mi</p>
      <label className="candidate-selector">
        <input
          aria-label={`Select ${candidate.dealer_name}`}
          checked={selected}
          disabled={disabled}
          onChange={(event) => onSelectionChange(candidate.id, event.target.checked)}
          type="checkbox"
        />
        <span>{selected ? "Selected" : "Select"}</span>
      </label>
    </div>
    <h3>{candidate.year} {candidate.make} {candidate.model} {candidate.trim}</h3>
    <p className="price">
      {candidate.advertised_price
        ? `$${Number(candidate.advertised_price).toLocaleString()}`
        : "Price unavailable"}
    </p>
    <p>{candidate.exterior_color} · {candidate.features.join(" · ")}</p>
  </article>;
}

function CandidateGrid({
  candidates,
  creationError,
  isCreating,
  onCreate,
  onSelectionChange,
  selectedIds,
}: {
  candidates: Candidate[];
  creationError: string | null;
  isCreating: boolean;
  onCreate: () => void;
  onSelectionChange: (candidateId: string, selected: boolean) => void;
  selectedIds: Set<string>;
}) {
  const selectionCount = selectedIds.size;
  return <>
    <div className="candidate-grid-heading">
      <div>
        <h2>{candidates.length} qualified candidates</h2>
        <p>Select 2–5 dealers to coordinate in one durable buying workspace.</p>
      </div>
      <span>{selectionCount} selected</span>
    </div>
    <div className="candidate-grid">{candidates.map((candidate) => <CandidateCard
      candidate={candidate}
      disabled={!selectedIds.has(candidate.id) && selectionCount >= 5}
      key={candidate.id}
      onSelectionChange={onSelectionChange}
      selected={selectedIds.has(candidate.id)}
    />)}</div>
    {!candidates.length && <p>No vehicles meet every hard constraint. No limits were relaxed.</p>}
    {!!candidates.length && <div className="purchase-start">
      <div>
        <strong>{selectionCount} dealer{selectionCount === 1 ? "" : "s"} selected</strong>
        <span>Each exact outbound message will still require individual approval.</span>
      </div>
      <button
        disabled={isCreating || selectionCount < 2 || selectionCount > 5}
        onClick={onCreate}
        type="button"
      >
        {isCreating ? "Starting buying agent…" : "Start buying agent"}
      </button>
    </div>}
    {creationError && <p className="error" role="alert">{creationError}</p>}
  </>;
}

export function App() {
  const [goal, setGoal] = useState(exampleGoal);
  const [purchaseId, setPurchaseId] = useState<string | null>(purchaseIdFromLocation);
  const [selectedVehicleIds, setSelectedVehicleIds] = useState<Set<string>>(new Set());
  const searchMutation = useMutation({ mutationFn: search });
  const purchaseMutation = useMutation({
    mutationFn: ({ purchaseGoal, vehicleIds }: {
      purchaseGoal: string;
      vehicleIds: string[];
    }) => createPurchase(purchaseGoal, vehicleIds),
    onSuccess: (workspace) => {
      showPurchaseInUrl(workspace.id);
      setPurchaseId(workspace.id);
    },
    retry: false,
  });

  useEffect(() => {
    const followLocation = () => setPurchaseId(purchaseIdFromLocation());
    window.addEventListener("popstate", followLocation);
    return () => window.removeEventListener("popstate", followLocation);
  }, []);

  const orderedSelectedVehicleIds = useMemo(() => (
    searchMutation.data?.candidates
      .filter((candidate) => selectedVehicleIds.has(candidate.id))
      .map((candidate) => candidate.id) ?? []
  ), [searchMutation.data, selectedVehicleIds]);

  if (purchaseId) {
    return <PurchaseWorkspace apiBaseUrl={apiBaseUrl} purchaseId={purchaseId} />;
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSelectedVehicleIds(new Set());
    purchaseMutation.reset();
    searchMutation.mutate(goal);
  };
  const changeSelection = (candidateId: string, selected: boolean) => {
    setSelectedVehicleIds((current) => {
      const next = new Set(current);
      if (selected) next.add(candidateId);
      else next.delete(candidateId);
      return next;
    });
  };
  const startPurchase = () => {
    if (orderedSelectedVehicleIds.length < 2 || orderedSelectedVehicleIds.length > 5) return;
    purchaseMutation.mutate({
      purchaseGoal: goal,
      vehicleIds: orderedSelectedVehicleIds,
    });
  };

  return <main>
    <p className="eyebrow">Vehicle offer intelligence</p>
    <h1>OutTheDoor</h1>
    <p className="summary">Describe the vehicle you want. We’ll preserve your hard limits and show the best matching fixture inventory.</p>
    <PurchaseGoalForm
      goal={goal}
      isPending={searchMutation.isPending}
      onGoalChange={setGoal}
      onSubmit={submit}
    />
    {searchMutation.isError && <p className="error">{searchMutation.error.message}</p>}
    {searchMutation.data && <section className="results">
      <InterpretedCriteria interpretation={searchMutation.data.interpretation} />
      <CandidateGrid
        candidates={searchMutation.data.candidates}
        creationError={purchaseMutation.isError ? purchaseMutation.error.message : null}
        isCreating={purchaseMutation.isPending}
        onCreate={startPurchase}
        onSelectionChange={changeSelection}
        selectedIds={selectedVehicleIds}
      />
    </section>}
    <QuoteAnalysisWorkspace apiBaseUrl={apiBaseUrl} />
  </main>;
}
