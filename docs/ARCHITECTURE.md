# Architecture

OutTheDoor is a bounded AI buyer advocate. It gathers transaction-specific dealer
evidence until qualified vehicles can be compared on written out-the-door economics,
while keeping every outbound dealer message under explicit buyer control.

> **LangGraph coordinates capabilities. Application services own truth, policy,
> authorization, and side effects.**

## System shape

```text
React buyer workspace
  search · purchase status · approvals · activity · offers · evidence · research
                              │
                              │ REST and explicit actions/refetch
                              ▼
FastAPI application layer
  inventory · purchases · outreach · interactions · comparison · research
              │                                      │
              ▼                                      ▼
   application SQLite                         provider boundaries
   business records and evidence              fixture or model-backed
              │
              └──────── child identity ───────────────┐
                                                     ▼
                                      single-dealer LangGraph workflow
                                      separate checkpoint SQLite
```

One durable `PurchaseRun` records the buyer goal and ordered selection of two to five
vehicles. It coordinates one independent child `AgentRun` per dealer; it is a durable
coordinator/read model, not another graph and not a multi-agent supervisor.

Each child graph reloads authoritative application records when explicitly resumed. It
can prepare an action, pause for approval, observe confirmed delivery, wait for a dealer
response, observe persisted analysis, prepare a bounded clarification, or finish. Its
phase is only the orchestrator's last observation; it does not override newer business
records.

## Responsibility boundaries

| Concern | Authority |
|---|---|
| Qualified inventory | Deterministic inventory filtering and shortlist services |
| Workflow sequencing and durable waits | Single-dealer LangGraph child |
| Current purchase/dealer state | Application persistence and services |
| Exact external authorization | Immutable proposed action plus approval snapshot |
| Messaging side effects | Application outreach service behind a provider boundary |
| Raw dealer response | Persisted inbound interaction record |
| Semantic quote facts | Task-scoped, tool-free structured extraction |
| Evidence validity | Deterministic source/excerpt validation |
| Completeness, transparency, and arithmetic | Deterministic quote assessment |
| Ranking, recommendation, and savings | Deterministic offer comparison |
| Add-on context | Bounded research capability; never transaction truth |
| Purchase activity | Read-only history derived from child events |

## Persistence and recovery

Application SQLite stores purchases, child identities, proposed actions, approvals,
deliveries, inbound messages, analyzed quotes, evidence, and research findings. A
logically separate SQLite database stores LangGraph checkpoints. Business records stay
authoritative if a checkpoint write fails; a later explicit resume reconciles the graph
with those records.

Purchase creation uses a caller-supplied stable creation identity and deterministic
child IDs. An ambiguous retry reconciles the same intent, while a conflicting intent is
rejected. Partial child setup remains visible and can recover only missing or unadvanced
children. Delivery uncertainty fails closed: an approved action with no durable receipt
is never sent again automatically.

## Evidence and provenance

The UI deliberately separates three source classes:

- **Inventory source** — advertised listing facts such as price, distance, and VIN.
- **Dealer evidence** — the written message excerpt supporting OTD, add-ons, fees, and
  conditions.
- **Independent research** — external context about a current material add-on.

Dealer and web content are untrusted data. Extraction and research synthesis receive no
tools or side-effect authority. Material extracted facts must retain exact source-backed
evidence, which deterministic code validates before quote policy or ranking can use
them.

## Deterministic and probabilistic work

Models are used only for semantic interpretation: quote extraction, bounded follow-up
wording, and research synthesis. Normal code owns exact constraint enforcement,
arithmetic, completeness policy, evidence validation, freshness, retry limits,
authorization, status transitions, ranking, recommendation, and savings.

The deterministic canonical smoke uses committed labeled quote outputs at extraction
and code-defined deterministic doubles for follow-up drafting and research synthesis.
It still exercises the real APIs, services, persistence, checkpoints, approval path,
fixture transport, inbound path, comparison, and research retrieval. Live model
evaluations remain separate, explicit, credentialed checks.

See [EVALS.md](EVALS.md) for the model-call inventory, proof boundaries, corpus
dimensions, run history, and limitations.

## Research boundary

Research targets are reconstructed from the latest authoritative quote and limited to
current material mandatory add-ons. Retrieval is fixture-backed in the current
implementation; synthesis is structured and tool-free. Deterministic validation
rechecks target identity, freshness, bounds, and source IDs before persisting a finding.

Research cannot change claimed OTD, comparability, quote assessment, ranking,
recommendation, savings, approval, or messaging. It remains visible in its own research
surface instead of being manufactured as a graph-phase event.

## Production evolution

The current reference implementation intentionally uses one deployment, fixture
providers, and two SQLite files. A production version could replace application and
checkpoint persistence with logically separate PostgreSQL stores, add transport
idempotency/reconciliation,
authentication, managed secrets, object storage, and measured telemetry. Those are
provider and infrastructure substitutions, not reasons to move policy into LangGraph or
models.
