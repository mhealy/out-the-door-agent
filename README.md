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

This command requires both explicit `OTD_RUN_LIVE_EVALS=1` consent and `OTD_OPENAI_API_KEY`. Missing consent, missing credentials, or provider failures produce a non-zero result; unrun evaluations are never reported as passing. The harness reports actual aggregate scalar, collection, condition, missing-information, and evidence-attribution metrics. Normal pytest runs from either the backend directory or repository root exclude live evaluations and use injected fakes.

Reference `gpt-5.6` run on August 19, 2026 (15/15 cases completed):

| Metric | Result |
|---|---:|
| Fully correct cases | 12/15 (80.0%) |
| Scalar exact accuracy | 105/105 (100.0%) |
| Fee/add-on/incentive sets | 58/60 (96.7%) |
| Condition accuracy | 34/34 (100.0%) |
| Missing-information concepts | 33/34 (97.1%) |
| Evidence attribution | 185/186 (99.5%) |

The reference command exited non-zero because strict per-case assertions preserved three quality failures: two government-fee items were inferred as mandatory without that exact status being stated, and one plus-TTL response produced a reasonable but unlabeled question about “the rest.” These are reported rather than converted into a fabricated pass.

## Demo mode

Start both applications and open `http://localhost:5173`. The top workspace searches the canonical Houston-area fixture inventory. In **Dealer response lab**, choose one of 15 raw response fixtures and select **Analyze response**. With a configured model key, the original message appears beside its typed quote extraction; evidence actions reveal exact supporting excerpts. Incomplete responses retain missing fields, conditional incentives remain conditional, and hostile instructions embedded in dealer text remain inert.

## Design principles

- Evidence supports economically important claims.
- Deterministic code owns arithmetic, constraints, policy, ranking, authorization, and state transitions.
- LLMs are reserved for bounded semantic interpretation.
- Human approval is required before outbound dealer communication.
- Fixture providers will exercise the same application paths as live providers.
- SQLite and a single application deployment are intentional for this assessment.

## Known limitations

Criteria interpretation remains a fixture implementation limited to the canonical Hyundai Tucson Hybrid vocabulary. Quote analysis requires an OpenAI API key and has not yet added persistence for extracted quote records. There is no live inventory, outbound dealer messaging, approval flow, quote completeness/reconciliation policy, comparison or ranking, LangGraph orchestration, or event streaming. Those capabilities remain intentionally deferred to later issues.

## Productionization

The assessment uses SQLite to minimize operational overhead. A production deployment would move domain persistence and LangGraph checkpoints to logically separate PostgreSQL-backed stores, use object storage for attachments, add production authentication and secret management, configure structured telemetry, and replace fixture providers selectively. Those changes should follow measured needs; the domain/provider boundaries are intended to make them incremental rather than require an architectural rewrite.
