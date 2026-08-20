import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentWorkflow, type AgentRunSnapshot } from "./AgentWorkflow";
import type { OutreachCandidate, OutreachProposal } from "./OutreachApproval";

const apiBaseUrl = "http://api.test";

const candidate: OutreachCandidate = {
  id: "baytown-blue",
  vin: "KM8JCDD10SU000001",
  stock_number: "B1001",
  year: 2025,
  make: "Hyundai",
  model: "Tucson Hybrid",
  trim: "Limited",
  dealer_id: "baytown",
  dealer_name: "Baytown Hyundai",
};

const pendingProposal: OutreachProposal = {
  id: "proposal-1",
  action_type: "SEND_INITIAL_QUOTE_REQUEST",
  dealer_id: candidate.dealer_id,
  vehicle_id: candidate.id,
  recipient: "quotes@baytown.example.test",
  subject: "Written out-the-door quote request — 2025 Hyundai Tucson Hybrid Limited",
  body: "Hello Baytown Hyundai team,\n\nPlease provide a complete written quote.",
  reason: "Obtain a complete written out-the-door quote for this selected vehicle.",
  requested_information: [
    "vehicle_identity",
    "selling_price",
    "dealer_fees",
    "mandatory_addons",
    "government_charges",
    "out_the_door_total",
    "incentives_and_eligibility",
    "financing_requirement",
    "trade_in_requirement",
    "quote_expiration",
  ],
  requested_information_labels: [
    "Exact VIN and/or stock number for the quoted vehicle",
    "Selling price before taxes and fees",
    "All dealer and documentation fees",
    "All mandatory dealer-installed products and add-ons, with amounts",
    "Taxes, title, license, and other government charges",
    "Written out-the-door total",
    "Included incentives and rebates, with eligibility conditions",
    "Whether the quoted economics require dealer financing",
    "Whether the quoted economics require a trade-in",
    "Quote expiration or validity period, if applicable",
  ],
  requires_approval: true,
  status: "PENDING_APPROVAL",
  vehicle: candidate,
  created_at: "2026-08-19T20:00:00Z",
  approval: null,
  delivery: null,
};

const sentProposal: OutreachProposal = {
  ...pendingProposal,
  status: "SENT",
  approval: {
    decision: "APPROVED",
    decided_at: "2026-08-19T20:01:00Z",
    action_snapshot: {
      vehicle_id: pendingProposal.vehicle_id,
      dealer_id: pendingProposal.dealer_id,
      recipient: pendingProposal.recipient,
      subject: pendingProposal.subject,
      body: pendingProposal.body,
    },
  },
  delivery: {
    action_id: pendingProposal.id,
    provider: "fixture",
    external_message_id: "fixture-proposal-1",
    sent_at: "2026-08-19T20:01:01Z",
  },
};

const approvedUnconfirmedProposal: OutreachProposal = {
  ...sentProposal,
  status: "APPROVED",
  delivery: null,
};

const pendingFollowup: OutreachProposal = {
  ...pendingProposal,
  id: "followup-1",
  action_type: "SEND_FOLLOWUP",
  subject: "Written quote clarification",
  body: "Please confirm the written out-the-door total.",
  reason: "Resolve deterministic comparison gaps in the latest dealer response.",
  requested_information: ["claimed_otd"],
  requested_information_labels: ["Written out-the-door total"],
};

const approvedUnconfirmedFollowup: OutreachProposal = {
  ...pendingFollowup,
  status: "APPROVED",
  approval: {
    decision: "APPROVED",
    decided_at: "2026-08-19T20:06:00Z",
    action_snapshot: {
      vehicle_id: pendingFollowup.vehicle_id,
      dealer_id: pendingFollowup.dealer_id,
      recipient: pendingFollowup.recipient,
      subject: pendingFollowup.subject,
      body: pendingFollowup.body,
    },
  },
  delivery: null,
};

type AgentEvent = {
  id: string;
  run_id: string;
  event_type: string;
  phase: string;
  node: string;
  action_id: string | null;
  interaction_id: string | null;
  message_id: string | null;
  message: string;
  created_at: string;
  metadata: Record<string, unknown>;
};

type AgentRun = {
  run_id: string;
  thread_id: string;
  vehicle_id: string;
  phase: string;
  interaction_id: string | null;
  initial_action_id: string | null;
  current_action_id: string | null;
  last_message_id: string | null;
  created_at: string;
  updated_at: string;
  events: AgentEvent[];
};

