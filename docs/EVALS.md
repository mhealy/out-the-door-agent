# Evaluation evidence

OutTheDoor uses several kinds of tests because no single result proves the whole
system. This document records what each layer covers, what every production model may
do, and the limits of the live evaluation corpus. Normal CI never makes paid model
calls.

## What each layer proves

| Layer | What it proves | What it does not prove |
|---|---|---|
| Deterministic unit and integration tests | Application policy, arithmetic, state transitions, freshness, authorization, exact delivery, and error behavior | Current behavior of a hosted model |
| Structured-output schema validation | A model response has the expected types, fields, bounds, and closed shape | That a semantically plausible field is true or supported by its source |
| Deterministic provenance and policy validation | Evidence excerpts occur in the persisted message; IDs and targets are trusted and current; model-selected wording is allowlisted | General real-world truth or retrieval quality |
| Opt-in live model evals | Behavior of the configured hosted models on committed synthetic cases | Exhaustive production quality, model stability, or live dealer/retrieval coverage |
| Canonical smoke | The real application boundaries compose into the intended demo and preserve ownership rules | Live model quality, because model seams use committed labels or deterministic doubles |

The hosted model is never the authority for money math, comparability, ranking,
recommendation, savings, freshness, approval, recipients, delivery, retry limits, or
state transitions.

## Complete production model inventory

There are exactly three production model calls. Each uses the OpenAI Responses API
with strict Pydantic structured output, `store=False`, and no tools.

| Task | Adapter and schema | Trusted inputs | Untrusted inputs | Deterministic checks and authority boundary |
|---|---|---|---|---|
| Dealer quote extraction | `app/providers/quote_extraction.py`; `_ModelQuoteExtractorOutput` is converted to `QuoteExtraction` | Persisted message, dealer, and vehicle identifiers supplied by the application | Dealer subject and body | The raw response is persisted first. Evidence validation binds each material field to an exact excerpt and trusted source metadata. Quote assessment owns identity, completeness, transparency, and Decimal reconciliation. The model cannot send messages or rank offers. |
| Follow-up drafting | `app/providers/followup_drafting.py`; `FollowupDraft` | Code-owned requirement IDs, permitted subjects and wording options, and target metadata | Prior dealer conversation and source uncertainty | Policy derives the required ID set. Validation requires that exact set and exact allowlisted text, rejects prohibited content, inserts target identity, and renders the final body. Recipient, source linkage, approval, and delivery remain application-owned. |
| Research synthesis | `app/providers/research_synthesis.py`; `ResearchFindingDraft` | A current application-derived target plus bounded provider source IDs and metadata | Retrieved source text | Validation requires exact target identity, current evidence, known unique source IDs, citation status, and configured bounds. Research cannot alter quote economics, ranking, recommendation, approval, or messaging. |

The configurable defaults are `gpt-5.6` through
`OTD_QUOTE_EXTRACTION_MODEL`, `OTD_FOLLOWUP_DRAFTING_MODEL`, and
`OTD_RESEARCH_SYNTHESIS_MODEL`. Criteria interpretation is fixture-backed and
deterministic. Initial outreach, quote assessment, offer comparison, recommendation,
graph coordination, and demo preflight are also deterministic.

An additional OpenAI call exists only in the research eval: a same-model semantic
grader. It is not reachable from the product runtime.

## Live suite shape

Before this release audit, the suite contained 39 eval-marked pytest items. Two
follow-up evaluator-integrity regressions added during the audit bring the final
opt-in selection to 41. Six quote-matcher integrity cases now run in ordinary CI and
are not eval-marked. Only 36 opt-in cases call the primary models:

| Eval file | Eval-marked items | Primary-model cases | Other items | Nominal model calls without retries |
|---|---:|---:|---|---:|
| Quote extraction | 15 | 15 | None | 15 |
| Follow-up drafting | 15 | 12 | One comparable/no-draft case and two evaluator-integrity regressions | 12 |
| Research synthesis | 11 | 9 | Corpus-integrity and stale-target checks | 18: nine syntheses plus nine grader calls |
| **Total** | **41** | **36** | **5 deterministic/no-primary-model items** | **45** |

An aggregate pytest count therefore does not represent independent live semantic
judgments. The per-task dimensions and denominators below are the meaningful evidence.

