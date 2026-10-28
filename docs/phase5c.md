# Phase 5C: baseline consolidation and implementation proposal

Baseline review: 2026-10-26. Phase 5C.1 final review passed: 2026-10-27.
Phase 5C.2a final review passed on 2026-10-28: the live synthesis provider accepts a
versioned draft and derives the canonical escalation flag from typed steps.
Public report schemas, standalone RAG, graph/planner behavior and frozen inputs
are preserved. Only the synthesis wire contract and its matching prompt instructions
change. 5C.2b and later checkpoints remain unimplemented. No new live requests.
This is a small development sample, not a held-out benchmark.

## Preserved baseline and provenance

Derived local artifacts live in `reports/phase5c/baseline-001/` (ignored by Git):

- `baseline.json`: all seven historical attempt rows, unique run/scenario IDs,
  original source hashes, model/prompt/evaluator configuration, recomputed metrics,
  preserved failures, telemetry and the unmodified saved evidence/recommendations.
- `offline-contract-probes.json`: fourteen authored SDK/contract probes, explicitly
  separated from live performance. None reconstructs a rejected model response.
- `consolidate.py`: the original historical analysis script, retained unchanged
  with its evidence. Its generic-error probes describe the pre-5C.1 contract;
  do not rerun it against changed validator error identities or edit the archive.

Reusable consolidation now lives in version-controlled
`evaluation/phase5b_baseline.py`, with checksum-only provenance in
`evaluation/phase5b_baseline_manifest.json`. Verify without writing any output:

```powershell
uv run --locked --offline python -m evaluation.phase5b_baseline
```

To create a new derived snapshot, add
`--output-dir reports/phase5c/<new-name>`. Output must be a new directory inside
`reports/phase5c`; existing directories/files are never overwritten. The 5C.1
verification snapshot is `reports/phase5c/baseline-002/baseline.json`. Originals
and all derived evidence remain ignored by Git. The manifest includes all twelve
original report hashes and the three original derived-artifact hashes. Available
derived files are verified; absent local copies are explicitly marked unavailable.
Required original pilot files must be present and match checksums; missing files
fail verification. A fresh clone has the procedure/manifest, not private reports.

The reusable code makes no model or database calls, does not load secret env
files, and never updates the manifest. It verifies historical source identities
against the archived manifest while recording current consolidation source
fingerprints separately. Later application revisions therefore cannot silently
relabel historical outputs. New diagnostic tests live in the tracked test suite;
they do not rewrite the old probe artifact or reinterpret old `value_error`s.

The consolidator hashes all twelve original JSON artifacts (six run directories),
production source/data, KB documents, evaluation code/fixtures and lockfile before
and after: 93 protected files. It validates the frozen Phase 5A manifest and checks
saved requests/labels, KB content/order/metadata/distance hashes, investigation
contracts, planner scores, accepted citation scores, per-run aggregates and usage.
Both future-condition attempts remain separate; there is no best-of selection.
Original manual worksheets remain pending. The source review below is a new Codex
assessment for user review, not a completed independent or blinded human review.

All six saved runs share the same application fingerprint, lockfile and prompts:
planner v3, synthesis v2, standalone recommendation v4. Generation uses
`gpt-4.1-mini-2025-04-14`; embeddings use `text-embedding-3-small`. Evaluator hashes
differ across transport/diagnostic increments and are preserved per run.
`future-003` predates synthesis diagnostics; missing diagnostics are not success.

Pairing checks: saved tickets match the frozen scenario requests, and shared KB
arrays exactly match validated agent retrieval evidence. Existing runner code
passes that same array to standalone generation. The two future-condition runs
also have identical KB hashes. Raw API inputs were intentionally not saved, so
artifacts alone cannot independently audit the transmitted request bodies.
Labels/review notes are evaluator metadata, not provider input in the inspected
pipeline. These are two different systems: only the agent gets operational data,
and prompts/contracts/budgets differ. Agent timing includes shared retrieval;
standalone timing is generation-only. Neither is a matched-cost model ablation.

