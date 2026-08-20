# OutTheDoor

OutTheDoor is an agentic AI buyer advocate for vehicle purchasing. It is designed to acquire and interpret written dealer offers, preserve evidence for material financial claims, and compare true out-the-door economics while keeping outbound dealer communication under explicit human control. The current vertical slices provide deterministic fixture inventory search, durable single-dealer LangGraph workflows, approval-gated initial and follow-up messages, evidence-backed dealer-response analysis, and deterministic vehicle-identity, quote-completeness, transparency, and arithmetic assessment.

> Screenshot/GIF placeholder — the buyer workspace now includes inventory search, durable workflow status/activity, exact-message outreach approval, and evidence-backed dealer-response analysis; a polished demo capture remains follow-up documentation work.

## Architecture

```text
React + TypeScript buyer workspace
              │ explicit REST events/resume
              ▼
          FastAPI API
              │
     LangGraph sequencing and waits
              │
       domain / services / providers
              │
       ┌──────┴─────────┐
       ▼                ▼
application SQLite   checkpoint SQLite
```

LangGraph owns only sequencing, routing, durable waiting, and checkpointed resume for one selected dealer/vehicle interaction. Every resume reloads authoritative application records. Existing services continue to own quote policy, evidence, follow-up requirements and limits, source freshness, exact approval content, dealer contacts, and messaging side effects. Initial outreach is composed deterministically because application policy already knows every required field; immutable proposals, exact approval snapshots, and delivery receipts are persisted before and after the fixture transport boundary. Quote extraction is a task-scoped provider call with no tools; deterministic services validate every evidence reference and source excerpt before applying comparison requirements and Decimal-based arithmetic.

The backend keeps domain contracts, deterministic services, external providers, API routes, orchestration, and persistence in separate packages. The implemented vertical slices stay within those boundaries while later orchestration and purchasing capabilities remain deferred.

`OpenAIQuoteExtractor` is the currently configured concrete extraction adapter. `QuoteAnalysisService`, API code, and domain code depend on the small `QuoteExtractor` protocol and never receive OpenAI Responses objects. A future provider can implement that same contract without changing quote analysis or deterministic evidence policy; this slice intentionally adds no provider routing or generic model configuration layer.

## Tech stack

- Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, SQLite, LangGraph, OpenAI Python SDK, pytest
- React, TypeScript, Vite, TanStack Query
- Separate application and LangGraph checkpoint SQLite stores

## Prerequisites

- Python 3.12 or newer
- Node.js 20 or newer and npm

## Setup

From the repository root, create the backend environment:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Install frontend dependencies:

```powershell
cd frontend
npm ci
```

Copy `.env.example` to `.env` at the repository root. Add `OTD_OPENAI_API_KEY` to enable dealer-response analysis. Do not commit `.env` files or credentials. Inventory search and fixture browsing remain available without a model key; analysis fails visibly with a configuration error rather than substituting fabricated data.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `OTD_APP_NAME` | `OutTheDoor API` | API display name |
| `OTD_ENVIRONMENT` | `development` | Runtime environment label |
| `OTD_DATABASE_URL` | `sqlite:///./out_the_door.db` | SQLAlchemy database URL |
| `OTD_LANGGRAPH_CHECKPOINT_PATH` | `./out_the_door_checkpoints.db` | Separate durable LangGraph checkpoint file |
| `OTD_CORS_ORIGINS` | `["http://localhost:5173"]` | JSON array of allowed origins |
| `OTD_QUOTE_EXTRACTION_MODEL` | `gpt-5.6` | Structured-output model used for dealer quote extraction |
| `OTD_FOLLOWUP_DRAFTING_MODEL` | `gpt-5.6` | Structured-output model used only for bounded follow-up wording |
| `OTD_OPENAI_API_KEY` | none | Secret used only by the configured quote extractor |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Frontend API base URL |

The model API key is required only when analyzing a dealer response. It is held as a secret setting and is never returned by the API.

## Run locally

Start the backend from `backend/` after activating its virtual environment:

```powershell
uvicorn app.main:app --reload
```

The API is available at `http://localhost:8000`; `GET /health` returns `{"status":"ok"}`. Application tables are created at startup, and the separate checkpoint schema is initialized on the first agent run.

Start the frontend from `frontend/` in another terminal:

```powershell
npm run dev
```

Vite serves the app at `http://localhost:5173` by default.

Alternatively, Docker users can start both applications from the repository root:

```powershell
docker compose up --build
```

Compose pins the application and checkpoint databases to separate files under `/data` so the named volume remains authoritative; local settings are used by non-container runs.

## Checks

Run backend tests from `backend/`:

```powershell
pytest
```

Run the frontend production check from `frontend/`:

```powershell
npm test
npm run build
```

