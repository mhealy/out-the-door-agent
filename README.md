# OutTheDoor

OutTheDoor is an agentic AI buyer advocate for vehicle purchasing. It is designed to acquire and interpret written dealer offers, preserve evidence for material financial claims, and compare true out-the-door economics while keeping outbound dealer communication under explicit human control. This repository currently contains the Phase 1 application foundation only.

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
npm install
```

Copy `.env.example` to `.env` at the repository root if you want to override defaults. Do not commit `.env` files or credentials.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `OTD_APP_NAME` | `OutTheDoor API` | API display name |
| `OTD_ENVIRONMENT` | `development` | Runtime environment label |
| `OTD_DATABASE_URL` | `sqlite:///./out_the_door.db` | SQLAlchemy database URL |
| `OTD_CORS_ORIGINS` | `["http://localhost:5173"]` | JSON array of allowed origins |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Future frontend API base URL |

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

The AI evaluation suite belongs to Phase 6. Once implemented, its command will be:

```powershell
pytest tests/evals -m eval
```

## Demo mode

Demo fixtures and controlled response release are later-phase work. Phase 1 has no inventory search, dealer messaging, quote analysis, LLM, or agent workflow to demo; both application processes can be started to verify the foundation.

## Design principles

- Evidence supports economically important claims.
- Deterministic code owns arithmetic, constraints, policy, ranking, authorization, and state transitions.
- LLMs are reserved for bounded semantic interpretation.
- Human approval is required before outbound dealer communication.
- Fixture providers will exercise the same application paths as live providers.
- SQLite and a single application deployment are intentional for this assessment.

## Known limitations

Phase 1 is scaffolding only. It does not yet interpret goals, search inventory, orchestrate workflows, send messages, extract quotes, stream events, compare offers, run AI evaluations, or provide a polished product UI. These capabilities are intentionally deferred according to the phased engineering plan.

## Productionization

The assessment uses SQLite to minimize operational overhead. A production deployment would move domain persistence and LangGraph checkpoints to logically separate PostgreSQL-backed stores, use object storage for attachments, add production authentication and secret management, configure structured telemetry, and replace fixture providers selectively. Those changes should follow measured needs; the domain/provider boundaries are intended to make them incremental rather than require an architectural rewrite.