## Mechanical baseline: retain every attempt

The primary post-connectivity cohort contains five pairs from four distinct
scenarios, including two attempts at `vpn-future-condition`.

| Run / scenario | Agent result | Synthesis requests | Standalone | Expected tool coverage |
| --- | --- | ---: | --- | --- |
| future-003 / vpn-future-condition | Partial; rejected `invalid_output`, boundary unknown | 1 | Accepted, no current escalation | 3/3 |
| future-004 / vpn-future-condition | Partial; SDK parse root `value_error` | 1 | Accepted, no current escalation | 3/3 |
| confirmed-001 / vpn-confirmed | Completed; accepted supported report, escalation true | 1 | Accepted, escalation true | 3/3 |
| remaining-001 / irrelevant-incident | Partial; SDK parse root `value_error` | 1 | Accepted, no escalation | 1/1 |
| remaining-001 / unsupported-procedure | Completed clarification; deterministic abstention | 0 | Accepted model-generated abstention | 0/0, not applicable |

- **Supported-case model synthesis: 1/4 accepted (25%), 3/4 rejected (75%).**
  Standalone supported-case generation: **4/4 accepted**.
- All post-connectivity recommendation outputs: agent **2/5 accepted**, including
  one deterministic abstention; standalone **5/5 accepted**. Never report the
  agent's second accepted output as a successful synthesis call.
- Preserved transport-failure history: `future-001` and `future-002` each failed
  before useful evidence; each made three unsuccessful requests and no synthesis
  or standalone generation request. Across **all seven collected pairs**, agent
  has **2 accepted, 3 rejected, 2 failed**; standalone **5 accepted, 2 failed**.
  The latter failures are shared-retrieval failures, not failed standalone API calls.
- Expected planner evidence **10/10**, with **12 successful lookups**, zero
  labelled redundant/unnecessary lookups, duplicate proposals or blocked calls.
  Four supported attempts used four decisions; unsupported used one and no tools.
  Extra permitted email lookups are not automatically useful merely because the
  finite scenario labels do not mark them unnecessary.
- Accepted step-KB citation validity/coverage: agent **3/3 references and 3/3
  steps**; standalone **12/12 references and 12/12 steps**. Rejected reports have
  no assessable candidate. Zero-step abstentions have null citation rates. The
  common metric does not score every finding/summary or prove entailment.
- Accepted escalation confusion counts: agent TP=1, TN=1, FP=0, FN=0, with **3
  unscored rejections**; standalone TP=1, TN=4, FP=0, FN=0. Precision and recall
  on these accepted labels are 1.0 for both, and positive-attempt recall is 1/1.
  Label agreement over all five attempts is **2/5 vs 5/5**, not 100% vs 100%.
- Crucially, agent premature escalation on the two future-condition attempts is
  **unassessable (0 accepted outputs / 2 attempts)**, not a 0% error rate. It
  delivered **0/2 accepted correct no-escalation answers**; standalone delivered
  **2/2**. Failed attempts must not become true negatives or safe abstentions.
- Both arms safely abstain on **1/1 unsupported case**. Agent missing-information
  usefulness fails manual review below. Incorrect abstentions on answerable
  cases are 0/4, but this does not conceal the agent's three unavailable answers.

Post-connectivity telemetry: **36 HTTP-200 requests**, **105,647 known tokens**,
no missing token counts. Including connectivity failures: **42 requests**, the
same known-token subtotal, **six requests with unknown usage**. Unknown is not
zero; billed cost is unavailable. All saved before/after database fingerprints
match. No inference about semantic quality follows from HTTP 200 or token usage.

## Structured source review: semantics and usefulness

Review dimensions are independent: source entailment, attribution/freshness,
procedure applicability, escalation-trigger justification, missing information,
and usefulness. Findings below are source-based judgments; no semantic pass rate
is calculated from citation IDs. Rejected agent text is unavailable and is never
scored as grounded, ungrounded, or correctly abstaining.