function event(
  id: string,
  eventType: string,
  phase: string,
  message: string,
  overrides: Partial<AgentEvent> = {},
): AgentEvent {
  return {
    id,
    run_id: "run-1",
    event_type: eventType,
    phase,
    node: "route_next_phase",
    action_id: null,
    interaction_id: null,
    message_id: null,
    message,
    created_at: `2026-08-19T20:00:0${id.at(-1) ?? "0"}Z`,
    metadata: {},
    ...overrides,
  };
}

const waitingForApprovalRun: AgentRun = {
  run_id: "run-1",
  thread_id: "agent-run-run-1",
  vehicle_id: candidate.id,
  phase: "WAITING_FOR_APPROVAL",
  interaction_id: null,
  initial_action_id: pendingProposal.id,
  current_action_id: pendingProposal.id,
  last_message_id: null,
  created_at: "2026-08-19T20:00:00Z",
  updated_at: "2026-08-19T20:00:02Z",
  events: [
    event(
      "event-1",
      "RUN_STARTED",
      "STARTING",
      "Agent workflow started for the selected vehicle.",
    ),
    event(
      "event-2",
      "INITIAL_OUTREACH_PREPARED",
      "PREPARING_INITIAL_OUTREACH",
      "Quote request prepared for review.",
      { action_id: pendingProposal.id, node: "prepare_initial_outreach" },
    ),
    event(
      "event-3",
      "WAITING_FOR_APPROVAL",
      "WAITING_FOR_APPROVAL",
      "Waiting for explicit approval before sending.",
      { action_id: pendingProposal.id },
    ),
  ],
};

const waitingForResponseRun: AgentRun = {
  ...waitingForApprovalRun,
  phase: "WAITING_FOR_EXTERNAL_RESPONSE",
  interaction_id: "interaction-1",
  updated_at: "2026-08-19T20:01:02Z",
  events: [
    ...waitingForApprovalRun.events,
    event(
      "event-4",
      "OUTREACH_SENT",
      "OBSERVING_ACTION",
      "Quote request delivery was confirmed.",
      { action_id: pendingProposal.id, interaction_id: "interaction-1" },
    ),
    event(
      "event-5",
      "WAITING_FOR_EXTERNAL_RESPONSE",
      "WAITING_FOR_EXTERNAL_RESPONSE",
      "Waiting for a dealer response.",
      { interaction_id: "interaction-1" },
    ),
  ],
};

const deliveryUnconfirmedRun: AgentRun = {
  ...waitingForApprovalRun,
  phase: "DELIVERY_UNCONFIRMED",
  updated_at: "2026-08-19T20:01:02Z",
  events: [
    ...waitingForApprovalRun.events,
    event(
      "event-4",
      "DELIVERY_UNCONFIRMED",
      "DELIVERY_UNCONFIRMED",
      "Approval was recorded, but dealer-message delivery is unconfirmed.",
      { action_id: pendingProposal.id },
    ),
  ],
};

const completedRun: AgentRun = {
  ...waitingForResponseRun,
  phase: "INTERACTION_COMPLETE",
  last_message_id: "message-1",
  updated_at: "2026-08-19T20:05:00Z",
  events: [
    ...waitingForResponseRun.events,
    event(
      "event-6",
      "RESPONSE_ANALYZED",
      "OBSERVING_INTERACTION",
      "Dealer response analyzed against deterministic quote policy.",
      { interaction_id: "interaction-1", message_id: "message-1" },
    ),
    event(
      "event-7",
      "INTERACTION_COMPLETE",
      "INTERACTION_COMPLETE",
      "The dealer offer is comparable.",
      { interaction_id: "interaction-1", message_id: "message-1" },
    ),
  ],
};

const waitingForAnalysisRun: AgentRun = {
  ...waitingForResponseRun,
  phase: "WAITING_FOR_ANALYSIS",
  last_message_id: "message-1",
  updated_at: "2026-08-19T20:04:00Z",
  events: [
    ...waitingForResponseRun.events,
    event(
      "event-6",
      "WAITING_FOR_ANALYSIS",
      "WAITING_FOR_ANALYSIS",
      "A persisted dealer response is waiting for analysis.",
      { interaction_id: "interaction-1", message_id: "message-1" },
    ),
  ],
};

