import { useId, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { OutreachApproval, type OutreachCandidate } from "./OutreachApproval";

type RunPhase =
  | "STARTING"
  | "WAITING_FOR_APPROVAL"
  | "WAITING_FOR_EXTERNAL_RESPONSE"
  | "WAITING_FOR_ANALYSIS"
  | "ANALYSIS_FAILED"
  | "DELIVERY_UNCONFIRMED"
  | "INTERACTION_COMPLETE"
  | "INTERACTION_INCOMPLETE_MAX_FOLLOWUPS"
  | "RUN_REJECTED"
  | "RUN_FAILED";

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
  metadata: Record<string, string | number | boolean | null>;
};

type AgentRun = {
  id: string;
  run_id: string;
  thread_id: string;
  vehicle_id: string;
  phase: RunPhase;
  initial_action_id: string;
  current_action_id: string | null;
  interaction_id: string | null;
  last_message_id: string | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
  events: AgentEvent[];
};

type ApiErrorPayload = {
  detail?: string | { message?: string };
};

type PhasePresentation = {
  title: string;
  description: string;
  tone: "active" | "warning" | "complete" | "failed";
  resumable: boolean;
};

const phasePresentations: Record<RunPhase, PhasePresentation> = {
  STARTING: {
    title: "Starting agent workflow",
    description: "Loading the selected candidate and choosing the next safe capability.",
    tone: "active",
    resumable: true,
  },
  WAITING_FOR_APPROVAL: {
    title: "Waiting for your approval",
    description: "Review the exact dealer message before anything is sent.",
    tone: "warning",
    resumable: true,
  },
  WAITING_FOR_EXTERNAL_RESPONSE: {
    title: "Waiting for dealer response",
    description: "Confirmed outreach was sent. Resume after an application-owned response arrives.",
    tone: "active",
    resumable: true,
  },
  WAITING_FOR_ANALYSIS: {
    title: "Waiting for response analysis",
    description: "The dealer response is preserved while its authoritative analysis finishes.",
    tone: "active",
    resumable: true,
  },
  ANALYSIS_FAILED: {
    title: "Response analysis failed",
    description: "The raw response remains preserved for a safe, explicit retry.",
    tone: "failed",
    resumable: true,
  },
  DELIVERY_UNCONFIRMED: {
    title: "Delivery unconfirmed",
    description: "Review before taking another action.",
    tone: "warning",
    resumable: false,
  },
  INTERACTION_COMPLETE: {
    title: "Offer is comparable",
    description: "The dealer interaction is complete under deterministic comparison policy.",
    tone: "complete",
    resumable: false,
  },
  INTERACTION_INCOMPLETE_MAX_FOLLOWUPS: {
    title: "Interaction remains incomplete",
    description: "The application-owned limit of two confirmed follow-ups has been reached.",
    tone: "warning",
    resumable: false,
  },
  RUN_REJECTED: {
    title: "Workflow stopped",
    description: "The proposed dealer message was rejected and nothing was sent.",
    tone: "failed",
    resumable: false,
  },
  RUN_FAILED: {
    title: "Workflow failed",
    description: "The workflow stopped without inventing a successful action.",
    tone: "failed",
    resumable: false,
  },
};

const eventDateFormatter = new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium",
  timeStyle: "short",
});

async function apiError(response: Response, fallback: string): Promise<Error> {
  const payload = (await response.json().catch(() => null)) as ApiErrorPayload | null;
  const detail = payload?.detail;
  const message = typeof detail === "string" ? detail : detail?.message;
  return new Error(message ?? fallback);
}