| Attempt / arm / field | Evidence and judgment | Dimension / disposition |
| --- | --- | --- |
| future-003 and future-004 / agent | Three relevant snapshots retained, but recommendation absent. Exact invalid output unavailable. | Delivery failure; semantic answer review not possible. |
| future-003 and future-004 / standalone / summary | Correctly attributes one failure and no retry to the ticket. Does not claim authentication succeeded. | Grounded. |
| same / steps 0-1 | `vpn-access#connection-failures` supports public connectivity check and one Corporate reconnect. No current escalation trigger reported. | Applicable actions; correct false escalation flag. |
| same / steps 2-3 | Password-related actions cite real applicable-to-password-change KB text, but no password change is reported; two overlapping credential-update branches are included while asking whether their prerequisite occurred. | Conditional wording avoids asserting a changed password, but branch selection is premature/repetitive. Prefer asking the prerequisite and retaining only current actions. |
| same / missing_information | Recent-password-change question is relevant to that branch. Error/time collection belongs after an actual failed retry; no failure should be presumed. | Useful with explicit conditional timing. Service-desk-guided credential changes are not evidence of an immediate handoff. |
| confirmed-001 / agent / summary | Stored summary is exactly 600 characters and ends mid-word `coincid`. It mixes dated snapshots with present-tense account language and a compound concluding claim. | Readability failure and uneven same-claim freshness. Length validation accepts incomplete prose; no application truncation was found in the inspected path. Cause of the clipped wording cannot be recovered. |
| confirmed-001 / agent / findings 0, 2, 4 | Ticket recurrence, dated account flags and the general KB escalation rule are supported by their respective sources. Account configuration does not prove current authentication success. | Mostly grounded attribution; tighten same-claim live-state qualification. |
| confirmed-001 / agent / findings 1, 3 | Inventory and incident dates are present, but “no missing devices reported” is not a guarantee of complete inventory. Incident is a recorded `investigating` snapshot, not verified current impact. | Preserve uncertainty; do not infer exhaustive device coverage or present causation. |
| confirmed-001 / both / steps 0-1 | Ticket already reports public sites loading and a failed Corporate reconnect. Agent instructs another reconnect; standalone says “as already done” but still includes the action. | Repeated diagnostics; acknowledge completed work and request only missing details. If the without-VPN condition matters, ask that narrow clarification rather than replaying the procedure. |
| confirmed-001 / agent / step 1 | “Refresh the tunnel routes” is in `connected-but-resources-unavailable`, but the step cites `connection-failures`. Ticket does not establish Connected-but-internal-sites-fail conditions. | Valid citation ID with incomplete entailment and wrong-branch contamination. |
| confirmed-001 / agent / escalation step | Current handoff is supported by reported recurrent G42 after a retry. Step uses recorded version 5.2-demo but cites only KB, not the inventory observation containing that value. | Correct escalation label; incomplete claim-level evidence and snapshot qualification in action text. |
| confirmed-001 / agent / escalation_reason | Ticket plus connection-failure KB already establishes the handoff. Reason additionally invokes an “ongoing high-severity incident” without qualifying its old snapshot in that claim. | Correct decision with a partially unsupported/current-state rationale. General uncertainty elsewhere does not repair it. |
| confirmed-001 / agent / uncertainties | Explicitly says observations dated 2026-10-16 are not verified live state. | Good limitation, but not a substitute for qualifying every dependent claim. |
| confirmed-001 / standalone / summary and escalation | Handoff is justified from ticket + KB. Summary adds “VPN internal access failing,” which the ticket did not explicitly report and may reflect the nearby Connected branch. | Correct escalation; over-specific symptom restatement needs correction. |
| confirmed-001 / both / missing_information | Error timestamps are genuinely missing. Standalone appropriately lacks agent inventory, so asking client version is not unfairly scored as redundant. | Score each arm against its available evidence; do not require operational facts from standalone. |
| irrelevant-incident / agent / planner | Checks email incidents, devices, and historical tickets; avoids unrelated scoped VPN incidents. Email coverage 1/1. | Relevant required coverage; optional devices/history have uncertain marginal utility, not a labelled failure. No synthesis text exists to assess historical-ticket contamination. |
| irrelevant-incident / standalone | Correct email branch, no VPN diagnosis or escalation. Repeats the webmail comparison already supplied; password-change action is conditional on an unreported event. | Grounded core check/restart guidance, with avoidable repetition and branch applicability caveats. |
| unsupported-procedure / agent | `clarify` asks for employee_id and software_ids. Graph creates a context-cited no-step abstention with escalation undetermined; it makes no synthesis request. | Safe mechanics but wrong gap explanation. IDs do not supply a cafeteria restoration procedure absent from retrieved KB. |
| unsupported-procedure / standalone | States retrieved evidence lacks transaction-restoration procedures; no steps, escalation undetermined. Requests documentation. | Useful, appropriately scoped abstention. Treat locating documentation as a support knowledge gap, not an obligation for the user to invent the policy. |

