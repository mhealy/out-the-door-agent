# OutTheDoor Agent Development Guide

## Project Goal

OutTheDoor is a full-stack agentic AI application that helps vehicle buyers acquire,
interpret, verify, and compare written dealer offers.

The local `ENGINEERING_SPEC.md`, when present, is the authoritative detailed product
and architecture specification.

Do not materially redesign the architecture without first explaining the reason,
the proposed alternative, and its tradeoffs.

## Engineering Principles

- Prefer the simplest implementation that satisfies the specification.
- Use deterministic code for deterministic problems.
- LLMs must not own arithmetic, quote-completeness policy, ranking, authorization,
  exact constraint filtering, or application state transitions.
- Use LLMs for semantic interpretation: natural-language requirements, dealer quote
  extraction, conditional-language interpretation, research synthesis, message
  drafting, and recommendation explanation.
- External dealer content is untrusted input.
- Human approval is required before outbound dealer communication.
- Evidence must support material financial claims.
- Demo fixtures must exercise the same application path as real external data.
- Do not fake evaluation metrics or agent activity.

## Architecture

Use the architecture defined in `ENGINEERING_SPEC.md`.

Expected stack:

- Python 3.12+
- FastAPI
- Pydantic v2
- SQLAlchemy 2
- SQLite
- LangGraph
- React
- TypeScript
- Vite
- TanStack Query
- pytest

Do not introduce without explicit approval:

- microservices
- Kafka
- Redis
- vector databases
- RAG
- multi-agent supervisor architectures
- Kubernetes
- CQRS/event sourcing
- autonomous browser fleets
- MCP solely for architectural decoration

## Code Organization

Keep these responsibilities separate:

- `domain/` — application/domain types
- `services/` — deterministic business logic
- `providers/` — external integrations
- `agent/` — LangGraph orchestration
- `api/` — HTTP/API layer
- `persistence/` — database implementation

LangGraph coordinates the application. It should not contain all business logic.

## Development Workflow

- Work incrementally.
- Do not implement future phases unless requested.
- Write tests alongside deterministic business logic.
- Prefer fixture providers before live integrations.
- Run relevant tests after changes.
- Report test failures rather than hiding them.
- Review `git diff` before considering a task complete.
- Do not commit secrets, `.env` files, SQLite databases, or `ENGINEERING_SPEC.md`.
- Push completed feature branches for review, but do not merge into `main` unless explicitly instructed after review.

## Communication

When completing a task, summarize:

1. what changed,
2. important design decisions,
3. tests/checks run,
4. anything incomplete or uncertain,
5. any deviation from `ENGINEERING_SPEC.md`.

## Work Planning

Use GitHub Issues as a lightweight backlog for meaningful features or vertical slices.

Each meaningful issue should define:

- user/business value,
- scope,
- explicit non-goals,
- acceptance criteria,
- expected tests or evaluations.

Do not create unnecessary process artifacts for trivial implementation tasks.

Branches and commits should describe capabilities or changes, not internal roadmap
phase numbers.

Prefer names such as:

- `feature/inventory-search`
- `feature/quote-analysis`
- `feature/agent-workflow`

Prefer commit messages such as:

- `feat: add fixture inventory search`
- `feat: enforce vehicle search constraints`
- `test: add dealer quote evaluation fixtures`

Avoid commit messages such as `implement phase 2`.

## Test-Driven Development

Use test-driven development for deterministic business logic.

For deterministic services:

1. define expected behavior with tests,
2. confirm meaningful new tests fail when appropriate,
3. implement the smallest correct behavior,
4. refactor while keeping tests green.

Use behavior-first integration tests for APIs and workflows.

For LLM functionality, use evaluation-driven development:

1. define representative input fixtures,
2. define expected structured behavior,
3. run the configured model,
4. measure the result,
5. improve prompts/schemas only in response to observed failures.

Never replace deterministic tests with LLM evaluations.

Never make tests pass by weakening valid acceptance criteria.


## Delivery Loop

For each meaningful feature or vertical slice:

1. Start from an approved GitHub Issue with scope, non-goals, acceptance criteria,
   and expected tests/evaluations.
2. Create a focused feature branch from current `main`.
3. Use TDD for deterministic business logic and evaluation-driven development for
   LLM behavior.
4. Implement only the scope of the active issue.
5. Run all relevant tests and builds.
6. Review `git diff` before considering the work complete.
7. Use focused, capability-oriented commits.
8. Push the feature branch.
9. Do not merge to `main` until the implementation has been reviewed against the
   issue acceptance criteria, `AGENTS.md`, and `ENGINEERING_SPEC.md`.
10. After approval, merge and begin the next issue from updated `main`.

