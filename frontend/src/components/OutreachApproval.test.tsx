import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OutreachApproval, type OutreachCandidate, type OutreachProposal } from "./OutreachApproval";

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
  dealer_id: "baytown",
  vehicle_id: "baytown-blue",
  recipient: "quotes@baytown.example.test",
  subject: "Written out-the-door quote request — 2025 Hyundai Tucson Hybrid Limited",
  body: "Hello Baytown Hyundai team,\n\nPlease provide a complete written quote.",
  reason: "Obtain a complete written out-the-door quote for this shortlisted vehicle.",
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
  requires_approval: true,
  status: "PENDING_APPROVAL",
  vehicle: candidate,
  approval: null,
  delivery: null,
};

const sentProposal: OutreachProposal = {
  ...pendingProposal,
  status: "SENT",
  approval: {
    decision: "APPROVED",
    decided_at: "2026-08-19T20:00:00Z",
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
    sent_at: "2026-08-19T20:00:01Z",
  },
};

const inboundMessage = {
  id: "interaction-1-message-1",
  dealer_id: "baytown",
  vehicle_id: "baytown-blue",
  direction: "INBOUND",
  subject: "No-add-on itemized quote",
  body: [
    "For VIN KM8JCDD10SU000001, the selling price is $37,950.",
    "We have no dealer-installed products or add-ons.",
    "The required documentation fee is $225, and tax, title, and license total $2,140.",
    "Your written cash OTD is $40,315.",
    "No dealer financing or trade-in is required.",
  ].join("\n"),
  received_at: "2026-08-19T14:40:00Z",
  source_provider: "fixture",
};

function dealerEvidence(id: string, fieldName: string, excerpt: string) {
  return {
    id,
    source_type: "DEALER_EMAIL",
    source_id: inboundMessage.id,
    field_name: fieldName,
    excerpt,
    created_at: inboundMessage.received_at,
  };
}

