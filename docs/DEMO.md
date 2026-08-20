# Canonical live demo

This runbook targets a 5–7 minute product walkthrough inside a 15-minute interview. It
uses the final Baytown/Houston/Katy story and preserves every approval and uncertainty
boundary.

## Before the interview

Stop any running host or Compose services before resetting. For a host-based run, use
the configured host stores from `backend/` with the virtual environment active:

```powershell
python -m app.demo reset
python -m app.demo preflight
```

Preflight makes no model call. Do not begin the live model-backed path unless it ends
with `READY canonical demo`. A configured credential check proves presence only, not
provider availability.

Start the host backend from `backend/`:

```powershell
uvicorn app.main:app --reload
```

Start the host frontend from `frontend/` in another terminal:

```powershell
npm run dev
```

Open `http://localhost:5173`.

For Docker Compose instead, run the following from the repository root so reset and
preflight inspect the same named-volume stores that the demo containers will use:

```powershell
docker compose down
docker compose build
docker compose run --rm backend python -m app.demo reset
docker compose run --rm backend python -m app.demo preflight
docker compose up
```

## 5–7 minute sequence

### 0:00–0:45 — State the buyer problem

Paste this goal:

> Find a new 2025 or 2026 Hyundai Tucson Hybrid Limited within 40 miles of
> Houston under $40,000. I require AWD. I care most about true out-the-door
> price.

Search inventory. Point out that hard constraints are interpreted, then enforced by
deterministic code rather than relaxed by a model.

### 0:45–1:15 — Select the three dealers

Select exactly:

- Houston Hyundai — `houston-white` — advertised $37,250
- Baytown Hyundai — `baytown-blue` — advertised $37,800
- Katy Hyundai — `katy-blue` — advertised $39,500

Choose **Start buying agent**. Explain that one durable purchase now coordinates three
independent single-dealer LangGraph runs.

### 1:15–2:15 — Show authorization

Open each prepared quote request. Show the exact recipient, subject, body, reason, and
required-information checklist. Approve and send each request individually.

Emphasize:

- purchase creation sent zero messages,
- every send authorizes one immutable exact payload,
- no action is silently approved or broadcast to every dealer.

### 2:15–3:20 — Release the dealer evidence

For Baytown, Houston, and Katy, use **DEMO CONTROL — Release dealer response**.
The fixture replaces the unreliable external party, not the downstream application
path: each raw response is persisted before extraction, evidence validation, assessment,
and graph observation. If a child still shows an older phase, use **DEMO CONTROL —
Resume from latest state** for that child only.

Point out the resulting states:

- Baytown — verified/comparable at $40,315 with no mandatory add-ons.
- Houston — verified/comparable at $41,780 with Ceramic Shield ($1,299) and
  SecureTrack theft recovery ($596) mandatory.
- Katy — stated $40,250, but vehicle identity and add-on status remain incomplete; one
  clarification is prepared and still awaits approval.

Do not approve the Katy clarification during the canonical demo, and do not fabricate a
second Katy response.

### 3:20–4:25 — Explain the decision and evidence

In the comparison, open the dealer evidence supporting Baytown's written OTD and the
Houston add-ons. Contrast provenance explicitly:

- **INVENTORY SOURCE** supports advertised listing facts.
- **DEALER EVIDENCE** supports transaction-specific quote facts.
- **INDEPENDENT RESEARCH** supplies external context only.

Show the purchase activity timeline as observational history. The current purchase,
approval, interaction, assessment, and comparison records remain authoritative.

### 4:25–5:20 — Investigate one add-on

Choose **Investigate** for Houston's Ceramic Shield. Open an external source and explain
that research is bounded to a current material term. It cannot change the dealer-stated
amount, mandatory status, OTD, comparability, ranking, recommendation, or savings.

### 5:20–6:15 — Land the reversal

Return to the comparison and say the numbers plainly:

- Houston looked **$550 cheaper online** than Baytown.
- Baytown is actually **$1,465 cheaper** in verified written OTD.
- Katy's lower stated total cannot win while its evidence remains incomplete.

Finish on:

> **Best verified offer so far — Baytown Hyundai — $40,315.**

## If a live model call fails

Do not hide the failure or load a prebuilt success database.

1. For quote-extraction failure, show that the raw dealer response remains persisted.
   After restoring configuration or provider availability, choose **Retry response
   analysis**, then resume that child if its phase still needs to observe the successful
   analysis. Existing approvals and evidence are not discarded.
2. For research synthesis failure, show the truthful failed research state and unchanged
   comparison, then use **Retry research** after recovery.
3. Follow-up drafting failure is recorded as a failed child run and has no in-place demo
   retry. Do not disguise it as recovered.
4. If a live boundary remains unavailable—or follow-up drafting failed—run the
   deterministic reviewer smoke from `backend/`:

   ```powershell
   python -m pytest tests/integration/test_canonical_demo_smoke.py -q
   ```

   Explain that the smoke injects committed labeled quote outputs at extraction and
   code-defined deterministic test doubles for drafting and research synthesis. It still
   exercises the real search, PurchaseRun, child graphs, exact approvals, fixture
   transport, inbound persistence, assessment, evidence, comparison, activity, and
   fixture research paths.

The fallback proves application correctness reproducibly; it is not evidence of current
live-model quality. Live model behavior is measured separately by the explicit eval
commands in the README.