const waitingForFollowupApprovalRun: AgentRun = {
  ...waitingForResponseRun,
  phase: "WAITING_FOR_APPROVAL",
  current_action_id: pendingFollowup.id,
  last_message_id: "message-1",
  updated_at: "2026-08-19T20:05:00Z",
  events: [
    ...waitingForResponseRun.events,
    event(
      "event-6",
      "RESPONSE_ANALYZED",
      "WAITING_FOR_EXTERNAL_RESPONSE",
      "Dealer response analyzed against deterministic quote policy.",
      { interaction_id: "interaction-1", message_id: "message-1" },
    ),
    event(
      "event-7",
      "FOLLOWUP_PREPARED",
      "WAITING_FOR_APPROVAL",
      "Dealer follow-up prepared for review.",
      { action_id: pendingFollowup.id, interaction_id: "interaction-1" },
    ),
  ],
};

const completedWithStalePendingFollowupRun: AgentRun = {
  ...completedRun,
  current_action_id: pendingFollowup.id,
  last_message_id: "message-2",
  events: [
    ...waitingForFollowupApprovalRun.events,
    event(
      "event-8",
      "RESPONSE_ANALYZED",
      "OBSERVING_INTERACTION",
      "A newer dealer response was analyzed against deterministic quote policy.",
      { interaction_id: "interaction-1", message_id: "message-2" },
    ),
    event(
      "event-9",
      "INTERACTION_COMPLETE",
      "INTERACTION_COMPLETE",
      "The newer dealer offer is comparable.",
      { interaction_id: "interaction-1", message_id: "message-2" },
    ),
  ],
};

const deliveryUnconfirmedFollowupRun: AgentRun = {
  ...waitingForFollowupApprovalRun,
  phase: "DELIVERY_UNCONFIRMED",
  updated_at: "2026-08-19T20:06:01Z",
  events: [
    ...waitingForFollowupApprovalRun.events,
    event(
      "event-8",
      "DELIVERY_UNCONFIRMED",
      "DELIVERY_UNCONFIRMED",
      "Follow-up approval was recorded, but dealer-message delivery is unconfirmed.",
      { action_id: pendingFollowup.id, interaction_id: "interaction-1" },
    ),
  ],
};

const awaitingResponseInteraction = {
  id: "interaction-1",
  initial_action_id: sentProposal.id,
  dealer_id: candidate.dealer_id,
  vehicle_id: candidate.id,
  vehicle: candidate,
  created_at: "2026-08-19T20:01:01Z",
  analysis_status: "AWAITING_RESPONSE",
  analysis_error_code: null,
  followups: [],
  sent_followup_count: 0,
  followup_limit: 2,
  followup_limit_reached: false,
  latest_response_followup_status: null,
  messages: [],
  analysis: null,
};

const responseAnalysisInProgressInteraction = {
  ...awaitingResponseInteraction,
  analysis_status: "ANALYSIS_IN_PROGRESS",
  messages: [{
    id: "message-1",
    dealer_id: candidate.dealer_id,
    vehicle_id: candidate.id,
    direction: "INBOUND",
    subject: "Dealer quote response",
    body: "The written quote is attached for review.",
    received_at: "2026-08-19T20:03:00Z",
    source_provider: "fixture",
  }],
};

const followupApprovalInteraction = {
  ...responseAnalysisInProgressInteraction,
  analysis_status: "ANALYZED",
  followups: [pendingFollowup],
  latest_response_followup_status: "PENDING_APPROVAL",
};

const comparableLatestMessage = {
  id: "message-2",
  dealer_id: candidate.dealer_id,
  vehicle_id: candidate.id,
  direction: "INBOUND",
  subject: "Complete written quote",
  body: "For VIN KM8JCDD10SU000001, the selling price is $37,950 and cash OTD is $40,315.",
  received_at: "2026-08-19T20:07:00Z",
  source_provider: "fixture",
};