The accepted agent report does **not** repeat the earlier unsupported claim that
5.2-demo is a supported version, or explicitly rule out credential problems from
account flags. That narrow improvement does not establish overall groundedness.
Both confirmed-case outputs are useful for routing, but neither is a clean
semantic pass. Standalone has higher accepted-output delivery in this sample;
these observations do not establish broad comparative superiority.

## Offline failure investigation

`OpenAISynthesis.responses.parse()` runs `InvestigationSynthesis` Pydantic
validators inside the SDK. JSON Schema validity alone cannot enforce all Python
cross-field checks. In the baseline source, model/root validation reuses Phase 2B.1
status/step and escalation consistency, then requires KB support in an escalation
reason. Four rule families can therefore surface as SDK `value_error` at `[]`:

| Rule family | Authored contradictory variants reproducing the same root signature |
| --- | --- |
| Status versus steps | supported with no steps; insufficient_evidence with steps |
| Escalation flag versus current typed steps | true without escalation step; false with escalation step |
| Flag versus reason presence | true with no reason; false with a reason |
| Reason documentation | escalation reason has ticket/observation references but no KB reference |

All **seven** variants produce the same saved diagnostic signature in one mocked
SDK request each. These are plausible categories, not identified causes of either
live failure. More than one invariant could be wrong, but validation may stop at
the first. `future-003` cannot even be narrowed to this boundary retrospectively.

Three comparison probes locate oversized summary text at `summary.text`
(`string_too_long`), duplicate references at `summary`, and an undocumented step
at `steps.0`. These are different from the two observed root errors. Thus an
overlong summary is not supported as their explanation. Unknown retrieved IDs
are checked later as `invalid_citation`, a different failure class.

Four further probes cover valid current escalation, valid abstention, and two
semantic negative controls: a supported-version claim citing only inventory, and
a conditional future handoff marked required now. Both negative controls pass
schema/reference checks intentionally. **Fourteen probes pass as tests; that is
not fourteen good recommendations.** No retries, repairs or live calls occur.

Most plausible architectural pressure is multiple model-authored representations
of the same decision (status, step types, flag, reason), coupled to typed evidence
and nested cross-field rules. This motivates a contract simplification proposal,
not a claim that escalation caused all three rejections. Phase 2B.1 previously
observed unidentified root validation errors too; standalone's five accepted
pilot outputs do not prove its contract is immune.

The unsupported-case clarification has a separate explanation: `ClarifyDecision`
can name only scope identifiers or `ticket_details`, and `validate_clarification`
checks supplied/duplicate fields, not relevance. The graph intercepts clarification
before model synthesis. No later synthesis-prompt improvement can correct the
explanation on that path. Empty fields make this decision structurally legal,
even though absent procedures are the actual limitation.

## Implementation checkpoints

Keep the same bounded graph, isolated OpenAI provider, canonical application
contracts, six restricted tools, shared retrieval and standalone RAG workflow.
No retrieval threshold, new model dependency, extra model judge, automatic retry,
repair loop, fallback recommendation, or new infrastructure is justified here.

### 5C.1: identifiable invariant failures (implemented, final review passed)

