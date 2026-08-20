import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const apiBaseUrl = "http://localhost:8000";

const candidates = [
  {
    id: "baytown-blue",
    vin: "KM8JCDD10SU000001",
    stock_number: "B1001",
    year: 2025,
    make: "Hyundai",
    model: "Tucson Hybrid",
    trim: "Limited",
    condition: "new",
    mileage: 8,
    advertised_price: "37800",
    msrp: "42150",
    exterior_color: "Deep Sea Blue",
    interior_color: "Gray",
    features: ["AWD"],
    dealer_id: "baytown",
    dealer_name: "Baytown Hyundai",
    latitude: null,
    longitude: null,
    distance_miles: 34,
    source_url: "https://example.test/inventory/baytown-blue",
    source_provider: "fixture",
  },
  {
    id: "houston-white",
    vin: "KM8JCDD11SU000002",
    stock_number: "H2002",
    year: 2025,
    make: "Hyundai",
    model: "Tucson Hybrid",
    trim: "Limited",
    condition: "new",
    mileage: 12,
    advertised_price: "37250",
    msrp: "41980",
    exterior_color: "White Pearl",
    interior_color: "Black",
    features: ["AWD"],
    dealer_id: "houston",
    dealer_name: "Houston Hyundai",
    latitude: null,
    longitude: null,
    distance_miles: 12,
    source_url: "https://example.test/inventory/houston-white",
    source_provider: "fixture",
  },
];

const searchResult = {
  interpretation: {
    criteria: {
      make: "Hyundai",
      model: "Tucson Hybrid",
      hard_constraints: ["New", "AWD"],
      soft_preferences: ["Blue exterior"],
    },
    assumptions: [],
    unresolved_ambiguities: [],
  },
  candidates,
};

function agentRun(vehicleId: string) {
  const suffix = vehicleId === "baytown-blue" ? "baytown" : "houston";
  return {
    id: `run-${suffix}`,
    run_id: `run-${suffix}`,
    thread_id: `thread-${suffix}`,
    vehicle_id: vehicleId,
    phase: "INTERACTION_COMPLETE",
    initial_action_id: `action-${suffix}`,
    current_action_id: `action-${suffix}`,
    interaction_id: `interaction-${suffix}`,
    last_message_id: `message-${suffix}`,
    error_code: null,
    created_at: "2026-08-19T20:00:00Z",
    updated_at: vehicleId === "baytown-blue"
      ? "2026-08-19T20:10:00Z"
      : "2026-08-19T20:11:00Z",
    events: [],
  };
}

const comparison = {
  offers: [
    {
      agent_run_id: "run-baytown",
      dealer_name: "Baytown Hyundai",
      advertised_price: "37800",
      claimed_otd: "40315",
      inventory_provenance: {
        source_type: "INVENTORY_LISTING",
        listing_id: "baytown-blue",
        source_provider: "fixture",
        source_url: "https://example.test/inventory/baytown-blue",
      },
      distance_miles: 34,
      mandatory_addons: [],
      conditions: [],
      sent_followup_count: 0,
      run_phase: "INTERACTION_COMPLETE",
      evidence: [],
      claimed_otd_evidence_ids: [],
      comparison_status: "VERIFIED",
      eligible: true,
      verified_rank: 1,
    },
    {
      agent_run_id: "run-houston",
      dealer_name: "Houston Hyundai",
      advertised_price: "37250",
      claimed_otd: "41780",
      inventory_provenance: {
        source_type: "INVENTORY_LISTING",
        listing_id: "houston-white",
        source_provider: "fixture",
        source_url: "https://example.test/inventory/houston-white",
      },
      distance_miles: 12,
      mandatory_addons: [],
      conditions: [],
      sent_followup_count: 0,
      run_phase: "INTERACTION_COMPLETE",
      evidence: [],
      claimed_otd_evidence_ids: [],
      comparison_status: "VERIFIED",
      eligible: true,
      verified_rank: 2,
    },
  ],
  ranked_agent_run_ids: ["run-baytown", "run-houston"],
  recommendation: {
    recommended_agent_run_id: "run-baytown",
    recommended_dealer_id: "baytown",
    recommended_dealer_name: "Baytown Hyundai",
    recommended_otd: "40315",
    next_best_verified_otd: "41780",
    savings_vs_next_verified: "1465",
    has_unresolved_alternatives: false,
    explanation_facts: [
      "Baytown Hyundai is the lowest verified written OTD at $40,315.00.",
    ],
  },
  advertised_vs_verified: {
    lowest_advertised_agent_run_id: "run-houston",
    lowest_advertised_price: "37250",
    lowest_advertised_verified_otd: "41780",
    recommended_agent_run_id: "run-baytown",
    recommended_advertised_price: "37800",
    recommended_verified_otd: "40315",
    advertised_price_difference: "550",
    verified_otd_savings: "1465",
  },
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => vi.restoreAllMocks());

describe("buyer workspace comparison integration", () => {
  it("compares stable child run IDs without recreating or auto-starting workflows", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === `${apiBaseUrl}/quotes/fixtures` && init?.method === undefined) {
        return jsonResponse([]);
      }
      if (input === `${apiBaseUrl}/candidates/search` && init?.method === "POST") {
        return jsonResponse(searchResult);
      }
      if (input === `${apiBaseUrl}/agent-runs` && init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as { vehicle_id: string };
        return jsonResponse(agentRun(body.vehicle_id), 201);
      }
      if (input === `${apiBaseUrl}/offer-comparisons` && init?.method === "POST") {
        return jsonResponse(comparison);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>,
    );

    expect(fetchMock.mock.calls.filter(([input]) => input === `${apiBaseUrl}/agent-runs`))
      .toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Search inventory" }));

    const baytownCard = (await screen.findByText("Baytown Hyundai · 34 mi")).closest("article");
    const houstonCard = screen.getByText("Houston Hyundai · 12 mi").closest("article");
    expect(baytownCard).not.toBeNull();
    expect(houstonCard).not.toBeNull();

    fireEvent.click(within(baytownCard as HTMLElement).getByRole("button", {
      name: "Start agent workflow",
    }));
    await within(baytownCard as HTMLElement).findByText("Offer is comparable");
    expect(fetchMock.mock.calls.filter(([input]) => input === `${apiBaseUrl}/offer-comparisons`))
      .toHaveLength(0);

    fireEvent.click(within(houstonCard as HTMLElement).getByRole("button", {
      name: "Start agent workflow",
    }));

    expect(await screen.findByRole("heading", { name: "Verified offers" })).toBeVisible();
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([input]) => input === `${apiBaseUrl}/offer-comparisons`))
        .toHaveLength(1);
    });
    const comparisonCall = fetchMock.mock.calls.find(
      ([input]) => input === `${apiBaseUrl}/offer-comparisons`,
    );
    expect(comparisonCall?.[1]).toEqual({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        agent_run_ids: ["run-baytown", "run-houston"],
      }),
    });
    expect(screen.getByRole("heading", { name: "Best verified offer" })).toBeVisible();
    expect(fetchMock.mock.calls.filter(([input]) => input === `${apiBaseUrl}/agent-runs`))
      .toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: "Search inventory" }));
    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "Verified offers" }))
        .not.toBeInTheDocument();
    });
    expect(fetchMock.mock.calls.filter(([input]) => input === `${apiBaseUrl}/agent-runs`))
      .toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "Start agent workflow" }))
      .toHaveLength(2);
  });
});
