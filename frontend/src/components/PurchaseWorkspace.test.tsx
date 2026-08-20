import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

const responseBInteractionId = "interaction-houston-response-b";
const responseBMessageId = "message-houston-response-b";
const responseBCeramicEvidenceId = "ev-houston-ceramic-response-b";
const responseBOtdEvidenceId = "ev-houston-otd-response-b";

const responseBHoustonOffer = {
  ...houstonOffer,
  interaction_id: responseBInteractionId,
  mandatory_addons: [
    {
      name: "Ceramic Shield",
      amount: "1299",
      stated_mandatory: true,
      evidence_id: responseBCeramicEvidenceId,
    },
  ],
  evidence: [
    {
      id: responseBCeramicEvidenceId,
      source_type: "DEALER_EMAIL",
      source_id: responseBMessageId,
      field_name: "addons",
      excerpt: "Our current response lists Ceramic Shield for $1,299 as mandatory.",
      created_at: "2026-08-19T20:29:30Z",
    },
    {
      id: responseBOtdEvidenceId,
      source_type: "DEALER_EMAIL",
      source_id: responseBMessageId,
      field_name: "claimed_otd",
      excerpt: "The current written out-the-door total is $41,780.",
      created_at: "2026-08-19T20:29:30Z",
    },
  ],
  claimed_otd_evidence_ids: [responseBOtdEvidenceId],
};

const responseBComparison = {
  ...canonicalComparison,
  offers: [baytownOffer, responseBHoustonOffer, katyOffer],
};

const responseBNoAddonsHoustonOffer = {
  ...responseBHoustonOffer,
  mandatory_addons: [],
  evidence: responseBHoustonOffer.evidence.filter((item) => (
    item.id === responseBOtdEvidenceId
  )),
};

const responseBNoAddonsComparison = {
  ...canonicalComparison,
  offers: [baytownOffer, responseBNoAddonsHoustonOffer, katyOffer],
};

const researchTargetsUrl = `${apiBaseUrl}/purchase-runs/${purchaseId}/research-targets`;

function investigateUrl(targetId: string) {
  return `${researchTargetsUrl}/${encodeURIComponent(targetId)}/investigate`;
}

const ceramicVendorSource = {
  id: "research-source-ceramic-vendor",
  url: "https://ceramic-shield.example.test/product-overview",
  title: "Ceramic Shield product overview",
  publisher: "Ceramic Shield Products",
  retrieved_at: "2026-08-19T20:20:00Z",
  excerpt: "The vendor describes a dealer-applied exterior coating intended to help protect painted surfaces.",
};

const ceramicIndependentSource = {
  id: "research-source-ceramic-independent",
  url: "https://consumer-auto.example.test/dealer-coatings",
  title: "Understanding dealer-applied coatings",
  publisher: null,
  retrieved_at: "2026-08-19T20:20:00Z",
  excerpt: "Dealer coating packages vary, so the exact application and coverage must be confirmed with the selling dealer.",
};

const ceramicFinding = {
  target_id: "research-target-houston-ceramic",
  target_name: "Ceramic Shield",
  summary: "Sources describe a dealer-applied exterior protection product.",
  what_it_appears_to_include: [
    "An exterior coating intended to help protect painted surfaces.",
  ],
  limitations: [
    "The exact scope of Houston Hyundai's package could not be independently verified.",
  ],
  source_ids: [ceramicVendorSource.id, ceramicIndependentSource.id],
  support_status: "SUPPORTED",
};

const ceramicTarget = {
  target_id: ceramicFinding.target_id,
  purchase_run_id: purchaseId,
  agent_run_id: "run-houston",
  interaction_id: "interaction-houston",
  source_message_id: "message-houston",
  dealer_id: houston.dealer_id,
  dealer_name: houston.dealer_name,
  vehicle_id: houston.id,
  target_type: "MANDATORY_ADDON",
  canonical_name: "Ceramic Shield",
  dealer_stated_amount: "1299",
  stated_mandatory: true,
  source_evidence_ids: ["ev-houston-ceramic"],
  recommended: true,
  investigation: null,
};

