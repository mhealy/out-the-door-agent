import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const apiBaseUrl = "http://localhost:8000";
const purchaseId = "purchase-1";
const exampleGoal = "Find a new 2025 or 2026 Hyundai Tucson Hybrid Limited within 40 miles of Houston under $40,000. I prefer blue and require AWD.";

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
  {
    id: "katy-blue",
    vin: "KM8JCDD12TU000003",
    stock_number: "K3003",
    year: 2026,
    make: "Hyundai",
    model: "Tucson Hybrid",
    trim: "Limited",
    condition: "new",
    mileage: 5,
    advertised_price: "39500",
    msrp: "42900",
    exterior_color: "Blue Stone",
    interior_color: "Gray",
    features: ["AWD"],
    dealer_id: "katy",
    dealer_name: "Katy Hyundai",
    latitude: null,
    longitude: null,
    distance_miles: 28,
    source_url: "https://example.test/inventory/katy-blue",
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

function agentRun(vehicleId: string, dealerId: string) {
  return {
    id: `run-${dealerId}`,
    run_id: `run-${dealerId}`,
    thread_id: `thread-${dealerId}`,
    vehicle_id: vehicleId,
    phase: "WAITING_FOR_APPROVAL",
    initial_action_id: `action-${dealerId}`,
    current_action_id: `action-${dealerId}`,
    interaction_id: null,
    last_message_id: null,
    error_code: null,
    created_at: "2026-08-19T20:00:00Z",
    updated_at: "2026-08-19T20:00:01Z",
    events: [],
  };
}

const purchaseWorkspace = {
  id: purchaseId,
  goal: exampleGoal,
  setup_status: "READY",
  decision_status: "GATHERING_OFFERS",
  selected_vehicle_ids: candidates.map((candidate) => candidate.id),
  children: candidates.map((vehicle) => ({
    vehicle,
    agent_run: agentRun(vehicle.id, vehicle.dealer_id),
    workflow_status: "APPROVAL_REQUIRED",
    comparison_status: "IN_PROGRESS",
    creation_error_code: null,
    active_unresolved: true,
  })),
  counts: {
    selected_vehicles: 3,
    linked_children: 3,
    quote_requests_prepared: 3,
    responses_analyzed: 0,
    verified_offers: 0,
    incomplete_offers: 0,
    pending_approvals: 3,
  },
  attention_items: candidates.map((vehicle) => ({
    category: "APPROVAL_REQUIRED",
    vehicle_id: vehicle.id,
    dealer_name: vehicle.dealer_name,
    agent_run_id: `run-${vehicle.dealer_id}`,
    action_id: `action-${vehicle.dealer_id}`,
    message: `${vehicle.dealer_name} quote request is awaiting approval.`,
    requires_buyer_action: true,
  })),
  comparison: null,
  created_at: "2026-08-19T20:00:00Z",
  updated_at: "2026-08-19T20:00:01Z",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function callsTo(
  fetchMock: { mock: { calls: Parameters<typeof fetch>[] } },
  url: string,
  method?: string,
) {
  return fetchMock.mock.calls.filter(([input, init]) => (
    input === url && (method === undefined || init?.method === method)
  ));
}

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});

describe("durable purchase workspace routing", () => {
  it("selects candidates and creates exactly one durable purchase without browser-created child runs", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === `${apiBaseUrl}/quotes/fixtures` && init?.method === undefined) {
        return jsonResponse([]);
      }
      if (input === `${apiBaseUrl}/candidates/search` && init?.method === "POST") {
        return jsonResponse(searchResult);
      }
      if (input === `${apiBaseUrl}/purchase-runs` && init?.method === "POST") {
        return jsonResponse(purchaseWorkspace, 201);
      }
      if (input === `${apiBaseUrl}/purchase-runs/${purchaseId}` && init?.method === undefined) {
        return jsonResponse(purchaseWorkspace);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    renderApp();

    fireEvent.click(screen.getByRole("button", { name: "Search inventory" }));
    expect(await screen.findByText("3 qualified candidates")).toBeVisible();

    const startButton = screen.getByRole("button", { name: "Start buying agent" });
    expect(startButton).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Baytown Hyundai" }));
    expect(startButton).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Houston Hyundai" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Katy Hyundai" }));
    expect(startButton).toBeEnabled();
    fireEvent.click(startButton);

    expect(await screen.findByRole("heading", { name: "Buying agent" })).toBeVisible();
    expect(window.location.search).toBe(`?purchase=${purchaseId}`);
    expect(callsTo(fetchMock, `${apiBaseUrl}/purchase-runs`, "POST")).toHaveLength(1);
    expect(callsTo(fetchMock, `${apiBaseUrl}/purchase-runs`, "POST")[0]?.[1]).toEqual({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        goal: exampleGoal,
        vehicle_ids: ["baytown-blue", "houston-white", "katy-blue"],
      }),
    });
    expect(callsTo(fetchMock, `${apiBaseUrl}/agent-runs`, "POST")).toHaveLength(0);
  });

  it("reloads a purchase directly from its durable URL without search or browser run grouping", async () => {
    window.history.replaceState({}, "", `/?purchase=${purchaseId}`);
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === `${apiBaseUrl}/purchase-runs/${purchaseId}` && init?.method === undefined) {
        return jsonResponse(purchaseWorkspace);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });

    renderApp();

    expect(await screen.findByRole("heading", { name: "Buying agent" })).toBeVisible();
    expect(screen.getByText(exampleGoal)).toBeVisible();
    expect(callsTo(fetchMock, `${apiBaseUrl}/purchase-runs/${purchaseId}`)).toHaveLength(1);
    expect(callsTo(fetchMock, `${apiBaseUrl}/candidates/search`, "POST")).toHaveLength(0);
    expect(callsTo(fetchMock, `${apiBaseUrl}/agent-runs`, "POST")).toHaveLength(0);
    expect(callsTo(fetchMock, `${apiBaseUrl}/offer-comparisons`, "POST")).toHaveLength(0);
    expect(callsTo(fetchMock, `${apiBaseUrl}/quotes/fixtures`)).toHaveLength(0);
  });
});
