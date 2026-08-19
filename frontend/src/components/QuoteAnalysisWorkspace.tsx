import { type FormEvent, useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

type DealerMessage = {
  id: string;
  dealer_id: string;
  vehicle_id: string | null;
  subject: string | null;
  body: string;
  received_at: string;
  source_provider: string;
};

type Evidence = {
  id: string;
  source_type: "DEALER_EMAIL" | "DEALER_ATTACHMENT" | "LISTING" | "OEM_SOURCE" | "WEB_SOURCE";
  source_id: string;
  field_name: string;
  excerpt: string;
  created_at: string;
};

type MoneyItem = {
  name: string;
  amount: string | null;
  stated_mandatory: boolean | null;
  evidence_id: string;
};

type Incentive = {
  name: string;
  amount: string | null;
  eligibility_condition: string | null;
  requires_financing: boolean | null;
  requires_trade: boolean | null;
  evidence_id: string;
};

type QuoteExtraction = {
  vehicle_vin: string | null;
  stock_number: string | null;
  selling_price: string | null;
  claimed_otd: string | null;
  dealer_fees: MoneyItem[];
  government_fees: MoneyItem[];
  addons: MoneyItem[];
  incentives: Incentive[];
  financing_required: boolean | null;
  trade_required: boolean | null;
  expiration: string | null;
  explicit_no_addons_statement: boolean;
  explicit_all_fees_included_statement: boolean;
  unresolved_questions: string[];
  evidence_ids: string[];
  extraction_confidence: number;
};

type QuoteAssessment = {
  comparable: boolean;
  transparent: boolean;
  reconciled: boolean | null;
  missing_for_comparison: string[];
  missing_for_transparency: string[];
  reconciliation_difference: string | null;
};

type QuoteAnalysisResponse = {
  message: DealerMessage;
  extraction: QuoteExtraction;
  evidence: Evidence[];
  assessment: QuoteAssessment;
};

type ApiErrorPayload = {
  detail?: string | { message?: string };
};

const currencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

const dateFormatter = new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium",
  timeStyle: "short",
});

const requirementLabels: Record<string, string> = {
  vehicle_identity: "Intended vehicle identity is not established",
  vehicle_identity_mismatch: "Dealer response references a different vehicle",
  claimed_otd: "Written out-the-door total",
  addon_status: "Whether dealer add-ons are mandatory",
  mandatory_addon_amount: "Mandatory add-on amount",
  financing_dependency: "Dealer-financing dependency",
  trade_dependency: "Trade-in dependency",
  pricing_condition: "Pricing or incentive conditions",
  selling_price: "Selling price",
  dealer_fee_detail: "Dealer or documentation fee detail",
  mandatory_addon_detail: "Mandatory add-on detail",
  government_fee_detail: "Tax, title, and license detail",
};

async function apiError(response: Response, fallback: string): Promise<Error> {
  const payload = (await response.json().catch(() => null)) as ApiErrorPayload | null;
  const detail = payload?.detail;
  const message = typeof detail === "string" ? detail : detail?.message;
  return new Error(message ?? fallback);
}

async function loadFixtures(apiBaseUrl: string): Promise<DealerMessage[]> {
  const response = await fetch(`${apiBaseUrl}/quotes/fixtures`);
  if (!response.ok) {
    throw await apiError(response, "The dealer response fixtures could not be loaded.");
  }
  return response.json() as Promise<DealerMessage[]>;
}