const responseBCeramicTarget = {
  ...ceramicTarget,
  target_id: "research-target-houston-ceramic-response-b",
  interaction_id: responseBInteractionId,
  source_message_id: responseBMessageId,
  source_evidence_ids: [responseBCeramicEvidenceId],
};

const secureTrackTarget = {
  target_id: "research-target-houston-securetrack",
  purchase_run_id: purchaseId,
  agent_run_id: "run-houston",
  interaction_id: "interaction-houston",
  source_message_id: "message-houston",
  dealer_id: houston.dealer_id,
  dealer_name: houston.dealer_name,
  vehicle_id: houston.id,
  target_type: "MANDATORY_ADDON",
  canonical_name: "SecureTrack theft recovery",
  dealer_stated_amount: "596",
  stated_mandatory: true,
  source_evidence_ids: ["ev-houston-securetrack"],
  recommended: true,
  investigation: null,
};

const completedCeramicTarget = {
  ...ceramicTarget,
  recommended: false,
  investigation: {
    id: "research-investigation-houston-ceramic",
    status: "COMPLETED",
    research_version: "research-v1",
    finding: ceramicFinding,
    sources: [ceramicVendorSource, ceramicIndependentSource],
    error_code: null,
    created_at: "2026-08-19T20:20:00Z",
    updated_at: "2026-08-19T20:20:01Z",
  },
};

const publisherlessSecureTrackSource = {
  id: "research-source-securetrack-public",
  url: "https://securetrack.example.test/product-details",
  title: "SecureTrack public product details",
  publisher: null,
  retrieved_at: "2026-08-19T20:20:00Z",
  excerpt: "The public page describes theft-recovery tracking features.",
};

const inProgressCeramicTarget = {
  ...ceramicTarget,
  recommended: false,
  investigation: {
    id: "research-investigation-houston-ceramic-progress",
    status: "IN_PROGRESS",
    research_version: "research-v1",
    finding: null,
    sources: [],
    error_code: null,
    created_at: "2026-08-19T20:20:00Z",
    updated_at: "2026-08-19T20:20:00Z",
  },
};

const failedSecureTrackTarget = {
  ...secureTrackTarget,
  investigation: {
    id: "research-investigation-houston-securetrack-failed",
    status: "FAILED",
    research_version: "research-v1",
    finding: null,
    sources: [publisherlessSecureTrackSource],
    error_code: "research_provider_failed",
    created_at: "2026-08-19T20:20:00Z",
    updated_at: "2026-08-19T20:20:01Z",
  },
};

