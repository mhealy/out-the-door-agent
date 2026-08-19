# OutTheDoor

OutTheDoor is an agentic AI buyer advocate for vehicle purchasing. It is designed to acquire and interpret written dealer offers, preserve evidence for material financial claims, and compare true out-the-door economics while keeping outbound dealer communication under explicit human control. The current vertical slice accepts a natural-language purchase goal, displays its interpreted constraints and preferences, and returns a deterministic shortlist from normalized fixture inventory.

> Screenshot/GIF placeholder — the buyer workspace will be demonstrated after the inventory and quote phases are implemented.

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

LangGraph orchestration is intentionally deferred to Phase 4.
```

The backend keeps domain contracts, deterministic services, external providers, API routes, orchestration, and persistence in separate packages. Phase 1 implements only the contracts and infrastructure needed for a clean starting point.

## Tech stack

- Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, SQLite, pytest
- React, TypeScript, Vite, TanStack Query
- LangGraph is part of the planned stack but is not installed or implemented in Phase 1

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

Copy `.env.example` to `.env` at the repository root if you want to override defaults. Do not commit `.env` files or credentials.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `OTD_APP_NAME` | `OutTheDoor API` | API display name |
| `OTD_ENVIRONMENT` | `development` | Runtime environment label |
| `OTD_DATABASE_URL` | `sqlite:///./out_the_door.db` | SQLAlchemy database URL |
| `OTD_CORS_ORIGINS` | `["http://localhost:5173"]` | JSON array of allowed origins |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Frontend API base URL |

No API keys are required in Phase 1.

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

## Checks

Run backend tests from `backend/`:

```powershell
pytest
```

Run the frontend production check from `frontend/`:

```powershell
npm run build
```

Run the deterministic fixture-interpreter and application tests with:

```powershell
pytest
```

## Demo mode

Start both applications, open `http://localhost:5173`, review or edit the example Houston-area purchase goal, and select **Search inventory**. The interpreted constraints, preferences, assumptions or ambiguities, and qualified fixture vehicles appear on the same page.

## Design principles

- Evidence supports economically important claims.
- Deterministic code owns arithmetic, constraints, policy, ranking, authorization, and state transitions.
- LLMs are reserved for bounded semantic interpretation.
- Human approval is required before outbound dealer communication.
- Fixture providers will exercise the same application paths as live providers.
- SQLite and a single application deployment are intentional for this assessment.

## Known limitations

Criteria interpretation is currently a fixture implementation limited to the canonical Hyundai Tucson Hybrid demo vocabulary. There is no configured model-backed interpreter, live inventory, agent orchestration, dealer messaging, quote analysis, event streaming, or polished final-product UI yet. These capabilities remain deferred according to the phased engineering plan.

## Productionization

The assessment uses SQLite to minimize operational overhead. A production deployment would move domain persistence and LangGraph checkpoints to logically separate PostgreSQL-backed stores, use object storage for attachments, add production authentication and secret management, configure structured telemetry, and replace fixture providers selectively. Those changes should follow measured needs; the domain/provider boundaries are intended to make them incremental rather than require an architectural rewrite.