async function analyzeMessage(apiBaseUrl: string, messageId: string): Promise<QuoteAnalysisResponse> {
  const response = await fetch(`${apiBaseUrl}/quotes/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message_id: messageId }),
  });
  if (!response.ok) {
    throw await apiError(response, "The dealer response could not be analyzed.");
  }
  return response.json() as Promise<QuoteAnalysisResponse>;
}

function formatMoney(value: string | null): string {
  if (value === null) return "Not stated";
  const amount = Number(value);
  return Number.isFinite(amount) ? currencyFormatter.format(amount) : value;
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : dateFormatter.format(date);
}

function formatRequirement(value: boolean | null): string {
  if (value === null) return "Not stated";
  return value ? "Required" : "Not required";
}

function formatRequirementLabel(value: string): string {
  const knownLabel = requirementLabels[value];
  if (knownLabel) return knownLabel;
  const words = value.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function formatDifference(value: string | null): string {
  if (value === null) return "Not computed";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return value;
  if (amount === 0) return currencyFormatter.format(0);
  const sign = amount > 0 ? "+" : "−";
  return `${sign}${currencyFormatter.format(Math.abs(amount))}`;
}

function assessmentState(value: boolean | null): { label: string; className: string } {
  if (value === null) return { label: "UNKNOWN", className: "is-unknown" };
  return value
    ? { label: "YES", className: "is-yes" }
    : { label: "NO", className: "is-no" };
}

function EvidenceLinks({
  evidence,
  expected,
  selectedEvidenceId,
  onSelect,
}: {
  evidence: Evidence[];
  expected?: boolean;
  selectedEvidenceId: string | null;
  onSelect: (evidenceId: string) => void;
}) {
  if (!evidence.length) {
    return expected ? <span className="evidence-missing">Evidence unavailable</span> : null;
  }
  return <span className="evidence-links">
    {evidence.map((item, index) => <button
      aria-pressed={selectedEvidenceId === item.id}
      className="evidence-trigger"
      key={item.id}
      onClick={() => onSelect(item.id)}
      type="button"
    >
      {evidence.length === 1 ? "View evidence" : `Evidence ${index + 1}`}
    </button>)}
  </span>;
}

function Fact({
  label,
  value,
  evidence,
  evidenceExpected,
  selectedEvidenceId,
  onSelectEvidence,
}: {
  label: string;
  value: string;
  evidence: Evidence[];
  evidenceExpected?: boolean;
  selectedEvidenceId: string | null;
  onSelectEvidence: (evidenceId: string) => void;
}) {
  return <div className="fact">
    <dt>{label}</dt>
    <dd>
      <span>{value}</span>
      <EvidenceLinks
        evidence={evidence}
        expected={evidenceExpected}
        selectedEvidenceId={selectedEvidenceId}
        onSelect={onSelectEvidence}
      />
    </dd>
  </div>;
}

function MoneyItems({
  title,
  items,
  emptyLabel,
  evidenceById,
  selectedEvidenceId,
  onSelectEvidence,
}: {
  title: string;
  items: MoneyItem[];
  emptyLabel: string;
  evidenceById: Map<string, Evidence>;
  selectedEvidenceId: string | null;
  onSelectEvidence: (evidenceId: string) => void;
}) {
  return <section className="quote-group">
    <h4>{title}</h4>
    {!items.length && <p className="muted">{emptyLabel}</p>}
    {!!items.length && <ul className="quote-items">
      {items.map((item, index) => {
        const evidence = evidenceById.get(item.evidence_id);
        const mandatoryLabel = item.stated_mandatory === null
          ? "Mandatory status not stated"
          : item.stated_mandatory ? "Stated mandatory" : "Stated optional";
        return <li key={`${item.name}-${index}`}>
          <div className="quote-item-heading">
            <strong>{item.name}</strong>
            <span>{formatMoney(item.amount)}</span>
          </div>
          <p className="item-detail">{mandatoryLabel}</p>
          <EvidenceLinks
            evidence={evidence ? [evidence] : []}
            expected
            selectedEvidenceId={selectedEvidenceId}
            onSelect={onSelectEvidence}
          />
        </li>;
      })}
    </ul>}
  </section>;
}

function Incentives({
  incentives,
  evidenceById,
  selectedEvidenceId,
  onSelectEvidence,
}: {
  incentives: Incentive[];
  evidenceById: Map<string, Evidence>;
  selectedEvidenceId: string | null;
  onSelectEvidence: (evidenceId: string) => void;
}) {
  return <section className="quote-group">
    <h4>Incentives</h4>
    {!incentives.length && <p className="muted">No incentives stated.</p>}
    {!!incentives.length && <ul className="quote-items">
      {incentives.map((incentive, index) => {
        const evidence = evidenceById.get(incentive.evidence_id);
        return <li key={`${incentive.name}-${index}`}>
          <div className="quote-item-heading">
            <strong>{incentive.name}</strong>
            <span>{formatMoney(incentive.amount)}</span>
          </div>
          <p className="item-detail">{incentive.eligibility_condition ?? "Eligibility not stated"}</p>
          <p className="item-detail">
            Financing: {formatRequirement(incentive.requires_financing)} · Trade: {formatRequirement(incentive.requires_trade)}
          </p>
          <EvidenceLinks
            evidence={evidence ? [evidence] : []}
            expected
            selectedEvidenceId={selectedEvidenceId}
            onSelect={onSelectEvidence}
          />
        </li>;
      })}
    </ul>}
  </section>;
}

function RawDealerMessage({ message }: { message: DealerMessage }) {
  return <section className="analysis-panel raw-message-panel" aria-labelledby="raw-message-heading">
    <p className="eyebrow">Original dealer response</p>
    <h3 id="raw-message-heading">{message.subject ?? "No subject"}</h3>
    <p className="message-meta">
      Dealer {message.dealer_id} · {formatDate(message.received_at)} · {message.source_provider}
    </p>
    <pre className="raw-message">{message.body}</pre>
  </section>;
}

function AssessmentResult({ label, value }: { label: string; value: boolean | null }) {
  const state = assessmentState(value);
  return <div className="assessment-card">
    <dt>{label}</dt>
    <dd className={`assessment-result ${state.className}`}>{state.label}</dd>
  </div>;
}

function PolicyRequirements({
  title,
  requirements,
  completeLabel,
}: {
  title: string;
  requirements: string[];
  completeLabel: string;
}) {
  return <section className="policy-group">
    <h4>{title}</h4>
    {!requirements.length && <p className="policy-complete">{completeLabel}</p>}
    {!!requirements.length && <ul className="policy-list">
      {requirements.map((requirement) => <li key={requirement}>
        <code>{requirement}</code>
        <span>{formatRequirementLabel(requirement)}</span>
      </li>)}
    </ul>}
  </section>;
}

function QuoteAssessmentPanel({ assessment }: { assessment: QuoteAssessment }) {
  const numericDifference = assessment.reconciliation_difference === null
    ? null
    : Number(assessment.reconciliation_difference);
  const reconciliationDetail = assessment.reconciled === null
    ? "Known line items are not complete or unambiguous enough for authoritative arithmetic."
    : assessment.reconciled
      ? `Known line items reconcile within the $0.01 tolerance (${formatDifference(assessment.reconciliation_difference)}).`
      : numericDifference !== null && Number.isFinite(numericDifference)
        ? `Known line items total ${currencyFormatter.format(Math.abs(numericDifference))} ${numericDifference > 0 ? "more" : "less"} than the dealer's claimed OTD.`
        : "Known line items do not reconcile with the dealer's claimed OTD.";

  return <section className="analysis-panel assessment-panel" aria-labelledby="assessment-heading">
    <p className="eyebrow">Deterministic assessment</p>
    <div className="panel-heading">
      <div>
        <h3 id="assessment-heading">Is this quote usable?</h3>
        <p className="assessment-intro">Application policy evaluates three independent dimensions. No score or dealer judgment is inferred.</p>
      </div>
    </div>

    <dl className="assessment-grid">
      <AssessmentResult label="Comparable" value={assessment.comparable} />
      <AssessmentResult label="Transparent" value={assessment.transparent} />
      <AssessmentResult label="Reconciled" value={assessment.reconciled} />
    </dl>

    <div className="policy-grid">
      <PolicyRequirements
        title="Missing for comparison"
        requirements={assessment.missing_for_comparison}
        completeLabel="No comparison-policy gaps."
      />
      <PolicyRequirements
        title="Missing for transparency"
        requirements={assessment.missing_for_transparency}
        completeLabel="No transparency-policy gaps."
      />
    </div>

    <section className="reconciliation-detail">
      <div className="reconciliation-heading">
        <h4>Arithmetic difference</h4>
        <strong>{formatDifference(assessment.reconciliation_difference)}</strong>
      </div>
      <p>{reconciliationDetail}</p>
      <p className="formula-note">Difference = computed known line-item total − claimed OTD. Positive means the line items total more; negative means they total less. An absolute difference of $0.01 or less counts as reconciled.</p>
    </section>
  </section>;
}

function StructuredQuote({
  analysis,
  selectedEvidenceId,
  onSelectEvidence,
}: {
  analysis: QuoteAnalysisResponse;
  selectedEvidenceId: string | null;
  onSelectEvidence: (evidenceId: string) => void;
}) {
  const { extraction, evidence } = analysis;
  const evidenceById = new Map(evidence.map((item) => [item.id, item]));
  const evidenceFor = (fieldName: string) => evidence.filter((item) => item.field_name === fieldName);

  return <section className="analysis-panel structured-quote" aria-labelledby="structured-quote-heading">
    <p className="eyebrow">Structured extraction</p>
    <div className="panel-heading">
      <h3 id="structured-quote-heading">Dealer-stated quote facts</h3>
      <span className="source-count">{evidence.length} evidence record{evidence.length === 1 ? "" : "s"}</span>
    </div>

    <dl className="fact-grid">
      <Fact
        label="Selling price"
        value={formatMoney(extraction.selling_price)}
        evidence={evidenceFor("selling_price")}
        evidenceExpected={extraction.selling_price !== null}
        selectedEvidenceId={selectedEvidenceId}
        onSelectEvidence={onSelectEvidence}
      />
      <Fact
        label="Claimed out-the-door"
        value={formatMoney(extraction.claimed_otd)}
        evidence={evidenceFor("claimed_otd")}
        evidenceExpected={extraction.claimed_otd !== null}
        selectedEvidenceId={selectedEvidenceId}
        onSelectEvidence={onSelectEvidence}
      />
      <Fact
        label="Vehicle VIN"
        value={extraction.vehicle_vin ?? "Not stated"}
        evidence={evidenceFor("vehicle_vin")}
        evidenceExpected={extraction.vehicle_vin !== null}
        selectedEvidenceId={selectedEvidenceId}
        onSelectEvidence={onSelectEvidence}
      />
      <Fact
        label="Stock number"
        value={extraction.stock_number ?? "Not stated"}
        evidence={evidenceFor("stock_number")}
        evidenceExpected={extraction.stock_number !== null}
        selectedEvidenceId={selectedEvidenceId}
        onSelectEvidence={onSelectEvidence}
      />
    </dl>

    <div className="quote-groups">
      <MoneyItems
        title="Dealer fees"
        items={extraction.dealer_fees}
        emptyLabel="No dealer fees stated."
        evidenceById={evidenceById}
        selectedEvidenceId={selectedEvidenceId}
        onSelectEvidence={onSelectEvidence}
      />
      <MoneyItems
        title="Government fees"
        items={extraction.government_fees}
        emptyLabel="No government fees itemized."
        evidenceById={evidenceById}
        selectedEvidenceId={selectedEvidenceId}
        onSelectEvidence={onSelectEvidence}
      />
      <MoneyItems
        title="Dealer add-ons"
        items={extraction.addons}
        emptyLabel="No dealer add-ons stated."
        evidenceById={evidenceById}
        selectedEvidenceId={selectedEvidenceId}
        onSelectEvidence={onSelectEvidence}
      />
      <Incentives
        incentives={extraction.incentives}
        evidenceById={evidenceById}
        selectedEvidenceId={selectedEvidenceId}
        onSelectEvidence={onSelectEvidence}
      />
    </div>

    <section className="quote-group conditions">
      <h4>Conditions and statements</h4>
      <dl className="fact-grid compact-facts">
        <Fact
          label="Dealer financing"
          value={formatRequirement(extraction.financing_required)}
          evidence={evidenceFor("financing_required")}
          evidenceExpected={extraction.financing_required !== null}
          selectedEvidenceId={selectedEvidenceId}
          onSelectEvidence={onSelectEvidence}
        />
        <Fact
          label="Trade-in"
          value={formatRequirement(extraction.trade_required)}
          evidence={evidenceFor("trade_required")}
          evidenceExpected={extraction.trade_required !== null}
          selectedEvidenceId={selectedEvidenceId}
          onSelectEvidence={onSelectEvidence}
        />
        <Fact
          label="Expiration"
          value={extraction.expiration ? formatDate(extraction.expiration) : "Not stated"}
          evidence={evidenceFor("expiration")}
          evidenceExpected={extraction.expiration !== null}
          selectedEvidenceId={selectedEvidenceId}
          onSelectEvidence={onSelectEvidence}
        />
        <Fact
          label="No add-ons statement"
          value={extraction.explicit_no_addons_statement ? "Explicitly stated" : "No explicit statement extracted"}
          evidence={evidenceFor("explicit_no_addons_statement")}
          evidenceExpected={extraction.explicit_no_addons_statement}
          selectedEvidenceId={selectedEvidenceId}
          onSelectEvidence={onSelectEvidence}
        />
        <Fact
          label="All fees included statement"
          value={extraction.explicit_all_fees_included_statement ? "Explicitly stated" : "No explicit statement extracted"}
          evidence={evidenceFor("explicit_all_fees_included_statement")}
          evidenceExpected={extraction.explicit_all_fees_included_statement}
          selectedEvidenceId={selectedEvidenceId}
          onSelectEvidence={onSelectEvidence}
        />
      </dl>
    </section>

    <section className="quote-group questions">
      <h4>Unresolved source uncertainty</h4>
      <p className="item-detail">These are ambiguities or refusals stated in the dealer source, not application-determined policy gaps.</p>
      {!extraction.unresolved_questions.length && <p className="muted">No source-grounded uncertainty extracted.</p>}
      {!!extraction.unresolved_questions.length && <ul>
        {extraction.unresolved_questions.map((question) => <li key={question}>{question}</li>)}
      </ul>}
      <EvidenceLinks
        evidence={evidenceFor("unresolved_questions")}
        selectedEvidenceId={selectedEvidenceId}
        onSelect={onSelectEvidence}
      />
    </section>
  </section>;
}

function EvidenceDrawer({ evidence, onClose }: { evidence: Evidence; onClose: () => void }) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const previouslyFocused = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    closeButtonRef.current?.focus();
    return () => previouslyFocused?.focus();
  }, []);

  return <aside
    aria-labelledby="evidence-heading"
    className="evidence-drawer"
    onKeyDown={(event) => {
      if (event.key === "Escape") onClose();
    }}
    role="dialog"
  >
    <div className="panel-heading">
      <div>
        <p className="eyebrow">Supporting evidence</p>
        <h3 id="evidence-heading">{evidence.field_name.replaceAll("_", " ")}</h3>
      </div>
      <button className="secondary-button" onClick={onClose} ref={closeButtonRef} type="button">Close</button>
    </div>
    <dl className="evidence-meta">
      <div><dt>Source</dt><dd>{evidence.source_type.replaceAll("_", " ").toLowerCase()}</dd></div>
      <div><dt>Message</dt><dd>{evidence.source_id}</dd></div>
      <div><dt>Captured</dt><dd>{formatDate(evidence.created_at)}</dd></div>
    </dl>
    <blockquote>{evidence.excerpt}</blockquote>
  </aside>;
}