Files: `app/rag/schemas.py`, `app/investigation/schemas.py`,
`evaluation/synthesis_diagnostics.py`, focused contract/diagnostic tests.

The four existing invariant failures now use fixed `PydanticCustomError` codes
at their original validator sites, in their original order:

| Code | Existing invariant |
| --- | --- |
| `status_steps_mismatch` | Supported iff steps exist; abstentions have no steps |
| `escalation_steps_mismatch` | Escalation flag agrees with escalation-typed steps |
| `escalation_reason_mismatch` | Escalation flag agrees with reason presence |
| `escalation_reason_missing_kb` | Investigation escalation reason has KB support |

Only these four custom codes join the existing standard-Pydantic-type allowlist.
Unknown custom codes, including similar prefixes/suffixes, remain redacted to
`other_validation_error`. Messages, inputs, context, titles, raw outputs and
arbitrary location names are not retained. Existing field-location bounds remain.
No exception-message parsing or SDK response interception changes were added.
Production `synthesis_invalid_output` and rejection/evidence semantics are intact.
Standalone RAG still rejects the same inputs with `invalid_output`; its existing
diagnostic `validation_types` now identifies the shared invariant. This is the
intended diagnostic change, not a recommendation or workflow behavior change.

Acceptance: same accepted/rejected language and JSON Schemas as before; seven
contradictions distinguishable by rule family; messages/inputs/custom unknown
codes remain redacted; one request per attempt; SDK inputs/responses untouched.
Add parity tests for Phase 2B and synthesis, nested SDK parsing, and sanitization.
Historical failures stay unknown. This increment alone cannot demonstrate a
model-quality improvement or recover the rejected outputs.

### 5C.2a: derive the redundant current escalation flag (implemented, final review passed)

`app/investigation/synthesis_draft.py` owns `InvestigationSynthesisDraftV1`.
`OpenAISynthesis.responses.parse()` now uses that model instead of the canonical
report. The SDK validates the draft, including conversion through the existing
canonical validators. The provider revalidates the parsed object, converts it to
`InvestigationSynthesis`, and returns the same provider-interface type as before.
`generate_synthesis` and the outer investigation result still validate all evidence
IDs and required limitations. No graph, planner, CLI or projection changes are needed.

| Field/behavior | Model-facing draft V1 | Canonical public report |
| --- | --- | --- |
| `schema_version` | Required literal `investigation-synthesis-draft-v1` | Absent; no output-envelope change |
| `escalation_required` | Absent; supplying it rejects as an extra field | Required Boolean, derived from `any(step.step_type == "escalation" for step in steps)` |
| Status, summary, findings, steps, missing information, uncertainties, reason | Existing fields, types, limits and descriptions | Unchanged |
| Citation validation | Same nested reference and KB-action rules | Existing membership validation against retrieved chunks and successful observations |
| Future guidance / typed trigger evidence | No new fields | No new fields |

The draft copies canonical field definitions without inheriting the independently
supplied Boolean. This retains field descriptions/constraints and nested schemas
without editing `InvestigationSynthesis` or Phase 2B. The conversion adds exactly
the derived Boolean and removes the draft version. It never reads action/reason
text to infer a type, relabels steps, removes reasons, changes status, or repairs
legacy outputs. A missing/wrong version or the removed Boolean rejects. Historical
canonical reports and scripted providers still use their original contract;
they do not pass through a legacy-to-draft production fallback.

Existing canonical validation remains authoritative: supported requires steps;
insufficient evidence forbids steps; escalation steps require a non-null reason
with KB support; without escalation steps the reason must be null. Typed steps
determine the flag, so flag/step disagreement cannot arise from a valid draft.
The canonical flag/step invariant still rejects inconsistent scripted/provider
reports. Unknown KB/observation IDs reject later as `invalid_citation`; valid IDs
still do not prove that a source entails a claim or establishes a trigger.

