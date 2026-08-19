# OutTheDoor

OutTheDoor is an agentic AI buyer advocate for vehicle purchasing. It is designed to acquire and interpret written dealer offers, preserve evidence for material financial claims, and compare true out-the-door economics while keeping outbound dealer communication under explicit human control. The current vertical slices provide deterministic fixture inventory search and bounded model-backed analysis of fixture dealer responses, including structured pricing terms, conditions, unresolved questions, and source-traceable evidence.

> Screenshot/GIF placeholder — the buyer workspace now includes inventory search and the dealer-response analysis lab; a polished demo capture remains follow-up documentation work.

## Architecture

```text
React + TypeScript buyer workspace
              │ REST (SSE in a later phase)
              ▼
          FastAPI API
              │
       domain / services / providers
              │
              ▼
     SQLAlchemy 2 + SQLite

LangGraph orchestration is intentionally deferred to a later issue. Quote extraction is a task-scoped provider call with no tools; deterministic services validate every evidence reference and source excerpt before returning it to the UI.
```

The backend keeps domain contracts, deterministic services, external providers, API routes, orchestration, and persistence in separate packages. The implemented vertical slices stay within those boundaries while later orchestration and purchasing capabilities remain deferred.

`OpenAIQuoteExtractor` is the currently configured concrete extraction adapter. `QuoteAnalysisService`, API code, and domain code depend on the small `QuoteExtractor` protocol and never receive OpenAI Responses objects. A future provider can implement that same contract without changing quote analysis or deterministic evidence policy; this slice intentionally adds no provider routing or generic model configuration layer.

## Tech stack

- Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, SQLite, OpenAI Python SDK, pytest
- React, TypeScript, Vite, TanStack Query
- LangGraph is part of the planned stack but is not installed or implemented yet

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
| `OTD_CORS_ORIGINS` | `["http://localhost:5173"]` | JSON array of allowed origins |
| `OTD_QUOTE_EXTRACTION_MODEL` | `gpt-5.6` | Structured-output model used for dealer quote extraction |
| `OTD_OPENAI_API_KEY` | none | Secret used only by the configured quote extractor |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Frontend API base URL |

The model API key is required only when analyzing a dealer response. It is held as a secret setting and is never returned by the API.

## Run locally

Start the backend from `backend/` after activating its virtual environment:

```powershell
uvicorn app.main:app --reload
```

The API is available at `http://localhost:8000`; `GET /health` returns `{"status":"ok"}`. The local SQLite schema is created at startup.

Start the frontend from `frontend/` in another terminal:

```powershell
npm run dev
```

Vite serves the app at `http://localhost:5173` by default.

Alternatively, Docker users can start both applications from the repository root:

```powershell
docker compose up --build
```

Compose pins the container database to `/data/out_the_door.db` so the named volume remains authoritative; the local `OTD_DATABASE_URL` value is used by non-container runs.

## Checks

Run backend tests from `backend/`:

```powershell
pytest
```

Run the frontend production check from `frontend/`:

```powershell
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

Start both applications and open `http://localhost:5173`. The top workspace searches the canonical Houston-area fixture inventory. In **Dealer response lab**, choose one of 15 raw response fixtures and select **Analyze response**. With a configured model key, the original message appears beside its typed quote extraction; evidence actions reveal exact supporting excerpts. Incomplete responses retain missing fields, conditional incentives remain conditional, and hostile instructions embedded in dealer text remain inert.

## Design principles

- Evidence supports economically important claims.
- Deterministic code owns arithmetic, constraints, policy, ranking, authorization, and state transitions.
- LLMs are reserved for bounded semantic interpretation.
- Quote extraction records what the dealer stated, including explicitly sourced uncertainty; deterministic completeness and follow-up policy belong to later issues.
- Human approval is required before outbound dealer communication.
- Fixture providers will exercise the same application paths as live providers.
- SQLite and a single application deployment are intentional for this assessment.

## Known limitations

Criteria interpretation remains a fixture implementation limited to the canonical Hyundai Tucson Hybrid vocabulary. Quote analysis requires an OpenAI API key and has not yet added persistence for extracted quote records. There is no live inventory, outbound dealer messaging, approval flow, quote completeness/reconciliation policy, comparison or ranking, LangGraph orchestration, or event streaming. Those capabilities remain intentionally deferred to later issues.

## Productionization

The assessment uses SQLite to minimize operational overhead. A production deployment would move domain persistence and LangGraph checkpoints to logically separate PostgreSQL-backed stores, use object storage for attachments, add production authentication and secret management, configure structured telemetry, and replace fixture providers selectively. Those changes should follow measured needs; the domain/provider boundaries are intended to make them incremental rather than require an architectural rewrite.
