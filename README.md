# OutTheDoor

OutTheDoor is an agentic AI buyer advocate for vehicle purchasing. It is designed to acquire and interpret written dealer offers, preserve evidence for material financial claims, and compare true out-the-door economics while keeping outbound dealer communication under explicit human control. The current vertical slices provide deterministic fixture inventory search, a durable multi-dealer purchase workspace backed by one single-dealer LangGraph workflow per selected vehicle, approval-gated initial and follow-up messages, evidence-backed dealer-response analysis, deterministic vehicle-identity, quote-completeness, transparency, arithmetic assessment, and offer ranking, plus bounded external research for material mandatory dealer add-ons.

> Screenshot/GIF placeholder — the buyer workspace now includes inventory search, durable workflow status/activity, exact-message outreach approval, evidence-backed dealer-response analysis, verified-offer comparison, and add-on investigation; a polished demo capture remains follow-up documentation work.

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

LangGraph owns only sequencing, routing, durable waiting, and checkpointed resume for one selected dealer/vehicle interaction. Every resume reloads authoritative application records. `PurchaseRun` durably records the buyer goal, ordered vehicle selections, and nullable child-run links; it is a coordinator/read boundary, not another graph. Existing services continue to own quote policy, evidence, follow-up requirements and limits, source freshness, exact approval content, dealer contacts, and messaging side effects. Initial outreach is composed deterministically because application policy already knows every required field; immutable proposals, exact approval snapshots, and delivery receipts are persisted before and after the fixture transport boundary. Quote extraction is a task-scoped provider call with no tools; deterministic services validate every evidence reference and source excerpt before applying comparison requirements and Decimal-based arithmetic. Cross-dealer comparison is a separate recomputable read model: it loads durable child IDs, their latest analyzed interactions, and inventory listing facts without resuming or mutating a workflow. Purchase creation reserves deterministic child identities, so recovery can adopt a child committed before an advancement failure and creates only genuinely missing workflows.

Research is a separate application capability, not a LangGraph node and not an input to quote assessment or comparison. The application reconstructs each research target from the latest persisted authoritative quote, limits eligibility to material mandatory add-ons, and rechecks target freshness before and after model synthesis. A `ResearchProvider` receives only the bounded target identity needed for retrieval. The current `FixtureResearchProvider` returns canonical source excerpts; `OpenAIResearchSynthesizer` receives only that target and source set, has no tools, and returns a strict structured draft. Deterministic validation owns target identity, exact source-ID provenance, bounds, and the final persisted finding. Research failure is visible and preserves retrieved sources when available, without changing the dealer quote, OTD arithmetic, comparability, ranking, or recommendation.

The backend keeps domain contracts, deterministic services, external providers, API routes, orchestration, and persistence in separate packages. The implemented vertical slices stay within those boundaries while later orchestration and purchasing capabilities remain deferred.

`OpenAIQuoteExtractor`, `OpenAIFollowupDrafter`, and `OpenAIResearchSynthesizer` are separate task-scoped structured-output adapters. Application and domain code depend on their small protocols and never receive OpenAI Responses objects. Each adapter can be replaced independently without changing deterministic evidence, comparison, authorization, or research-validation policy; the application intentionally has no generic model-provider abstraction or model routing layer.

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

Copy `.env.example` to `.env` at the repository root. Add `OTD_OPENAI_API_KEY` to enable dealer-response extraction, bounded follow-up drafting, and research synthesis. Do not commit `.env` files or credentials. Inventory search, fixture browsing, and deterministic fixture-backed research retrieval remain available without a model key; model-backed operations fail visibly with a configuration error rather than substituting fabricated data.

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
| `OTD_RESEARCH_SYNTHESIS_MODEL` | `gpt-5.6` | Structured-output model used only for bounded add-on research synthesis |
| `OTD_OPENAI_API_KEY` | none | Secret used by quote extraction, follow-up drafting, and research synthesis |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Frontend API base URL |

The model API key is required when analyzing a dealer response, drafting a bounded follow-up, or synthesizing an add-on investigation. It is held as a secret setting and is never returned by the API.

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

Run only the focused research-synthesis evaluation with:

```powershell
$env:OTD_RUN_LIVE_EVALS="1"
pytest -m eval tests/evals/test_research_synthesis_eval.py -vv
```

Live commands require both explicit `OTD_RUN_LIVE_EVALS=1` consent and `OTD_OPENAI_API_KEY`. Missing consent, missing credentials, or provider failures produce a non-zero result; unrun evaluations are never reported as passing. The harness reports quote-extraction and research-synthesis metrics separately. Normal pytest runs from either the backend directory or repository root exclude live evaluations and use injected fakes.

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

### Research-synthesis evaluation

Reference `gpt-5.6` run on August 20, 2026 (9/9 model cases completed and 9/9 strict model cases passed):

| Metric | Result |
|---|---:|
| Target identity preserved | 9/9 |
| Exact source-ID sets | 9/9 |
| Allowed support status | 9/9 |
| Supported summary concepts | 9/9 |
| Required limitations retained | 9/9 |
| Required disagreements retained | 4/4 |
| Strict insufficient-evidence cases remained insufficient | 2/2 |
| No invented monetary value | 9/9 |
| No prohibited judgment or application action | 9/9 |
| Prompt-injection source remained inert | 1/1 |
| Semantic source support | 9/9 |
| Unsupported product scope absent | 9/9 |
| Semantic disagreements retained | 4/4 |
| Semantic limitations retained | 9/9 |
| Semantic no value or purchase recommendation | 9/9 |
| Semantic no scam, fraud, or trust judgment | 9/9 |
| Semantic no application action | 9/9 |
| Semantic prompt-injection resistance | 1/1 |
| Stale target blocked before model synthesis | 1/1 |

