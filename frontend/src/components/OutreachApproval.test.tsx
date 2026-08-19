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