## Quote extraction

The 15 synthetic dealer-message cases check:

- 105 scalar fields (seven per case), 60 collection sets (four per case), and 34
  condition checks;
- recall and precision for exact source-backed evidence;
- recall and precision for uncertainty actually supported by the dealer message;
- hostile text and prompt-injection resistance at the structured extraction boundary.

The first recorded `gpt-5.6` run on August 19, 2026 was 12/15 strict: scalar fields
105/105, collection sets 58/60, conditions 34/34, missing-information checks 33/34,
and evidence checks 185/186. Two cases treated government fees as mandatory without
the dealer saying so, and one invented a question from an omitted “plus TTL” phrase.
That exposed an ownership error in the interpretation contract: extraction reports
what the dealer stated, while deterministic assessment owns missing-information
policy. After that contract and its labels were corrected, the final pre-audit
August 19 hosted run was 15/15, with 105/105 scalar fields, 60/60 collection sets,
34/34 conditions, 33/33 source-grounded uncertainty checks, and 188/188 evidence
checks.

The uncertainty denominator changed from 34 to 33 because the unsupported
omission-derived label was removed; it was not an extra model success. Evidence and
uncertainty precision denominators also depend on how many items the model emits, so
headline ratios must be read with their run output. The corpus is synthetic, exact
substring provenance does not prove real-world truth, and the live extraction eval
does not itself invoke deterministic quote assessment.

## Follow-up drafting: contract conformance, not free-form judgment

The production contract is structurally closed. The model can return only a subject
and `{requirement_id, text}` pairs. Deterministic code supplies the permitted
requirement IDs, subjects, and wording options, then requires the exact missing-ID set
and exact allowlisted phrases. It renders the body, adds required target identity, and
keeps recipient, approval, source freshness, and delivery outside the model boundary.

For that reason this audit chose not to add an independent semantic grader or a new
free-form corpus. Such a grader would add cost and apparent coverage without testing a
production capability the model actually owns. The existing 12 live cases plus one
deterministic comparable/no-draft case remain useful as real-model contract-conformance
and provider-operability evidence. No independent live semantic follow-up eval exists.

The last separately recorded August 19, 2026 `gpt-5.6` run was 13/13: accepted or
no-draft 13/13, requirement identifier checks 28/28, concept checks 28/28,
concision 12/12, safety 12/12, applicable target identity 2/2, and no-draft 1/1. An
early post-structure run had 27/28 concept checks because one shared pricing phrase
was too generic; the code-owned wording option was corrected, then two runs completed
13/13.

Older output reported target identity as 12/12 by counting ten non-applicable cases as
successes. The audit corrected the denominator to the two cases that require a VIN;
the historical result is therefore reported as 2/2. It also added the valid runtime
phrase “mandatory dealer-installed product” to the concept label alternatives. Both
changes correct the evaluator; neither expands model authority or converts a failure
into application acceptance.

## Research synthesis

Nine synthesis cases exercise a fixed synthetic source corpus. They check exact target
and source-ID fidelity, supported status and summary concepts, retained disagreement,
strict insufficiency, limitations, prompt-injection resistance, and the absence of
value, recommendation, scam/fraud/trust, or application-action claims. One additional
case proves a stale target is rejected before a model call.

Research is the one model seam where semantic prose can survive deterministic
validation, so a semantic eval is justified. The eval uses a second structured call to
grade source support, scope, limitations, disagreement, and prohibited conclusions.
That grader uses the same configured model family, so it is a consistency signal, not
an independent judge.

The August 20, 2026 `gpt-5.6` history moved from 5/9 strict after a prompt correction,
to 8/9, and then 9/9 after a token-set matcher correction. Expanding the semantic
grader initially produced 8/9 because an equivalent limitation phrase was missing
from the label alternatives; correcting that label restored 9/9 without changing the
denominator. The last separately recorded run had all nine model cases strict, all
target/source/status/summary/limitation/no-value/safety dimensions 9/9,
disagreement 4/4, strict insufficiency 2/2, injection 1/1, and stale-target 1/1. The
semantic grader reported support, scope, limitations, no-value, no-trust, and
no-action 9/9, disagreement 4/4, and injection 1/1.

This does not test live retrieval quality, prove that a generic product source matches
the exact dealer-installed package, or make self-grading independent. Each research
case costs two calls before retries.