const connectedInteraction = {
  id: "interaction-1",
  initial_action_id: sentProposal.id,
  dealer_id: sentProposal.dealer_id,
  vehicle_id: sentProposal.vehicle_id,
  vehicle: sentProposal.vehicle,
  created_at: "2026-08-19T20:00:01Z",
  analysis_status: "ANALYZED",
  analysis_error_code: null,
  messages: [inboundMessage],
  analysis: {
    message: inboundMessage,
    extraction: {
      vehicle_vin: "KM8JCDD10SU000001",
      stock_number: null,
      selling_price: "37950",
      claimed_otd: "40315",
      dealer_fees: [{
        name: "Documentation fee",
        amount: "225",
        stated_mandatory: true,
        evidence_id: "ev-doc-fee",
      }],
      government_fees: [{
        name: "Tax, title, and license",
        amount: "2140",
        stated_mandatory: true,
        evidence_id: "ev-government-fees",
      }],
      addons: [],
      incentives: [],
      financing_required: false,
      trade_required: false,
      expiration: null,
      explicit_no_addons_statement: true,
      explicit_all_fees_included_statement: false,
      unresolved_questions: [],
      evidence_ids: [
        "ev-vin",
        "ev-selling-price",
        "ev-claimed-otd",
        "ev-doc-fee",
        "ev-government-fees",
        "ev-no-addons",
        "ev-financing",
        "ev-trade",
      ],
      extraction_confidence: 0.99,
    },
    evidence: [
      dealerEvidence(
        "ev-vin",
        "vehicle_vin",
        "For VIN KM8JCDD10SU000001, the selling price is $37,950.",
      ),
      dealerEvidence(
        "ev-selling-price",
        "selling_price",
        "For VIN KM8JCDD10SU000001, the selling price is $37,950.",
      ),
      dealerEvidence("ev-claimed-otd", "claimed_otd", "Your written cash OTD is $40,315."),
      dealerEvidence("ev-doc-fee", "dealer_fees", "The required documentation fee is $225"),
      dealerEvidence("ev-government-fees", "government_fees", "tax, title, and license total $2,140"),
      dealerEvidence("ev-no-addons", "explicit_no_addons_statement", "We have no dealer-installed products or add-ons."),
      dealerEvidence("ev-financing", "financing_required", "No dealer financing or trade-in is required."),
      dealerEvidence("ev-trade", "trade_required", "No dealer financing or trade-in is required."),
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

const failedInteraction = {
  ...connectedInteraction,
  analysis_status: "ANALYSIS_FAILED",
  analysis_error_code: "invalid_quote_evidence",
  analysis: null,
};

const inProgressInteraction = {
  ...connectedInteraction,
  analysis_status: "ANALYSIS_IN_PROGRESS",
  analysis_error_code: null,
  analysis: null,
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  document.getElementById("root")?.remove();
});

describe("OutreachApproval", () => {
  it("shows the exact recipient, vehicle, subject, body, and friendly checklist before approval", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(pendingProposal, 201))
      .mockResolvedValueOnce(jsonResponse(sentProposal));

    render(<OutreachApproval apiBaseUrl="http://api.test" candidate={candidate} />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare quote request" }));

    const dialog = await screen.findByRole("dialog", { name: "Review dealer quote request" });
    expect(within(dialog).getByText("quotes@baytown.example.test")).toBeVisible();
    expect(within(dialog).getByText("2025 Hyundai Tucson Hybrid Limited")).toBeVisible();
    expect(within(dialog).getByText("VIN KM8JCDD10SU000001 · Stock B1001")).toBeVisible();
    expect(within(dialog).getByText(pendingProposal.subject)).toBeVisible();
    expect(within(dialog).getByText((_, element) => (
      element?.tagName === "PRE" && element.textContent === pendingProposal.body
    ))).toBeVisible();
    expect(within(dialog).getByText("Exact VIN and/or stock number for the quoted vehicle")).toBeVisible();
    expect(within(dialog).getByText("Written out-the-door total")).toBeVisible();
    expect(within(dialog).getByText("Sending requires your explicit approval.")).toBeVisible();
    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://api.test/outreach/proposals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vehicle_id: candidate.id }),
    });

    fireEvent.click(within(dialog).getByRole("button", { name: "Approve & send" }));

    expect(await within(dialog).findByText("Sent through the fixture provider")).toBeVisible();
    expect(within(dialog).getByText("fixture-proposal-1")).toBeVisible();
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://api.test/outreach/proposals/proposal-1/approve",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      },
    );
  });

  it("persists rejection in the visible review without sending", async () => {
    const rejectedProposal: OutreachProposal = {
      ...pendingProposal,
      status: "REJECTED",
      approval: {
        decision: "REJECTED",
        decided_at: "2026-08-19T20:00:00Z",
        action_snapshot: {
          vehicle_id: pendingProposal.vehicle_id,
          dealer_id: pendingProposal.dealer_id,
          recipient: pendingProposal.recipient,
          subject: pendingProposal.subject,
          body: pendingProposal.body,
        },
      },
    };
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(pendingProposal, 201))
      .mockResolvedValueOnce(jsonResponse(rejectedProposal));

    render(<OutreachApproval apiBaseUrl="http://api.test" candidate={candidate} />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare quote request" }));
    const dialog = await screen.findByRole("dialog", { name: "Review dealer quote request" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Reject request" }));

    expect(await within(dialog).findByText("Request rejected")).toBeVisible();
    expect(within(dialog).queryByText("Sent through the fixture provider")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("reloads and displays persisted SEND_FAILED state without claiming success", async () => {
    const failedProposal: OutreachProposal = {
      ...sentProposal,
      status: "SEND_FAILED",
      delivery: null,
    };
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(pendingProposal, 201))
      .mockResolvedValueOnce(jsonResponse({
        detail: {
          code: "outreach_send_failed",
          message: "The approved dealer message could not be sent.",
        },
      }, 502))
      .mockResolvedValueOnce(jsonResponse(failedProposal));

    render(<OutreachApproval apiBaseUrl="http://api.test" candidate={candidate} />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare quote request" }));
    const dialog = await screen.findByRole("dialog", { name: "Review dealer quote request" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve & send" }));

    expect(await within(dialog).findByText("Delivery failed")).toBeVisible();
    expect(within(dialog).getByText("The approved dealer message could not be sent.")).toBeVisible();
    expect(within(dialog).queryByText("Sent through the fixture provider")).not.toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "http://api.test/outreach/proposals/proposal-1",
    );
  });

  it("reconciles a lost approval response from persisted state", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(pendingProposal, 201))
      .mockRejectedValueOnce(new TypeError("connection closed after send"))
      .mockResolvedValueOnce(jsonResponse(sentProposal));

    render(<OutreachApproval apiBaseUrl="http://api.test" candidate={candidate} />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare quote request" }));
    const dialog = await screen.findByRole("dialog", { name: "Review dealer quote request" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve & send" }));

    expect(await within(dialog).findByText("Sent through the fixture provider")).toBeVisible();
    expect(within(dialog).queryByRole("button", { name: "Approve & send" })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "http://api.test/outreach/proposals/proposal-1",
    );
  });

  it("releases a confirmed SENT response and shows one connected evidence-backed lifecycle", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(pendingProposal, 201))
      .mockResolvedValueOnce(jsonResponse(sentProposal))
      .mockResolvedValueOnce(jsonResponse(connectedInteraction));

    render(<OutreachApproval apiBaseUrl="http://api.test" candidate={candidate} />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare quote request" }));
    const dialog = await screen.findByRole("dialog", { name: "Review dealer quote request" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve & send" }));

    expect(await within(dialog).findByText("Sent through the fixture provider")).toBeVisible();
    fireEvent.click(within(dialog).getByRole("button", { name: "Release dealer response" }));

    expect(await within(dialog).findByText("Dealer response received")).toBeVisible();
    expect(within(dialog).getByText("Dealer response analyzed")).toBeVisible();
    expect(within(dialog).getByText((_, element) => (
      element?.tagName === "PRE" && element.textContent === inboundMessage.body
    ))).toBeVisible();
    expect(within(dialog).getByRole("heading", { name: "Is this quote usable?" })).toBeVisible();
    expect(within(dialog).getByText("No comparison-policy gaps.")).toBeVisible();
    expect(within(dialog).getByText("No transparency-policy gaps.")).toBeVisible();
    expect(within(dialog).getByText("No source-grounded uncertainty extracted.")).toBeVisible();

    const claimedOtdFact = within(dialog).getByText("Claimed out-the-door").closest(".fact");
    expect(claimedOtdFact).not.toBeNull();
    fireEvent.click(within(claimedOtdFact as HTMLElement).getByRole("button", { name: "View evidence" }));
    const evidenceDrawer = await screen.findByRole("dialog", { name: "claimed otd" });
    expect(within(evidenceDrawer).getByText("Your written cash OTD is $40,315.")).toBeVisible();
    fireEvent.keyDown(evidenceDrawer, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "claimed otd" }))
      .not.toBeInTheDocument());
    expect(dialog).toBeVisible();

    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "http://api.test/outreach/proposals/proposal-1/demo-response",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it.each([
    ["PENDING_APPROVAL", pendingProposal],
    ["REJECTED", { ...pendingProposal, status: "REJECTED" }],
    ["APPROVED without confirmed delivery", { ...sentProposal, status: "APPROVED", delivery: null }],
    ["SEND_FAILED", { ...sentProposal, status: "SEND_FAILED", delivery: null }],
  ])("does not expose response release for %s", async (_, proposal) => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(proposal, 201));

    render(<OutreachApproval apiBaseUrl="http://api.test" candidate={candidate} />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare quote request" }));
    const dialog = await screen.findByRole("dialog", { name: "Review dealer quote request" });

    expect(within(dialog).queryByRole("button", { name: "Release dealer response" })).not.toBeInTheDocument();
    expect(within(dialog).queryByText("Dealer response received")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("Dealer response analyzed")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("reconciles a lost release response to the idempotent persisted result", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(pendingProposal, 201))
      .mockResolvedValueOnce(jsonResponse(sentProposal))
      .mockRejectedValueOnce(new TypeError("connection closed after release"))
      .mockResolvedValueOnce(jsonResponse(connectedInteraction));

    render(<OutreachApproval apiBaseUrl="http://api.test" candidate={candidate} />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare quote request" }));
    const dialog = await screen.findByRole("dialog", { name: "Review dealer quote request" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve & send" }));
    const release = await within(dialog).findByRole("button", { name: "Release dealer response" });
    fireEvent.click(release);

    expect(await within(dialog).findByText("Dealer response analyzed")).toBeVisible();
    expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
    expect(within(dialog).getAllByText("Original dealer response")).toHaveLength(1);
    expect(within(dialog).getAllByText((_, element) => (
      element?.tagName === "PRE" && element.textContent === inboundMessage.body
    ))).toHaveLength(1);
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "http://api.test/outreach/proposals/proposal-1/interaction",
    );
  });

  it("shows the persisted raw response and a retry after analysis failure", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(pendingProposal, 201))
      .mockResolvedValueOnce(jsonResponse(sentProposal))
      .mockResolvedValueOnce(jsonResponse({
        detail: {
          code: "invalid_quote_evidence",
          message: "The extracted quote evidence could not be validated.",
        },
      }, 502))
      .mockResolvedValueOnce(jsonResponse(failedInteraction));

    render(<OutreachApproval apiBaseUrl="http://api.test" candidate={candidate} />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare quote request" }));
    const dialog = await screen.findByRole("dialog", { name: "Review dealer quote request" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve & send" }));
    fireEvent.click(await within(dialog).findByRole("button", { name: "Release dealer response" }));

    expect(await within(dialog).findByText("Dealer response received")).toBeVisible();
    expect(within(dialog).getByText("Dealer response analysis failed")).toBeVisible();
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "The extracted quote evidence could not be validated.",
    );
    expect(within(dialog).getByText((_, element) => (
      element?.tagName === "PRE" && element.textContent === inboundMessage.body
    ))).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Retry response analysis" })).toBeVisible();
  });

  it("shows a competing analysis claim without offering another analysis attempt", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(pendingProposal, 201))
      .mockResolvedValueOnce(jsonResponse(sentProposal))
      .mockResolvedValueOnce(jsonResponse({
        detail: {
          code: "outreach_response_analysis_in_progress",
          message: "This dealer response is already being analyzed.",
        },
      }, 409))
      .mockResolvedValueOnce(jsonResponse(inProgressInteraction));

    render(<OutreachApproval apiBaseUrl="http://api.test" candidate={candidate} />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare quote request" }));
    const dialog = await screen.findByRole("dialog", { name: "Review dealer quote request" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve & send" }));
    fireEvent.click(await within(dialog).findByRole("button", { name: "Release dealer response" }));

    expect(await within(dialog).findByText("Dealer response analysis in progress")).toBeVisible();
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "This dealer response is already being analyzed.",
    );
    expect(within(dialog).queryByRole("button", { name: "Resume response analysis" }))
      .not.toBeInTheDocument();
  });

  it("reopens a completed interaction without preparing duplicate outreach", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(pendingProposal, 201))
      .mockResolvedValueOnce(jsonResponse(sentProposal))
      .mockResolvedValueOnce(jsonResponse(connectedInteraction));

    render(<OutreachApproval apiBaseUrl="http://api.test" candidate={candidate} />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare quote request" }));
    const dialog = await screen.findByRole("dialog", { name: "Review dealer quote request" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve & send" }));
    fireEvent.click(await within(dialog).findByRole("button", { name: "Release dealer response" }));
    expect(await within(dialog).findByText("Dealer response analyzed")).toBeVisible();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));

    const reopen = await screen.findByRole("button", { name: "View dealer interaction" });
    fireEvent.click(reopen);
    const reopened = await screen.findByRole("dialog", { name: "Review dealer quote request" });
    expect(within(reopened).getByText("Dealer response analyzed")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("shows a response-release failure without claiming receipt or analysis", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(pendingProposal, 201))
      .mockResolvedValueOnce(jsonResponse(sentProposal))
      .mockResolvedValueOnce(jsonResponse({
        detail: {
          code: "demo_response_fixture_not_found",
          message: "No deterministic dealer response fixture is configured for this interaction.",
        },
      }, 422));

    render(<OutreachApproval apiBaseUrl="http://api.test" candidate={candidate} />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare quote request" }));
    const dialog = await screen.findByRole("dialog", { name: "Review dealer quote request" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve & send" }));
    fireEvent.click(await within(dialog).findByRole("button", { name: "Release dealer response" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "No deterministic dealer response fixture is configured for this interaction.",
    );
    expect(within(dialog).queryByText("Dealer response received")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("Dealer response analyzed")).not.toBeInTheDocument();
  });

  it("keeps focus inside the modal and hides the background from assistive technology", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse(pendingProposal, 201));
    const appRoot = document.createElement("div");
    appRoot.id = "root";
    document.body.append(appRoot);

    render(
      <OutreachApproval apiBaseUrl="http://api.test" candidate={candidate} />,
      { container: appRoot },
    );
    fireEvent.click(screen.getByRole("button", { name: "Prepare quote request" }));
    const dialog = await screen.findByRole("dialog", { name: "Review dealer quote request" });
    const close = within(dialog).getByRole("button", { name: "Close" });
    const approve = within(dialog).getByRole("button", { name: "Approve & send" });

    expect(appRoot).toHaveAttribute("inert");
    expect(appRoot).toHaveAttribute("aria-hidden", "true");
    expect(close).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(approve).toHaveFocus();
  });
});
