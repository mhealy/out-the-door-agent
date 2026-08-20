import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AgentRunSnapshot } from "./AgentWorkflow";
import { VerifiedOffersComparison } from "./VerifiedOffersComparison";

const apiBaseUrl = "http://api.test";

const canonicalRuns = [
  {
    run_id: "run-baytown",
    vehicle_id: "baytown-blue",
    phase: "INTERACTION_COMPLETE",
    updated_at: "2026-08-19T20:10:00Z",
  },
  {
    run_id: "run-houston",
    vehicle_id: "houston-white",
    phase: "INTERACTION_COMPLETE",
    updated_at: "2026-08-19T20:11:00Z",
  },
  {
    run_id: "run-katy",
    vehicle_id: "katy-blue",
    phase: "INTERACTION_INCOMPLETE_MAX_FOLLOWUPS",
    updated_at: "2026-08-19T20:12:00Z",
  },
] satisfies AgentRunSnapshot[];

const baytownOffer = {
  agent_run_id: "run-baytown",
  dealer_name: "Baytown Hyundai",
  advertised_price: "37800",
  claimed_otd: "40315",
  inventory_provenance: {
    source_type: "INVENTORY_LISTING",
    source_provider: "fixture",
    source_url: "https://example.test/inventory/baytown-blue",
  },
  mandatory_addons: [],
  conditions: [
    {
      description: "No dealer financing or trade-in is required.",
      evidence_ids: ["ev-baytown-financing", "ev-baytown-trade"],
    },
  ],
  comparison_status: "VERIFIED",
  eligible: true,
  verified_rank: 1,
  run_phase: "INTERACTION_COMPLETE",
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
    {
      id: "ev-baytown-financing",
      source_type: "DEALER_EMAIL",
      source_id: "message-baytown",
      field_name: "financing_required",
      excerpt: "No dealer financing or trade-in is required.",
      created_at: "2026-08-19T20:09:00Z",
    },
    {
      id: "ev-baytown-trade",
      source_type: "DEALER_EMAIL",
      source_id: "message-baytown",
      field_name: "trade_required",
      excerpt: "No dealer financing or trade-in is required.",
      created_at: "2026-08-19T20:09:00Z",
    },
  ],
  claimed_otd_evidence_ids: ["ev-baytown-otd"],
};