Run the opt-in live model evaluation suite with:

```powershell
$env:OTD_RUN_LIVE_EVALS="1"
pytest -m eval tests/evals
```

This command requires both explicit `OTD_RUN_LIVE_EVALS=1` consent and `OTD_OPENAI_API_KEY`. Missing consent, missing credentials, or provider failures produce a non-zero result; unrun evaluations are never reported as passing. The harness reports actual aggregate scalar, collection, condition, source-grounded uncertainty, and evidence-attribution metrics. Normal pytest runs from either the backend directory or repository root exclude live evaluations and use injected fakes.

Reference `gpt-5.6` run on August 19, 2026 (15/15 cases completed):

| Metric | Result |
|---|---:|
| Fully correct cases | 15/15 (100.0%) |
| Scalar exact accuracy | 105/105 (100.0%) |
| Fee/add-on/incentive sets | 60/60 (100.0%) |
| Condition accuracy | 34/34 (100.0%) |
| Source-grounded uncertainty | 33/33 (100.0%) |
| Evidence attribution | 188/188 (100.0%) |

This post-correction reference command passed all strict assertions. The initial evaluation remains part of the development record: it completed 15/15 calls but passed 12/15 cases, with 105/105 scalar, 58/60 collection, 34/34 condition, 33/34 missing-information-concept, and 185/186 evidence checks. Its two government-fee mandatory-status over-attributions and one omission-derived plus-TTL question led to general semantic corrections rather than fixture-specific exceptions. The uncertainty denominator changed after the labels were narrowed from omission-derived missing information to source-grounded uncertainty, so that metric is not a like-for-like percentage comparison. As with any live model evaluation, a future run may vary and should be reported as observed.

## Demo mode

Start both applications and open `http://localhost:5173`. The top workspace searches the canonical Houston-area fixture inventory. Each candidate can start one durable agent workflow. The workflow prepares the existing immutable quote request, stops at the real approval boundary, resumes only after an explicit application event, and shows persisted user-safe activity. The approval dialog still shows the exact candidate, fictitious `.example.test` recipient, subject, full body, reason, and requested-information checklist before any send. After confirmed delivery, the fixture response can be released and analyzed through the existing boundary; an incomplete assessment causes the graph to invoke the existing approval-gated follow-up service.

In **Dealer response lab**, choose one of 15 raw response fixtures and select **Analyze response**. With a configured model key, the original message appears beside its typed quote extraction and deterministic assessment; evidence actions reveal exact supporting excerpts. The assessment shows comparable, transparent, and reconciled states independently, separates source-stated uncertainty from application-policy gaps, and explains reconciliation as known line items minus claimed OTD.

## Design principles

- Evidence supports economically important claims.
- Deterministic code owns arithmetic, constraints, policy, ranking, authorization, and state transitions.
- LLMs are reserved for bounded semantic interpretation.
- Initial quote-request wording is deterministic and immutable because its economic content is fully specified by application policy.
- Quote extraction records what the dealer stated, including explicitly sourced uncertainty; deterministic assessment separately owns identity, completeness, transparency, missing requirements, and arithmetic.
- Human approval is required before outbound dealer communication.
- LangGraph coordinates capabilities but never owns business policy or messaging side effects.
- Durable waits use explicit resume and a separate SQLite checkpoint store; there is no polling worker.
- Fixture providers will exercise the same application paths as live providers.
- SQLite and a single application deployment are intentional for this assessment.

## Known limitations

Criteria interpretation remains a fixture implementation limited to the canonical Hyundai Tucson Hybrid vocabulary. Quote analysis and follow-up wording require an OpenAI API key. Outbound messaging is limited to one buyer-selected dealer/vehicle workflow at a time, immutable drafts, fictitious contacts, and a side-effect-free fixture provider. The demo has one deterministic response per interaction, so a sent follow-up truthfully stops at `WAITING_FOR_EXTERNAL_RESPONSE`; it does not fabricate a second response. There is no Gmail transport, draft editing, automatic background resume, durable outbox reconciliation, multi-dealer comparison/ranking, or event streaming.

Delivery is deliberately fail-closed. If the process stops after an approved provider call but before its receipt is persisted, the proposal remains `APPROVED` with delivery unconfirmed and cannot be sent again automatically. A production transport needs idempotency/reconciliation support before an operator prepares any replacement proposal, because an unconfirmed outcome may already have reached the dealer.

## Productionization

The assessment uses SQLite to minimize operational overhead. A production deployment would move domain persistence and LangGraph checkpoints to logically separate PostgreSQL-backed stores, use object storage for attachments, add production authentication and secret management, configure structured telemetry, and replace fixture providers selectively. Those changes should follow measured needs; the domain/provider boundaries are intended to make them incremental rather than require an architectural rewrite.
