import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import {
  QuoteAnalysisResultView,
  RawDealerMessage,
  type DealerMessage,
  type QuoteAnalysisResponse,
} from "./QuoteAnalysisWorkspace";

export type OutreachCandidate = {
  id: string;
  vin: string | null;
  stock_number: string | null;
  year: number;
  make: string;
  model: string;
  trim: string | null;
  dealer_id: string;
  dealer_name: string;
};

type ActionSnapshot = {
  vehicle_id: string;
  dealer_id: string;
  recipient: string;
  subject: string;
  body: string;
};

type ApprovalRecord = {
  decision: "APPROVED" | "REJECTED";
  decided_at: string;
  action_snapshot: ActionSnapshot;
};

type DeliveryReceipt = {
  action_id: string;
  provider: string;
  external_message_id: string;
  sent_at: string;
};

export type OutreachProposal = {
  id: string;
  action_type: "SEND_INITIAL_QUOTE_REQUEST";
  dealer_id: string;
  vehicle_id: string;
  recipient: string;
  subject: string;
  body: string;
  reason: string;
  requested_information: string[];
  requested_information_labels?: string[];
  requires_approval: true;
  status: "PENDING_APPROVAL" | "APPROVED" | "REJECTED" | "SENT" | "SEND_FAILED";
  vehicle: OutreachCandidate;
  created_at?: string;
  approval: ApprovalRecord | null;
  delivery: DeliveryReceipt | null;
};

type OutreachInteraction = {
  id: string;
  initial_action_id: string;
  dealer_id: string;
  vehicle_id: string;
  vehicle: OutreachCandidate;
  created_at: string;
  analysis_status:
    | "AWAITING_RESPONSE"
    | "RESPONSE_RECEIVED"
    | "ANALYSIS_IN_PROGRESS"
    | "ANALYZED"
    | "ANALYSIS_FAILED";
  analysis_error_code: string | null;
  messages: DealerMessage[];
  analysis: QuoteAnalysisResponse | null;
};

type ApiErrorPayload = {
  detail?: string | { message?: string };
};

const requirementLabels: Record<string, string> = {
  vehicle_identity: "Exact VIN and/or stock number for the quoted vehicle",
  selling_price: "Selling price before taxes and fees",
  dealer_fees: "All dealer and documentation fees",
  mandatory_addons: "All mandatory dealer-installed products and add-ons, with amounts",
  government_charges: "Taxes, title, license, and other government charges",
  out_the_door_total: "Written out-the-door total",
  incentives_and_eligibility: "Included incentives and rebates, with eligibility conditions",
  financing_requirement: "Whether the quoted economics require dealer financing",
  trade_in_requirement: "Whether the quoted economics require a trade-in",
  quote_expiration: "Quote expiration or validity period, if applicable",
};

async function errorMessage(response: Response, fallback: string): Promise<string> {
  const payload = (await response.json().catch(() => null)) as ApiErrorPayload | null;
  const detail = payload?.detail;
  const message = typeof detail === "string" ? detail : detail?.message;
  return message ?? fallback;
}