const houstonOffer = {
  agent_run_id: "run-houston",
  dealer_name: "Houston Hyundai",
  advertised_price: "37250",
  claimed_otd: "41780",
  inventory_provenance: {
    source_type: "INVENTORY_LISTING",
    source_provider: "fixture",
    source_url: "https://example.test/inventory/houston-white",
  },
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
  conditions: [
    {
      description: "No dealer financing or trade-in is required.",
      evidence_ids: ["ev-houston-financing"],
    },
  ],
  comparison_status: "VERIFIED",
  eligible: true,
  verified_rank: 2,
  run_phase: "INTERACTION_COMPLETE",
  evidence: [
    {
      id: "ev-houston-ceramic",
      source_type: "DEALER_EMAIL",
      source_id: "message-houston",
      field_name: "addons",
      excerpt: "Every vehicle is delivered with Ceramic Shield for $1,299 and SecureTrack theft recovery for $596; both products are mandatory and cannot be removed.",
      created_at: "2026-08-19T20:09:30Z",
    },
    {
      id: "ev-houston-securetrack",
      source_type: "DEALER_EMAIL",
      source_id: "message-houston",
      field_name: "addons",
      excerpt: "Every vehicle is delivered with Ceramic Shield for $1,299 and SecureTrack theft recovery for $596; both products are mandatory and cannot be removed.",
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
    {
      id: "ev-houston-financing",
      source_type: "DEALER_EMAIL",
      source_id: "message-houston",
      field_name: "financing_required",
      excerpt: "Dealer financing and a trade-in are not required.",
      created_at: "2026-08-19T20:09:30Z",
    },
  ],
  claimed_otd_evidence_ids: ["ev-houston-otd"],
};

const katyOffer = {
  agent_run_id: "run-katy",
  dealer_name: "Katy Hyundai",
  advertised_price: "39500",
  claimed_otd: "40250",
  inventory_provenance: {
    source_type: "INVENTORY_LISTING",
    source_provider: "fixture",
    source_url: "https://example.test/inventory/katy-blue",
  },
  mandatory_addons: [],
  conditions: [
    {
      description: "The written total assumes a qualifying 2015-or-newer trade-in.",
      evidence_ids: ["ev-katy-trade"],
    },
    {
      description: "Vehicle identity and dealer add-on status remain unresolved.",
      evidence_ids: ["ev-katy-unresolved"],
    },
  ],
  comparison_status: "INCOMPLETE",
  eligible: false,
  verified_rank: null,
  run_phase: "INTERACTION_INCOMPLETE_MAX_FOLLOWUPS",
  evidence: [
    {
      id: "ev-katy-otd",
      source_type: "DEALER_EMAIL",
      source_id: "message-katy",
      field_name: "claimed_otd",
      excerpt: "The written OTD shown is $40,250 and assumes the qualifying trade.",
      created_at: "2026-08-19T20:09:45Z",
    },
    {
      id: "ev-katy-trade",
      source_type: "DEALER_EMAIL",
      source_id: "message-katy",
      field_name: "trade_required",
      excerpt: "Our $36,900 selling price includes $1,500 trade assistance and assumes a qualifying 2015-or-newer trade-in.",
      created_at: "2026-08-19T20:09:45Z",
    },
    {
      id: "ev-katy-unresolved",
      source_type: "DEALER_EMAIL",
      source_id: "message-katy",
      field_name: "unresolved_questions",
      excerpt: "Add-on status and fee itemization are not provided.",
      created_at: "2026-08-19T20:09:45Z",
    },
  ],
  claimed_otd_evidence_ids: ["ev-katy-otd"],
};

const canonicalComparison = {
  offers: [baytownOffer, houstonOffer, katyOffer],
  ranked_agent_run_ids: ["run-baytown", "run-houston"],
  recommendation: {
    recommended_agent_run_id: "run-baytown",
    recommended_dealer_id: "baytown",
    recommended_dealer_name: "Baytown Hyundai",
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

function queryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

function renderComparison(
  runs: AgentRunSnapshot[],
  client: QueryClient = queryClient(),
) {
  return render(
    <QueryClientProvider client={client}>
      <VerifiedOffersComparison apiBaseUrl={apiBaseUrl} runs={runs} />
    </QueryClientProvider>,
  );
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

afterEach(() => vi.restoreAllMocks());

describe("VerifiedOffersComparison", () => {
  it("does not request or show a cross-dealer comparison before two runs are known", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");

    renderComparison([canonicalRuns[0]]);
    await Promise.resolve();

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: "Verified offers" }))
      .not.toBeInTheDocument();
  });

  it("posts only the stable AgentRun IDs once at least two runs are known", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(canonicalComparison));

    renderComparison(canonicalRuns.slice(0, 2));

    expect(await screen.findByRole("heading", { name: "Verified offers" })).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(`${apiBaseUrl}/offer-comparisons`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        agent_run_ids: ["run-baytown", "run-houston"],
      }),
    });
  });

  it("uses run updated_at values as a refetch key without adding them to the request", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(canonicalComparison))
      .mockResolvedValueOnce(jsonResponse(canonicalComparison));
    const client = queryClient();
    const initialRuns = canonicalRuns.slice(0, 2);
    const view = renderComparison(initialRuns, client);

    expect(await screen.findByRole("heading", { name: "Verified offers" })).toBeVisible();
    await waitFor(() => {
      expect(callsTo(fetchMock, `${apiBaseUrl}/offer-comparisons`, "POST"))
        .toHaveLength(1);
    });

    const refreshedRuns: AgentRunSnapshot[] = [
      initialRuns[0],
      {
        ...initialRuns[1],
        updated_at: "2026-08-19T20:20:00Z",
      },
    ];
    view.rerender(
      <QueryClientProvider client={client}>
        <VerifiedOffersComparison apiBaseUrl={apiBaseUrl} runs={refreshedRuns} />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(callsTo(fetchMock, `${apiBaseUrl}/offer-comparisons`, "POST"))
        .toHaveLength(2);
    });
    for (const [, init] of callsTo(
      fetchMock,
      `${apiBaseUrl}/offer-comparisons`,
      "POST",
    )) {
      expect(init?.body).toBe(JSON.stringify({
        agent_run_ids: ["run-baytown", "run-houston"],
      }));
    }
  });

  it("renders backend order and keeps every workflow status visibly distinct", async () => {
    const statusRuns = [
      canonicalRuns[0],
      {
        run_id: "run-incomplete",
        vehicle_id: "vehicle-incomplete",
        phase: "INTERACTION_INCOMPLETE_MAX_FOLLOWUPS",
        updated_at: "2026-08-19T20:21:00Z",
      },
      {
        run_id: "run-progress",
        vehicle_id: "vehicle-progress",
        phase: "WAITING_FOR_EXTERNAL_RESPONSE",
        updated_at: "2026-08-19T20:22:00Z",
      },
      {
        run_id: "run-blocked",
        vehicle_id: "vehicle-blocked",
        phase: "DELIVERY_UNCONFIRMED",
        updated_at: "2026-08-19T20:23:00Z",
      },
      {
        run_id: "run-failed",
        vehicle_id: "vehicle-failed",
        phase: "RUN_FAILED",
        updated_at: "2026-08-19T20:24:00Z",
      },
      {
        run_id: "run-rejected",
        vehicle_id: "vehicle-rejected",
        phase: "RUN_REJECTED",
        updated_at: "2026-08-19T20:25:00Z",
      },
    ] satisfies AgentRunSnapshot[];
    const statusOffers = [
      baytownOffer,
      {
        ...katyOffer,
        agent_run_id: "run-incomplete",
        dealer_name: "Incomplete Dealer",
        claimed_otd: null,
        claimed_otd_evidence_ids: [],
      },
      {
        ...katyOffer,
        agent_run_id: "run-progress",
        dealer_name: "In-progress Dealer",
        claimed_otd: null,
        comparison_status: "IN_PROGRESS",
        run_phase: "WAITING_FOR_EXTERNAL_RESPONSE",
        claimed_otd_evidence_ids: [],
      },
      {
        ...katyOffer,
        agent_run_id: "run-blocked",
        dealer_name: "Blocked Dealer",
        claimed_otd: null,
        comparison_status: "BLOCKED",
        run_phase: "DELIVERY_UNCONFIRMED",
        claimed_otd_evidence_ids: [],
      },
      {
        ...katyOffer,
        agent_run_id: "run-failed",
        dealer_name: "Failed Dealer",
        claimed_otd: null,
        comparison_status: "FAILED",
        run_phase: "RUN_FAILED",
        claimed_otd_evidence_ids: [],
      },
      {
        ...katyOffer,
        agent_run_id: "run-rejected",
        dealer_name: "Rejected Dealer",
        claimed_otd: null,
        comparison_status: "REJECTED",
        run_phase: "RUN_REJECTED",
        claimed_otd_evidence_ids: [],
      },
    ];
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse({
      offers: statusOffers,
      ranked_agent_run_ids: ["run-baytown"],
      recommendation: {
        ...canonicalComparison.recommendation,
        next_best_verified_otd: null,
        savings_vs_next_verified: null,
      },
      advertised_vs_verified: canonicalComparison.advertised_vs_verified,
    }));

    renderComparison(statusRuns);

    const table = await screen.findByRole("table", { name: "Verified dealer offers" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((row) => within(row).getByRole("rowheader").textContent)).toEqual([
      "Baytown Hyundai",
      "Incomplete Dealer",
      "In-progress Dealer",
      "Blocked Dealer",
      "Failed Dealer",
      "Rejected Dealer",
    ]);
    expect(within(rows[0]).getByText("Verified")).toBeVisible();
    expect(within(rows[1]).getByText("Incomplete")).toBeVisible();
    expect(within(rows[2]).getByText("In progress")).toBeVisible();
    expect(within(rows[3]).getByText("Blocked")).toBeVisible();
    expect(within(rows[4]).getByText("Failed")).toBeVisible();
    expect(within(rows[5]).getByText("Rejected")).toBeVisible();
  });

  it("makes inventory price and dealer-response OTD separate and tells the canonical story", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(canonicalComparison));

    renderComparison(canonicalRuns);

    const table = await screen.findByRole("table", { name: "Verified dealer offers" });
    expect(within(table).getByRole("columnheader", {
      name: /Advertised price.*inventory listing/i,
    })).toBeVisible();
    expect(within(table).getByRole("columnheader", {
      name: /Written OTD.*dealer response/i,
    })).toBeVisible();

    const rows = within(table).getAllByRole("row").slice(1);
    const baytownRow = rows[0];
    const katyRow = rows[2];
    expect(within(baytownRow).getByText("$37,800.00")).toBeVisible();
    expect(within(baytownRow).getByText(/INVENTORY SOURCE.*fixture/i)).toBeVisible();
    expect(within(baytownRow).getByText("$40,315.00")).toBeVisible();
    expect(within(baytownRow).getByText("DEALER EVIDENCE")).toBeVisible();
    expect(within(katyRow).getByText("$40,250.00")).toBeVisible();
    expect(within(katyRow).getByText("Incomplete")).toBeVisible();
    expect(within(katyRow).getByText("Not eligible")).toBeVisible();

    expect(screen.getByRole("heading", { name: "Best verified offer" })).toBeVisible();
    expect(screen.getByText(
      "Baytown Hyundai is the lowest verified written OTD at $40,315.00.",
    )).toBeVisible();
    expect(screen.getByText(
      "That is $1,465.00 below Houston Hyundai's verified written OTD.",
    )).toBeVisible();
    expect(screen.getByText(
      "Houston Hyundai looked $550.00 cheaper online, but Baytown Hyundai has the lower verified transaction cost.",
    )).toBeVisible();
    expect(screen.getByText(
      "Katy Hyundai has a stated $40,250.00 OTD but remains incomplete and is not rankable.",
    )).toBeVisible();
  });

  it("opens authoritative written-OTD and mandatory-add-on evidence", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(canonicalComparison));

    renderComparison(canonicalRuns);

    const table = await screen.findByRole("table", { name: "Verified dealer offers" });
    const rows = within(table).getAllByRole("row").slice(1);
    fireEvent.click(within(rows[0]).getByRole("button", {
      name: "View Baytown Hyundai written OTD evidence",
    }));

    const otdEvidence = await screen.findByRole("dialog", { name: "claimed otd" });
    expect(within(otdEvidence).getByText("DEALER EVIDENCE")).toBeVisible();
    expect(within(otdEvidence).getByText("Your written cash OTD is $40,315."))
      .toBeVisible();
    fireEvent.click(within(otdEvidence).getByRole("button", { name: "Close" }));

    fireEvent.click(within(rows[1]).getByRole("button", {
      name: "View Ceramic Shield evidence",
    }));
    const addonEvidence = await screen.findByRole("dialog", { name: "addons" });
    expect(within(addonEvidence).getByText(/both products are mandatory and cannot be removed/i))
      .toBeVisible();
  });

  it("resolves an open evidence drawer from refreshed comparison data", async () => {
    const updatedComparison = {
      ...canonicalComparison,
      offers: [
        {
          ...baytownOffer,
          evidence: baytownOffer.evidence.map((item) => (
            item.id === "ev-baytown-otd"
              ? { ...item, excerpt: "Updated authoritative written OTD evidence." }
              : item
          )),
        },
        houstonOffer,
        katyOffer,
      ],
    };
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(canonicalComparison))
      .mockResolvedValueOnce(jsonResponse(updatedComparison));
    const client = queryClient();
    const view = renderComparison(canonicalRuns, client);

    const table = await screen.findByRole("table", { name: "Verified dealer offers" });
    fireEvent.click(within(within(table).getAllByRole("row")[1]).getByRole("button", {
      name: "View Baytown Hyundai written OTD evidence",
    }));
    expect(await screen.findByText("Your written cash OTD is $40,315.")).toBeVisible();

    view.rerender(
      <QueryClientProvider client={client}>
        <VerifiedOffersComparison
          apiBaseUrl={apiBaseUrl}
          runs={canonicalRuns.map((run, index) => (
            index === 0 ? { ...run, updated_at: "2026-08-19T20:30:00Z" } : run
          ))}
        />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Updated authoritative written OTD evidence."))
      .toBeVisible();
    expect(screen.queryByText("Your written cash OTD is $40,315."))
      .not.toBeInTheDocument();
  });

  it("closes evidence when a refreshed analysis reuses its ID for a new source", async () => {
    const reusedIdComparison = {
      ...canonicalComparison,
      offers: [
        {
          ...baytownOffer,
          advertised_price: "37999",
          evidence: baytownOffer.evidence.map((item) => (
            item.id === "ev-baytown-otd"
              ? {
                ...item,
                source_id: "message-new",
                excerpt: "A different dealer message reused this evidence ID.",
              }
              : item
          )),
        },
        houstonOffer,
        katyOffer,
      ],
    };
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(canonicalComparison))
      .mockResolvedValueOnce(jsonResponse(reusedIdComparison));
    const client = queryClient();
    const view = renderComparison(canonicalRuns, client);

    const table = await screen.findByRole("table", { name: "Verified dealer offers" });
    fireEvent.click(within(within(table).getAllByRole("row")[1]).getByRole("button", {
      name: "View Baytown Hyundai written OTD evidence",
    }));
    expect(await screen.findByText("Your written cash OTD is $40,315.")).toBeVisible();

    view.rerender(
      <QueryClientProvider client={client}>
        <VerifiedOffersComparison
          apiBaseUrl={apiBaseUrl}
          runs={canonicalRuns.map((run, index) => (
            index === 0 ? { ...run, updated_at: "2026-08-19T20:31:00Z" } : run
          ))}
        />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("$37,999.00")).toBeVisible();
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "claimed otd" }))
        .not.toBeInTheDocument();
    });
    expect(screen.queryByText("A different dealer message reused this evidence ID."))
      .not.toBeInTheDocument();
  });

  it("identifies an unresolved lowest-advertised listing without inventing OTD savings", async () => {
    const unresolvedLowest = {
      ...katyOffer,
      advertised_price: "36000",
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse({
      offers: [baytownOffer, unresolvedLowest],
      ranked_agent_run_ids: ["run-baytown"],
      recommendation: {
        ...canonicalComparison.recommendation,
        next_best_verified_otd: null,
        savings_vs_next_verified: null,
      },
      advertised_vs_verified: {
        lowest_advertised_agent_run_id: "run-katy",
        lowest_advertised_price: "36000",
        lowest_advertised_verified_otd: null,
        recommended_agent_run_id: "run-baytown",
        recommended_advertised_price: "37800",
        recommended_verified_otd: "40315",
        advertised_price_difference: "1800",
        verified_otd_savings: null,
      },
    }));

    renderComparison([canonicalRuns[0], canonicalRuns[2]]);

    const story = await screen.findByRole("group", { name: "Advertised versus verified" });
    expect(within(story).getByText("Lowest advertised listing")).toBeVisible();
    expect(within(story).getByText(/Katy Hyundai.*\$36,000.00/)).toBeVisible();
    expect(within(story).getByText("Best verified transaction cost")).toBeVisible();
    expect(within(story).getByText(/Baytown Hyundai.*\$40,315.00/)).toBeVisible();
    expect(within(story).queryByText(/saves/i)).not.toBeInTheDocument();
  });

  it("does not describe zero deltas as cheaper or savings", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse({
      ...canonicalComparison,
      advertised_vs_verified: {
        ...canonicalComparison.advertised_vs_verified,
        advertised_price_difference: "0",
        verified_otd_savings: "0",
      },
    }));

    renderComparison(canonicalRuns);

    expect(await screen.findByRole("heading", { name: "Best verified offer" })).toBeVisible();
    expect(screen.queryByText(/looked \$0\.00 cheaper/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/saves \$0\.00/i)).not.toBeInTheDocument();
  });

  it("does not invent a recommendation when no offer is eligible", async () => {
    const noVerifiedComparison = {
      offers: [
        {
          ...katyOffer,
          agent_run_id: "run-katy",
          dealer_name: "Katy Hyundai",
        },
        {
          ...katyOffer,
          agent_run_id: "run-houston",
          dealer_name: "Houston Hyundai",
          claimed_otd: null,
          comparison_status: "IN_PROGRESS",
          run_phase: "WAITING_FOR_EXTERNAL_RESPONSE",
          claimed_otd_evidence_ids: [],
        },
      ],
      ranked_agent_run_ids: [],
      recommendation: null,
      advertised_vs_verified: {
        lowest_advertised_agent_run_id: "run-houston",
        lowest_advertised_price: "37250",
        lowest_advertised_verified_otd: null,
        recommended_agent_run_id: null,
        recommended_advertised_price: null,
        recommended_verified_otd: null,
        advertised_price_difference: null,
        verified_otd_savings: null,
      },
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse(noVerifiedComparison));

    renderComparison(canonicalRuns.slice(1));

    expect(await screen.findByRole("heading", { name: "No verified offer yet" }))
      .toBeVisible();
    expect(screen.queryByRole("heading", { name: "Best verified offer" }))
      .not.toBeInTheDocument();
    expect(screen.queryByText(/recommended dealer/i)).not.toBeInTheDocument();
  });

  it("calls one eligible offer best verified while preserving the unresolved caveat", async () => {
    const oneVerifiedComparison = {
      offers: [baytownOffer, katyOffer],
      ranked_agent_run_ids: ["run-baytown"],
      recommendation: {
        recommended_agent_run_id: "run-baytown",
        recommended_dealer_id: "baytown",
        recommended_dealer_name: "Baytown Hyundai",
        recommended_otd: "40315",
        next_best_verified_otd: null,
        savings_vs_next_verified: null,
        has_unresolved_alternatives: true,
        explanation_facts: [
          "Baytown Hyundai is currently the only verified written offer at $40,315.00.",
          "No second verified offer is currently available.",
          "Katy Hyundai remains incomplete and is not yet rankable.",
        ],
      },
      advertised_vs_verified: {
        lowest_advertised_agent_run_id: "run-baytown",
        lowest_advertised_price: "37800",
        lowest_advertised_verified_otd: "40315",
        recommended_agent_run_id: "run-baytown",
        recommended_advertised_price: "37800",
        recommended_verified_otd: "40315",
        advertised_price_difference: "0",
        verified_otd_savings: "0",
      },
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse(oneVerifiedComparison));

    renderComparison([canonicalRuns[0], canonicalRuns[2]]);

    expect(await screen.findByRole("heading", { name: "Best verified offer" })).toBeVisible();
    expect(screen.getByText(
      "Baytown Hyundai is currently the only verified written offer at $40,315.00.",
    )).toBeVisible();
    expect(screen.getByText("No second verified offer is currently available."))
      .toBeVisible();
    expect(screen.getByText("Katy Hyundai remains incomplete and is not yet rankable."))
      .toBeVisible();
    expect(screen.queryByText(/\$0\.00 below the next verified offer/i))
      .not.toBeInTheDocument();
  });
});