const comparableAfterStalePendingInteraction = {
  ...followupApprovalInteraction,
  followups: [pendingFollowup],
  latest_response_followup_status: null,
  messages: [
    ...responseAnalysisInProgressInteraction.messages,
    comparableLatestMessage,
  ],
  analysis: {
    message: comparableLatestMessage,
    extraction: {
      vehicle_vin: "KM8JCDD10SU000001",
      stock_number: null,
      selling_price: "37950",
      claimed_otd: "40315",
      dealer_fees: [],
      government_fees: [],
      addons: [],
      incentives: [],
      financing_required: false,
      trade_required: false,
      expiration: null,
      explicit_no_addons_statement: true,
      explicit_all_fees_included_statement: true,
      unresolved_questions: [],
      evidence_ids: ["ev-selling-price", "ev-claimed-otd"],
      extraction_confidence: 0.99,
    },
    evidence: [
      {
        id: "ev-selling-price",
        source_type: "DEALER_EMAIL",
        source_id: comparableLatestMessage.id,
        field_name: "selling_price",
        excerpt: "the selling price is $37,950",
        created_at: comparableLatestMessage.received_at,
      },
      {
        id: "ev-claimed-otd",
        source_type: "DEALER_EMAIL",
        source_id: comparableLatestMessage.id,
        field_name: "claimed_otd",
        excerpt: "cash OTD is $40,315",
        created_at: comparableLatestMessage.received_at,
      },
    ],
    assessment: {
      comparable: true,
      transparent: true,
      reconciled: true,
      missing_for_comparison: [],
      missing_for_transparency: [],
      reconciliation_difference: "0",
    },
  },
};

