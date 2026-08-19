# OutTheDoor

**OutTheDoor** is an agentic AI application that helps vehicle buyers discover, acquire, interpret, and compare real dealership offers.

Rather than relying on advertised prices alone, OutTheDoor is designed to gather transaction-specific evidence such as written out-the-door pricing, dealer fees, mandatory add-ons, conditional incentives, and financing requirements. It then normalizes those offers so a buyer can make an informed, evidence-backed purchasing decision.

## Why This Exists

Finding vehicle inventory is relatively easy.

Determining what a vehicle will **actually cost** can be much harder.

Dealership quotes may include or omit:

* mandatory dealer-installed products,
* documentation and dealer fees,
* financing-dependent discounts,
* trade-in incentives,
* loyalty or eligibility-based rebates,
* taxes, title, and registration,
* other conditions not reflected in the advertised price.

OutTheDoor explores how an AI agent can reduce that information asymmetry by gathering missing information, interpreting unstructured dealer responses, researching material add-ons, and presenting comparable offers.

## Core Design Principles

* **Evidence over assertion** — important pricing claims should be traceable to their source.
* **Bounded autonomy** — the agent can research and analyze autonomously, while external dealer communication requires human approval.
* **Deterministic logic where possible** — calculations, constraints, quote validation, policy, and ranking belong in normal code.
* **AI where semantics matter** — LLMs are used for natural-language interpretation, quote extraction, conditional-language analysis, research synthesis, and communication.
* **Observable behavior** — agent actions, decisions, evidence, and workflow state should be visible and auditable.
* **Measured quality** — AI behavior should be evaluated against representative dealer-response scenarios rather than judged only by demo quality.

## Planned Architecture

```text
React + TypeScript
        │
        ▼
      FastAPI
        │
        ▼
LangGraph Buyer Agent
   │       │       │
   ▼       ▼       ▼
Inventory Messaging Research
        │
        ▼
Structured LLM Operations
        │
        ▼
SQLite + Evidence + Tracing
```

### Planned Stack

**Frontend**

* React
* TypeScript
* Vite
* TanStack Query

**Backend**

* Python
* FastAPI
* Pydantic
* SQLAlchemy
* SQLite

**Agentic AI**

* LangGraph
* Structured LLM outputs
* Human-in-the-loop approval

**Quality**

* pytest
* deterministic unit and integration tests
* AI evaluation fixtures

## Project Status

🚧 **Early development**

The repository is currently being initialized. The first development phase establishes the application foundation, including:

* FastAPI backend
* React/TypeScript frontend
* persistence foundation
* core domain models
* testing infrastructure
* local development workflow

Agent workflows and external integrations will be added incrementally after the foundation is stable.

## Repository Structure

The planned top-level structure is:

```text
out-the-door-agent/
├── backend/
├── frontend/
├── demo/
├── AGENTS.md
└── README.md
```

Detailed implementation guidance is maintained separately during development.

## Development Philosophy

This project intentionally favors a small, understandable architecture over unnecessary AI or infrastructure complexity.

The goal is not to maximize the number of agents, frameworks, or services. The goal is to build a reliable agentic workflow where AI is used only where it provides meaningful value.

## License

This project is currently private and under development.
