import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  EvidenceDrawer,
  QuoteAnalysisResultView,
  QuoteAnalysisWorkspace,
  type Evidence,
  type QuoteAnalysisResponse,
} from "./QuoteAnalysisWorkspace";

const message = {
  id: "msg-plus-ttl",
  dealer_id: "houston",
  vehicle_id: "houston-white",
  direction: "INBOUND",
  subject: "Price plus TTL",
  body: "The selling price for VIN KM8JCDD11SU000002 is $37,450 plus tax, title, and license.",
  received_at: "2026-08-19T14:10:00Z",
  source_provider: "fixture",
};

const analysis: QuoteAnalysisResponse = {
  message,
  extraction: {
    vehicle_vin: "KM8JCDD11SU000002",
    stock_number: null,
    selling_price: "37450",
    claimed_otd: null,
    dealer_fees: [],
    government_fees: [],
    addons: [],
    incentives: [],
    financing_required: null,
    trade_required: null,
    expiration: null,
    explicit_no_addons_statement: false,
    explicit_all_fees_included_statement: false,
    unresolved_questions: [],
    evidence_ids: ["ev-selling"],
    extraction_confidence: 0.95,
  },
  evidence: [
    {
      id: "ev-selling",
      source_type: "DEALER_EMAIL",
      source_id: message.id,
      field_name: "selling_price",
      excerpt: "The selling price for VIN KM8JCDD11SU000002 is $37,450",
      created_at: message.received_at,
    },
  ],
  assessment: {
    comparable: false,
    transparent: false,
    reconciled: null,
    missing_for_comparison: [
      "claimed_otd",
      "addon_status",
      "financing_dependency",
      "trade_dependency",
    ],
    missing_for_transparency: [
      "dealer_fee_detail",
      "mandatory_addon_detail",
      "government_fee_detail",
    ],
    reconciliation_difference: null,
  },
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => vi.restoreAllMocks());

describe("QuoteAnalysisWorkspace", () => {
  it("keeps source uncertainty separate from deterministic missing requirements", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse([message]))
      .mockResolvedValueOnce(jsonResponse(analysis));
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <QuoteAnalysisWorkspace apiBaseUrl="http://api.test" />
      </QueryClientProvider>,
    );

    expect(await screen.findByText(message.subject)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Analyze response" }));

    expect(await screen.findByRole("heading", { name: "Is this quote usable?" })).toBeVisible();
    expect(screen.getByText("Written out-the-door total")).toBeVisible();
    expect(screen.getByText("Whether dealer add-ons are mandatory")).toBeVisible();
    expect(screen.getByText("Dealer or documentation fee detail")).toBeVisible();
    expect(screen.getByText("No source-grounded uncertainty extracted.")).toBeVisible();
    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://api.test/quotes/fixtures");
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://api.test/quotes/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message_id: message.id }),
    });
  });

  it("uses unique accessible labels for each reusable analysis view", () => {
    render(<>
      <QuoteAnalysisResultView analysis={analysis} />
      <QuoteAnalysisResultView analysis={analysis} />
    </>);

    const ids = Array.from(document.querySelectorAll<HTMLElement>("[id]"))
      .map((element) => element.id);
    expect(ids.length).toBeGreaterThan(0);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it.each([
    { sourceType: "OEM_SOURCE" as const, label: "OEM SOURCE" },
    { sourceType: "WEB_SOURCE" as const, label: "WEB SOURCE" },
  ])("labels $sourceType evidence without claiming independent research", ({
    sourceType,
    label,
  }) => {
    const evidence: Evidence = {
      ...analysis.evidence[0],
      source_type: sourceType,
    };

    render(<EvidenceDrawer evidence={evidence} onClose={() => undefined} />);

    expect(screen.getByText(label)).toBeVisible();
    expect(screen.queryByText("INDEPENDENT RESEARCH")).not.toBeInTheDocument();
  });
});