Prompt `investigation-synthesis-v3` aligns the existing instructions with the new
wire contract: request the version, omit the Boolean, preserve current-step/reason
consistency and the existing prohibition on unconfirmed future handoffs. Grounding
policy, model/settings, one-request/no-retry behavior and safety controls stay the
same. `evaluation/live_telemetry.py` recognizes both old and new SDK schema names
as synthesis. The diagnostic sanitizer adds only the fixed `schema_version` field
location; no additional error messages, values, inputs or context are retained.
Frozen evaluations, baseline reports and standalone Phase 2B are unchanged.

The CLI commands and flags in the Phase 4B.2 documentation remain valid; only the
opted-in live synthesis provider's wire contract changes. Live evaluation metadata
records prompt v3 and the new application fingerprint. Archived attempts retain
their old configuration and failure denominators. New SDK mocks explicitly create
draft responses; deterministic fixture replay continues to use canonical reports.

This checkpoint does **not** establish whether a model-labelled escalation is
actually justified now. If a model incorrectly types a future handoff as a current
escalation and supplies a structurally valid reason, validation can still accept
it. Existing negative controls deliberately demonstrate this semantic limitation.
No keyword filter, silent correction, conditional-guidance representation or
typed trigger evidence has been added. Stop for review before 5C.2b.

### 5C.2b: add conditional guidance (not implemented)

Add `conditional_guidance` separately: documented condition, advisory future
action, KB references, and evidence still needed. It does not contribute to the
current escalation flag, steps or completed actions. With no current documented
action, status remains insufficient_evidence even if future guidance exists.

Checkpoint acceptance: validated future KB references; future entries never set
the current flag or enter current steps; no invented actions on unsupported cases.
The paired legacy projection scores current actions only. Stop for review before
adding typed trigger evidence.

### 5C.2c: add typed current-escalation trigger evidence (not implemented)

For a current handoff, add a typed `trigger_basis` referencing both the KB rule
and ticket/observation claimed to establish its trigger. An asserted trigger is
not independently verified merely because the field is populated.

Keep a canonical investigation report retaining existing fields/meaning; version
the extension and adapt the evaluator's Phase 2 projection to current steps only.
Preserve legacy scripted reports through explicit defaults/adapter tests. Update
telemetry stage detection if the SDK schema name changes, so synthesis requests
cannot be mislabeled as embeddings. Never loosen canonical citation validation.

Acceptance: valid confirmed handoff, unconfirmed condition, abstention with only
future guidance, multiple current steps, and partial-investigation cases all
map consistently; unknown IDs, absent KB action support, missing trigger-source
types, wrong reason/status and hidden cross-field contradictions reject. Validate
future references too. No new scope/actions/calls; evidence survives every failure.
Regression controls with real IDs but false claims must remain labelled semantic
failures rather than advertised as automatically detected. Exact DTO fields and
compatibility mapping should be finalized within its separately authorized checkpoint; do not
introduce a separate orchestration layer or duplicate Phase 2 validation logic.

### 5C.3: distinguish clarification from unavailable procedures

Proposed files: planner decision contracts/payload, `app/investigation/graph.py`,
its abstention formatter, planner/provider/CLI tests, new development cases.

Extend the bounded terminal decision with a small typed knowledge-gap outcome
(e.g. `insufficient_evidence` plus `gap_kind=documentation`), separate from a
clarification that actually enables a useful permitted lookup. Preserve clarify
for missing scope/symptom information, and retain deterministic supplied-field
and scope checks. The graph should produce a no-action explanation that supplied
KB evidence lacks a usable procedure, without claiming the entire company has
no such procedure. Do not require identifiers just to fill optional slots.

Acceptance: unsupported restoration asks for applicable documentation, not
unrelated employee/software IDs; account and entitlement cases genuinely needing
scope still clarify; supported action with incomplete submission details is not
incorrectly blocked. No API synthesis call on deterministic terminal abstention,
no scope expansion, no phrase/keyword router and no similarity cutoff. Procedure
relevance remains a model/reviewer judgment, not a deterministic guarantee.

### 5C.4: improve action applicability and claim-level usefulness

