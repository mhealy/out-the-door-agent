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

## Communication

When completing a task, summarize:

1. what changed,
2. important design decisions,
3. tests/checks run,
4. anything incomplete or uncertain,
5. any deviation from `ENGINEERING_SPEC.md`.