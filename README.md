# OutTheDoor

OutTheDoor is an AI buyer advocate that turns qualified vehicle listings and messy
dealer correspondence into an evidence-backed purchase decision. A buyer selects two to
five dealers; one durable purchase coordinates independent, checkpointed dealer
workflows; every exact outbound message requires approval; raw responses are persisted
before semantic extraction; deterministic code validates evidence, completeness, and
arithmetic; and only verified written offers can rank. The canonical demo reveals why a
slightly higher listing can be the better transaction: Baytown wins at $40,315 written
OTD even though Houston looked $550 cheaper online.

## Final product story

```text
buyer goal
  → deterministic qualified inventory
  → durable PurchaseRun with independent dealer AgentRuns
  → exact proposal and human approval
  → persisted dealer response
  → structured extraction and source validation
  → deterministic assessment and bounded clarification
  → verified-offer comparison
  → optional bounded add-on research
  → best verified offer
```

The final fixture economics are intentionally fixed:

| Dealer | Advertised | Written/stated OTD | Status |
|---|---:|---:|---|
| Baytown Hyundai | $37,800 | **$40,315** | Verified; no mandatory add-ons; winner |
| Houston Hyundai | $37,250 | $41,780 | Verified; Ceramic Shield $1,299 and SecureTrack $596 mandatory |
| Katy Hyundai | $39,500 | $40,250 | Incomplete; cannot rank |

Houston appears $550 cheaper in inventory, but Baytown saves $1,465 in verified written
OTD. “Verified” means evidence-backed and comparable under application policy; it is not
a guarantee that a dealer will honor the quote.

## Architecture

```text
React buyer workspace
        │ explicit REST actions and refetch
        ▼
FastAPI application services ─── fixture/model provider seams
        │
        ├── application SQLite: business truth, evidence, authorization
        │
        └── single-dealer LangGraph children
                  └── separate checkpoint SQLite
```

`PurchaseRun` is a durable coordinator/read model, not another graph. Each selected
dealer receives one instance of the same single-dealer LangGraph workflow. The purchase
activity feed is a read-only projection over persisted child events and never drives
current state.

> **LangGraph coordinates capabilities. Application services own truth, policy,
> authorization, and side effects.**

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the concise ownership, persistence,
evidence, recovery, and research boundaries.

### Deterministic versus probabilistic work

| Deterministic application responsibility | Bounded model responsibility |
|---|---|
| Constraint filtering and shortlist policy | Dealer quote extraction |
| Evidence/source validation | Follow-up wording from code-owned requirements |
| Quote completeness, transparency, and arithmetic | Research synthesis from bounded sources |
| Status transitions and follow-up limits | |
| Exact authorization and messaging side effects | |
| Ranking, recommendation, and savings | |
| Research target identity, freshness, and provenance | |

Dealer messages and external sources are untrusted data. Model adapters are task-scoped,
structured-output only, and have no tools or side-effect authority.

## Tech stack

- Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, SQLite, LangGraph, OpenAI SDK,
  pytest
- React 19, TypeScript, Vite, TanStack Query, Vitest
- Separate application and LangGraph checkpoint SQLite files

## Prerequisites

- Python 3.12 or newer
- Node.js 20.19 or newer and npm
- Docker with Compose, optional

## Setup

From the repository root, create and install the backend environment:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Install frontend dependencies:

```powershell
cd ..\frontend
npm ci
```

Copy `.env.example` to `.env` at the repository root. Add
`OTD_OPENAI_API_KEY` for live quote extraction, follow-up drafting, and research
synthesis. Never commit `.env` or credentials.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `OTD_ENVIRONMENT` | `development` | Runtime label; reset refuses production-like values |
| `OTD_DATABASE_URL` | `sqlite:///./out_the_door.db` | Application persistence |
| `OTD_LANGGRAPH_CHECKPOINT_PATH` | `./out_the_door_checkpoints.db` | Separate graph checkpoints |
| `OTD_CORS_ORIGINS` | `["http://localhost:5173"]` | Allowed browser origins |
| `OTD_QUOTE_EXTRACTION_MODEL` | `gpt-5.6` | Quote structured output |
| `OTD_FOLLOWUP_DRAFTING_MODEL` | `gpt-5.6` | Follow-up structured output |
| `OTD_RESEARCH_SYNTHESIS_MODEL` | `gpt-5.6` | Research structured output |
| `OTD_OPENAI_API_KEY` | none | Local model credential |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Frontend API target |

## Reset and preflight

Stop running applications first. For a host-based run, use the configured host stores
from `backend/` with the environment active:

```powershell
python -m app.demo reset
python -m app.demo preflight
```

