import { FormEvent, useState } from "react";
import { useMutation } from "@tanstack/react-query";

type SearchResult = {
  interpretation: {
    criteria: { make: string; model: string; hard_constraints: string[]; soft_preferences: string[] };
    assumptions: string[]; unresolved_ambiguities: string[];
  };
  candidates: Array<{ id: string; year: number; make: string; model: string; trim: string | null; advertised_price: string | null; exterior_color: string | null; dealer_name: string; distance_miles: number | null; features: string[] }>;
};

const exampleGoal = "Find a new 2025 or 2026 Hyundai Tucson Hybrid Limited within 40 miles of Houston under $40,000. I prefer blue and require AWD.";
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function search(goal: string): Promise<SearchResult> {
  const response = await fetch(`${apiBaseUrl}/candidates/search`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goal }) });
  if (!response.ok) throw new Error("The inventory search could not be completed.");
  return response.json() as Promise<SearchResult>;
}

export function App() {
  const [goal, setGoal] = useState(exampleGoal);
  const mutation = useMutation({ mutationFn: search });
  const submit = (event: FormEvent) => { event.preventDefault(); mutation.mutate(goal); };
  return <main>
    <p className="eyebrow">Vehicle offer intelligence</p><h1>OutTheDoor</h1>
    <p className="summary">Describe the vehicle you want. We’ll preserve your hard limits and show the best matching fixture inventory.</p>
    <form onSubmit={submit}><label htmlFor="goal">Purchase goal</label><textarea id="goal" value={goal} onChange={(event) => setGoal(event.target.value)} /><button disabled={mutation.isPending || !goal.trim()}>{mutation.isPending ? "Searching…" : "Search inventory"}</button></form>
    {mutation.isError && <p className="error">{mutation.error.message}</p>}
    {mutation.data && <section className="results"><div className="criteria"><p className="eyebrow">Interpreted criteria</p><h2>{mutation.data.interpretation.criteria.make} {mutation.data.interpretation.criteria.model}</h2><ul>{mutation.data.interpretation.criteria.hard_constraints.map((item) => <li key={item}>{item}</li>)}</ul>
      {!!mutation.data.interpretation.criteria.soft_preferences.length && <p><strong>Preferences:</strong> {mutation.data.interpretation.criteria.soft_preferences.join(", ")}</p>}
      {!!mutation.data.interpretation.assumptions.length && <p><strong>Assumptions:</strong> {mutation.data.interpretation.assumptions.join(" ")}</p>}
      {!!mutation.data.interpretation.unresolved_ambiguities.length && <p><strong>Needs clarification:</strong> {mutation.data.interpretation.unresolved_ambiguities.join(" ")}</p>}</div>
      <h2>{mutation.data.candidates.length} qualified candidates</h2><div className="candidate-grid">{mutation.data.candidates.map((candidate) => <article key={candidate.id}><p className="eyebrow">{candidate.dealer_name} · {candidate.distance_miles} mi</p><h3>{candidate.year} {candidate.make} {candidate.model} {candidate.trim}</h3><p className="price">{candidate.advertised_price ? `$${Number(candidate.advertised_price).toLocaleString()}` : "Price unavailable"}</p><p>{candidate.exterior_color} · {candidate.features.join(" · ")}</p></article>)}</div>
      {!mutation.data.candidates.length && <p>No vehicles meet every hard constraint. No limits were relaxed.</p>}</section>}
  </main>;
}
