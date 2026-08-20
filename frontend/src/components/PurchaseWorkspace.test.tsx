import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PurchaseWorkspace } from "./PurchaseWorkspace";

const apiBaseUrl = "http://api.test";
const purchaseId = "purchase-1";
const goal = "Find the best verified Tucson Hybrid offer.";

const baytown = {
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
};

const houston = {
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
};

const katy = {
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
};

type FixtureVehicle = typeof baytown;

function agentRun(
  vehicle: FixtureVehicle,
  phase: string,
  overrides: Record<string, unknown> = {},
) {
  return {
    id: `run-${vehicle.dealer_id}`,
    run_id: `run-${vehicle.dealer_id}`,
    thread_id: `thread-${vehicle.dealer_id}`,
    vehicle_id: vehicle.id,
    phase,
    initial_action_id: `action-${vehicle.dealer_id}`,
    current_action_id: `action-${vehicle.dealer_id}`,
    interaction_id: phase === "WAITING_FOR_APPROVAL" ? null : `interaction-${vehicle.dealer_id}`,
    last_message_id: null,
    error_code: null,
    created_at: "2026-08-19T20:00:00Z",
    updated_at: "2026-08-19T20:00:01Z",
    events: [
      {
        id: `event-${vehicle.dealer_id}`,
        run_id: `run-${vehicle.dealer_id}`,
        event_type: "RUN_STARTED",
        phase: "STARTING",
        node: "load_run_context",
        action_id: null,
        interaction_id: null,
        message_id: null,
        message: `Agent workflow started for ${vehicle.dealer_name}.`,
        created_at: "2026-08-19T20:00:00Z",
        metadata: {},
      },
    ],
    ...overrides,
  };
}

function child(
  vehicle: FixtureVehicle,
  run: ReturnType<typeof agentRun> | null,
  workflowStatus: string,
  overrides: Record<string, unknown> = {},
) {
  return {
    vehicle,
    agent_run: run,
    workflow_status: workflowStatus,
    comparison_status: null,
    action_id: run?.current_action_id ?? null,
    creation_error_code: null,
    active_unresolved: true,
    ...overrides,
  };
}

function attention(
  category: string,
  vehicle: FixtureVehicle,
  message: string,
  overrides: Record<string, unknown> = {},
) {
  return {
    category,
    vehicle_id: vehicle.id,
    dealer_name: vehicle.dealer_name,
    agent_run_id: `run-${vehicle.dealer_id}`,
    action_id: `action-${vehicle.dealer_id}`,
    message,
    requires_buyer_action: category === "APPROVAL_REQUIRED",
    ...overrides,
  };
}

function workspace(overrides: Record<string, unknown> = {}) {
  return {
    id: purchaseId,
    goal,
    setup_status: "READY",
    decision_status: "GATHERING_OFFERS",
    selected_vehicle_ids: [baytown.id, houston.id],
    children: [
      child(baytown, agentRun(baytown, "WAITING_FOR_EXTERNAL_RESPONSE"), "APPROVAL_REQUIRED"),
      child(houston, agentRun(houston, "WAITING_FOR_EXTERNAL_RESPONSE"), "WAITING_FOR_DEALER"),
    ],
    counts: {
      selected_vehicles: 2,
      linked_children: 2,
      quote_requests_prepared: 2,
      responses_analyzed: 0,
      verified_offers: 0,
      incomplete_offers: 0,
      pending_approvals: 1,
    },
    attention_items: [
      attention(
        "APPROVAL_REQUIRED",
        baytown,
        "Baytown quote request is awaiting your approval.",
      ),
      attention(
        "WAITING_FOR_DEALER",
        houston,
        "Houston is waiting for a dealer response.",
        { requires_buyer_action: false },
      ),
    ],
    comparison: null,
    created_at: "2026-08-19T20:00:00Z",
    updated_at: "2026-08-19T20:00:01Z",
    ...overrides,
  };
}

const pendingBaytownProposal = {
  id: "action-baytown",
  action_type: "SEND_INITIAL_QUOTE_REQUEST",
  dealer_id: baytown.dealer_id,
  vehicle_id: baytown.id,
  recipient: "quotes@baytown.example.test",
  subject: "Written out-the-door quote request — stock B1001",
  body: "Please provide the complete written cash out-the-door price for VIN KM8JCDD10SU000001.",
  reason: "A written OTD is required before this offer can be compared.",
  requested_information: ["out_the_door_total", "mandatory_addons"],
  requires_approval: true,
  status: "PENDING_APPROVAL",
  vehicle: baytown,
  approval: null,
  delivery: null,
};