const deliveryUnconfirmedFollowupInteraction = {
  ...comparableAfterStalePendingInteraction,
  followups: [approvedUnconfirmedFollowup],
  latest_response_followup_status: "APPROVED",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderWorkflow(onRunChange?: (run: AgentRunSnapshot) => void) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AgentWorkflow
        apiBaseUrl={apiBaseUrl}
        candidate={candidate}
        onRunChange={onRunChange}
      />
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

describe("AgentWorkflow", () => {
  it("reports the stable run identity and phase to its parent after creation", async () => {
    const onRunChange = vi.fn();
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(waitingForApprovalRun, 201));

    renderWorkflow(onRunChange);
    fireEvent.click(screen.getByRole("button", { name: "Start agent workflow" }));

    expect(await screen.findByText("Waiting for your approval")).toBeVisible();
    expect(onRunChange).toHaveBeenCalledTimes(1);
    expect(onRunChange).toHaveBeenLastCalledWith({
      run_id: waitingForApprovalRun.run_id,
      vehicle_id: waitingForApprovalRun.vehicle_id,
      phase: waitingForApprovalRun.phase,
      updated_at: waitingForApprovalRun.updated_at,
    });
    expect(callsTo(fetchMock, `${apiBaseUrl}/agent-runs`, "POST")).toHaveLength(1);
  });

  it("reports an explicitly recovered run without recreating the workflow", async () => {
    const onRunChange = vi.fn();
    const runId = waitingForApprovalRun.run_id;
    let inspectionAttempts = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === `${apiBaseUrl}/agent-runs` && init?.method === "POST") {
        return jsonResponse({
          detail: {
            code: "agent_run_advancement_failed",
            message: "The workflow exists but its first inspection failed.",
            run_id: runId,
          },
        }, 500);
      }
      if (input === `${apiBaseUrl}/agent-runs/${runId}` && init?.method === undefined) {
        inspectionAttempts += 1;
        return inspectionAttempts === 1
          ? jsonResponse({ detail: { message: "Inspection is temporarily unavailable." } }, 503)
          : jsonResponse(waitingForApprovalRun);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });

    renderWorkflow(onRunChange);
    fireEvent.click(screen.getByRole("button", { name: "Start agent workflow" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Recover existing workflow",
    }));

    expect(await screen.findByText("Waiting for your approval")).toBeVisible();
    expect(onRunChange).toHaveBeenCalledTimes(1);
    expect(onRunChange).toHaveBeenLastCalledWith({
      run_id: waitingForApprovalRun.run_id,
      vehicle_id: waitingForApprovalRun.vehicle_id,
      phase: waitingForApprovalRun.phase,
      updated_at: waitingForApprovalRun.updated_at,
    });
    expect(callsTo(fetchMock, `${apiBaseUrl}/agent-runs`, "POST")).toHaveLength(1);
    expect(callsTo(fetchMock, `${apiBaseUrl}/agent-runs/${runId}`)).toHaveLength(2);
  });

  it("reports the newer authoritative phase after resuming the same run", async () => {
    const onRunChange = vi.fn();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === `${apiBaseUrl}/agent-runs` && init?.method === "POST") {
        return jsonResponse(waitingForResponseRun, 201);
      }
      if (
        input === `${apiBaseUrl}/agent-runs/${waitingForResponseRun.run_id}/resume`
        && init?.method === "POST"
      ) {
        return jsonResponse(completedRun);
      }
      if (input === `${apiBaseUrl}/outreach/proposals/${sentProposal.id}`) {
        return jsonResponse(sentProposal);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });

    renderWorkflow(onRunChange);
    fireEvent.click(screen.getByRole("button", { name: "Start agent workflow" }));
    expect(await screen.findByText("Waiting for dealer response")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Resume from latest state" }));

    expect(await screen.findByText("Offer is comparable")).toBeVisible();
    expect(onRunChange).toHaveBeenCalledTimes(2);
    expect(onRunChange).toHaveBeenNthCalledWith(1, {
      run_id: waitingForResponseRun.run_id,
      vehicle_id: waitingForResponseRun.vehicle_id,
      phase: waitingForResponseRun.phase,
      updated_at: waitingForResponseRun.updated_at,
    });
    expect(onRunChange).toHaveBeenNthCalledWith(2, {
      run_id: completedRun.run_id,
      vehicle_id: completedRun.vehicle_id,
      phase: completedRun.phase,
      updated_at: completedRun.updated_at,
    });
    expect(callsTo(fetchMock, `${apiBaseUrl}/agent-runs`, "POST")).toHaveLength(1);
  });

  it("creates a run, shows its authoritative wait and activity, and reviews the existing action", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(waitingForApprovalRun, 201))
      .mockResolvedValueOnce(jsonResponse(pendingProposal));

    renderWorkflow();
    fireEvent.click(screen.getByRole("button", { name: "Start agent workflow" }));

    expect(await screen.findByText("Waiting for your approval")).toBeVisible();
    const activity = screen.getByRole("list", { name: "Agent activity" });
    expect(within(activity).getByText("Agent workflow started for the selected vehicle."))
      .toBeVisible();
    expect(within(activity).getByText("Quote request prepared for review.")).toBeVisible();
    expect(within(activity).getByText("Waiting for explicit approval before sending."))
      .toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Review approval" }));
    const dialog = await screen.findByRole("dialog", { name: "Review dealer quote request" });
    expect(within(dialog).getByText(pendingProposal.subject)).toBeVisible();
    expect(within(dialog).getByText((_, element) => (
      element?.tagName === "PRE" && element.textContent === pendingProposal.body
    ))).toBeVisible();

    expect(fetchMock).toHaveBeenNthCalledWith(1, `${apiBaseUrl}/agent-runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vehicle_id: candidate.id }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `${apiBaseUrl}/outreach/proposals/${pendingProposal.id}`,
    );
    expect(callsTo(fetchMock, `${apiBaseUrl}/outreach/proposals`, "POST")).toHaveLength(0);
  });

  it("adopts the durable run exposed by a recoverable create failure", async () => {
    const runId = waitingForApprovalRun.run_id;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === `${apiBaseUrl}/agent-runs` && init?.method === "POST") {
        return jsonResponse({
          detail: {
            code: "agent_run_advancement_failed",
            message: (
              "The workflow was created but could not finish advancing. "
              + "Inspect or resume the existing workflow."
            ),
            run_id: runId,
          },
        }, 500);
      }
      if (input === `${apiBaseUrl}/agent-runs/${runId}` && init?.method === undefined) {
        return jsonResponse(waitingForApprovalRun);
      }
      if (
        input === `${apiBaseUrl}/agent-runs/${runId}/resume`
        && init?.method === "POST"
      ) {
        return jsonResponse(waitingForApprovalRun);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });

    renderWorkflow();
    fireEvent.click(screen.getByRole("button", { name: "Start agent workflow" }));

    expect(await screen.findByText("Waiting for your approval")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Start agent workflow" }))
      .not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(callsTo(fetchMock, `${apiBaseUrl}/agent-runs`, "POST")).toHaveLength(1);
    expect(callsTo(fetchMock, `${apiBaseUrl}/agent-runs/${runId}`)).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Resume from latest state" }));

    await waitFor(() => {
      expect(callsTo(
        fetchMock,
        `${apiBaseUrl}/agent-runs/${runId}/resume`,
        "POST",
      )).toHaveLength(1);
    });
    expect(callsTo(fetchMock, `${apiBaseUrl}/agent-runs`, "POST")).toHaveLength(1);
    expect(callsTo(fetchMock, `${apiBaseUrl}/outreach/proposals`, "POST")).toHaveLength(0);
  });

  it("keeps recovery available without replaying create when initial inspection fails", async () => {
    const runId = waitingForApprovalRun.run_id;
    let inspectionAttempts = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === `${apiBaseUrl}/agent-runs` && init?.method === "POST") {
        return jsonResponse({
          detail: {
            code: "agent_run_advancement_failed",
            message: (
              "The workflow was created but could not finish advancing. "
              + "Inspect or resume the existing workflow."
            ),
            run_id: runId,
          },
        }, 500);
      }
      if (input === `${apiBaseUrl}/agent-runs/${runId}` && init?.method === undefined) {
        inspectionAttempts += 1;
        return inspectionAttempts === 1
          ? jsonResponse({ detail: { message: "Workflow inspection is temporarily unavailable." } }, 503)
          : jsonResponse(waitingForApprovalRun);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });

    renderWorkflow();
    fireEvent.click(screen.getByRole("button", { name: "Start agent workflow" }));

    const recoverButton = await screen.findByRole("button", {
      name: "Recover existing workflow",
    });
    expect(screen.queryByRole("button", { name: "Start agent workflow" }))
      .not.toBeInTheDocument();
    expect(callsTo(fetchMock, `${apiBaseUrl}/agent-runs`, "POST")).toHaveLength(1);
    expect(callsTo(fetchMock, `${apiBaseUrl}/agent-runs/${runId}`)).toHaveLength(1);

    fireEvent.click(recoverButton);

    expect(await screen.findByText("Waiting for your approval")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Start agent workflow" }))
      .not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(callsTo(fetchMock, `${apiBaseUrl}/agent-runs`, "POST")).toHaveLength(1);
    expect(callsTo(fetchMock, `${apiBaseUrl}/agent-runs/${runId}`)).toHaveLength(2);
  });

  it("uses the existing approval endpoint before resuming the durable run", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(waitingForApprovalRun, 201))
      .mockResolvedValueOnce(jsonResponse(pendingProposal))
      .mockResolvedValueOnce(jsonResponse(sentProposal))
      .mockResolvedValueOnce(jsonResponse(waitingForResponseRun));

    renderWorkflow();
    fireEvent.click(screen.getByRole("button", { name: "Start agent workflow" }));
    expect(await screen.findByText("Waiting for your approval")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Review approval" }));
    const dialog = await screen.findByRole("dialog", { name: "Review dealer quote request" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve & send" }));

    expect(await screen.findByText("Waiting for dealer response")).toBeVisible();
    expect(screen.getByText("Quote request delivery was confirmed.")).toBeVisible();
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      `${apiBaseUrl}/outreach/proposals/${pendingProposal.id}/approve`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      `${apiBaseUrl}/agent-runs/${waitingForApprovalRun.run_id}/resume`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      },
    );
    expect(callsTo(fetchMock, `${apiBaseUrl}/outreach/proposals`, "POST")).toHaveLength(0);
  });

  it("loads a graph-prepared follow-up without invoking manual preparation", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(waitingForFollowupApprovalRun, 201))
      .mockResolvedValueOnce(jsonResponse(sentProposal))
      .mockResolvedValueOnce(jsonResponse(pendingFollowup))
      .mockResolvedValueOnce(jsonResponse(followupApprovalInteraction));

    renderWorkflow();
    fireEvent.click(screen.getByRole("button", { name: "Start agent workflow" }));
    expect(await screen.findByText("Waiting for your approval")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Review approval" }));

    const dialog = await screen.findByRole("dialog", { name: "Review dealer follow-up" });
    expect(within(dialog).getByText(pendingFollowup.subject)).toBeVisible();
    expect(within(dialog).queryByRole("button", { name: "Prepare follow-up" }))
      .not.toBeInTheDocument();
    expect(callsTo(
      fetchMock,
      `${apiBaseUrl}/outreach/proposals/${pendingProposal.id}/followups`,
      "POST",
    )).toHaveLength(0);
  });

  it("resumes only on an explicit action and never polls while waiting", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === `${apiBaseUrl}/agent-runs` && init?.method === "POST") {
        return jsonResponse(waitingForResponseRun, 201);
      }
      if (
        input === `${apiBaseUrl}/agent-runs/${waitingForResponseRun.run_id}/resume`
        && init?.method === "POST"
      ) {
        return jsonResponse(completedRun);
      }
      if (input === `${apiBaseUrl}/outreach/proposals/${sentProposal.id}`) {
        return jsonResponse(sentProposal);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });

    renderWorkflow();
    fireEvent.click(screen.getByRole("button", { name: "Start agent workflow" }));

    expect(await screen.findByText("Waiting for dealer response")).toBeVisible();
    await Promise.resolve();
    expect(callsTo(
      fetchMock,
      `${apiBaseUrl}/agent-runs/${waitingForResponseRun.run_id}/resume`,
      "POST",
    )).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Resume from latest state" }));

    expect(await screen.findByText("Offer is comparable")).toBeVisible();
    expect(screen.getByText("The dealer offer is comparable.")).toBeVisible();
    expect(callsTo(
      fetchMock,
      `${apiBaseUrl}/agent-runs/${waitingForResponseRun.run_id}/resume`,
      "POST",
    )).toHaveLength(1);
  });

  it("keeps comparable interaction evidence visible without approving a stale pending follow-up", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === `${apiBaseUrl}/agent-runs` && init?.method === "POST") {
        return jsonResponse(waitingForFollowupApprovalRun, 201);
      }
      if (
        input === `${apiBaseUrl}/agent-runs/${waitingForFollowupApprovalRun.run_id}/resume`
        && init?.method === "POST"
      ) {
        return jsonResponse(completedWithStalePendingFollowupRun);
      }
      if (input === `${apiBaseUrl}/outreach/proposals/${sentProposal.id}`) {
        return jsonResponse(sentProposal);
      }
      if (input === `${apiBaseUrl}/outreach/proposals/${pendingFollowup.id}`) {
        return jsonResponse(pendingFollowup);
      }
      if (input === `${apiBaseUrl}/outreach/proposals/${sentProposal.id}/interaction`) {
        return jsonResponse(comparableAfterStalePendingInteraction);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });

    renderWorkflow();
    fireEvent.click(screen.getByRole("button", { name: "Start agent workflow" }));
    expect(await screen.findByText("Waiting for your approval")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Resume from latest state" }));
    expect(await screen.findByText("Offer is comparable")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "View dealer interaction" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Dealer-stated quote facts")).toBeVisible();
    const claimedOtdFact = within(dialog).getByText("Claimed out-the-door").closest(".fact");
    expect(claimedOtdFact).not.toBeNull();
    fireEvent.click(within(claimedOtdFact as HTMLElement).getByRole(
      "button",
      { name: "View evidence" },
    ));
    const evidence = await screen.findByRole("dialog", { name: "claimed otd" });
    expect(within(evidence).getByText("cash OTD is $40,315")).toBeVisible();

    expect(within(dialog).queryByRole("button", { name: "Approve & send" }))
      .not.toBeInTheDocument();
    expect(callsTo(
      fetchMock,
      `${apiBaseUrl}/outreach/proposals/${pendingFollowup.id}/approve`,
      "POST",
    )).toHaveLength(0);
  });

  it("persists the demo response through its existing endpoint before resuming", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(waitingForResponseRun, 201))
      .mockResolvedValueOnce(jsonResponse(sentProposal))
      .mockResolvedValueOnce(jsonResponse(awaitingResponseInteraction))
      .mockResolvedValueOnce(jsonResponse(responseAnalysisInProgressInteraction))
      .mockResolvedValueOnce(jsonResponse(waitingForAnalysisRun));

    renderWorkflow();
    fireEvent.click(screen.getByRole("button", { name: "Start agent workflow" }));
    expect(await screen.findByText("Waiting for dealer response")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "View dealer interaction" }));
    const dialog = await screen.findByRole("dialog", { name: "Review dealer quote request" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Release dealer response" }));

    expect(await screen.findByText("Waiting for response analysis")).toBeVisible();
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      `${apiBaseUrl}/outreach/proposals/${sentProposal.id}/demo-response`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      `${apiBaseUrl}/agent-runs/${waitingForResponseRun.run_id}/resume`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      },
    );
  });

  it("shows approved but unconfirmed delivery as blocked without retrying or advancing", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(waitingForApprovalRun, 201))
      .mockResolvedValueOnce(jsonResponse(pendingProposal))
      .mockResolvedValueOnce(jsonResponse(approvedUnconfirmedProposal))
      .mockResolvedValueOnce(jsonResponse(deliveryUnconfirmedRun));

    renderWorkflow();
    fireEvent.click(screen.getByRole("button", { name: "Start agent workflow" }));
    expect(await screen.findByText("Waiting for your approval")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Review approval" }));
    const dialog = await screen.findByRole("dialog", { name: "Review dealer quote request" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve & send" }));

    const workflowState = (await screen.findByText("Review before taking another action."))
      .closest("[role='status']");
    expect(workflowState).not.toBeNull();
    expect(within(workflowState as HTMLElement).getByText("Delivery unconfirmed")).toBeVisible();
    expect(screen.queryByText("Waiting for dealer response")).not.toBeInTheDocument();
    expect(within(dialog).getByText("Delivery has not been confirmed.")).toBeVisible();
    expect(within(dialog).queryByRole("button", { name: "Release dealer response" }))
      .not.toBeInTheDocument();
    await waitFor(() => {
      expect(callsTo(
        fetchMock,
        `${apiBaseUrl}/outreach/proposals/${pendingProposal.id}/approve`,
        "POST",
      )).toHaveLength(1);
    });
    expect(callsTo(fetchMock, `${apiBaseUrl}/outreach/proposals`, "POST")).toHaveLength(0);
  });

  it("exposes an unconfirmed follow-up read-only with its ambiguous delivery status", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(deliveryUnconfirmedFollowupRun, 201))
      .mockResolvedValueOnce(jsonResponse(sentProposal))
      .mockResolvedValueOnce(jsonResponse(approvedUnconfirmedFollowup))
      .mockResolvedValueOnce(jsonResponse(deliveryUnconfirmedFollowupInteraction));

    renderWorkflow();
    fireEvent.click(screen.getByRole("button", { name: "Start agent workflow" }));

    const workflowState = (await screen.findByText("Review before taking another action."))
      .closest("[role='status']");
    expect(workflowState).not.toBeNull();
    expect(within(workflowState as HTMLElement).getByText("Delivery unconfirmed")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "View dealer interaction" }));
    const dialog = await screen.findByRole("dialog", { name: "Review dealer follow-up" });
    expect(within(dialog).getByText("Delivery has not been confirmed.")).toBeVisible();
    expect(within(dialog).getByText("Dealer-stated quote facts")).toBeVisible();
    expect(within(dialog).queryByRole("button", { name: "Approve & send" }))
      .not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Reject follow-up" }))
      .not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Release dealer response" }))
      .not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume from latest state" }))
      .not.toBeInTheDocument();
    expect(callsTo(
      fetchMock,
      `${apiBaseUrl}/outreach/proposals/${pendingFollowup.id}/approve`,
      "POST",
    )).toHaveLength(0);
  });

  it("renders only the user-safe event message and not arbitrary metadata", async () => {
    const unsafeReasoning = "Secret hidden chain of thought that must never be displayed.";
    const unsafePrompt = "Internal model prompt that must never be displayed.";
    const unsafeDealerBody = "Raw dealer message content that does not belong in activity.";
    const safeRun: AgentRun = {
      ...deliveryUnconfirmedRun,
      initial_action_id: null,
      current_action_id: null,
      events: [
        event(
          "event-1",
          "DELIVERY_UNCONFIRMED",
          "DELIVERY_UNCONFIRMED",
          "Delivery could not be confirmed; the workflow stopped safely.",
          {
            metadata: {
              reason_code: "delivery_unconfirmed",
              chain_of_thought: unsafeReasoning,
              model_prompt: unsafePrompt,
              raw_dealer_message: unsafeDealerBody,
            },
          },
        ),
      ],
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse(safeRun, 201));

    renderWorkflow();
    fireEvent.click(screen.getByRole("button", { name: "Start agent workflow" }));

    const activity = await screen.findByRole("list", { name: "Agent activity" });
    expect(within(activity).getByText(
      "Delivery could not be confirmed; the workflow stopped safely.",
    )).toBeVisible();
    expect(screen.queryByText(unsafeReasoning)).not.toBeInTheDocument();
    expect(screen.queryByText(unsafePrompt)).not.toBeInTheDocument();
    expect(screen.queryByText(unsafeDealerBody)).not.toBeInTheDocument();
  });
});