The first `gpt-5.6` research run completed all 9 model cases but passed 5/9 strict cases: target identity was 9/9, exact source IDs 9/9, summary concepts 7/9, limitations 6/9, disagreement 4/4, strict insufficient evidence 2/2, no invented monetary value 9/9, safe language 9/9, prompt-injection resistance 1/1, and stale-target preflight 1/1. A general prompt correction made insufficient evidence and missing dealer-specific limitations explicit. The second run passed 8/9; its sole failure was an evaluator false negative caused by contiguous-phrase matching. The evaluator then changed to token-set concept matching without changing any denominator, and the first post-correction reference run passed 9/9.

An acceptance audit then added a separate typed, tool-free semantic grader, introducing new 9-case semantic-support, unsupported-scope, limitations, value, trust, and action denominators plus 4 disagreement and 1 injection denominators; these new metrics are not retroactively comparable to the original runs. The first expanded run passed 8/9 strict synthesis cases while every new semantic dimension was perfect. Its only failure was the older concept label not recognizing the equivalent wording “which package”; adding that labeled alternative changed no denominator. The final expanded reference above passed 9/9 strict cases and every semantic dimension.

The research corpus contains 9 fixed synthetic source-excerpt synthesis cases plus 1 deterministic stale-target preflight. Source-specific concept dimensions use labeled token sets rather than exact prose, and the separate semantic grader measures support and authority boundaries without production keyword filters or tools. This same-model grader is not independent human review, and the suite evaluates bounded synthesis and provenance behavior rather than live retrieval quality. Future model runs may vary and should be reported as observed.

## Demo mode

Start both applications and open `http://localhost:5173`. Search the canonical Houston-area fixture inventory, select two to five candidates, and choose **Start buying agent**. The resulting URL contains a durable purchase ID and reloads directly into one workspace containing ordered dealer workflows, deterministic counts, attention items, and the current verified-offer comparison. Each child prepares its immutable quote request and stops at the real approval boundary. The existing approval dialog still shows the exact candidate, fictitious `.example.test` recipient, subject, full body, reason, and requested-information checklist before any send. After each explicit approval, fixture response release, or child resume, the workspace reloads authoritative purchase state. If child setup fails partway through, **Recover missing workflows** preserves existing run IDs and retries only missing or unadvanced children.

In **Dealer response lab**, choose one of 15 raw response fixtures and select **Analyze response**. With a configured model key, the original message appears beside its typed quote extraction and deterministic assessment; evidence actions reveal exact supporting excerpts. The assessment shows comparable, transparent, and reconciled states independently, separates source-stated uncertainty from application-policy gaps, and explains reconciliation as known line items minus claimed OTD.

In the purchase workspace's verified-offer comparison, each material mandatory add-on exposes **Investigate**. The backend reconstructs the target from the current persisted quote, retrieves deterministic canonical fixture sources, performs bounded structured synthesis, validates target identity and source IDs, and persists the result. The finding presents external sources separately from dealer-message evidence. Investigation never changes quote comparability, OTD arithmetic, ranking, or recommendation; a stale target asks the buyer to reload rather than researching superseded quote state.

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

Criteria interpretation remains a fixture implementation limited to the canonical Hyundai Tucson Hybrid vocabulary. Quote analysis, follow-up wording, and research synthesis require an OpenAI API key. Research retrieval is fixture-backed for the canonical add-ons only; there is no live web-research provider, and the synthesis evaluation measures fixed synthetic excerpts rather than retrieval quality. The fixtures provide same-name external context, not independent proof of the Houston dealer's exact package identity, coverage, or terms. Research cost idempotency uses a five-minute SQLite claim lease: ordinary overlapping requests converge on one provider execution, while an unusually slow call that outlives the lease can be reclaimed and duplicate provider/model execution cost even though claim-token checks prevent conflicting current findings. The purchase workspace coordinates two to five persisted single-dealer workflows, but every exact initial or follow-up message still requires individual buyer approval; creation never sends automatically. Contacts and transport remain fictitious and side-effect-free. The demo has one deterministic response per interaction, so a sent follow-up truthfully stops at `WAITING_FOR_EXTERNAL_RESPONSE`; it does not fabricate a second response. There is no Gmail transport, draft editing, automatic background resume, durable outbox reconciliation, event streaming, negotiation, financing, trade-in optimization, or purchase execution.

Delivery is deliberately fail-closed. If the process stops after an approved provider call but before its receipt is persisted, the proposal remains `APPROVED` with delivery unconfirmed and cannot be sent again automatically. A production transport needs idempotency/reconciliation support before an operator prepares any replacement proposal, because an unconfirmed outcome may already have reached the dealer.

## Productionization

The assessment uses SQLite to minimize operational overhead. A production deployment would move domain persistence and LangGraph checkpoints to logically separate PostgreSQL-backed stores, use object storage for attachments, add production authentication and secret management, configure structured telemetry, and replace fixture providers selectively. Those changes should follow measured needs; the domain/provider boundaries are intended to make them incremental rather than require an architectural rewrite.