Proposed files: synthesis instructions/descriptions, additive development-only
evaluation cases, claim-review worksheets and regression tests. Start with the
agent; retain standalone as a fixed comparator for attribution of changes.

Use compact generic examples for completed checks versus next actions, reported
symptoms versus inferred protocol stages, same-claim snapshot qualification,
source-specific version facts, and nearby but inapplicable KB branches. Prefer
short complete summaries to exhaustive inventories; keep detail in findings.
Use existing evidence rather than a new fact-extraction model or keyword filters.
Treat standalone applicability defects as documented follow-up scope, not a silent
change to both arms during the comparison.

Acceptance: authored positive/negative pairs cover repeated reconnect, stale
incident rationale, wrong-section route-refresh claim, conditional password
changes, valid-ID unsupported version/authentication claims and mid-word summary.
Mechanical tests validate provider inputs/contracts/retained evidence. Source
entailment, completeness of prose, and usefulness require manual review; fixture
acceptance cannot demonstrate that a live model follows the examples.

### 5C.5: controlled validation after separate paid approval

Run the entire existing suite plus new tests, including restricted-role PostgreSQL
integration and before/after KB/vector/ops fingerprints. Preserve frozen Phase 5A
fixtures, all Phase 5B attempts, and comparison denominators. Put new cases in an
additive Phase 5C development file, with distinct provenance; do not call them held-out.

Then seek separate approval for a predeclared live pilot using the existing paired
runner: initially two attempts for each of the four scenarios (eight pairs), same
ticket/evidence per pair, fixed models/settings/budgets and new output directories.
At the current bound this is at most 64 requests; agree a usage/cost limit before
execution. No best-of selection, automatic retries or silently excluded failures.
Freeze the candidate revision; scope of any follow-up repetitions must be explicit.

Proposed pilot review gates: all six supported synthesis attempts yield accepted
reports; both unsupported cases identify the documentation gap without invented
actions; both confirmed cases justify a current handoff; both future-condition
cases produce an accepted answer with no premature handoff. All citations valid,
no safety/scope/write regression, no fabricated live-state/version/authentication
claims, no repeated completed actions, and no incorrect abstentions in the reviewed
outputs. Keep delivery and semantic gates separate. A failed attempt fails the
delivery gate even though its content cannot be assessed. Document failures rather
than weaken the gate or validation. Passing this tiny development pilot supports
review of the change, not statistical reliability or readiness for unattended use.

## Validation of the baseline planning increment (2026-10-26)

Fourteen new local offline SDK probes passed; all seven root-error variants were
reproduced without raw live responses. The unchanged full repository suite passed:
**640 tests in 65.03 seconds**, including **74 PostgreSQL integration tests**. Before/after
fingerprints match for all **79 operational rows and 36 KB chunks/vectors**;
temporary test reader roles remaining: **0**. All 93 protected source/report files
still match their consolidation hashes after testing. The only Git-visible change
is this new planning document; local derived artifacts remain ignored. Nothing is
staged or committed. No pushes or paid API calls were made.

## Phase 5C.1 verification (2026-10-27)

Tracked tests cover all seven contradictions, nested schemas, mocked SDK parsing,
Phase 2B provider error compatibility, the full 32-combination status/step/flag/reason
truth table in both contracts, strict sanitizer allowlisting/redaction, and twelve
pre-change JSON Schema hashes (validation, serialization, SDK strict schemas for
four public models). Unrelated field/citation validators and semantic negative
controls remain in the existing suite. Baseline-consolidation tests use authored
temporary archives, not private pilot files or API keys, and exercise immutable
checksums, repeats/failure denominators, semantic integrity and safe output paths.

The initial sandboxed consolidation-test invocation could not access the Windows
pytest temporary directory. It was rerun as part of the full suite with the required
local filesystem permissions: **721 tests passed in 71.16 seconds**, including all
**74 PostgreSQL integration tests**. This preserves the 640-test suite and adds
69 invariant/parity cases plus 12 baseline-consolidation cases. The five existing
diagnostic expectations affected by the new error identities were updated.