function canonicalWorkspace(overrides: Record<string, unknown> = {}) {
  return workspace({
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
    ...overrides,
  });
}

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

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function renderWorkspace(queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })) {
  const view = render(
    <QueryClientProvider client={queryClient}>
      <PurchaseWorkspace apiBaseUrl={apiBaseUrl} purchaseId={purchaseId} />
    </QueryClientProvider>,
  );
  return { ...view, queryClient };
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

  it("offers bounded investigation for the two current material Houston add-ons", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === `${apiBaseUrl}/purchase-runs/${purchaseId}` && init?.method === undefined) {
        return jsonResponse(canonicalWorkspace());
      }
      if (input === researchTargetsUrl && init?.method === undefined) {
        return jsonResponse([ceramicTarget, secureTrackTarget]);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    renderWorkspace();

    const table = await screen.findByRole("table", { name: "Verified dealer offers" });
    const houstonRow = within(table).getByRole("row", { name: /Houston Hyundai/i });
    const baytownRow = within(table).getByRole("row", { name: /Baytown Hyundai/i });

    expect(await within(houstonRow).findByRole("button", {
      name: "Investigate Ceramic Shield",
    })).toBeVisible();
    expect(within(houstonRow).getByRole("button", {
      name: "Investigate SecureTrack theft recovery",
    })).toBeVisible();
    expect(within(baytownRow).queryByRole("button", { name: /Investigate/i }))
      .not.toBeInTheDocument();
    expect(callsTo(fetchMock, researchTargetsUrl)).toHaveLength(1);
  });

  it("joins research by authoritative evidence identity when displayed add-on names repeat", async () => {
    const duplicateEvidenceId = "ev-houston-protection-second";
    const duplicateNameOffer = {
      ...houstonOffer,
      mandatory_addons: [
        {
          ...houstonOffer.mandatory_addons[0],
          name: "Protection Package",
        },
        {
          name: "Protection Package",
          amount: "899",
          stated_mandatory: true,
          evidence_id: duplicateEvidenceId,
        },
      ],
      evidence: [
        ...houstonOffer.evidence,
        {
          id: duplicateEvidenceId,
          source_type: "DEALER_EMAIL",
          source_id: "message-houston",
          field_name: "addons",
          excerpt: "A second protection package for $899 is mandatory.",
          created_at: "2026-08-19T20:09:30Z",
        },
      ],
    };
    const identityFinding = {
      ...ceramicFinding,
      target_name: "Normalized exterior protection",
      summary: "This finding belongs only to the evidence-linked $899 term.",
    };
    const identityTarget = {
      ...completedCeramicTarget,
      canonical_name: "Normalized exterior protection",
      dealer_stated_amount: "899",
      source_evidence_ids: [duplicateEvidenceId],
      investigation: {
        ...completedCeramicTarget.investigation,
        id: "research-investigation-houston-protection-second",
        finding: identityFinding,
      },
    };
    const comparison = {
      ...canonicalComparison,
      offers: canonicalComparison.offers.map((offer) => (
        offer.agent_run_id === duplicateNameOffer.agent_run_id ? duplicateNameOffer : offer
      )),
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === `${apiBaseUrl}/purchase-runs/${purchaseId}` && init?.method === undefined) {
        return jsonResponse(canonicalWorkspace({ comparison }));
      }
      if (input === researchTargetsUrl && init?.method === undefined) {
        return jsonResponse([identityTarget]);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    renderWorkspace();

    const table = await screen.findByRole("table", { name: "Verified dealer offers" });
    const houstonRow = within(table).getByRole("row", { name: /Houston Hyundai/i });
    const firstTerm = within(houstonRow)
      .getByText("$1,299.00", { exact: false })
      .closest(".comparison-term");
    const secondTerm = within(houstonRow)
      .getByText("$899.00", { exact: false })
      .closest(".comparison-term");

    expect(firstTerm).not.toBeNull();
    expect(secondTerm).not.toBeNull();
    expect(within(firstTerm as HTMLElement).queryByText(identityFinding.summary))
      .not.toBeInTheDocument();
    expect(within(firstTerm as HTMLElement).queryByRole("region", {
      name: "Independent research for Protection Package",
    })).not.toBeInTheDocument();
    expect(await within(secondTerm as HTMLElement).findByText(identityFinding.summary))
      .toBeVisible();
    expect(within(secondTerm as HTMLElement).getByRole("region", {
      name: "Independent research for Protection Package",
    })).toBeVisible();
    expect(screen.queryByRole("button", { name: /Investigate Protection Package/i }))
      .not.toBeInTheDocument();
  });

  it("posts only an empty object and keeps external research distinct from dealer evidence", async () => {
    const investigationResponse = deferred<Response>();
    const secureTrackResponse = deferred<Response>();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === `${apiBaseUrl}/purchase-runs/${purchaseId}` && init?.method === undefined) {
        return jsonResponse(canonicalWorkspace());
      }
      if (input === researchTargetsUrl && init?.method === undefined) {
        return jsonResponse([ceramicTarget, secureTrackTarget]);
      }
      if (input === investigateUrl(ceramicTarget.target_id) && init?.method === "POST") {
        return investigationResponse.promise;
      }
      if (input === investigateUrl(secureTrackTarget.target_id) && init?.method === "POST") {
        return secureTrackResponse.promise;
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    renderWorkspace();

    const table = await screen.findByRole("table", { name: "Verified dealer offers" });
    const houstonRow = within(table).getByRole("row", { name: /Houston Hyundai/i });
    const investigate = await within(houstonRow).findByRole("button", {
      name: "Investigate Ceramic Shield",
    });
    fireEvent.click(investigate);

    await waitFor(() => expect(investigate).toBeDisabled());
    expect(investigate).toHaveTextContent("Investigating…");
    fireEvent.click(investigate);

    await waitFor(() => expect(callsTo(
      fetchMock,
      investigateUrl(ceramicTarget.target_id),
      "POST",
    )).toHaveLength(1));
    const postCalls = callsTo(
      fetchMock,
      investigateUrl(ceramicTarget.target_id),
      "POST",
    );
    expect(postCalls[0]?.[1]?.body).toBe("{}");
    expect(JSON.parse(String(postCalls[0]?.[1]?.body))).toEqual({});
    expect(postCalls).toHaveLength(1);

    const investigateSecureTrack = within(houstonRow).getByRole("button", {
      name: "Investigate SecureTrack theft recovery",
    });
    fireEvent.click(investigateSecureTrack);
    await waitFor(() => {
      expect(investigate).toBeDisabled();
      expect(investigateSecureTrack).toBeDisabled();
    });
    fireEvent.click(investigate);
    expect(callsTo(
      fetchMock,
      investigateUrl(ceramicTarget.target_id),
      "POST",
    )).toHaveLength(1);
    const secureTrackPosts = callsTo(
      fetchMock,
      investigateUrl(secureTrackTarget.target_id),
      "POST",
    );
    expect(secureTrackPosts).toHaveLength(1);
    expect(secureTrackPosts[0]?.[1]?.body).toBe("{}");

    await act(async () => {
      investigationResponse.resolve(jsonResponse(completedCeramicTarget));
      await investigationResponse.promise;
    });

    const research = await within(houstonRow).findByRole("region", {
      name: "Independent research for Ceramic Shield",
    });
    expect(investigateSecureTrack).toBeDisabled();
    expect(within(research).getByText("Independent research")).toBeVisible();
    expect(within(research).getByText(ceramicFinding.summary)).toBeVisible();
    expect(within(research).getByText(ceramicFinding.limitations[0])).toBeVisible();
    expect(within(houstonRow).getByRole("button", {
      name: "Investigate SecureTrack theft recovery",
    })).toBeDisabled();

    await act(async () => {
      secureTrackResponse.resolve(jsonResponse(secureTrackTarget));
      await secureTrackResponse.promise;
    });
    expect(await within(houstonRow).findByRole("button", {
      name: "Investigate SecureTrack theft recovery",
    })).toBeEnabled();

    fireEvent.click(within(research).getByRole("button", {
      name: `View research source ${ceramicVendorSource.title}`,
    }));
    const sourceDrawer = await screen.findByRole("dialog", {
      name: ceramicVendorSource.title,
    });
    expect(within(sourceDrawer).getByText(ceramicVendorSource.publisher)).toBeVisible();
    expect(within(sourceDrawer).getByText(ceramicVendorSource.excerpt)).toBeVisible();
    expect(within(sourceDrawer).getByRole("link", { name: "Open source page" }))
      .toHaveAttribute("href", ceramicVendorSource.url);
    fireEvent.click(within(sourceDrawer).getByRole("button", { name: "Close" }));

    fireEvent.click(within(houstonRow).getByRole("button", {
      name: "View Ceramic Shield evidence",
    }));
    const dealerEvidence = await screen.findByRole("dialog", { name: "addons" });
    expect(within(dealerEvidence).getByText("Ceramic Shield for $1,299 is mandatory."))
      .toBeVisible();
    expect(within(dealerEvidence).queryByText(ceramicVendorSource.publisher))
      .not.toBeInTheDocument();
  });

  it("shows a research failure without changing verified transaction economics", async () => {
    const failureMessage = (
      "Independent research is temporarily unavailable. The verified dealer "
      + "comparison remains unchanged."
    );
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === `${apiBaseUrl}/purchase-runs/${purchaseId}` && init?.method === undefined) {
        return jsonResponse(canonicalWorkspace());
      }
      if (input === researchTargetsUrl && init?.method === undefined) {
        return jsonResponse([ceramicTarget, secureTrackTarget]);
      }
      if (input === investigateUrl(ceramicTarget.target_id) && init?.method === "POST") {
        return jsonResponse({
          detail: {
            code: "research_provider_unavailable",
            message: failureMessage,
          },
        }, 503);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    renderWorkspace();

    const table = await screen.findByRole("table", { name: "Verified dealer offers" });
    const houstonRow = within(table).getByRole("row", { name: /Houston Hyundai/i });
    fireEvent.click(await within(houstonRow).findByRole("button", {
      name: "Investigate Ceramic Shield",
    }));

    expect(await screen.findByRole("alert")).toHaveTextContent(failureMessage);
    expect(screen.getByRole("heading", { name: "Best verified offer so far" }))
      .toBeVisible();
    expect(screen.getByText("$40,315.00 written OTD")).toBeVisible();
    expect(screen.getByText(/looked \$550\.00 cheaper in inventory/)).toBeVisible();
    expect(screen.getByText(/saves \$1,465\.00 on verified written OTD/)).toBeVisible();
    expect(within(houstonRow).getByText("$41,780.00")).toBeVisible();
    expect(within(houstonRow).getByText("Verified rank #2")).toBeVisible();
    expect(screen.queryByText(ceramicFinding.summary)).not.toBeInTheDocument();
    expect(callsTo(fetchMock, `${apiBaseUrl}/offer-comparisons`, "POST"))
      .toHaveLength(0);
  });

  it("does not reissue persisted states automatically and allows an explicit failed retry", async () => {
    const retryFailure = "Independent research is still temporarily unavailable.";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === `${apiBaseUrl}/purchase-runs/${purchaseId}` && init?.method === undefined) {
        return jsonResponse(canonicalWorkspace());
      }
      if (input === researchTargetsUrl && init?.method === undefined) {
        return jsonResponse([inProgressCeramicTarget, failedSecureTrackTarget]);
      }
      if (
        input === investigateUrl(secureTrackTarget.target_id)
        && init?.method === "POST"
      ) {
        return jsonResponse({
          detail: {
            code: "research_provider_failed",
            message: retryFailure,
          },
        }, 502);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    renderWorkspace();

    const table = await screen.findByRole("table", { name: "Verified dealer offers" });
    const houstonRow = within(table).getByRole("row", { name: /Houston Hyundai/i });
    expect(await within(houstonRow).findByRole("status")).toHaveTextContent(
      "Independent research is in progress. The dealer quote remains unchanged.",
    );
    expect(within(houstonRow).getByRole("alert")).toHaveTextContent(
      "Independent research failed (Research provider failed). "
      + "The dealer quote and comparison remain unchanged.",
    );
    expect(within(houstonRow).queryByRole("button", { name: /Investigate/i }))
      .not.toBeInTheDocument();
    expect(within(houstonRow).getByRole("button", {
      name: "Retry independent research for SecureTrack theft recovery",
    })).toBeVisible();

    fireEvent.click(within(houstonRow).getByRole("button", {
      name: `View research source ${publisherlessSecureTrackSource.title}`,
    }));
    const sourceDrawer = await screen.findByRole("dialog", {
      name: publisherlessSecureTrackSource.title,
    });
    expect(within(sourceDrawer).getByText("Publisher not provided")).toBeVisible();
    fireEvent.click(within(sourceDrawer).getByRole("button", { name: "Close" }));
    expect(callsTo(fetchMock, investigateUrl(ceramicTarget.target_id), "POST"))
      .toHaveLength(0);
    expect(callsTo(fetchMock, investigateUrl(secureTrackTarget.target_id), "POST"))
      .toHaveLength(0);

    fireEvent.click(within(houstonRow).getByRole("button", {
      name: "Retry independent research for SecureTrack theft recovery",
    }));
    expect(await within(houstonRow).findByText(retryFailure)).toBeVisible();
    expect(callsTo(fetchMock, investigateUrl(secureTrackTarget.target_id), "POST"))
      .toHaveLength(1);
  });

  it("refreshes a failed target when another request already reclaimed it", async () => {
    const inProgressMessage = "Research for this current target is already in progress.";
    const refreshedTargets = deferred<Response>();
    let targetReads = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === `${apiBaseUrl}/purchase-runs/${purchaseId}` && init?.method === undefined) {
        return jsonResponse(canonicalWorkspace());
      }
      if (input === researchTargetsUrl && init?.method === undefined) {
        targetReads += 1;
        return targetReads === 1
          ? jsonResponse([failedSecureTrackTarget])
          : refreshedTargets.promise;
      }
      if (
        input === investigateUrl(secureTrackTarget.target_id)
        && init?.method === "POST"
      ) {
        return jsonResponse({
          detail: {
            code: "research_in_progress",
            message: inProgressMessage,
          },
        }, 409);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    renderWorkspace();

    const retry = await screen.findByRole("button", {
      name: "Retry independent research for SecureTrack theft recovery",
    });
    fireEvent.click(retry);

    expect(await screen.findByText(inProgressMessage)).toBeVisible();
    expect(callsTo(fetchMock, researchTargetsUrl)).toHaveLength(2);
    await act(async () => {
      refreshedTargets.resolve(jsonResponse([{
        ...inProgressCeramicTarget,
        ...secureTrackTarget,
        investigation: {
          ...inProgressCeramicTarget.investigation,
          id: "research-investigation-houston-securetrack-progress",
          target_id: secureTrackTarget.target_id,
        },
      }]));
      await refreshedTargets.promise;
    });

    expect(await screen.findByText(
      "Independent research is in progress. The dealer quote remains unchanged.",
    )).toBeVisible();
    expect(screen.queryByRole("button", {
      name: "Retry independent research for SecureTrack theft recovery",
    })).not.toBeInTheDocument();
    expect(callsTo(fetchMock, investigateUrl(secureTrackTarget.target_id), "POST"))
      .toHaveLength(1);
  });

  it("refreshes research after a child authority event even when the workspace timestamp is unchanged", async () => {
    const unchangedUpdatedAt = "2026-08-19T20:12:00Z";
    const waitingHoustonRun = agentRun(houston, "WAITING_FOR_ANALYSIS", {
      interaction_id: "interaction-houston",
      last_message_id: "message-houston",
    });
    const refreshedHoustonRun = agentRun(houston, "INTERACTION_COMPLETE", {
      interaction_id: responseBInteractionId,
      last_message_id: responseBMessageId,
    });
    const responseAWorkspace = canonicalWorkspace({
      children: [
        child(baytown, agentRun(baytown, "INTERACTION_COMPLETE"), "OFFER_VERIFIED", {
          comparison_status: "VERIFIED",
          active_unresolved: false,
        }),
        child(houston, waitingHoustonRun, "OFFER_VERIFIED", {
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
      updated_at: unchangedUpdatedAt,
    });
    const responseBWorkspace = canonicalWorkspace({
      children: [
        child(baytown, agentRun(baytown, "INTERACTION_COMPLETE"), "OFFER_VERIFIED", {
          comparison_status: "VERIFIED",
          active_unresolved: false,
        }),
        child(houston, refreshedHoustonRun, "OFFER_VERIFIED", {
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
      comparison: responseBComparison,
      updated_at: unchangedUpdatedAt,
    });
    let purchaseReads = 0;
    let targetReads = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === `${apiBaseUrl}/purchase-runs/${purchaseId}` && init?.method === undefined) {
        purchaseReads += 1;
        return jsonResponse(purchaseReads === 1 ? responseAWorkspace : responseBWorkspace);
      }
      if (input === researchTargetsUrl && init?.method === undefined) {
        targetReads += 1;
        return jsonResponse(
          targetReads === 1 ? [completedCeramicTarget] : [responseBCeramicTarget],
        );
      }
      if (input === `${apiBaseUrl}/agent-runs/run-houston/resume` && init?.method === "POST") {
        return jsonResponse(refreshedHoustonRun);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    const { queryClient } = renderWorkspace();

    expect(await screen.findByText(ceramicFinding.summary)).toBeVisible();
    const houstonWorkflow = screen.getByText("run-houston").closest("article");
    expect(houstonWorkflow).not.toBeNull();
    fireEvent.click(within(houstonWorkflow as HTMLElement).getByRole("button", {
      name: "Resume from latest state",
    }));

    await waitFor(() => expect(callsTo(
      fetchMock,
      `${apiBaseUrl}/purchase-runs/${purchaseId}`,
    )).toHaveLength(2));
    await waitFor(() => expect(callsTo(fetchMock, researchTargetsUrl)).toHaveLength(2));
    await waitFor(() => expect(screen.queryByText(ceramicFinding.summary))
      .not.toBeInTheDocument());
    expect(await screen.findByRole("button", { name: "Investigate Ceramic Shield" }))
      .toBeVisible();
    expect(queryClient.getQueryData([
      "purchase-research-targets",
      apiBaseUrl,
      purchaseId,
    ])).toEqual([responseBCeramicTarget]);
    expect(callsTo(fetchMock, investigateUrl(ceramicTarget.target_id), "POST"))
      .toHaveLength(0);
    expect(callsTo(fetchMock, investigateUrl(responseBCeramicTarget.target_id), "POST"))
      .toHaveLength(0);
  });

  it("loads the replacement target after a stale 409 even when the workspace timestamp is unchanged", async () => {
    const staleMessage = (
      "This research target changed with the dealer's latest quote. "
      + "Review the current term before investigating."
    );
    const unchangedUpdatedAt = "2026-08-19T20:12:00Z";
    const refreshedPurchaseResponse = deferred<Response>();
    const refreshedTargetsResponse = deferred<Response>();
    let purchaseReads = 0;
    let targetReads = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === `${apiBaseUrl}/purchase-runs/${purchaseId}` && init?.method === undefined) {
        purchaseReads += 1;
        return purchaseReads === 1
          ? jsonResponse(canonicalWorkspace({ updated_at: unchangedUpdatedAt }))
          : refreshedPurchaseResponse.promise;
      }
      if (input === researchTargetsUrl && init?.method === undefined) {
        targetReads += 1;
        return targetReads === 1
          ? jsonResponse([completedCeramicTarget, secureTrackTarget])
          : refreshedTargetsResponse.promise;
      }
      if (input === investigateUrl(secureTrackTarget.target_id) && init?.method === "POST") {
        return jsonResponse({
          detail: {
            code: "research_target_changed",
            message: staleMessage,
          },
        }, 409);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    const { queryClient } = renderWorkspace();

    const table = await screen.findByRole("table", { name: "Verified dealer offers" });
    const houstonRow = within(table).getByRole("row", { name: /Houston Hyundai/i });
    const research = await within(houstonRow).findByRole("region", {
      name: "Independent research for Ceramic Shield",
    });
    fireEvent.click(within(research).getByRole("button", {
      name: `View research source ${ceramicVendorSource.title}`,
    }));
    expect(await screen.findByRole("dialog", { name: ceramicVendorSource.title }))
      .toBeVisible();

    fireEvent.click(within(houstonRow).getByRole("button", {
      name: "Investigate SecureTrack theft recovery",
    }));

    expect(await screen.findByRole("alert")).toHaveTextContent(staleMessage);
    await waitFor(() => expect(callsTo(
      fetchMock,
      `${apiBaseUrl}/purchase-runs/${purchaseId}`,
    )).toHaveLength(2));
    await waitFor(() => expect(callsTo(fetchMock, researchTargetsUrl)).toHaveLength(2));
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: ceramicVendorSource.title }))
        .not.toBeInTheDocument();
      expect(screen.queryByText(ceramicFinding.summary)).not.toBeInTheDocument();
    });
    await act(async () => {
      refreshedPurchaseResponse.resolve(jsonResponse(canonicalWorkspace({
        comparison: responseBComparison,
        updated_at: unchangedUpdatedAt,
      })));
      refreshedTargetsResponse.resolve(jsonResponse([responseBCeramicTarget]));
      await Promise.all([
        refreshedPurchaseResponse.promise,
        refreshedTargetsResponse.promise,
      ]);
    });
    expect(await screen.findByRole("button", { name: "Investigate Ceramic Shield" }))
      .toBeVisible();
    expect(queryClient.getQueryData([
      "purchase-research-targets",
      apiBaseUrl,
      purchaseId,
    ])).toEqual([responseBCeramicTarget]);
    expect(screen.queryByText("SecureTrack theft recovery")).not.toBeInTheDocument();
    expect(callsTo(fetchMock, investigateUrl(responseBCeramicTarget.target_id), "POST"))
      .toHaveLength(0);
  });

  it("keeps stale findings hidden when the refreshed quote removes every material add-on", async () => {
    const staleMessage = (
      "This research target changed with the dealer's latest quote. "
      + "Review the current term before investigating."
    );
    const unchangedUpdatedAt = "2026-08-19T20:12:00Z";
    let purchaseReads = 0;
    let targetReads = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === `${apiBaseUrl}/purchase-runs/${purchaseId}` && init?.method === undefined) {
        purchaseReads += 1;
        return jsonResponse(canonicalWorkspace({
          comparison: purchaseReads === 1
            ? canonicalComparison
            : responseBNoAddonsComparison,
          updated_at: unchangedUpdatedAt,
        }));
      }
      if (input === researchTargetsUrl && init?.method === undefined) {
        targetReads += 1;
        return jsonResponse(
          targetReads === 1
            ? [completedCeramicTarget, secureTrackTarget]
            : [],
        );
      }
      if (input === investigateUrl(secureTrackTarget.target_id) && init?.method === "POST") {
        return jsonResponse({
          detail: {
            code: "research_target_changed",
            message: staleMessage,
          },
        }, 409);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    const { queryClient } = renderWorkspace();

    expect(await screen.findByText(ceramicFinding.summary)).toBeVisible();
    fireEvent.click(screen.getByRole("button", {
      name: "Investigate SecureTrack theft recovery",
    }));

    expect(await screen.findByRole("alert")).toHaveTextContent(staleMessage);
    await waitFor(() => expect(callsTo(
      fetchMock,
      `${apiBaseUrl}/purchase-runs/${purchaseId}`,
    )).toHaveLength(2));
    await waitFor(() => expect(callsTo(fetchMock, researchTargetsUrl)).toHaveLength(2));
    await waitFor(() => {
      expect(screen.queryByText(ceramicFinding.summary)).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Investigate/i }))
        .not.toBeInTheDocument();
    });
    expect(queryClient.getQueryData([
      "purchase-research-targets",
      apiBaseUrl,
      purchaseId,
    ])).toEqual([]);
  });

  it("hydrates a persisted finding after reload without another investigation POST", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === `${apiBaseUrl}/purchase-runs/${purchaseId}` && init?.method === undefined) {
        return jsonResponse(canonicalWorkspace());
      }
      if (input === researchTargetsUrl && init?.method === undefined) {
        return jsonResponse([completedCeramicTarget, secureTrackTarget]);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });

    const firstView = renderWorkspace();
    expect(await screen.findByText(ceramicFinding.summary)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Investigate Ceramic Shield" }))
      .not.toBeInTheDocument();
    const firstResearch = screen.getByRole("region", {
      name: "Independent research for Ceramic Shield",
    });
    const sourceButtonName = `View research source ${ceramicVendorSource.title}`;
    fireEvent.click(within(firstResearch).getByRole("button", { name: sourceButtonName }));
    const firstDrawer = await screen.findByRole("dialog", { name: ceramicVendorSource.title });
    fireEvent.click(within(firstDrawer).getByRole("button", { name: "Close" }));
    fireEvent.click(within(firstResearch).getByRole("button", { name: sourceButtonName }));
    const reopenedDrawer = await screen.findByRole("dialog", { name: ceramicVendorSource.title });
    fireEvent.keyDown(reopenedDrawer, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", {
      name: ceramicVendorSource.title,
    })).not.toBeInTheDocument());
    firstView.unmount();

    renderWorkspace();
    expect(await screen.findByText(ceramicFinding.summary)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Investigate Ceramic Shield" }))
      .not.toBeInTheDocument();
    const reloadedResearch = screen.getByRole("region", {
      name: "Independent research for Ceramic Shield",
    });
    fireEvent.click(within(reloadedResearch).getByRole("button", { name: sourceButtonName }));
    expect(await screen.findByRole("dialog", { name: ceramicVendorSource.title }))
      .toBeVisible();
    expect(callsTo(fetchMock, researchTargetsUrl)).toHaveLength(2);
    expect(callsTo(
      fetchMock,
      investigateUrl(ceramicTarget.target_id),
      "POST",
    )).toHaveLength(0);
    expect(screen.getByRole("heading", { name: "Best verified offer so far" }))
      .toBeVisible();
    expect(screen.getByText("$40,315.00 written OTD")).toBeVisible();
  });
});
