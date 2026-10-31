# Phase 5C: baseline consolidation and implementation proposal

Baseline review: 2026-10-26. Phase 5C.1 final review passed: 2026-10-27.
Phase 5C.2a final review passed on 2026-10-28; 5C.2b on 2026-10-29.
Phase 5C.2c final review passed on 2026-10-30: draft V3 requires typed policy/factual
trigger evidence for current escalation. Conditional future guidance stays separate.
The canonical report gains a nullable default for historical input compatibility;
all pre-existing invariants, standalone RAG, planning and frozen inputs are preserved.
The synthesis wire contract and matching prompt are versioned. Phase 5C.3 now adds
a versioned planner terminal for insufficient procedural evidence; implementation
and verification are recorded below. Phase 5C.4 now refines synthesis instructions
and manual review; Phase 5C.5 remains unimplemented. No new live requests.
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

### 5C.2b: conditional future guidance (implemented, final review passed)

`InvestigationSynthesisDraftV2` extends the V1 draft with a required
`conditional_guidance` list and literal version `investigation-synthesis-draft-v2`.
The OpenAI provider requests/revalidates V2 and returns the canonical report through
the same conversion method. Prompt `investigation-synthesis-v4` separates future
advisory actions from current actions; model selection, request limits, retries,
error codes and graph behavior are unchanged. No new dependency or graph node.

Each `ConditionalGuidance` entry has four required fields:

| Field | Contract |
| --- | --- |
| `condition` | Nonblank text describing the documented, not-yet-established condition |
| `action` | Nonblank advisory action only if the condition becomes established |
| `references` | One to eight distinct typed KB chunk references; no ticket/operational/context references |
| `missing_evidence` | Nonblank text identifying the observation/evidence still needed to establish the condition |

Text fields retain the existing 600-character limit; the list permits zero to four
entries. Types, bounds, required fields, duplicate references and extra fields are
validated, not repaired. A KB ID must also belong to the retrieved evidence set.
The entries join `cited_items()`, so existing application/result-envelope reference
validation checks them, and synthesis citation-coverage counts include them. A
structurally valid ID does not prove the condition or action is documented; that
requires semantic review. Operational observations cannot authorize a future action.

Current escalation remains exactly `any(step.step_type == "escalation" for step in
steps)`. No guidance text, condition, reason or reference contributes to that value.
Future entries cannot contain `step_type`, `escalation_required`, or `trigger_basis`.
The unchanged canonical validators still enforce current status/steps, reason
presence, KB support and flag/step agreement. Guidance alone requires
`insufficient_evidence`, `steps=[]`, `escalation_required=false`, and a null current
escalation reason. False still means undetermined on abstention, not safe. Guidance
never records a completed action, changes tool execution, or sends an escalation.

For a first VPN failure with no retry, a current connectivity check/reconnect can
coexist with a future Network Support handoff conditional on persistent gateway
errors. A reported persistent gateway error after retry can independently support
a current escalation. A different future condition may coexist with that current
handoff without contributing to its flag or reason. The prompt retains human
review, approvals, source entailment and timestamp/uncertainty requirements, and
forbids hiding future handoffs in current steps, summaries or current reasons.

#### Public compatibility and schema impact

The canonical `InvestigationSynthesis` adds `conditional_guidance` with a fresh
empty-list default for legacy inputs. Existing scripted providers, canonical report
archives and deterministic abstentions continue to validate without supplying it.
The field is preserved in new JSON output, including `[]` when empty. Thus public
report/result JSON Schemas change additively; consumers with an older closed schema
must adopt the new field. This is input/backward compatibility, not byte-identical
serialization. Every pre-existing property, requiredness, nested definition and
invariant stays unchanged. Standalone Phase 2B contracts remain exactly unchanged.

