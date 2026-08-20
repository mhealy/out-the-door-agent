import { FormEvent, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { AgentWorkflow } from "./components/AgentWorkflow";
import type { OutreachCandidate } from "./components/OutreachApproval";
import { QuoteAnalysisWorkspace } from "./components/QuoteAnalysisWorkspace";

type Criteria = { make: string; model: string; hard_constraints: string[]; soft_preferences: string[] };
type Interpretation = { criteria: Criteria; assumptions: string[]; unresolved_ambiguities: string[] };
type Candidate = OutreachCandidate & {
  advertised_price: string | null; exterior_color: string | null;
  distance_miles: number | null; features: string[];
};
type SearchResult = { interpretation: Interpretation; candidates: Candidate[] };

const exampleGoal = "Find a new 2025 or 2026 Hyundai Tucson Hybrid Limited within 40 miles of Houston under $40,000. I prefer blue and require AWD.";
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function search(goal: string): Promise<SearchResult> {
  const response = await fetch(`${apiBaseUrl}/candidates/search`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goal }),
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: { message?: string } } | null;
    throw new Error(payload?.detail?.message ?? "The inventory search could not be completed.");
  }
  return response.json() as Promise<SearchResult>;
}

function PurchaseGoalForm({ goal, isPending, onGoalChange, onSubmit }: {
  goal: string; isPending: boolean; onGoalChange: (goal: string) => void;
  onSubmit: (event: FormEvent) => void;
}) {
  return <form onSubmit={onSubmit}>
    <label htmlFor="goal">Purchase goal</label>
    <textarea id="goal" value={goal} onChange={(event) => onGoalChange(event.target.value)} />
    <button disabled={isPending || !goal.trim()}>{isPending ? "Searching…" : "Search inventory"}</button>
  </form>;
}

function InterpretedCriteria({ interpretation }: { interpretation: Interpretation }) {
  const { criteria } = interpretation;
  return <div className="criteria">
    <p className="eyebrow">Interpreted criteria</p>
    <h2>{criteria.make} {criteria.model}</h2>
    <ul>{criteria.hard_constraints.map((item) => <li key={item}>{item}</li>)}</ul>
    {!!criteria.soft_preferences.length && <p><strong>Preferences:</strong> {criteria.soft_preferences.join(", ")}</p>}
    {!!interpretation.assumptions.length && <p><strong>Assumptions:</strong> {interpretation.assumptions.join(" ")}</p>}
    {!!interpretation.unresolved_ambiguities.length && <p><strong>Needs clarification:</strong> {interpretation.unresolved_ambiguities.join(" ")}</p>}
  </div>;
}

function CandidateCard({ candidate }: { candidate: Candidate }) {
  return <article>
    <p className="eyebrow">{candidate.dealer_name} · {candidate.distance_miles} mi</p>
    <h3>{candidate.year} {candidate.make} {candidate.model} {candidate.trim}</h3>
    <p className="price">{candidate.advertised_price ? `$${Number(candidate.advertised_price).toLocaleString()}` : "Price unavailable"}</p>
    <p>{candidate.exterior_color} · {candidate.features.join(" · ")}</p>
    <AgentWorkflow apiBaseUrl={apiBaseUrl} candidate={candidate} />
  </article>;
}

function CandidateGrid({ candidates }: { candidates: Candidate[] }) {
  return <>
    <h2>{candidates.length} qualified candidates</h2>
    <div className="candidate-grid">{candidates.map((candidate) => <CandidateCard key={candidate.id} candidate={candidate} />)}</div>
    {!candidates.length && <p>No vehicles meet every hard constraint. No limits were relaxed.</p>}
  </>;
}

export function App() {
  const [goal, setGoal] = useState(exampleGoal);
  const mutation = useMutation({ mutationFn: search });
  const submit = (event: FormEvent) => { event.preventDefault(); mutation.mutate(goal); };
  return <main>
    <p className="eyebrow">Vehicle offer intelligence</p><h1>OutTheDoor</h1>
    <p className="summary">Describe the vehicle you want. We’ll preserve your hard limits and show the best matching fixture inventory.</p>
    <PurchaseGoalForm goal={goal} isPending={mutation.isPending} onGoalChange={setGoal} onSubmit={submit} />
    {mutation.isError && <p className="error">{mutation.error.message}</p>}
    {mutation.data && <section className="results">
      <InterpretedCriteria interpretation={mutation.data.interpretation} />
      <CandidateGrid candidates={mutation.data.candidates} />
    </section>}
    <QuoteAnalysisWorkspace apiBaseUrl={apiBaseUrl} />
  </main>;
}