const sentBaytownProposal = {
  ...pendingBaytownProposal,
  status: "SENT",
  approval: {
    decision: "APPROVED",
    decided_at: "2026-08-19T20:02:00Z",
    action_snapshot: {
      vehicle_id: baytown.id,
      dealer_id: baytown.dealer_id,
      recipient: pendingBaytownProposal.recipient,
      subject: pendingBaytownProposal.subject,
      body: pendingBaytownProposal.body,
    },
  },
  delivery: {
    action_id: pendingBaytownProposal.id,
    provider: "fixture",
    external_message_id: "fixture-outbound-baytown",
    sent_at: "2026-08-19T20:02:01Z",
  },
};

const resumedBaytownRun = agentRun(baytown, "WAITING_FOR_EXTERNAL_RESPONSE", {
  interaction_id: "interaction-baytown",
  updated_at: "2026-08-19T20:02:02Z",
});

const baytownOffer = {
  agent_run_id: "run-baytown",
  interaction_id: "interaction-baytown",
  vehicle_id: baytown.id,
  dealer_id: baytown.dealer_id,
  dealer_name: baytown.dealer_name,
  advertised_price: "37800",
  distance_miles: 34,
  inventory_provenance: {
    source_type: "INVENTORY_LISTING",
    listing_id: baytown.id,
    source_provider: "fixture",
    source_url: baytown.source_url,
  },
  claimed_otd: "40315",
  comparable: true,
  transparent: true,
  reconciled: true,
  missing_for_comparison: [],
  mandatory_addons: [],
  conditions: [],
  sent_followup_count: 0,
  run_phase: "INTERACTION_COMPLETE",
  analysis_status: "ANALYZED",
  evidence: [
    {
      id: "ev-baytown-no-addons",
      source_type: "DEALER_EMAIL",
      source_id: "message-baytown",
      field_name: "explicit_no_addons_statement",
      excerpt: "We have no dealer-installed products or add-ons.",
      created_at: "2026-08-19T20:09:00Z",
    },
    {
      id: "ev-baytown-otd",
      source_type: "DEALER_EMAIL",
      source_id: "message-baytown",
      field_name: "claimed_otd",
      excerpt: "Your written cash OTD is $40,315.",
      created_at: "2026-08-19T20:09:00Z",
    },
  ],
  claimed_otd_evidence_ids: ["ev-baytown-otd"],
  comparison_status: "VERIFIED",
  eligible: true,
  verified_rank: 1,
};

const houstonOffer = {
  agent_run_id: "run-houston",
  interaction_id: "interaction-houston",
  vehicle_id: houston.id,
  dealer_id: houston.dealer_id,
  dealer_name: houston.dealer_name,
  advertised_price: "37250",
  distance_miles: 12,
  inventory_provenance: {
    source_type: "INVENTORY_LISTING",
    listing_id: houston.id,
    source_provider: "fixture",
    source_url: houston.source_url,
  },
  claimed_otd: "41780",
  comparable: true,
  transparent: true,
  reconciled: true,
  missing_for_comparison: [],
  mandatory_addons: [
    {
      name: "Ceramic Shield",
      amount: "1299",
      stated_mandatory: true,
      evidence_id: "ev-houston-ceramic",
    },
    {
      name: "SecureTrack theft recovery",
      amount: "596",
      stated_mandatory: true,
      evidence_id: "ev-houston-securetrack",
    },
  ],
  conditions: [],
  sent_followup_count: 0,
  run_phase: "INTERACTION_COMPLETE",
  analysis_status: "ANALYZED",
  evidence: [
    {
      id: "ev-houston-ceramic",
      source_type: "DEALER_EMAIL",
      source_id: "message-houston",
      field_name: "addons",
      excerpt: "Ceramic Shield for $1,299 is mandatory.",
      created_at: "2026-08-19T20:09:30Z",
    },
    {
      id: "ev-houston-securetrack",
      source_type: "DEALER_EMAIL",
      source_id: "message-houston",
      field_name: "addons",
      excerpt: "SecureTrack for $596 is mandatory.",
      created_at: "2026-08-19T20:09:30Z",
    },
    {
      id: "ev-houston-otd",
      source_type: "DEALER_EMAIL",
      source_id: "message-houston",
      field_name: "claimed_otd",
      excerpt: "The written out-the-door total is $41,780.",
      created_at: "2026-08-19T20:09:30Z",
    },
  ],
  claimed_otd_evidence_ids: ["ev-houston-otd"],
  comparison_status: "VERIFIED",
  eligible: true,
  verified_rank: 2,
};