async function createAgentRun(apiBaseUrl: string, vehicleId: string): Promise<AgentRun> {
  const response = await fetch(`${apiBaseUrl}/agent-runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ vehicle_id: vehicleId }),
  });
  if (!response.ok) {
    throw await apiError(response, "The agent workflow could not be started.");
  }
  return response.json() as Promise<AgentRun>;
}

async function resumeAgentRun(apiBaseUrl: string, runId: string): Promise<AgentRun> {
  const response = await fetch(`${apiBaseUrl}/agent-runs/${runId}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  if (!response.ok) {
    throw await apiError(response, "The agent workflow could not be resumed.");
  }
  return response.json() as Promise<AgentRun>;
}

function formatEventType(eventType: string): string {
  const words = eventType.replaceAll("_", " ").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function formatEventDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : eventDateFormatter.format(date);
}

function AgentActivity({ events }: { events: AgentEvent[] }) {
  const headingId = useId();

  return <section className="agent-activity" aria-labelledby={headingId}>
    <div className="agent-workflow-section-heading">
      <h4 id={headingId}>Agent activity</h4>
      <span>{events.length} event{events.length === 1 ? "" : "s"}</span>
    </div>
    {!events.length && <p className="muted">No workflow activity has been recorded yet.</p>}
    {!!events.length && <ol aria-label="Agent activity" className="agent-activity-list">
      {events.map((event) => <li key={event.id}>
        <div className="agent-event-heading">
          <strong>{formatEventType(event.event_type)}</strong>
          <time dateTime={event.created_at}>{formatEventDate(event.created_at)}</time>
        </div>
        <p>{event.message}</p>
        <span className="agent-event-node">{event.node.replaceAll("_", " ")}</span>
      </li>)}
    </ol>}
  </section>;
}

export function AgentWorkflow({
  apiBaseUrl,
  candidate,
}: {
  apiBaseUrl: string;
  candidate: OutreachCandidate;
}) {
  const headingId = useId();
  const [run, setRun] = useState<AgentRun | null>(null);
  const createMutation = useMutation({
    mutationFn: () => createAgentRun(apiBaseUrl, candidate.id),
    onSuccess: setRun,
  });
  const resumeMutation = useMutation({
    mutationFn: (runId: string) => resumeAgentRun(apiBaseUrl, runId),
    onSuccess: setRun,
  });

  const resume = async () => {
    if (!run || resumeMutation.isPending) return;
    await resumeMutation.mutateAsync(run.run_id);
  };

  const mutationError = createMutation.error ?? resumeMutation.error;

  if (!run) {
    return <section className="agent-workflow agent-workflow-empty" aria-labelledby={headingId}>
      <p className="eyebrow">Agent workflow</p>
      <h4 id={headingId}>Carry this dealer interaction forward</h4>
      <p>Prepare the next safe action, then pause for real approval and dealer-response events.</p>
      <button
        disabled={createMutation.isPending}
        onClick={() => createMutation.mutate()}
        type="button"
      >
        {createMutation.isPending ? "Starting…" : "Start agent workflow"}
      </button>
      {mutationError && <p className="error" role="alert">{mutationError.message}</p>}
    </section>;
  }

  const presentation = phasePresentations[run.phase];
  const reviewLabel = run.phase === "WAITING_FOR_APPROVAL"
    ? "Review approval"
    : "View dealer interaction";

  return <section className="agent-workflow" aria-labelledby={headingId}>
    <div className="agent-workflow-heading">
      <div>
        <p className="eyebrow">Agent workflow</p>
        <h4 id={headingId}>{candidate.dealer_name}</h4>
      </div>
      <code>{run.run_id}</code>
    </div>

    <div className={`agent-workflow-state agent-workflow-state-${presentation.tone}`} role="status">
      <strong>{presentation.title}</strong>
      <span>{presentation.description}</span>
    </div>

    <AgentActivity events={run.events} />

    <div className="agent-workflow-actions">
      {run.current_action_id && <OutreachApproval
        apiBaseUrl={apiBaseUrl}
        candidate={candidate}
        controlledButtonLabel={reviewLabel}
        currentActionId={run.current_action_id}
        initialActionId={run.initial_action_id}
        key={`${run.initial_action_id}:${run.current_action_id}`}
        onAuthoritativeEvent={resume}
      />}
      {presentation.resumable && <button
        className="secondary-button"
        disabled={resumeMutation.isPending}
        onClick={() => void resume()}
        type="button"
      >
        {resumeMutation.isPending ? "Resuming…" : "Resume from latest state"}
      </button>}
    </div>

    {mutationError && <p className="error" role="alert">{mutationError.message}</p>}
  </section>;
}