export function QuoteAnalysisWorkspace({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [requestedMessageId, setRequestedMessageId] = useState("");
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null);
  const fixtures = useQuery({
    queryKey: ["quote-fixtures", apiBaseUrl],
    queryFn: () => loadFixtures(apiBaseUrl),
  });
  const analysis = useMutation({
    mutationFn: (messageId: string) => analyzeMessage(apiBaseUrl, messageId),
    onMutate: () => setSelectedEvidenceId(null),
  });
  const selectedMessageId = requestedMessageId || fixtures.data?.[0]?.id || "";
  const selectedFixture = fixtures.data?.find((message) => message.id === selectedMessageId) ?? null;
  const selectedEvidence = analysis.data?.evidence.find((item) => item.id === selectedEvidenceId) ?? null;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (selectedMessageId) analysis.mutate(selectedMessageId);
  };

  const changeMessage = (messageId: string) => {
    setRequestedMessageId(messageId);
    setSelectedEvidenceId(null);
    analysis.reset();
  };

  return <section className="quote-analysis" aria-labelledby="quote-analysis-heading">
    <p className="eyebrow">Dealer response lab</p>
    <h2 id="quote-analysis-heading">Extract the facts, then test what is usable</h2>
    <p className="section-summary">
      Choose a fixture response to preserve its source-backed facts, then deterministically assess identity, completeness, transparency, and arithmetic.
    </p>

    <form className="quote-analysis-form" onSubmit={submit}>
      <div className="fixture-picker">
        <label htmlFor="dealer-message">Dealer response</label>
        <select
          disabled={fixtures.isPending || fixtures.isError || analysis.isPending}
          id="dealer-message"
          onChange={(event) => changeMessage(event.target.value)}
          value={selectedMessageId}
        >
          {fixtures.isPending && <option value="">Loading fixture responses…</option>}
          {fixtures.data?.map((message) => <option key={message.id} value={message.id}>
            {message.dealer_id} — {message.subject ?? message.id}
          </option>)}
        </select>
      </div>
      <button disabled={!selectedMessageId || analysis.isPending} type="submit">
        {analysis.isPending ? "Analyzing…" : "Analyze response"}
      </button>
    </form>

    {fixtures.isError && <p className="error" role="alert">{fixtures.error.message}</p>}
    {fixtures.isSuccess && !fixtures.data.length && <p className="empty-state">No fixture dealer responses are available.</p>}
    {analysis.isError && <p className="error" role="alert">{analysis.error.message}</p>}
    {analysis.isPending && <p className="analysis-status" role="status">Extracting source-supported facts before deterministic assessment…</p>}

    {selectedFixture && !analysis.isSuccess && <div className="analysis-grid">
      <RawDealerMessage message={selectedFixture} />
    </div>}

    {analysis.isSuccess && <>
      <div className="analysis-grid">
        <RawDealerMessage message={analysis.data.message} />
        <div className="analysis-stack">
          <QuoteAssessmentPanel assessment={analysis.data.assessment} />
          <StructuredQuote
            analysis={analysis.data}
            selectedEvidenceId={selectedEvidenceId}
            onSelectEvidence={setSelectedEvidenceId}
          />
        </div>
      </div>
      {selectedEvidence && <EvidenceDrawer
        evidence={selectedEvidence}
        key={selectedEvidence.id}
        onClose={() => setSelectedEvidenceId(null)}
      />}
    </>}
  </section>;
}