const katyOffer = {
  agent_run_id: "run-katy",
  interaction_id: "interaction-katy",
  vehicle_id: katy.id,
  dealer_id: katy.dealer_id,
  dealer_name: katy.dealer_name,
  advertised_price: "39500",
  distance_miles: 28,
  inventory_provenance: {
    source_type: "INVENTORY_LISTING",
    listing_id: katy.id,
    source_provider: "fixture",
    source_url: katy.source_url,
  },
  claimed_otd: "40250",
  comparable: false,
  transparent: false,
  reconciled: null,
  missing_for_comparison: ["vehicle_identity", "addon_status"],
  mandatory_addons: [],
  conditions: [
    {
      description: "Vehicle identity and dealer add-on status remain unresolved.",
      evidence_ids: ["ev-katy-unresolved"],
    },
  ],
  sent_followup_count: 0,
  run_phase: "WAITING_FOR_APPROVAL",
  analysis_status: "ANALYZED",
  evidence: [
    {
      id: "ev-katy-otd",
      source_type: "DEALER_EMAIL",
      source_id: "message-katy",
      field_name: "claimed_otd",
      excerpt: "The written OTD shown is $40,250.",
      created_at: "2026-08-19T20:09:45Z",
    },
    {
      id: "ev-katy-unresolved",
      source_type: "DEALER_EMAIL",
      source_id: "message-katy",
      field_name: "unresolved_questions",
      excerpt: "Vehicle identity and add-on status are not provided.",
      created_at: "2026-08-19T20:09:45Z",
    },
  ],
  claimed_otd_evidence_ids: ["ev-katy-otd"],
  comparison_status: "INCOMPLETE",
  eligible: false,
  verified_rank: null,
};

