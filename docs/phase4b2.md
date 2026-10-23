# Phase 4B.2: evidence-grounded investigation synthesis

This milestone adds one optional OpenAI synthesis request after the existing
bounded investigation loop. It produces a structured advisory report from the
ticket, retrieved KB procedures and validated operational observations. It does
not change planner selection, scope policy, tool execution or database access.
There are no new dependencies, migrations, seeds or credentials.

The initial implementation and its 510-test validation are recorded below.
See [the live-review correction](#live-review-correction-prompt-v2) for the later
semantic reliability adjustment and its separate offline evaluation.

## Architecture

```text
validate -> classify -> retrieve -> plan -> guard -> execute -> plan ...
                                   |        |         |
                                   +--------+---------+-- stop
                                                         |
                                                    synthesize
                                                         |
                                                      assemble
```

Early stops from classification/retrieval also reach synthesis. Without a
synthesis provider the original graph routes directly to assembly. The CLI
enables the new node only with `investigate live --synthesize`; plain live
planning and both scripted modes remain available with their original behavior.
Programmatic dependency injection also supports fake synthesis with scripted
planning for deterministic tests. No live synthesis was run for this milestone.

| File | Responsibility |
| --- | --- |
| `app/investigation/schemas.py` | Application-owned report, typed references, source membership and structural escalation validation |
| `app/investigation/synthesis.py` | Fixed prompt, immutable JSON evidence snapshot, abstention and provider-independent validation |
| `app/providers/synthesis.py` | One-method provider protocol and fixed error type |
| `app/providers/openai_synthesis.py` | Independent model setting, strict Structured Outputs, bounded SDK request and sanitized errors |
| `app/investigation/graph.py` | Optional synthesis node; preserves observations, traces, stop reason and existing failure semantics |
| `app/investigation/cli.py` | Explicit opt-in and model metadata in JSON output |
| `evaluation/investigation_synthesis.jsonl` | Eleven fictional, labelled response-replay cases and manual review rubrics |
| `evaluation/investigation_synthesis.py` | Offline replay and mechanical metrics; no model judge or network calls |

The existing classifier, retrieval query construction, pgvector store, six tools,
planner prompt and decision validation are reused unchanged. Synthesis does not
retrieve again, execute tools or feed instructions back into the planning loop.
The standalone Phase 2B.1 recommendation pipeline is unchanged. The new schema
projects its steps/status/escalation fields into `SupportRecommendation` to reuse
the existing consistency rules and text limits. Its prompt preserves Phase 2B.1's
applicability, conditional-handoff, identity-check and approval requirements while
adding operational evidence. It does not make a second standalone RAG request.

## Report and evidence contracts

`InvestigationSynthesis` contains:

- `status`: `supported` or `insufficient_evidence`.
- `summary`: cited descriptive statement.
- `findings`: up to eight cited statements.
- `steps`: up to six cited actions, each typed `troubleshooting` or `escalation`.
- `missing_information`: up to five requests for needed context/documentation.
- `uncertainties`: up to eight cited statements.
- `escalation_required` and nullable, cited `escalation_reason`.

Every statement/action requires one to eight distinct typed references. All
objects are closed; response fields are required, including nullable fields.
Each text is nonblank and at most 600 characters. The SDK receives the
application schema using `responses.parse(text_format=InvestigationSynthesis)`;
nested reference alternatives use `anyOf` and explicit required discriminators,
following the [Structured Outputs requirements](https://developers.openai.com/api/docs/guides/structured-outputs).

| Reference | Permitted meaning |
| --- | --- |
| `{"kind":"kb_chunk","chunk_id":"..."}` | A retrieved documented procedure, condition or prohibition |
| `{"kind":"operational_observation","lookup_id":"lookup-1"}` | A validated read-only lookup's recorded facts, including negative/not-found results |
| `{"kind":"ticket"}` | What the user reports; not independently verified state |
| `{"kind":"investigation_context"}` | Run limits, missing evidence, errors, clarification and fixed snapshot/review metadata |

Every summary, finding, uncertainty, step and escalation reason is checked for
reference membership. Any unknown chunk or lookup ID rejects the entire candidate.
The outer result validates references again. A step must include at least one KB
reference: ticket text, snapshots and historical resolutions cannot independently
authorize procedures. Escalation requires an escalation-typed step and a KB-cited
reason. `supported` requires steps; `insufficient_evidence` forbids steps and has
`escalation_required=false`, `escalation_reason=null`.

The prompt requires the whole claim to be supported by its cited evidence,
including summaries, branch conditions and escalation triggers. It forbids
invented commands, contacts, approvals, repairs and promised outcomes. Conflicting
sources must be cited together, with uncertainty preserved; dependent actions
must be withheld unless an independently applicable documented action remains.
Missing information must not request passwords, API keys or MFA codes.

**These are two different checks:** code guarantees schema/reference membership
and KB citation presence; applicability, entailment, correct source type usage
and summary groundedness require manual content review. Attaching a real KB ID
to an invented action does not make it supported. There is no semantic verifier,
LLM judge, relevance-distance threshold or automatic policy authorization engine.

The outer result retains complete KB chunks with source path, section, chunk
metadata and distance, plus typed operational results and lookup outcomes.
`queried_at`, observation/update/last-seen timestamps and `live_verified=false`
remain available. Prompt instructions distinguish recorded synthetic snapshots
from verified live state; a recent query or historical timestamp does not prove
freshness. A report using operational observations must include uncertainties;
an incomplete run additionally requires an uncertainty referencing run context.
These checks establish the presence of limitations, not their semantic accuracy.

## Flow, budgets and failure semantics

The new result fields are `synthesis_status` (`not_run`, `completed`, `failed`,
`skipped`), `synthesis_attempts` (0 or 1), and nullable `recommendation`.
Opt-in results have `phase=4B.2`. Classification is retained separately and is
not passed as factual evidence to synthesis.

| Situation | Behavior |
| --- | --- |
| No provider / existing scripted or plain live mode | No synthesis node; `not_run`, zero attempts, null recommendation |
| Planner requests valid clarification | Application-generated abstention, zero synthesis calls; preserves missing fields |
| No retrieved KB procedures, including retrieval failure | Application-generated abstention, zero synthesis calls; preserves observations and component errors |
| Valid evidence and finish | One provider attempt, full schema/source validation, then assembly |
| Partial investigation with some KB evidence | May produce a limited report; requires contextual uncertainty and cannot promote the run to completed |
| Deadline exhausted or context limit reached before synthesis | `skipped`, zero calls, null recommendation and a fixed synthesis error |
| Refusal, malformed/missing/incomplete output, API failure or invalid citation | `failed`, one attempt, null recommendation; gathered evidence and traces remain |
| Deadline reached after the request | Discard candidate, record failure; never present a late response as a successful recommendation |

Original completion rules remain: clean `finish`/`clarify` with no errors is
`completed`; errors/limits with classification or KB/operational evidence produce
`partial`; no usable evidence produces `failed`. Completed means the workflow
finished, not that an issue was repaired or the report was verified correct.
An abstention can be a completed synthesis while the investigation remains
failed/partial. Synthesis errors are recorded separately from the original stop
reason, so a `finish` may have a `partial` overall result after synthesis fails.
CLI exit codes remain 0 completed, 2 partial, 1 failed.

The existing four planner decisions, four lookup attempts, 24,000-character
operational context cap and 120-second run budget remain. Synthesis adds at most
one request: zero retries, a 30-second SDK timeout, 3,000 output tokens and a
64,000-character serialized payload cap. There is no repair loop, extra lookup,
truncation of evidence or budget extension. The run deadline is checked before
and after synthesis; it is not hard cancellation of an in-flight network call.
`store=False` and disabled LangSmith tracing are retained; this is not a claim of
zero provider retention. Errors expose fixed codes, not raw model/API bodies.

No action is executed. `mutating_actions_executed=false` and
`human_review_required=true` remain application-controlled. The latter is a
mandatory review indicator, not an approval UI, authorization check, persistence,
pause/resume mechanism or unattended escalation. On abstention, false escalation
means no grounded escalation was issued, **not** that escalation is unnecessary
or the issue is safe. The prompt and deterministic abstention explicitly state
that escalation need is undetermined.

## Local CLI

Use the previously provisioned restricted readers. Neither operational nor KB
access falls back to administrative credentials. Set the API key locally as
before. `.env.example` now includes `OPENAI_SYNTHESIS_MODEL`, defaulting to
`gpt-4.1-mini-2025-04-14`, independently of classification, recommendation and
planner models. Changing the model requires compatibility with the response
schema and request options; no other model has been validated here.

The following command makes paid requests and was **not** run in this milestone:

```powershell
uv run --locked --env-file .env --env-file .env.ops --env-file .env.kb python -m app.cli investigate live --request examples/investigation-request.json --synthesize
```

Omit `--synthesize` to preserve Phase 4B.1 behavior. Existing `investigate scripted`
commands remain entirely independent of live synthesis. Illustrative successful
trace with injected responses, not a recorded live-model result:

```text
validate -> classify -> retrieve
-> plan(lookup) -> guard(allowed) -> execute(lookup-1, ok)
-> plan(finish) -> synthesize(accepted) -> assemble(completed)
```

Inspect `recommendation` together with `kb_evidence`, `operational_evidence`,
`lookup_trace`, `errors` and `synthesis_status`; never display report text alone
as a verified resolution. Operational and KB prose remain untrusted data in
separate JSON sections under fixed system instructions. Prompt-injection defense
is not perfect, but synthesis has no tool interface or ability to expand scope.

## Evaluation and validation

Run the offline, fixed-response evaluation:

```powershell
uv run --locked python -m evaluation.investigation_synthesis
```

The 11 cases cover a documented diagnostic, a triggered handoff, unrelated KB
evidence, conflicting snapshots, fabricated IDs, an observation-only action,
unsupported action/summary with real IDs, premature escalation, incorrect
abstention and provider failure. The fixture candidates are intentionally mixed
quality; they are not generated by a live model and are not a model accuracy score.
The same candidates run through real SDK parsing with mocked HTTP in tests.

| Offline response replay metric | Result |
| --- | --- |
| Accepted by structural/source checks | 8/11 |
| Rejected or failed | 3/11: invalid citation, invalid output, provider failure |
| Valid typed references among accepted reports | 30/30 |
| Cited items among accepted reports | 19/19 |
| Unsupported-case abstentions among accepted reports | 2/2 |
| Incorrect abstentions on accepted answerable cases | 1/6 |
| Escalation label matches among accepted reports | 7/8 |

Four accepted negative controls are labelled **incorrect** in the manual rubrics:
an action prohibited by its cited KB, an unsupported repair/live-state summary,
a handoff whose trigger never occurred, and an unnecessary abstention. Mechanical
metrics deliberately do not count any of those as groundedness successes. Failed
or rejected responses remain separate from accepted-case metric denominators.

For future approved live evaluation, review each claim against the complete cited
text, its applicability and prerequisites; verify escalation triggers and role
boundaries; check contradictory/negative facts, snapshot language and omitted
evidence. Review summary correctness independently of step citations. Record
manual findings separately from source membership and abstention/escalation counts.
Do not reinterpret these response replays as live model quality measurements.

Validation on the prepared PostgreSQL environment: **510 tests passed**, preserving
all 437 existing tests and adding 73. This includes **69 PostgreSQL integration
tests** and 441 offline tests. New coverage includes all citation locations,
structured-output failures/refusals, single-attempt API failures, malformed and
mutated provider models, abstention, partial results, deadlines/context caps,
optional CLI wiring, evaluation negative controls, and synthesis over actual
read-only pgvector and operational results with mocked OpenAI responses.

Before/after full-suite snapshots matched for **79 operational records** across
eight tables and **36 KB chunks**, including their vectors and metadata. Temporary
test reader roles remaining: **0**. Integration fixtures use a separate test
database; the application database was not seeded, migrated or modified. No paid
API requests were made. No changes were committed or pushed.

Remaining limitations include unmeasured live synthesis quality/latency,
prompt-level semantic grounding and injection resistance, synthetic snapshots,
manual applicability/conflict review, and the existing local developer identity
model rather than production authentication/authorization. No frontend, web API,
write-capable tools, persistence or future-phase infrastructure is introduced.

## Live-review correction: prompt v2

The user reported a successful first real run (three relevant lookups, four planner
decisions, one accepted synthesis), followed by five semantic errors. This review
uses that description and the application code/KB, not an independently inspected
raw live-response artifact. The examples below reconstruct those errors with
fictional fixtures; they are not verbatim captured model outputs.

| Reported error | Why a valid citation is insufficient | Required distinction |
| --- | --- | --- |
| Enabled account and MFA enrollment exclude or reduce the likelihood of credential problems | Configuration flags are not tests of the attempted login | Record the flags; authentication outcome and credential validity remain unestablished |
| Installed `5.2-demo` is supported | Inventory is not version-support policy; the VPN KB contains no version matrix | State the recorded version; support/compatibility requires explicit applicable KB policy |
| Tunnel establishment failed after successful authentication | Temporal symptom wording does not establish protocol stages; no tunnel diagnostics were gathered | Attribute the reported sequence and leave the failure stage unknown |
| Incident is ongoing now and explains this ticket | The active-incidents query selects recorded status, with `live_verified=false` | Include the source observation time and unverified current status in the claim itself; association is not causation |
| Conditional persistent-gateway-error handoff marked required | KB text supplies a condition, not evidence that the condition occurred for this user | Establish the trigger before recommending the handoff |

The prior prompt already prohibited invention and required source membership, but
did not make these distinctions explicit enough. Schema validation accepted the
responses because the IDs and step/flag/reason relationships were valid. It does
not interpret claims or establish their applicability. Phase 2B.1 had already
observed the same hypothetical-handoff problem, including a handoff hidden in a
troubleshooting step despite a false escalation flag.

The smallest change is prompt `investigation-synthesis-v2` plus descriptions on
the existing Pydantic fields. Output fields, requiredness, limits, validators,
provider/model, tools and graph are unchanged. No new claim classifier, keyword
filter, diagnostic authority or approval mechanism was introduced. In particular,
no deterministic rule attempts to interpret diagnosis or escalation prose from
account flags or a KB paragraph. Those semantics cannot be checked reliably from
the current free-text output contract.

The revised instructions require:

- Summary/findings distinguish ticket reports, timestamp-qualified snapshots and
  explicit documented policy. They omit speculative diagnoses. Any useful inference
  belongs only in uncertainties, labelled unverified with its basis and limitations;
  adding "likely" is not a substitute for evidence.
- Qualification accompanies each snapshot claim, including summaries. A generic
  disclaimer elsewhere cannot repair an unsupported current-state assertion.
  Query time is never substituted for observation time; missing source times are
  stated as unavailable. No version string or service-specific tool sequence is
  hardcoded in runtime behavior.
- Steps contain currently applicable actions. `escalation_required=true` still
  means an escalation-typed step and a cited nonnull reason. That reason should
  cite both the KB condition and the report/observation establishing the trigger.
  Code checks reference membership, not whether the trigger is semantically met.
- Unknown/unmet future triggers yield no escalation step and a false/null flag/reason
  unless another current handoff is independently justified. If useful, uncertainties
  may describe a documented future condition as unestablished; this is policy context,
  not an instruction to escalate. Missing trigger facts become clarification questions.
  A hypothetical handoff must not be disguised as troubleshooting or summary text.
- An established handoff remains valid even when submission details are missing.
  If no current action is supported, abstain with no steps and escalation undetermined.

This follows the earlier Phase 2B.1 distinction between a first failure and an
actually failed retry. That standalone pipeline, its prompts, schemas, evaluation
sets and frozen hashes are unchanged. Prompt versioning and explicit behavioral
instructions follow the [official OpenAI prompting guidance](https://developers.openai.com/api/docs/guides/prompt-engineering);
they do not establish a semantic guarantee.

### Focused offline evaluation

```powershell
uv run --locked python -m evaluation.investigation_synthesis --cases evaluation/investigation_synthesis_semantics.jsonl
```

The original 11-case replay set and default command are preserved. The new file
adds five pairs using identical evidence: an unsupported claim and a preferred
authored correction for each live-review error. Four additional cases cover
explicitly reported authentication success, explicit version-support policy,
an established escalation trigger with missing submission details, and abstention
when only a conditional handoff is documented and its trigger is unknown.

These are inspected development fixtures with manually authored review labels,
not a held-out set or results from rerunning the model. All 14 candidates pass
structural/source checks, including the five labelled incorrect negative controls.
Replay counts: **110/110 valid references**, **56/56 cited items**, **13/14 escalation
label matches**, **1/1 unsupported-case abstentions**, **0/13 incorrect abstentions
on answerable cases**, and **0 rejected/failed**. Perfect citation metrics coexist
with the five semantic failures by design. The evaluation does not use an LLM
judge or mistake an authored corrected response for measured prompt improvement.

Nineteen new offline tests run the candidates through actual SDK parsing over
mocked HTTP, check paired-evidence equality and existing escalation invariants,
and replay account/device/incident lookups followed by synthesis. The graph test
checks that typed evidence survives unchanged, with four planner decisions, three
lookups and one synthesis attempt, using the actual VPN Markdown chunks.

Full validation: **529 passed** (460 offline and 69 PostgreSQL integration tests),
preserving all previous 510 tests. Before/after snapshots matched for all **79
operational records** and **36 KB chunks including vectors/metadata**; temporary
test reader roles remaining: **0**. No application data was seeded or modified.
No paid requests, commits or pushes are part of this correction. A future approved
live comparison and human claim-by-claim review are needed to assess whether the
new instructions reduce these errors. Unsupported statements with valid IDs can
still pass; timestamps remain synthetic snapshots, not live verification.