V1's wire schema is retained unchanged for explicit compatibility checks; the live
provider does not negotiate or silently fall back to it. V2 requires the guidance
field, even when empty, consistent with the SDK's strict
[Structured Outputs contract](https://developers.openai.com/api/docs/guides/structured-outputs).
Missing/wrong versions, an omitted/null list, or the removed independently supplied
Boolean reject. Canonical conversion is followed by the same source-membership and
limitation checks. No invalid entry is dropped to salvage a report.

#### Evaluation and diagnostics

Both existing Phase 2 projections continue to select current `steps`, status,
flag and reason only. Conditional future actions never enter current-step citation
metrics or escalation precision/recall. Full agent outputs retain the future list;
manual review worksheets now include `conditional_guidance.N` entries for condition
entailment, applicability, missing-evidence usefulness and snapshot review. The
standalone worksheet/projection remains unchanged. The synthesis-specific citation
metric counts a guidance entry as one cited item, not proof of each claim's truth.

Telemetry recognizes canonical, V1 and V2 SDK names as synthesis. The diagnostic
allowlist derives its fixed field names from the canonical schema and therefore
includes the new guidance field locations; arbitrary keys/values, inputs, context,
messages and raw outputs remain excluded. No new error code, repair or retry path.
Rejected synthesis still preserves classification, KB/operational evidence, planner
decisions, lookup trace and prior errors; no partial recommendation is fabricated.

Nine additive development cases live in
`evaluation/investigation_conditional_guidance.jsonl`, using copied text and IDs
from the existing VPN/software KB. They do not alter frozen Phase 5A data, saved
Phase 5B pilots, labels or denominators. Reproduce the offline response replay with:

```powershell
uv run --locked --offline python -m evaluation.investigation_synthesis --cases evaluation/investigation_conditional_guidance.jsonl
```

Expected mechanics: seven accepted, two rejected (missing KB references and unknown
KB ID); 27/27 accepted references valid and 22/22 cited items covered; current
escalation labels match 6/7 accepted candidates. Four accepted cases are authored
positive controls; **three accepted cases are intentionally semantically wrong**:
an unsupported future action, a premature current escalation and an unsupported
condition. These are test expectations, not observed model accuracy or live quality.
Valid IDs do not prove that a condition is supported, unknown, or established now.

At the 5C.2b handoff, no typed trigger-evidence fields or Phase 5C.2c implementation
had been added; the separately authorized extension is described next.

### 5C.2c: typed current-escalation trigger evidence (implemented, final review passed)

`InvestigationSynthesisDraftV3` extends V2 with the required literal version
`investigation-synthesis-draft-v3` and a required nullable `trigger_basis` key.
The OpenAI provider requests and revalidates V3 only. V1/V2 remain explicit
historical contracts; there is no negotiation, response repair or version fallback.
The inherited conversion still derives `escalation_required` exclusively from
current escalation-typed steps, then invokes canonical validation. V3 additionally
rejects any current escalation lacking a non-null basis. With no current escalation,
canonical validation requires null. Guidance-only abstentions remain no-step reports
with a false flag and null reason/basis. Prose and future guidance never set the flag.

One report-level `EscalationTriggerBasis` has three required fields:

| Field | Contract |
| --- | --- |
| `policy_references` | One to eight distinct retrieved KB references authorizing current handoffs |
| `factual_references` | One to eight distinct ticket and/or successful operational-observation references claimed to establish current triggers |
| `explanation` | Nonblank text, at most 600 characters, connecting the facts to each current handoff policy with attribution and uncertainty |

The groups are disjoint by reference type. Context, KB-as-fact, ticket-as-policy,
empty groups, duplicates, wrong types and extra fields reject. Existing duplicate
reference validation is reused. A nonserialized `references` property exposes both
groups to the existing citation/coverage traversal. Every KB ID must be retrieved;
every operational ID must resolve to the investigation's evidence. Trigger facts
additionally require `result.status="ok"`. The graph supplies that subset of its
validated observations, and the outer result independently computes it from linked
lookups. Missing successful-ID sets fail closed for new operational trigger claims.
`not_found` remains citable as missing-information context elsewhere, never as a
current trigger; blocked, failed and unexecuted requests are not trigger evidence.
This is a small extension to the existing source validator, not a new graph or tool.

A successful lookup is **not** verification of a trigger, live freshness or causality.
The typed groups identify what the model claims supports its decision. They do not
interpret policy or establish that every handoff is entailed. The single explanation
must connect each current handoff to its policy/facts; semantic coverage for multiple
handoffs remains manual. No action-text detector, model judge or automatic retry.

Prompt `investigation-synthesis-v5` explains V3, preserves current-step/reason rules,
and requires ticket attribution and same-claim snapshot qualification in the basis.
It explicitly excludes future conditions, unrelated observations and failed/not-found
lookups as trigger proof. Existing freshness/limitation checks and source validation
remain in force. Required basis fields do not replace step citations, the KB-cited
escalation reason, or mandatory human review. Model/settings, budgets, planner, scope,
read-only tools, standalone RAG and CLI flags are unchanged.

#### Canonical compatibility and migration

`InvestigationSynthesis.trigger_basis` defaults to `None` for legacy inputs, including
legacy escalations. Existing V1/V2 conversion, scripted providers, stored reports and
deterministic abstentions still load. Non-null supplied bases are always validated;
canonical reports reject a basis without current escalation. The stricter V3 requirement
runs at SDK parsing, provider revalidation and conversion; the canonical legacy default
does not exempt live V3 output. There is no production adapter that invents basis fields.

Public report/result schemas add `trigger_basis` and `EscalationTriggerBasis`; new
serialization includes `trigger_basis:null` when absent historically. Consumers using
older closed JSON Schemas must update before consuming new reports. This is additive
input compatibility, not byte-identical output. Schema checks preserve all old fields,
both historical draft schemas and standalone Phase 2B schemas. SDK V3 fields remain
explicitly required, including null, following the
[Structured Outputs contract](https://developers.openai.com/api/docs/guides/structured-outputs).

#### Evaluation and failure handling

Both Phase 2 projections and escalation metrics continue to score current steps/flag
only. Full outputs and manual worksheets retain `trigger_basis.0` separately from
`conditional_guidance.N`; entailment, trigger applicability and snapshot freshness
remain pending reviewer judgments. Citation metrics include the basis as one cited
item and count both reference groups, without claiming semantic correctness.

Telemetry recognizes canonical/V1/V2/V3 names as synthesis. The diagnostic
sanitizer derives the new fixed field locations from the canonical schema; it still
retains only allowlisted types and bounded locations, never messages/input/context,
raw outputs or arbitrary exception text. The single new, exact allowlisted code
`escalation_trigger_mismatch` identifies missing current bases or bases without
current escalation; similarly named custom codes remain redacted. Existing four
custom invariant codes stay unchanged. This avoids a new ambiguous root `value_error`.
SDK rejection and provider revalidation map to `invalid_output`; invalid membership
or unsuccessful trigger observations map to `invalid_citation`. Missing limitations
still reject. One attempt only; failed synthesis preserves evidence, planner decisions,
lookup trace and prior errors, without an invented partial recommendation.

Fourteen additive authored cases live in `evaluation/investigation_trigger_basis.jsonl`.
They use V3 wire candidates; all previous evaluation inputs stay unchanged. Explicit
draft replay reuses the production V3 model/conversion, while the default evaluator
still loads historical canonical candidates. Reproduce without API calls:

```powershell
uv run --locked --offline python -m evaluation.investigation_synthesis --cases evaluation/investigation_trigger_basis.jsonl --draft-v3
```

Expected mechanics: **7 accepted, 7 rejected**, including 5 invalid outputs and 2
invalid citations; 40/40 accepted references valid, 27/27 cited items covered, and
5/7 current-escalation label matches. One guidance-only case abstains; no accepted
answerable case incorrectly abstains. Five accepted candidates are authored positive
controls. **Two accepted candidates are intentionally incorrect recommendations**:
stale incident data asserted as current causality, and unrelated account flags used
as gateway-trigger proof. Their valid references and populated basis do not establish
entailment. These are deterministic development replays, not live-model quality scores.

Existing SDK mock fixtures explicitly author placeholder basis claims when testing
legacy mechanical cases; frozen files are never edited and no such adapter runs in
production. New V3 cases author the field directly, including deliberate omissions
and invalid values. Phase 5C.3 has not begun.

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

## Phase 5C.2b verification (2026-10-28)

The final complete suite passed: **808 tests in 70.20 seconds**, including **76
PostgreSQL integration tests**. This retains the previous 753 cases with wire/output
expectations updated for the explicit extension, plus 55 regressions: 50 focused
guidance tests, two paired-run tests, one additional legacy telemetry case and two
restricted-database guidance cases. No paid API request was made.

Schema checks distinguish intentional extension from regression: six standalone
Phase 2B hashes remain exactly equal, six canonical/result comparisons match every
pre-existing field and definition after removing only the declared guidance
property/definition, and three V1 schema hashes are unchanged. Three V2 checks
also verify its shared fields, required list/version and excluded Boolean.
SDK mocks exercise strict schema serialization, parsing and canonical revalidation.
Legacy input omission defaults to `[]`; wrong versions, missing V2 fields, forbidden
reference types, missing/duplicate/unknown KB references, conflicting status/reason,
mutated SDK models, future trigger fields and invalid outer-result citations reject.

The first targeted invocation passed 181 cases but five temporary-output tests hit
the Windows filesystem sandbox; the complete suite ran with the required local
permissions. The first full run caught a missing snapshot disclaimer in a new paired
mock response. That fixture was corrected to satisfy the existing limitation rule;
no production check was weakened. Both paired cases and the final full suite pass.

The nine-case additive offline replay has the expected seven accepted/two rejected
outcomes described above. Its three accepted semantic negative controls remain
manual failures. Live-model quality, acceptance, cost and escalation improvement
are unmeasured. No model judge or NLP/keyword routing was introduced.

Before/after application fingerprints match for all **79 operational records and
36 KB chunks, vectors and metadata**. Temporary reader roles remaining: zero.
All eleven frozen evaluation JSON/JSONL files, twelve KB documents, twelve original
Phase 5B artifacts and six pre-existing Phase 5C report/verification files retain
their pre-change hashes. The baseline consolidator still verifies all seven saved
pairs without writes, API calls or database calls. No standalone RAG, classifier,
planner, graph, retrieval, operational tool/data, dependency or lockfile changes.

The additive public field means old strict consumers need the updated schema;
existing input/report loading and scripted pipelines remain compatible. Citation
membership and nonblank missing-evidence text cannot establish source entailment,
real-world trigger truth, freshness or action applicability. Human review remains
mandatory. No 5C.2c typed trigger evidence, staging, commits or pushes occurred.

Finalization review (2026-10-29) found no blocking issues across all twenty changed
files. The complete suite passed again: **808 tests in 55.67 seconds**, including
76 PostgreSQL integration tests and the schema compatibility checks described above.
The initial verification attempt stopped before tests because Docker Desktop and
the existing database container were stopped; starting them preserved the existing
volume, with no recreation or reseeding. Before/after fingerprints again match all
79 operational records and 36 KB chunks, vectors and metadata; no temporary test
reader roles remain. Frozen evaluation inputs, original Phase 5B reports and archived
Phase 5C baseline hashes remain unchanged. The nine-case replay again produced
seven mechanical acceptances and two rejections; the three accepted semantic negative
controls remain explicitly incorrect recommendations. No credentials, local environment
files or generated reports are included. The user authorized normal commit/push
after these checks. No paid calls or Phase 5C.2c development occurred.

## Phase 5C.2c verification (2026-10-29)

The final complete suite passed: **891 tests in 52.21 seconds**, including **80
restricted PostgreSQL integration tests** and **811 offline tests**. All previous
808 cases remain, with SDK/serialization expectations updated for the explicit
extension. The 83 added cases include 75 focused trigger regressions, four restricted
database cases, two paired-evaluation cases, one V2 live-fallback rejection and one
V3 telemetry identity. The first complete pass had 886 successes; review then added
the exact trigger-invariant diagnostic code and five redaction/SDK tests before the
final full pass. No production acceptance rule was weakened.

Schema checks preserve the exact V1/V2 hashes in validation, serialization and SDK
forms, and exact standalone Phase 2B hashes. Canonical/report compatibility checks
remove only the declared new property/definition before comparing with the 5C.2b
hashes; older parity checks likewise preserve every pre-existing field. Current V3
checks require its literal version, nullable basis key and guidance list, omit the
independently generated Boolean, and reuse the canonical field constraints. Legacy
canonical escalation reports still load without basis; V3 cannot use that exemption.

The additive fourteen-case replay produced **7 accepted and 7 rejected** as specified
above. Both accepted negative controls remain manual failures. The seven saved pilot
pairs still pass baseline verification without writes or API/database calls. All
twelve pre-existing evaluation JSON/JSONL files, twelve KB documents, twelve original
Phase 5B reports and seven pre-existing Phase 5C archive/verification files retain
their preimplementation hashes. Only the nine approved application/evaluation source
modules differ in that protected-file manifest.

Read-only fingerprints taken before implementation and after the complete tests match
all **79 operational records and 36 KB chunks, vectors and metadata**. Full-suite
before/after fingerprints also match; temporary test reader roles remaining: **0**.
Integration fixtures initialize only the separate disposable test database. Application
data was never initialized, reseeded or modified. Secret/path scans and whitespace
checks pass; environment files and generated verification artifacts remain ignored.

Changed files (23):

- Application: `app/investigation/schemas.py`, `synthesis_draft.py`, `synthesis.py`,
  `graph.py`, and `app/providers/openai_synthesis.py`.
- Evaluation: `evaluation/investigation_synthesis.py`, `investigation_e2e.py`,
  `live_telemetry.py`, `synthesis_diagnostics.py`, and the new
  `investigation_trigger_basis.jsonl`.
- Tests under `tests/investigation/`: new `test_trigger_basis.py`, `conftest.py`,
  `test_conditional_guidance.py`, `test_live_evaluation.py`,
  `test_live_investigation_cli.py`, `test_postgres.py`, `test_synthesis_diagnostics.py`,
  `test_synthesis_draft.py`, `test_synthesis_semantics.py`, `test_validation_invariants.py`.
- Documentation: `docs/phase5c.md`, `docs/phase4b2.md`, `docs/phase5b.md`.

Remaining risks: basis references can be real while the explanation is unsupported,
stale or unrelated; a populated basis is not an authorization or entailment proof.
Multiple-handoff applicability remains manual. Strict downstream JSON consumers
must update their schema. Live V3 acceptance and semantic quality are unmeasured.
No paid calls, staging, commits, pushes or Phase 5C.3 implementation occurred.

Finalization review (2026-10-30) reconciled the inventory exactly: **21 modified
tracked files plus two new development files, 23 total**. No blocking findings.
The complete suite passed again: **891 tests in 53.32 seconds**, including all
80 PostgreSQL integration tests and schema compatibility checks. The initial
verification attempt stopped before tests because Docker Desktop and the existing
database container were stopped; both were restarted without recreation or reseeding.
Application fingerprints match the preimplementation snapshot and the suite's
before/after snapshots; all 79 operational records and 36 KB chunks/vectors are
unchanged, with zero temporary reader roles. Frozen fixtures, original reports
and archived baseline hashes match. The fourteen-case V3 replay again produced
seven mechanical acceptances and seven rejections; its two accepted semantic
negative controls remain explicitly incorrect. The new evaluation fixture and
test file are included in the approved commit inventory. No credentials, local
environment files, generated reports or unrelated changes are included. The user
authorized a normal commit/push after verification. No paid calls or Phase 5C.3
development occurred during finalization.

## Phase 5C.3 implementation

Local `main`, its remote-tracking ref and GitHub were verified at
`c71f00d7bdf68bb94eb2f8b4a65b9e735939b275` before changes. Direct GitHub access
failed; a command-scoped local proxy verified the remote without changing Git
configuration, fetching, committing or pushing.

### Minimal terminal contract

The live provider now requests `PlannerResponseV2`, a closed application-owned
Structured Outputs envelope with required literal version
`"investigation-planner-response-v2"`. Its nested decision adds one choice:

```json
{
  "schema_version": "investigation-planner-response-v2",
  "decision": {"kind": "insufficient_evidence", "gap_kind": "documentation"}
}
```

There is no free-text reason, action, missing-field list or invented identifier in
that variant. The original six typed lookup variants, finish and clarify retain
their contracts. The historical unversioned `PlannerResponse` remains unchanged;
there is no version negotiation, automatic conversion of old live envelopes, or
fallback. Scripted providers still return plain decision dictionaries and can
use the new decision without a wire envelope. Existing scripts remain valid.

Planner prompt v4 distinguishes three terminal meanings:

| Choice | Intended use |
| --- | --- |
| `clarify` | Actually missing scope or symptom information would enable useful permitted investigation or distinguish applicable documented branches. |
| `insufficient_evidence`, `gap_kind=documentation` | Supplied KB material does not establish an applicable procedure. Unrelated identifiers and operational lookups cannot supply missing policy. |
| `finish` | Further permitted lookups would not help; a procedural gap is not the blocker. An applicable diagnostic/handoff can proceed to synthesis even with optional IDs absent. |

The prompt preserves marginal-information-gain guidance and directs the planner
to consider useful available lookups before clarifying or declaring a procedural
gap. A supplied identifier only permits a lookup; it does not make it relevant.
Tool failures, stale records and absent optional IDs do not themselves prove a
documentation gap. Conversely, having retrieved chunks does not prove any is
applicable. There is no keyword router, distance threshold or model judge.

Existing clarification validation still rejects duplicate labels and requests for
already supplied scope. Relevance of an absent identifier and procedure
applicability remain semantic judgments; deterministic validation cannot prove
them. This change gives the model an appropriate outcome and clearer instructions,
not a guarantee that it will always choose correctly.

### Graph behavior and compatibility

The existing plan node validates the decision, records the terminal trace and
stops the lookup loop. No node, execution loop or guard was added. With synthesis
enabled, the synthesis node intercepts the documentation terminal after its
existing deadline/context guards. It uses the existing canonical abstention
formatter and makes **zero synthesis calls**:

> The supplied KB evidence does not establish an applicable documented procedure
> for this request. Escalation need is undetermined.

The report asks for applicable procedure documentation for human review. It has
`status=insufficient_evidence`, no current steps, empty conditional guidance,
`escalation_required=false`, null escalation reason/basis, and context-cited
summary/uncertainty. It neither requests unrelated IDs nor asserts that no
procedure exists elsewhere. False escalation is not a safety assessment. This
fixed text records the planner's bounded judgment; it is not independent proof
that the planner assessed the KB correctly.

The result records `stop_reason=insufficient_evidence` and the synthesis trace
records `documentation_abstention`. `missing_fields=[]`; planner decisions,
classification, retrieved chunks, executed observations, timestamps, errors and
traces remain intact. A clean terminal is completed; existing errors still yield
partial if usable evidence exists, otherwise failed. Completion does not mean
resolution. Blocked/failed lookups, budget stops and planner errors cannot be
bypassed by a later scripted documentation terminal. No retry/repair occurs.

Without a synthesis provider (scripted CLI or plain live CLI), the existing
planner-only output convention remains: no synthesis node, `not_run`, zero
attempts, null recommendation, with the new terminal reason/trace and retained
evidence. CLI flags and exit codes are unchanged. All reports remain advisory,
with mandatory human review and no mutating actions or authorization workflow.

Public result and synthesis JSON Schemas are unchanged. Exact hash checks cover
historical planner, canonical report/result, synthesis drafts V1/V2/V3 and
standalone Phase 2B in validation, serialization and SDK forms (21 checks).
Strict **planner wire** consumers must adopt V2; consumers exhaustively handling
stop-reason strings must recognize `insufficient_evidence`. No canonical report
migration is needed. Synthesis V3 policy/factual triggers, current-step-derived
escalation, conditional guidance, membership validation and all Phase 2B behavior
remain unchanged.

Telemetry recognizes both `PlannerResponse` and `PlannerResponseV2` as planner
requests. The existing evaluation recorder preserves the new typed terminal;
recommendation projections still score current actions only. Paired mocks verify
zero synthesis requests/diagnostics for this path, retained identical KB evidence,
normal standalone generation and no current escalation. Failure codes and
redaction remain unchanged. Revalidation suppresses Pydantic serialization
warnings from mutated parsed planner objects, since those warnings can include
input values; the objects still reject, without logging those values.

### Development evaluation and reproduction

`evaluation/planner_terminals.jsonl` is an additive eight-case development set;
`evaluation/planner_terminals.py` reuses the existing scripted dependencies and
graph. It contains cafeteria recovery, genuine missing employee/product scope,
supported troubleshooting without optional IDs, irrelevant KB, and missing
essential symptom detail. Two explicit negative controls cover irrelevant-ID
clarification and premature documentation abstention despite a supplied procedure.
They are intentionally accepted structurally and **semantically incorrect**.

```powershell
uv run --locked --offline --extra dev python -m evaluation.planner_terminals
uv run --locked --offline --extra dev python -m evaluation.investigation_synthesis --cases evaluation/investigation_trigger_basis.jsonl --draft-v3
uv run --locked --offline --extra dev python -m evaluation.phase5b_baseline
uv run --locked --offline --extra dev pytest -m "not integration"
uv run --locked --offline --env-file .env.db --extra dev pytest
```

The final command requires locally configured administrative application/test
URLs for fingerprint verification/test setup; integration fixtures modify only a
separate disposable `_test` database. Production graph lookups use restricted
reader credentials. No model key, paid call or application reseeding is required.
Baseline verification additionally needs the locally archived reports described
above; originals and derived archives are not rewritten. Fingerprints must be
compared before and after testing, including vector contents, not just counts.

Replay reports 8/8 mechanical completions, 6/8 matches to authored terminal and
missing-field expectations, and two accepted incorrect negative controls. These
are fixture assertions, **not measured live-model accuracy or improvement**.
No evaluation labels enter the planner payload. The prior 14-case V3 replay still
has seven accepted and seven rejected responses; its two accepted semantic
negative controls remain incorrect. Full verification results follow below.

### Phase 5C.3 verification (2026-10-30)

The complete suite passes **961 tests: 879 offline and 82 PostgreSQL integration**,
preserving the previous 891 cases and adding 70. This includes the 21 exact schema
hash checks, eight-case scripted and mocked-SDK terminal replay, strict wire-version
and variant rejection, revalidation without value-bearing warnings, fixed abstention,
genuine clarification, unchanged supported synthesis, partial/failed results,
deadline/budget/guard stops, evidence retention, CLI behavior, telemetry and paired
evaluation. Two new restricted-reader integration cases use scripted/mocked-SDK
planners and compare full database snapshots before/after the terminal branch.

The initial full pass emitted warnings only from an intentionally corrupted parsed
planner test object. Suppressing those warnings before unchanged validation and
asserting no warning emission removed that diagnostic exposure. Final prompt review
also changed the older generic "finish when lookups are redundant" wording to
"choose a terminal decision", aligning it with the new terminal choices. No safety
guard, schema acceptance rule, synthesis policy or production fallback was weakened.

Before/after application fingerprints, and comparison with the preimplementation
snapshot, preserve **79 operational records and 36 KB chunks, vectors and metadata**.
Temporary integration reader roles remaining: zero. All 46 pre-existing protected
data/report files retain their hashes: 13 evaluation JSON/JSONL inputs, twelve KB
documents, twelve original Phase 5B artifacts and nine archived Phase 5C files.
Baseline verification still validates all seven saved pairs without writes or API
calls. The nine-case conditional-guidance replay remains seven accepted/two rejected,
with its three accepted negative controls explicitly incorrect. The fourteen-case
V3 results are unchanged as described above.

Changed inventory: **19 files (16 modified, three new)**:

- Application (5): `app/investigation/schemas.py`, `planner.py`, `graph.py`,
  `scripted.py` (comment only), and `app/providers/openai_planner.py`.
- Evaluation (3): `evaluation/live_telemetry.py`, new `planner_terminals.py` and
  new `planner_terminals.jsonl`.
- Tests (8, under `tests/investigation/`): new `test_planner_terminals.py`,
  `conftest.py`, `test_openai_planner.py`, `test_planner_efficiency.py`,
  `test_live_evaluation.py`, `test_live_investigation_cli.py`, `test_postgres.py`,
  and `test_synthesis_semantics.py` (current planner schema identity only).
- Documentation (3): `docs/phase4b1.md`, `docs/phase4b2.md`, `docs/phase5c.md`.

Whitespace and secret-format scans pass. Local environment files, credentials and
generated reports remain ignored; nothing is staged. No dependencies, database
schema, seed data, frozen input, V3 synthesis implementation, standalone RAG,
retrieval, operational tool, execution policy or budget changed. New fixture files
are intentionally uncommitted development inputs, separate from frozen baselines.

Remaining limitations: an absent ID can still be requested irrelevantly if the
model ignores instructions; a typed documentation gap can still be premature.
Real reference IDs, valid envelopes and fixed abstention text do not prove
applicability, completeness or source entailment. Manual review remains necessary.
Live planner quality and any reduction in irrelevant clarifications are unmeasured.
No paid API calls, staging, commits, pushes or Phase 5C.4 implementation occurred.

Finalization review (2026-10-31) reconciled all **19 files: 16 modified and three
new development files**. No blocking findings. The complete suite passed again:
**961 tests in 83.52 seconds**, including all 82 PostgreSQL integration tests and
21 exact schema parity checks, with no warnings or skipped tests. The eight-case
terminal replay again produced six expected choices and two explicitly incorrect
semantic negative controls; the existing fourteen-case V3 replay retained seven
acceptances and seven rejections, including its two incorrect accepted controls.
All seven original Phase 5B saved pairs passed baseline verification without writes.
Application fingerprints match both the suite's before/after snapshots and the
preimplementation snapshot: 79 operational records and 36 KB chunks/vectors are
unchanged, with zero temporary reader roles. All 46 protected fixture, KB, original
report and archived baseline files retain their hashes. The exact V2 envelope,
deterministic terminal, compatibility, safe diagnostics, unchanged guards and
failure preservation passed review. Environment files and generated artifacts are
ignored, and no credentials or unrelated files are included. The user authorized
normal commit/push after these checks. No paid calls or Phase 5C.4 work occurred.

## Phase 5C.4: synthesis grounding and usefulness

Implemented against clean `main` at `e00910abb39305f76189d1f7e3f6831c970dec9b`.
The Phase 5B source review above is the motivation, including the repeated
confirmed-case reconnect, wrong-section route-refresh rationale, old incident
described as ongoing, unreported password-change prerequisites and a 600-character
summary ending mid-word. Rejected pilot outputs remain unavailable and are not
retroactively assigned semantic causes or grades.

### Prompt v6, unchanged V3 contract

Only `INSTRUCTIONS` and `PROMPT_VERSION` change in application code, both in
`app/investigation/synthesis.py`. The current identifier is
`investigation-synthesis-v6`; the SDK still requests
`InvestigationSynthesisDraftV3`. Models, model settings, 3,000-token output cap,
one-attempt synthesis behavior, graph, planner V2, guards, citations, schemas,
conditional guidance and typed trigger evidence are unchanged. Standalone Phase
2B is the fixed comparator, including its previously documented applicability
limitations. No output trimming, rewriting, keyword checks or semantic repair is
added. A valid but ungrounded response can still pass structural validation.

Precise instruction changes:

- Select the section matching symptoms and established prerequisites. Do not
  borrow a neighboring section's rationale. Unknown prerequisites remain unknown;
  useful documented future actions belong in conditional guidance.
- Separate completed checks from remaining actions. Record completed work as
  ticket-attributed findings. A repeat needs a reason supported by new evidence
  and the documented procedure. Ask for a specific missing detail when completion
  is unclear rather than prescribing the whole sequence again.
- Cite the source of case-specific values inside action text as well as findings.
  KB references must support both action and stated purpose. Split compound
  claims when different sources support different parts.
- Preserve same-claim timestamp/current-state qualifications. A user report of a
  current incident confirmation does not upgrade an older operational snapshot.
  Returned scoped devices and empty `missing_entities` do not prove complete
  physical inventory. Existing version-support/authentication distinctions remain.
- Prefer one or two short complete summary sentences describing the reported
  problem and supported disposition/evidence gap. Keep details in findings. The
  unchanged 600-character cap is a ceiling; rewrite to fit instead of clipping
  words or concatenating fragments.

Four compact teaching examples illustrate completed versus remaining diagnostic
work and conditional handoff, symptom-branch/prerequisite matching, narrow
inventory/authentication attribution, and a complete summary. The retry example
explicitly requires connectivity to have been confirmed first. They are patterns,
not extra KB policies or citable evidence, and no example identifiers or fixed
tool sequence are introduced. This follows the [official OpenAI prompt guidance](https://developers.openai.com/api/docs/guides/prompt-engineering)
on versioning instructions in code and supplying a small variety of examples.

Historical prompt v5 remains recoverable at the starting commit, with UTF-8
instruction SHA-256
`12fe0946860ddf444c0937dc01b4d85bfdc0daf4af12c8589bdb2b1f2533d3f9`.
The v5 prompt had 1,365 whitespace-separated words; v6 has 1,751. This is a small
instruction/example extension, not a model migration or added model call. It does
increase input length; actual token cost, latency and quality impact are unmeasured.
Live evaluation metadata reads v6 for future runs; historical prompt identifiers,
reports, provenance and checksums are never relabelled.

### Additive development cases

`evaluation/investigation_synthesis_usefulness.jsonl` contains **26 authored V3
responses: 13 positive and 13 deliberate semantic negative controls**. It reuses
`SynthesisCase`, the existing replay provider and application validators; no new
evaluation engine or model judge is introduced. KB IDs and section text match the
existing corpus. Compact operational strings are fictional authored observations,
not modified database records or actual collected live evidence. No expected
label or review note is passed into model inputs.

| Contrast | Manual review target |
| --- | --- |
| Completed Corporate retry versus repeating it | Acknowledge completed checks; recommend only the justified remaining handoff. |
| First failure without retry versus immediate handoff | Retry remains useful; future escalation must not become current. |
| Dated incident snapshot versus ongoing causal claim | Same-claim timestamp qualification and no inferred current user impact. |
| Reported current incident confirmation versus upgraded operational claim | Attribute current confirmation to the ticket; do not treat it as independent tool verification. |
| Connection-failure versus connected-resource branch | Action, purpose, symptoms and cited section must agree. Both directions have positive/negative examples. |
| Confirmed password change versus an invented extra change | Remove saved credentials only under the documented prerequisite; do not prescribe another password change. |
| Unreported password change: future guidance versus current step | Guidance-only insufficient evidence is valid; asking the prerequisite does not justify acting as if it occurred. |
| Recorded client version versus approved-version claim | Inventory does not supply a support policy. |
| Account flags versus successful authentication | Configuration/old login history do not prove success. An additional positive attributes a reported diagnostic event to the ticket. |
| Returned device records versus exhaustive inventory | Do not infer undiscovered-device absence. |
| Complete summary versus mid-word/awkward endings | Length and punctuation checks are not readability or completeness judgments. |

There is **no verified-live operational source in this architecture**: tool outputs
require `live_verified=false`. The current-incident contrast therefore uses a
ticket reporting a status-page confirmation, explicitly attributed as unverified
by this investigation. It does not pretend to supply an independently verified
incident feed. A regression also confirms `live_verified=true` cannot pass the
existing operational contract. A future real live-source integration would need
separate design and approval; none is added here.

All 26 authored responses intentionally pass schema/reference checks, including
the 13 incorrect controls. That result demonstrates the limits of mechanical
validation, **not 26 correct recommendations**. The first-failure negative includes
real ticket/KB IDs and a populated typed basis that falsely alleges a retry; it
still fails manual trigger review. The replay CLI now prints authored manual labels
alongside mechanical outcomes for all datasets; existing metrics/denominators are
unchanged. Labels are fixture annotations, not measured live-model grades.

### Manual worksheet v2

`review_items()` is shared by the deterministic paired replay and opt-in live
runner. Worksheet cases now declare `investigation-manual-review-v2`, with explicit
criteria and four additive item fields. Existing item fields and current-action
metric projections retain their meaning. Original saved worksheets are not
rewritten. Strict consumers of new worksheet JSON must accept the added fields;
production recommendation/report schemas do not change.

For each item, a human splits compound text into `atomic_claims`, compares each
with the supplied evidence, and records `pass`, `fail` or `not_applicable` for each
dimension with source-specific notes. `None` remains pending; the code never
populates a semantic grade or treats a valid citation as a pass.

| Criterion | Review question |
| --- | --- |
| `entailment` | Does the cited text establish each atomic claim, including action purpose and values? |
| `attribution` (new) | Is the claim correctly attributed to ticket, snapshot, documented policy or explicitly unverified inference? |
| `snapshot_freshness` | Does each dependent claim retain the actual source time and uncertainty without substituting query time? |
| `applicability` | Do symptoms and prerequisites select this exact procedure branch? |
| `completed_vs_proposed` (new) | Has the action already been completed, and is any repetition independently justified? |
| `trigger_established` | Does each current handoff have applicable policy and factual trigger support? Future guidance is separate. |
| `practical_usefulness` (new) | Is the remaining action useful, non-redundant and within human role/approval boundaries? |
| `summary_completeness` (new) | Is the summary coherent, complete and concise? Apply to summary items; other items can be not applicable. |

Both arms get the same review dimensions, judged only against their available
evidence. Standalone is not penalized for lacking operational observations. Failed
or rejected reports have no claim items and remain unreviewed/unavailable, never
semantic successes. The manual grades are not automatically aggregated into a
model-quality score in this milestone.

### Verification and reproduction

```powershell
uv run --locked --offline --extra dev python -m evaluation.investigation_synthesis --cases evaluation/investigation_synthesis_usefulness.jsonl --draft-v3
uv run --locked --offline --extra dev python -m evaluation.investigation_synthesis --cases evaluation/investigation_trigger_basis.jsonl --draft-v3
uv run --locked --offline --extra dev python -m evaluation.planner_terminals
uv run --locked --offline --extra dev python -m evaluation.phase5b_baseline
uv run --locked --offline --env-file .env.db --extra dev pytest
```

The database command requires the existing separate disposable `_test` database;
application records and vectors are fingerprinted read-only before and after the
suite. Baseline verification needs the locally archived historical reports already
documented above and does not rewrite them. No paid requests or API key are needed
for replay/tests. All tests use mocks/scripted components for model requests.

New regression coverage includes every authored V3 candidate through real SDK
parsing over mocked HTTP and deterministic replay, unchanged model settings and
one request, no label leakage, and exact preservation of accepted text. Deliberate
bad citations, missing KB support, inconsistent reasons/basis, and a 601-character
summary still reject without repair or retry. Full graph cases exercise completed
work, first failure and guidance-only abstention, plus provider failures retaining
classification, KB, executed observations and human-review boundaries. Existing
paired/live artifact tests verify the additive worksheet fields remain pending.

Remaining risks: these examples are development inputs based on observed defects,
not a held-out benchmark. Structural tests cannot establish that a live model
follows v6, that a claim is entailed, or that a summary is useful. Prompt growth
can introduce tradeoffs and requires later controlled evaluation. There are no
paid calls, commits, pushes or Phase 5C.5 pilot implementation in this milestone.

### Phase 5C.4 verification (2026-10-31)

The final complete suite passed **1,004 tests in 79.19 seconds**, with no warnings
or skips: **922 offline and 82 PostgreSQL integration tests**. All 961 previous
cases remain, plus 43 regressions. The suite includes the 21 exact validation,
serialization and SDK schema parity checks. The first complete pass also passed;
final review then made the teaching example's connectivity prerequisite explicit
and reran the full suite. No validation rule was changed to make a test pass.

Replay results, with semantic negatives kept distinct from mechanical acceptance:

| Dataset | Cases | Accepted | Rejected/failed | Accepted authored semantic negatives |
| --- | ---: | ---: | ---: | ---: |
| Original synthesis | 11 | 8 | 3 | 4 |
| Prior synthesis semantics | 14 | 14 | 0 | 5 |
| Conditional guidance | 9 | 7 | 2 | 3 |
| V3 trigger basis | 14 | 7 | 7 | 2 |
| New usefulness controls | 26 | 26 | 0 | 13 |

The eight-case planner-terminal replay still yields six expected choices and two
incorrect controls. Frozen Phase 5A paired replay preserves its 12 cases, 16/17
expected lookups, one redundant and one unnecessary lookup, and 12 pending manual
reviews. The seven original Phase 5B pairs still pass baseline verification without
writes or model/database calls. The new replay CLI explicitly prints the 13
acceptable and 13 incorrect authored labels, with no live-model quality claim.

Read-only fingerprints match the preimplementation snapshot and the suite's own
before/after snapshots for **79 operational records and 36 KB chunks, vectors and
metadata**. Temporary reader roles remaining: zero. All **49 pre-existing protected
data/archive files** retain their hashes: 14 evaluation JSON/JSONL inputs, twelve
KB documents, twelve original Phase 5B artifacts and eleven Phase 5C archive files.
All pre-existing application modules except the synthesis prompt file are byte-for-byte
unchanged. Comparing that file's parsed Python AST after excluding only
`INSTRUCTIONS` and `PROMPT_VERSION` also matches the starting commit exactly.
This verifies that payload building, abstention and runtime validation did not change.
Current v6 instruction SHA-256:
`28dfa57eb493444f75a2b33e6c99180d66dbfce1d8d29701cbe72801d60697f7`.

Changed inventory: **12 files (10 modified, two new)**:

- Application: `app/investigation/synthesis.py`.
- Evaluation: `evaluation/investigation_e2e.py`, `investigation_synthesis.py`,
  `live_investigation.py`, and new `investigation_synthesis_usefulness.jsonl`.
- Tests under `tests/investigation/`: new `test_synthesis_usefulness.py`,
  `test_synthesis_semantics.py`, `test_e2e_evaluation.py`, `test_live_evaluation.py`.
- Documentation: `docs/phase5c.md`, `docs/phase4b2.md`, `docs/phase5b.md`.

Whitespace and secret-format scans pass. Local credentials, environment files,
generated reports and the one-time fixture authoring helper remain ignored;
only the resulting development JSONL is part of the proposed change. Nothing is
staged, committed or pushed. No dependencies, models, model-call budgets, planner,
retrieval, tools, schemas, frozen inputs or standalone RAG code changed. Live
semantic quality, token usage and latency remain unmeasured pending separate approval.

Finalization review (2026-10-31) found no blocking issues across the **12 intended
files**, including both new development files. No implementation, fixture or test
changes were needed; only this review record was added. Static source review
confirmed that application code differs from `e00910a` only in the two synthesis
prompt constants, and both recorded prompt hashes match. Examples, control labels,
pending manual grades, model-input separation, compatibility and excluded local
artifacts match the documented scope. No material change to the verified code,
fixtures, dependency configuration or environment was identified.

Per the user's risk-based verification instruction, the existing **1,004-test
pass (82 PostgreSQL tests and 21 schema parity checks)** and prior evaluation,
database and archive integrity results were reused. No tests, database fingerprints
or historical baseline consolidation were rerun. This documentation addition
changes no executable example or command. The user authorized a normal commit and
push after staged-diff review. No paid API calls or Phase 5C.5 work occurred.