const canonicalComparison = {
  offers: [baytownOffer, houstonOffer, katyOffer],
  ranked_agent_run_ids: ["run-baytown", "run-houston"],
  recommendation: {
    recommended_agent_run_id: "run-baytown",
    recommended_dealer_id: baytown.dealer_id,
    recommended_dealer_name: baytown.dealer_name,
    recommended_otd: "40315",
    next_best_verified_otd: "41780",
    savings_vs_next_verified: "1465",
    has_unresolved_alternatives: true,
    explanation_facts: [
      "Baytown Hyundai is the lowest verified written OTD at $40,315.00.",
      "That is $1,465.00 below Houston Hyundai's verified written OTD.",
      "Houston Hyundai looked $550.00 cheaper online, but Baytown Hyundai has the lower verified transaction cost.",
      "Katy Hyundai has a stated $40,250.00 OTD but remains incomplete and is not rankable.",
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

function callsTo(
  fetchMock: { mock: { calls: Parameters<typeof fetch>[] } },
  url: string,
  method?: string,
) {
  return fetchMock.mock.calls.filter(([input, init]) => (
    input === url && (method === undefined || init?.method === method)
  ));
}

function renderWorkspace() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <PurchaseWorkspace apiBaseUrl={apiBaseUrl} purchaseId={purchaseId} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("PurchaseWorkspace", () => {
  it("hydrates an existing child approval flow and reloads the parent after the exact child resumes", async () => {
    const refreshed = workspace({
      children: [
        child(baytown, resumedBaytownRun, "WAITING_FOR_DEALER"),
        child(houston, agentRun(houston, "WAITING_FOR_EXTERNAL_RESPONSE"), "WAITING_FOR_DEALER"),
      ],
      counts: {
        selected_vehicles: 2,
        linked_children: 2,
        quote_requests_prepared: 2,
        responses_analyzed: 0,
        verified_offers: 0,
        incomplete_offers: 0,
        pending_approvals: 0,
      },
      attention_items: [
        attention(
          "WAITING_FOR_DEALER",
          baytown,
          "Baytown is waiting for a dealer response.",
          { requires_buyer_action: false },
        ),
        attention(
          "WAITING_FOR_DEALER",
          houston,
          "Houston is waiting for a dealer response.",
          { requires_buyer_action: false },
        ),
      ],
      updated_at: "2026-08-19T20:02:02Z",
    });
    let purchaseReads = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === `${apiBaseUrl}/purchase-runs/${purchaseId}` && init?.method === undefined) {
        purchaseReads += 1;
        return jsonResponse(purchaseReads === 1 ? workspace() : refreshed);
      }
      if (input === `${apiBaseUrl}/outreach/proposals/${pendingBaytownProposal.id}` && init?.method === undefined) {
        return jsonResponse(pendingBaytownProposal);
      }
      if (input === `${apiBaseUrl}/outreach/proposals/${pendingBaytownProposal.id}/approve` && init?.method === "POST") {
        return jsonResponse(sentBaytownProposal);
      }
      if (input === `${apiBaseUrl}/agent-runs/run-baytown/resume` && init?.method === "POST") {
        return jsonResponse(resumedBaytownRun);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    renderWorkspace();

    expect(await screen.findByText("Baytown quote request is awaiting your approval.")).toBeVisible();
    expect(screen.getByText("run-baytown")).toBeVisible();
    expect(callsTo(fetchMock, `${apiBaseUrl}/agent-runs`, "POST")).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Review approval" }));
    const dialog = await screen.findByRole("dialog", { name: "Review dealer quote request" });
    expect(within(dialog).getByText(pendingBaytownProposal.subject)).toBeVisible();
    expect(within(dialog).getByText(pendingBaytownProposal.body)).toBeVisible();
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve & send" }));

    expect(await screen.findByText("Baytown is waiting for a dealer response.")).toBeVisible();
    expect(screen.queryByText("Baytown quote request is awaiting your approval."))
      .not.toBeInTheDocument();
    await waitFor(() => {
      expect(callsTo(fetchMock, `${apiBaseUrl}/purchase-runs/${purchaseId}`))
        .toHaveLength(2);
    });
    const calls = fetchMock.mock.calls;
    const approveIndex = calls.findIndex(([input]) => (
      input === `${apiBaseUrl}/outreach/proposals/${pendingBaytownProposal.id}/approve`
    ));
    const resumeIndex = calls.findIndex(([input]) => (
      input === `${apiBaseUrl}/agent-runs/run-baytown/resume`
    ));
    const reloadIndex = calls.reduce(
      (latest, [input], index) => (
        input === `${apiBaseUrl}/purchase-runs/${purchaseId}` ? index : latest
      ),
      -1,
    );
    expect(approveIndex).toBeGreaterThan(-1);
    expect(resumeIndex).toBeGreaterThan(approveIndex);
    expect(reloadIndex).toBeGreaterThan(resumeIndex);
  });

  it("keeps partial setup inspectable and recovers only missing workflows through the purchase API", async () => {
    const partial = workspace({
      setup_status: "RECOVERY_REQUIRED",
      selected_vehicle_ids: [baytown.id, houston.id, katy.id],
      children: [
        child(baytown, agentRun(baytown, "WAITING_FOR_APPROVAL"), "APPROVAL_REQUIRED"),
        child(houston, null, "RECOVERY_REQUIRED", {
          creation_error_code: "agent_run_creation_failed",
        }),
        child(katy, null, "RECOVERY_REQUIRED", {
          creation_error_code: "agent_run_advancement_failed",
        }),
      ],
      counts: {
        selected_vehicles: 3,
        linked_children: 1,
        quote_requests_prepared: 1,
        responses_analyzed: 0,
        verified_offers: 0,
        incomplete_offers: 0,
        pending_approvals: 1,
      },
      attention_items: [
        attention(
          "RECOVERY_REQUIRED",
          houston,
          "Houston workflow creation failed and can be recovered.",
          { agent_run_id: null, action_id: null, requires_buyer_action: true },
        ),
        attention(
          "RECOVERY_REQUIRED",
          katy,
          "Katy workflow advancement failed and can be recovered.",
          { agent_run_id: null, action_id: null, requires_buyer_action: true },
        ),
      ],
    });
    const recovered = workspace({
      selected_vehicle_ids: [baytown.id, houston.id, katy.id],
      children: [
        child(baytown, agentRun(baytown, "WAITING_FOR_APPROVAL"), "APPROVAL_REQUIRED"),
        child(houston, agentRun(houston, "WAITING_FOR_APPROVAL"), "APPROVAL_REQUIRED"),
        child(katy, agentRun(katy, "WAITING_FOR_APPROVAL"), "APPROVAL_REQUIRED"),
      ],
      counts: {
        selected_vehicles: 3,
        linked_children: 3,
        quote_requests_prepared: 3,
        responses_analyzed: 0,
        verified_offers: 0,
        incomplete_offers: 0,
        pending_approvals: 3,
      },
      attention_items: [
        attention("APPROVAL_REQUIRED", baytown, "Baytown quote request is awaiting approval."),
        attention("APPROVAL_REQUIRED", houston, "Houston quote request is awaiting approval."),
        attention("APPROVAL_REQUIRED", katy, "Katy quote request is awaiting approval."),
      ],
      updated_at: "2026-08-19T20:03:00Z",
    });
    let purchaseReads = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === `${apiBaseUrl}/purchase-runs/${purchaseId}` && init?.method === undefined) {
        purchaseReads += 1;
        return jsonResponse(purchaseReads === 1 ? partial : recovered);
      }
      if (input === `${apiBaseUrl}/purchase-runs/${purchaseId}/recover` && init?.method === "POST") {
        return jsonResponse(recovered);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    renderWorkspace();

    expect(await screen.findByText("Houston workflow creation failed and can be recovered."))
      .toBeVisible();
    expect(screen.getByText("run-baytown")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Recover missing workflows" }));

    expect(await screen.findByText("run-houston")).toBeVisible();
    expect(screen.getByText("run-katy")).toBeVisible();
    expect(screen.getByText("run-baytown")).toBeVisible();
    expect(screen.queryByText("Houston workflow creation failed and can be recovered."))
      .not.toBeInTheDocument();
    expect(callsTo(
      fetchMock,
      `${apiBaseUrl}/purchase-runs/${purchaseId}/recover`,
      "POST",
    )).toHaveLength(1);
    expect(callsTo(fetchMock, `${apiBaseUrl}/agent-runs`, "POST")).toHaveLength(0);
  });

  it("renders the embedded canonical comparison and evidence without recomputing it in the browser", async () => {
    const canonical = workspace({
      decision_status: "COMPARISON_AVAILABLE",
      selected_vehicle_ids: [baytown.id, houston.id, katy.id],
      children: [
        child(baytown, agentRun(baytown, "INTERACTION_COMPLETE"), "OFFER_VERIFIED", {
          comparison_status: "VERIFIED",
          active_unresolved: false,
        }),
        child(houston, agentRun(houston, "INTERACTION_COMPLETE"), "OFFER_VERIFIED", {
          comparison_status: "VERIFIED",
          active_unresolved: false,
        }),
        child(katy, agentRun(katy, "WAITING_FOR_APPROVAL", {
          initial_action_id: "action-katy-initial",
          current_action_id: "action-katy-followup",
          interaction_id: "interaction-katy",
        }), "APPROVAL_REQUIRED", {
          comparison_status: "INCOMPLETE",
          active_unresolved: true,
        }),
      ],
      counts: {
        selected_vehicles: 3,
        linked_children: 3,
        quote_requests_prepared: 3,
        responses_analyzed: 3,
        verified_offers: 2,
        incomplete_offers: 1,
        pending_approvals: 1,
      },
      attention_items: [
        attention(
          "APPROVAL_REQUIRED",
          katy,
          "Katy follow-up is awaiting approval.",
          {
            action_id: "action-katy-followup",
            requires_buyer_action: true,
          },
        ),
      ],
      comparison: canonicalComparison,
      updated_at: "2026-08-19T20:12:00Z",
    });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === `${apiBaseUrl}/purchase-runs/${purchaseId}` && init?.method === undefined) {
        return jsonResponse(canonical);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    renderWorkspace();

    expect(await screen.findByRole("heading", { name: "Verified offers" })).toBeVisible();
    expect(screen.getByText("2 verified offers")).toBeVisible();
    expect(screen.getByText("1 incomplete")).toBeVisible();
    expect(screen.getByText("Katy follow-up is awaiting approval.")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Best verified offer so far" })).toBeVisible();
    expect(screen.getByText("$40,315.00 written OTD")).toBeVisible();
    expect(screen.getByText(/looked \$550\.00 cheaper in inventory/)).toBeVisible();
    expect(screen.getByText(/Unresolved alternatives remain/)).toBeVisible();

    fireEvent.click(screen.getByRole("button", {
      name: "View Baytown Hyundai written OTD evidence",
    }));
    const evidence = await screen.findByRole("dialog", { name: "claimed otd" });
    expect(within(evidence).getByText("Your written cash OTD is $40,315."))
      .toBeVisible();
    expect(callsTo(fetchMock, `${apiBaseUrl}/offer-comparisons`, "POST"))
      .toHaveLength(0);
  });
});