Reset is local/demo-only, accepts no path arguments, clears only the configured distinct
SQLite stores, recreates their schemas, and never modifies fixture files. Preflight
checks canonical inventory, dealer messages, labeled expected outputs, research sources,
database/checkpoint usability, configuration, frontend target syntax, and model-key
presence. It never calls a model or validates the key remotely. A missing key truthfully
means the complete live UI demo is not ready, while deterministic tests remain usable.

For Docker Compose, reset and inspect the named-volume stores from the repository root
instead of the separate host files:

```powershell
docker compose down
docker compose build
docker compose run --rm backend python -m app.demo reset
docker compose run --rm backend python -m app.demo preflight
```

## Run

Start the backend from `backend/`:

```powershell
uvicorn app.main:app --reload
```

Start the frontend from `frontend/` in another terminal:

```powershell
npm run dev
```

Open `http://localhost:5173`. The API health endpoint is
`http://localhost:8000/health`.

After the Compose reset/preflight above, launch from the repository root:

```powershell
docker compose up
```

Compose stores application and checkpoint data in separate files inside one named
volume.

## Canonical demo

Search with:

> Find a new 2025 or 2026 Hyundai Tucson Hybrid Limited within 40 miles of
> Houston under $40,000. I require AWD. I care most about true out-the-door
> price.

Select Baytown, Houston, and Katy, then choose **Start buying agent**. Creation prepares
three messages and sends zero. Review and approve each exact request individually. Use
the explicitly labeled demo controls to release fixture dealer responses and resume only
the relevant durable child when needed.

The workspace should show two verified offers, Katy incomplete with one clarification
awaiting approval, a compact cross-dealer activity history, dealer evidence for material
quote facts, and separate independent research for current Houston add-ons. Research
must leave comparison economics unchanged.

Follow [docs/DEMO.md](docs/DEMO.md) for the exact 5–7 minute sequence and truthful
live-provider fallback.

## Tests and checks

Run the default backend suite from `backend/`:

```powershell
python -m pytest
python -m compileall -q app
```

The default pytest configuration excludes tests marked `eval`.

Run the deterministic canonical reviewer smoke:

```powershell
python -m pytest tests/integration/test_canonical_demo_smoke.py -q
```

The smoke uses committed labeled quote outputs at the extraction boundary and
code-defined deterministic test doubles at the follow-up-drafting and
research-synthesis boundaries. It still exercises real APIs, services, persistence,
checkpoints, approval, fixture messaging, inbound analysis, evidence, comparison,
activity, and fixture research retrieval. It is not presented as a live-model
evaluation.

Run frontend tests and the production build from `frontend/`:

```powershell
npm test
npm run build
```

Normal CI runs those backend and frontend commands on pull requests and pushes to
`main`, without secrets or paid model calls.

### Live model evaluations

Live evals require explicit consent and a configured key:

```powershell
$env:OTD_RUN_LIVE_EVALS="1"
python -m pytest -m eval tests/evals
```

Missing consent, missing credentials, or provider failures are not reported as passes.
The most recent documented `gpt-5.6` reference runs were 15/15 strict quote-extraction
cases on August 19, 2026 and 9/9 strict research-synthesis cases on August 20, 2026.
Future runs may vary; the command output is authoritative for the run being discussed.

## Design principles

- Evidence supports every material transaction claim.
- Deterministic code owns math, constraints, policy, ranking, authorization, and state.
- Models are reserved for bounded semantic interpretation.
- Every outbound dealer message requires exact, individual approval.
- Application business state is authoritative; graph phase is the last observation.
- Activity is observational history, never business truth.
- Fixture responses use the same inbound path as external responses would.
- Explicit resume replaces sleeping processes, polling workers, and hidden auto-advance.

## Known limitations

- Criteria interpretation is fixture-backed and intentionally limited to the canonical
  Hyundai Tucson Hybrid vocabulary.
- Quote extraction, follow-up drafting, and research synthesis require a live model key
  in the UI; there is no hidden runtime success fallback.
- Inventory, dealer contacts, messaging, responses, and research retrieval are fixtures.
- Each interaction has one deterministic demo response. Katy remains unresolved after
  its clarification is prepared; no second response is fabricated.
- Research sources provide external context, not proof of the dealer's exact package,
  coverage, duration, exclusions, or value.
- There is no automatic background resume, Gmail transport, live inventory, negotiation,
  financing/trade optimization, authentication, payment, deposit, or purchase execution.
- Delivery remains fail-closed. A production transport needs idempotency and
  reconciliation before retrying an unconfirmed send.
- SQLite is appropriate for the take-home, not a claim of production scale.

## Productionization

A production deployment would move application and checkpoint persistence to logically
separate PostgreSQL-backed stores, add transport idempotency/reconciliation, managed
authentication and secrets, object storage for attachments, and measured structured
telemetry. Live inventory, messaging, and research providers can replace fixtures behind
the existing seams. These changes do not move policy, authorization, arithmetic, or
ranking into LangGraph or models.