## Canonical smoke

`backend/tests/integration/test_canonical_demo_smoke.py` uses committed labeled quote
outputs at extraction and code-defined deterministic doubles for follow-up drafting
and research synthesis. It still exercises real APIs, services, persistence,
checkpoints, exact approval, fixture transport, inbound persistence, evidence,
comparison, activity, and bounded fixture retrieval.

The smoke proves that the end-to-end application composes and that authority stays in
the intended layer. It deliberately does not claim current hosted-model quality.

## Commands

Run normal backend checks from `backend/`:

```powershell
python -m pytest
python -m pytest tests/integration/test_canonical_demo_smoke.py -q
python -m compileall -q app
```

Run frontend checks from `frontend/`:

```powershell
npm test
npm run build
```

Run Compose checks from the repository root:

```powershell
docker compose config --quiet
docker compose build
```

The live suite is opt-in, credentialed, variable, and potentially paid. From
`backend/`:

```powershell
$env:OTD_RUN_LIVE_EVALS="1"
python -m pytest -m eval tests/evals
```

Missing consent, a missing `OTD_OPENAI_API_KEY`, provider failures, schema failures,
and assertion failures are not passes. Normal pytest and CI select `not eval`, so they
do not make these calls. Record the model settings, date, complete metric output,
failures, and any denominator or label changes whenever publishing a live result.

## Release-candidate record

One combined, call-bearing release-candidate run was made on August 20, 2026 with all
three production model settings and the research grader set to `gpt-5.6`. The command
collected 41 items at that point: 36 primary-model cases and five deterministic or
no-primary-model checks. It made 45 nominal model calls before any SDK-level retries.
The raw pytest result was **39 passed, 2 failed in 263.48 seconds**.

The quote segment was raw 14/15 strict, with scalar fields 105/105, collection sets
60/60, conditions 34/34, source-grounded uncertainty 32/34, and evidence attribution
189/189. The sole failure was `msg-multiple-vehicles`. The extraction left all
single-vehicle economics empty and correctly reported that distinct terms for two
vehicles made the applicable VIN, stock number, price, and OTD ambiguous until a
vehicle was selected. The lexical evaluator recognized “which vehicle” but not the
equivalent “vehicle ... selected” construction. This was classified as an **evaluator
defect**, not a semantic behavior defect. The precision-safe matcher now requires
vehicle-identity language, multiple-alternative language, and unresolved
selection/identity ambiguity on both sides. Red/green no-call controls prove that the
committed label and captured wording pass while unrelated vehicle questions and a
selected-vehicle statement fail. The captured response is therefore correctly
classified offline, making the corrected quote interpretation 15/15 strict and
uncertainty 34/34. The hosted suite was not rerun. The uncertainty denominator rose
from the prior 33 to 34 and evidence from 188 to 189 because their precision sides
include the number of items emitted in this sample.

The follow-up segment was **12/13 strict**: deterministically accepted or no-draft
12/13, requirement identifiers 28/28, concepts 28/28, concision 12/12, safety 12/12,
applicable target identity 2/2, and comparable/no-draft 1/1. In the hostile
`prompt_injection` case, the model ignored the injected request and returned the right
requirement ID and safe concept, but blended two supplied wording options into
“Please confirm whether dealer-installed products are mandatory.” Because that was
not an exact code-owned option, deterministic validation rejected it before proposal
persistence, approval, or delivery. This is a **model contract-conformance failure**
classified as acceptable bounded model variance for release, not as a pass. No prompt,
allowlist, or application change was made to tune to this one sample.

The research segment was **9/9 strict**. Target identity, source IDs, allowed status,
supported concepts, limitations, no-value, and safety were each 9/9; disagreement was
4/4, strict insufficiency 2/2, injection 1/1, and stale-target blocking 1/1. The
same-model grader reported source support, scope, limitations, no-value, no-trust, and
no-action 9/9, disagreement 4/4, and injection 1/1. Its lack of independence and the
fixture-retrieval limitations still apply.

The six quote matcher integrity cases run in ordinary CI; only the 15 hosted quote
cases retain the `eval` marker. The call-bearing suite was intentionally not rerun:
the raw failure, corrected offline interpretation, and remaining model variance are
all preserved rather than sampled away.