All twelve JSON Schemas exactly match their pre-change copies. Conditions, error
precedence and accepted output serialization are unchanged. Original/derived
baseline rows, metadata and mechanical aggregates match the archived baseline;
all twelve original reports and three historical derived artifacts match their
checksums. Only the two validator modules and diagnostic sanitizer changed among
previously fingerprinted production/evaluation inputs; prompts, providers, graph,
tools, KB and frozen fixtures did not change.

Before/after application fingerprints match for **79 operational records and 36
KB chunks, including vectors and metadata**; no temporary test reader roles remain.
Local environment files and reports remain ignored. The implementation handoff
made no Phase 5C.2 changes, paid calls, staging, commits or pushes. Finalization was
subsequently authorized after review.

Remaining limits: new codes identify only the first failing invariant family;
they cannot recover which rule failed in historical root `value_error` reports,
prove semantic groundedness, or establish improved live acceptance. The unchanged
validators still reject all inconsistent combinations. The baseline procedure
requires local original reports; checksums do not publish or reconstruct them.

Finalization reran the complete suite: **721 passed in 66.20 seconds**, including
74 PostgreSQL integration tests and all 12 JSON Schema parity checks. The database
fingerprints and archived baseline hashes remained unchanged. All ten milestone
files were reviewed; no credentials, local configuration or generated reports are
included. Consolidation code/manifest use repository-relative paths and document
the required local archives. No paid calls or Phase 5C.2 implementation occurred.

## Phase 5C.2a verification (2026-10-27)

The complete suite passed: **753 tests in 68.36 seconds**, including **74 PostgreSQL
integration tests**. All 721 existing cases remain, with SDK mocks updated to the
versioned response format, plus 32 focused draft-contract regressions. The twelve
canonical/Phase 2B JSON Schema hash checks still pass. Three additional checks
confirm that draft schemas differ only by the version and removed Boolean while
sharing all remaining field definitions and nested schemas.

Coverage includes confirmed current handoffs, VPN failure without a confirmed
trigger, troubleshooting, abstention, status/reason contradictions, missing KB
support, unknown references, removed-field/version rejection, mutated SDK models,
legacy/scripted parity, live planner/CLI contracts, and one-attempt failure paths.
A partial investigation with three lookups retains its prior classification error,
all observations, KB evidence, planner count and lookup trace after SDK validation,
citation or HTTP failure. HTTP 200 followed by rejection still counts as one
synthesis request; missing usage is recorded as unknown, not measured zero usage.
All SDK requests in these tests use mocks. These results measure code behavior,
not live-model acceptance, grounding or escalation precision.

Before/after read-only application fingerprints match for all **79 operational
records and 36 KB chunks, vectors and metadata**. No temporary test reader roles
remain. All eleven frozen evaluation JSON/JSONL files, twelve KB Markdown documents,
twelve original Phase 5B artifacts and five pre-existing Phase 5C archive files
match their pre-change hashes. The tracked consolidator independently verifies
all seven saved pairs without modifying originals or making API/database calls.
Standalone RAG, classifier, retrieval, planner, graph, operational tools and their
data remain unchanged. No dependencies, database migrations or reseeding were needed.

No paid calls, staging, commits or pushes were made. 5C.2b/5C.2c remain unimplemented.
Live server acceptance of the new schema and any improvement in model reliability
remain unmeasured until a separately approved pilot. The draft reduces redundant
model choices; it does not remove reason/status validation failures or establish
the semantic applicability of a handoff.

Finalization review (2026-10-28) found no blocking issues across all eighteen
changed files. The full suite passed again: **753 tests in 75.51 seconds**, including
74 PostgreSQL integration tests and all twelve canonical JSON Schema parity checks.
Operational/KB/vector fingerprints, frozen evaluation inputs and archived baseline
hashes remained unchanged; no temporary test reader roles remained. No credentials,
local environment files or generated reports are included in the milestone. The
user authorized a normal commit/push after these checks. No paid API calls or
Phase 5C.2b/5C.2c development occurred during finalization.