async function prepareProposal(apiBaseUrl: string, vehicleId: string): Promise<OutreachProposal> {
  const response = await fetch(`${apiBaseUrl}/outreach/proposals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ vehicle_id: vehicleId }),
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response, "The quote request could not be prepared."));
  }
  return response.json() as Promise<OutreachProposal>;
}

async function inspectProposal(apiBaseUrl: string, actionId: string): Promise<OutreachProposal> {
  const response = await fetch(`${apiBaseUrl}/outreach/proposals/${actionId}`);
  if (!response.ok) {
    throw new Error(await errorMessage(response, "The quote request status could not be loaded."));
  }
  return response.json() as Promise<OutreachProposal>;
}

async function releaseDemoResponse(
  apiBaseUrl: string,
  actionId: string,
): Promise<OutreachInteraction> {
  const response = await fetch(`${apiBaseUrl}/outreach/proposals/${actionId}/demo-response`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response, "The dealer response could not be released."));
  }
  return response.json() as Promise<OutreachInteraction>;
}

async function inspectInteraction(
  apiBaseUrl: string,
  actionId: string,
): Promise<OutreachInteraction> {
  const response = await fetch(`${apiBaseUrl}/outreach/proposals/${actionId}/interaction`);
  if (!response.ok) {
    throw new Error(await errorMessage(response, "The dealer interaction status could not be loaded."));
  }
  return response.json() as Promise<OutreachInteraction>;
}

async function decideProposal(
  apiBaseUrl: string,
  actionId: string,
  decision: "approve" | "reject",
): Promise<{ proposal: OutreachProposal | null; error: string | null }> {
  const fallback = decision === "approve"
    ? "The approved dealer message could not be sent."
    : "The quote request could not be rejected.";
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}/outreach/proposals/${actionId}/${decision}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
  } catch (caught) {
    const message = caught instanceof Error ? caught.message : fallback;
    return reconcileDecision(apiBaseUrl, actionId, decision, message);
  }

  if (response.ok) {
    try {
      return {
        proposal: await response.json() as OutreachProposal,
        error: null,
      };
    } catch {
      return reconcileDecision(
        apiBaseUrl,
        actionId,
        decision,
        "The server saved the decision, but its response could not be read.",
      );
    }
  }

  const message = await errorMessage(response, fallback);
  return reconcileDecision(apiBaseUrl, actionId, decision, message);
}

async function reconcileDecision(
  apiBaseUrl: string,
  actionId: string,
  decision: "approve" | "reject",
  message: string,
): Promise<{ proposal: OutreachProposal; error: string | null }> {
  try {
    const proposal = await inspectProposal(apiBaseUrl, actionId);
    const outcomeConfirmed = decision === "approve"
      ? proposal.status === "SENT"
      : proposal.status === "REJECTED";
    return {
      proposal,
      error: outcomeConfirmed ? null : message,
    };
  } catch {
    throw new Error(message);
  }
}

function vehicleName(vehicle: OutreachCandidate): string {
  return [vehicle.year, vehicle.make, vehicle.model, vehicle.trim]
    .filter((part) => part !== null && part !== "")
    .join(" ");
}

function vehicleIdentifiers(vehicle: OutreachCandidate): string | null {
  const identifiers = [
    vehicle.vin ? `VIN ${vehicle.vin}` : null,
    vehicle.stock_number ? `Stock ${vehicle.stock_number}` : null,
  ].filter((identifier): identifier is string => identifier !== null);
  return identifiers.length ? identifiers.join(" · ") : null;
}

function ProposalStatus({ proposal, error }: { proposal: OutreachProposal; error: string | null }) {
  if (proposal.status === "SENT" && proposal.delivery) {
    return <div className="outreach-result outreach-result-success" role="status">
      <strong>Sent through the fixture provider</strong>
      <span>Delivery receipt <code>{proposal.delivery.external_message_id}</code></span>
    </div>;
  }
  if (proposal.status === "REJECTED") {
    return <div className="outreach-result outreach-result-rejected" role="status">
      <strong>Request rejected</strong>
      <span>No message was sent to the dealer.</span>
    </div>;
  }
  if (proposal.status === "SEND_FAILED") {
    return <div className="outreach-result outreach-result-failed" role="alert">
      <strong>Delivery failed</strong>
      <span>{error ?? "The approved dealer message could not be sent."}</span>
    </div>;
  }
  if (proposal.status === "APPROVED") {
    return <div className="outreach-result outreach-result-pending" role="status">
      <strong>Approved</strong>
      <span>Delivery has not been confirmed.</span>
    </div>;
  }
  return null;
}

function ProposalDialog({
  proposal,
  decisionInFlight,
  interaction,
  releaseInFlight,
  error,
  onApprove,
  onRelease,
  onReject,
  onClose,
}: {
  proposal: OutreachProposal;
  decisionInFlight: "approve" | "reject" | null;
  interaction: OutreachInteraction | null;
  releaseInFlight: boolean;
  error: string | null;
  onApprove: () => void;
  onRelease: () => void;
  onReject: () => void;
  onClose: () => void;
}) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const identifiers = vehicleIdentifiers(proposal.vehicle);
  const isDeciding = decisionInFlight !== null;
  const isBusy = isDeciding || releaseInFlight;
  const latestMessage = interaction?.messages.at(-1) ?? null;
  const messageCount = interaction?.messages.length ?? 0;

  useEffect(() => {
    const previouslyFocused = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const appRoot = document.getElementById("root");
    const rootWasInert = appRoot?.hasAttribute("inert") ?? false;
    const previousAriaHidden = appRoot?.getAttribute("aria-hidden") ?? null;
    appRoot?.setAttribute("inert", "");
    appRoot?.setAttribute("aria-hidden", "true");
    closeButtonRef.current?.focus();
    return () => {
      if (!rootWasInert) appRoot?.removeAttribute("inert");
      if (previousAriaHidden === null) {
        appRoot?.removeAttribute("aria-hidden");
      } else {
        appRoot?.setAttribute("aria-hidden", previousAriaHidden);
      }
      previouslyFocused?.focus();
    };
  }, [proposal.id]);

  return createPortal(<div className="outreach-backdrop">
    <section
      aria-labelledby="outreach-review-heading"
      aria-modal="true"
      className={`outreach-dialog${latestMessage ? " outreach-dialog-expanded" : ""}`}
      ref={dialogRef}
      onKeyDown={(event) => {
        if (event.key === "Escape" && !isBusy) onClose();
        if (event.key !== "Tab") return;
        const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? []);
        if (!focusable.length) {
          event.preventDefault();
          return;
        }
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && (document.activeElement === first || !dialogRef.current?.contains(document.activeElement))) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }}
      role="dialog"
    >
      <div className="outreach-dialog-heading">
        <div>
          <p className="eyebrow">Human approval required</p>
          <h2 id="outreach-review-heading">Review dealer quote request</h2>
        </div>
        <button
          className="secondary-button"
          disabled={isBusy}
          onClick={onClose}
          ref={closeButtonRef}
          type="button"
        >
          Close
        </button>
      </div>

      <p className="outreach-approval-note">Sending requires your explicit approval.</p>

      <dl className="outreach-meta">
        <div><dt>Dealer</dt><dd>{proposal.vehicle.dealer_name}</dd></div>
        <div><dt>Recipient</dt><dd>{proposal.recipient}</dd></div>
        <div className="outreach-meta-wide">
          <dt>Vehicle</dt>
          <dd>{vehicleName(proposal.vehicle)}</dd>
          {identifiers && <dd className="muted">{identifiers}</dd>}
        </div>
        <div className="outreach-meta-wide"><dt>Why contact this dealer</dt><dd>{proposal.reason}</dd></div>
      </dl>

      <section className="outreach-message-review" aria-labelledby="outreach-message-heading">
        <h3 id="outreach-message-heading">Exact message</h3>
        <dl>
          <div><dt>Subject</dt><dd>{proposal.subject}</dd></div>
        </dl>
        <pre>{proposal.body}</pre>
      </section>

      <section className="outreach-requirements" aria-labelledby="outreach-requirements-heading">
        <h3 id="outreach-requirements-heading">Requested information</h3>
        <ul>
          {proposal.requested_information.map((requirement, index) => <li key={requirement}>
            {proposal.requested_information_labels?.[index]
              ?? requirementLabels[requirement]
              ?? requirement.replaceAll("_", " ")}
          </li>)}
        </ul>
      </section>

      <ProposalStatus error={error} proposal={proposal} />
      {error && proposal.status !== "SEND_FAILED" && <p className="error" role="alert">{error}</p>}

      {proposal.status === "SENT" && proposal.delivery && <section
        aria-labelledby="dealer-interaction-heading"
        className="outreach-interaction"
      >
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Dealer interaction</p>
            <h3 id="dealer-interaction-heading">Continue the fixture conversation</h3>
          </div>
          <code>{interaction?.id ?? proposal.id}</code>
        </div>

        {!latestMessage && <>
          <p className="item-detail">
            Delivery is confirmed. Release the application-owned fixture response when you are ready to continue this interaction.
          </p>
          <button disabled={releaseInFlight} onClick={onRelease} type="button">
            {releaseInFlight ? "Releasing…" : "Release dealer response"}
          </button>
        </>}

        {latestMessage && <>
          <ol className="interaction-lifecycle" aria-label="Dealer response lifecycle">
            <li><strong>Quote request sent</strong><span>Fixture delivery confirmed</span></li>
            <li>
              <strong>Dealer response received</strong>
              <span>{messageCount} inbound message{messageCount === 1 ? "" : "s"}</span>
            </li>
            {interaction?.analysis_status === "ANALYZED" && <li>
              <strong>Dealer response analyzed</strong>
              <span>Evidence validated and policy assessed</span>
            </li>}
            {interaction?.analysis_status === "ANALYSIS_FAILED" && <li>
              <strong>Dealer response analysis failed</strong>
              <span>The raw response is preserved for a safe retry</span>
            </li>}
            {interaction?.analysis_status === "RESPONSE_RECEIVED" && <li>
              <strong>Dealer response awaiting analysis</strong>
              <span>The raw response is preserved</span>
            </li>}
            {interaction?.analysis_status === "ANALYSIS_IN_PROGRESS" && <li>
              <strong>Dealer response analysis in progress</strong>
              <span>Another request holds the analysis claim</span>
            </li>}
          </ol>
          {interaction?.analysis
            ? <QuoteAnalysisResultView analysis={interaction.analysis} />
            : <>
              <div className="analysis-grid">
                <RawDealerMessage message={latestMessage} />
              </div>
              {interaction?.analysis_status !== "ANALYSIS_IN_PROGRESS" && <button
                disabled={releaseInFlight}
                onClick={onRelease}
                type="button"
              >
                {releaseInFlight
                  ? "Analyzing…"
                  : interaction?.analysis_status === "ANALYSIS_FAILED"
                    ? "Retry response analysis"
                    : "Resume response analysis"}
              </button>}
            </>}
        </>}
      </section>}

      {proposal.status === "PENDING_APPROVAL" && <div className="outreach-actions">
        <button
          className="secondary-button outreach-reject-button"
          disabled={isDeciding}
          onClick={onReject}
          type="button"
        >
          {decisionInFlight === "reject" ? "Rejecting…" : "Reject request"}
        </button>
        <button disabled={isDeciding} onClick={onApprove} type="button">
          {decisionInFlight === "approve" ? "Sending…" : "Approve & send"}
        </button>
      </div>}
    </section>
  </div>, document.body);
}

export function OutreachApproval({
  apiBaseUrl,
  candidate,
}: {
  apiBaseUrl: string;
  candidate: OutreachCandidate;
}) {
  const [proposal, setProposal] = useState<OutreachProposal | null>(null);
  const [isPreparing, setIsPreparing] = useState(false);
  const [decisionInFlight, setDecisionInFlight] = useState<"approve" | "reject" | null>(null);
  const [releaseInFlight, setReleaseInFlight] = useState(false);
  const [interaction, setInteraction] = useState<OutreachInteraction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const prepare = async () => {
    setIsPreparing(true);
    setError(null);
    setInteraction(null);
    try {
      setProposal(await prepareProposal(apiBaseUrl, candidate.id));
      setDialogOpen(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The quote request could not be prepared.");
    } finally {
      setIsPreparing(false);
    }
  };

  const decide = async (decision: "approve" | "reject") => {
    if (!proposal) return;
    setDecisionInFlight(decision);
    setError(null);
    try {
      const result = await decideProposal(apiBaseUrl, proposal.id, decision);
      if (result.proposal) setProposal(result.proposal);
      setError(result.error);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The approval decision could not be completed.");
    } finally {
      setDecisionInFlight(null);
    }
  };

  const release = async () => {
    if (!proposal || proposal.status !== "SENT" || !proposal.delivery) return;
    setReleaseInFlight(true);
    setError(null);
    try {
      setInteraction(await releaseDemoResponse(apiBaseUrl, proposal.id));
    } catch (caught) {
      const releaseError = caught instanceof Error
        ? caught.message
        : "The dealer response could not be released.";
      try {
        const persistedInteraction = await inspectInteraction(apiBaseUrl, proposal.id);
        setInteraction(persistedInteraction);
        setError(persistedInteraction.analysis_status === "ANALYZED" ? null : releaseError);
      } catch {
        setError(releaseError);
      }
    } finally {
      setReleaseInFlight(false);
    }
  };

  const close = () => {
    setDialogOpen(false);
  };

  const openOrPrepare = () => {
    if (proposal) {
      setDialogOpen(true);
      return;
    }
    void prepare();
  };

  return <>
    <button disabled={isPreparing} onClick={openOrPrepare} type="button">
      {isPreparing
        ? "Preparing…"
        : proposal?.status === "SENT"
          ? "View dealer interaction"
          : proposal
            ? "View quote request"
            : "Prepare quote request"}
    </button>
    {error && !proposal && <p className="error" role="alert">{error}</p>}
    {proposal && dialogOpen && <ProposalDialog
      decisionInFlight={decisionInFlight}
      error={error}
      interaction={interaction}
      onApprove={() => decide("approve")}
      onClose={close}
      onReject={() => decide("reject")}
      onRelease={release}
      proposal={proposal}
      releaseInFlight={releaseInFlight}
    />}
  </>;
}
