import { useCallback, useEffect, useId, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { OutreachApproval, type OutreachCandidate } from "./OutreachApproval";

export type RunPhase =
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

export type AgentRun = {
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

export type AgentRunSnapshot = Pick<
  AgentRun,
  "run_id" | "vehicle_id" | "phase" | "updated_at"
>;

type ApiErrorDetail = {
  code?: string;
  message?: string;
  run_id?: string;
};

type ApiErrorPayload = {
  detail?: string | ApiErrorDetail;
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

class RecoverableAgentRunError extends Error {
  readonly runId: string;

  constructor(runId: string, message: string) {
    super(message);
    this.name = "RecoverableAgentRunError";
    this.runId = runId;
  }
}

async function inspectAgentRun(apiBaseUrl: string, runId: string): Promise<AgentRun> {
  const response = await fetch(`${apiBaseUrl}/agent-runs/${runId}`);
  if (!response.ok) {
    throw await apiError(response, "The existing agent workflow could not be inspected.");
  }
  return response.json() as Promise<AgentRun>;
}

async function createAgentRun(apiBaseUrl: string, vehicleId: string): Promise<AgentRun> {
  const response = await fetch(`${apiBaseUrl}/agent-runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ vehicle_id: vehicleId }),
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as ApiErrorPayload | null;
    const detail = payload?.detail;
    const structuredDetail = typeof detail === "object" ? detail : null;
    const recoverableRunId = structuredDetail?.code === "agent_run_advancement_failed"
      && typeof structuredDetail.run_id === "string"
      ? structuredDetail.run_id.trim()
      : "";
    const message = typeof detail === "string"
      ? detail
      : structuredDetail?.message ?? "The agent workflow could not be started.";

    if (recoverableRunId) {
      try {
        return await inspectAgentRun(apiBaseUrl, recoverableRunId);
      } catch {
        throw new RecoverableAgentRunError(recoverableRunId, message);
      }
    }
    throw new Error(message);
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
  authoritativeActionId,
  authorizationRequired,
  candidate,
  initialRun,
  onRunChange,
}: {
  apiBaseUrl: string;
  authoritativeActionId?: string | null;
  authorizationRequired?: boolean;
  candidate: OutreachCandidate;
  initialRun?: AgentRun;
  onRunChange?: (run: AgentRunSnapshot) => void;
}) {
  const headingId = useId();
  const [run, setRun] = useState<AgentRun | null>(initialRun ?? null);
  const [recoverableRunId, setRecoverableRunId] = useState<string | null>(null);
  useEffect(() => {
    if (!initialRun) return;
    setRun((current) => (
      current?.run_id === initialRun.run_id
      && current.updated_at === initialRun.updated_at
        ? current
        : initialRun
    ));
  }, [initialRun]);
  const adoptRun = useCallback((nextRun: AgentRun) => {
    setRun(nextRun);
    onRunChange?.({
      run_id: nextRun.run_id,
      vehicle_id: nextRun.vehicle_id,
      phase: nextRun.phase,
      updated_at: nextRun.updated_at,
    });
  }, [onRunChange]);
  const createMutation = useMutation({
    mutationFn: () => createAgentRun(apiBaseUrl, candidate.id),
    onError: (error) => {
      if (error instanceof RecoverableAgentRunError) {
        setRecoverableRunId(error.runId);
      }
    },
    onSuccess: (createdRun) => {
      setRecoverableRunId(null);
      adoptRun(createdRun);
    },
    retry: false,
  });
  const recoverMutation = useMutation({
    mutationFn: (runId: string) => inspectAgentRun(apiBaseUrl, runId),
    onSuccess: (recoveredRun) => {
      createMutation.reset();
      setRecoverableRunId(null);
      adoptRun(recoveredRun);
    },
    retry: false,
  });
  const resumeMutation = useMutation({
    mutationFn: (runId: string) => resumeAgentRun(apiBaseUrl, runId),
    onSuccess: adoptRun,
    retry: false,
  });

  const resume = async () => {
    if (!run || resumeMutation.isPending) return;
    await resumeMutation.mutateAsync(run.run_id);
  };

  const mutationError = recoverMutation.error ?? createMutation.error ?? resumeMutation.error;

  if (!run) {
    return <section className="agent-workflow agent-workflow-empty" aria-labelledby={headingId}>
      <p className="eyebrow">Agent workflow</p>
      <h4 id={headingId}>Carry this dealer interaction forward</h4>
      <p>Prepare the next safe action, then pause for real approval and dealer-response events.</p>
      {recoverableRunId
        ? <button
          disabled={recoverMutation.isPending}
          onClick={() => recoverMutation.mutate(recoverableRunId)}
          type="button"
        >
          {recoverMutation.isPending ? "Recovering…" : "Recover existing workflow"}
        </button>
        : <button
          disabled={createMutation.isPending}
          onClick={() => createMutation.mutate()}
          type="button"
        >
          {createMutation.isPending ? "Starting…" : "Start agent workflow"}
        </button>}
      {mutationError && <p className="error" role="alert">{mutationError.message}</p>}
    </section>;
  }

  const presentation = phasePresentations[run.phase];
  const authorizationEnabled = authorizationRequired ?? run.phase === "WAITING_FOR_APPROVAL";
  const reviewLabel = authorizationEnabled
    ? "Review approval"
    : "View dealer interaction";
  const phaseActionIdForReview = run.phase === "STARTING"
    ? null
    : authorizationEnabled || run.phase === "DELIVERY_UNCONFIRMED"
      ? run.current_action_id
      : run.initial_action_id;
  const actionIdForReview = authorizationEnabled && authorizationRequired !== undefined
    ? authoritativeActionId ?? null
    : authoritativeActionId ?? phaseActionIdForReview;

  return <section className="agent-workflow" aria-labelledby={headingId}>
    <div className="agent-workflow-heading">
      <div>
        <p className="eyebrow">Agent workflow</p>
        <h4 id={headingId}>{candidate.dealer_name}</h4>
      </div>
      <code>{run.run_id}</code>
    </div>

    {authorizationRequired !== undefined && <p className="agent-workflow-authority-note">
      The purchase status above is authoritative. This phase is the orchestrator’s latest observation.
    </p>}

    <div className={`agent-workflow-state agent-workflow-state-${presentation.tone}`} role="status">
      <strong>{presentation.title}</strong>
      <span>{presentation.description}</span>
    </div>

    <AgentActivity events={run.events} />

    <div className="agent-workflow-actions">
      {actionIdForReview && <OutreachApproval
        apiBaseUrl={apiBaseUrl}
        authorizationEnabled={authorizationEnabled}
        candidate={candidate}
        controlledButtonLabel={reviewLabel}
        currentActionId={actionIdForReview}
        initialActionId={run.initial_action_id}
        key={`${run.initial_action_id}:${actionIdForReview}`}
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
