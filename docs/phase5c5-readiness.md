# Phase 5C.5: controlled development pilot readiness

Prepared 2026-10-31. **No paid requests, connectivity probes, live smoke tests,
commits or pushes were made. Execution requires separate, explicit approval.**
This document and `evaluation/phase5c5_protocol.json` predeclare the comparison.
The evaluation-only controller is `evaluation/phase5c_pilot.py`.

**Historical preparation record:** the statements and commands below describe
the frozen V6/V3 candidate at preparation time. The combined finalization also
includes synthesis V7/Draft V4, so its checkout intentionally fails this archived
controller's preflight. Protocol/controller hashes and original pilot artifacts
remain unchanged. These commands are not instructions to repeat a pilot or to
bypass the freeze; any new live evaluation requires separate review and approval.

## Frozen candidate and provenance

| Item | Frozen value |
| --- | --- |
| Application Git commit | `495b24a8f1410f2a88e402474721b16121b134be` |
| Branch at preparation | `main`, matching local `origin/main` |
| Application SHA-256 | `de2b3168f137f237e280d024d230364291e5ceaf0d5ba49575310ddf87523bb5` |
| Lockfile SHA-256 | `6ca15d767cc9a9697c01ed60262a841e661e30e47f12a9ecf0d61fb0d113bb94` |
| Protocol SHA-256 | `3c4347ddabc762c07e0efdc265e47a5c019465b8e6226e6a038e327129559575` |
| Controller SHA-256 | `5031f50d4ff1888a5bb6ac91731d6b3cc34720f21474d3062c3a3f5704da45d5` |
| Planner | `investigation-planner-v4`; `PlannerResponseV2`, literal `investigation-planner-response-v2` |
| Synthesis | `investigation-synthesis-v6`; `InvestigationSynthesisDraftV3`, literal `investigation-synthesis-draft-v3` |
| Standalone | `grounded-recommendation-v4`; canonical `SupportRecommendation` |
| Manual worksheet | `investigation-manual-review-v2`; all semantic grades remain pending |

Application hashing reuses `source_metadata()`: sorted `app/**/*.py` relative
POSIX paths followed by their UTF-8 text with normalized LF line endings. The
controller also rejects Git differences in `app`, `knowledge_base`, `uv.lock`
and `pyproject.toml`, and verifies frozen input and preparation-source hashes.
The candidate application is committed; **the evaluation preparation increment
is uncommitted** and has separate hashes. A changed HEAD or source/configuration
fails preflight; updating this freeze requires review, not an automatic refresh.

Prompt hashes, computed on the exact instruction strings:

| Prompt | SHA-256 |
| --- | --- |
| Planner v4 | `e8493fefa6e5cf1dd47386dfe52e74404e0a7286e0cdee2e7b32679791fe34aa` |
| Synthesis v6 | `28dfa57eb493444f75a2b33e6c99180d66dbfce1d8d29701cbe72801d60697f7` |
| Standalone v4 | `8fbaf1fb619b7075dfa872cf675e5c5446ac63e0f979d7a43edfec595da38275` |

The protocol also records planner/synthesis JSON Schema hashes, individual
evaluation source hashes and package versions: Python 3.12.7, OpenAI 2.54.0,
HTTPX 0.28.1, Pydantic 2.13.5, LangGraph 1.2.16, psycopg 3.3.6, pgvector 0.5.1.
These installed versions and the selected model environment values were checked
without displaying or inspecting the API key. No dependencies or settings changed.

### Models and generation

All generation roles use **`gpt-4.1-mini-2025-04-14`**, matching every saved Phase
5B pilot. Embeddings use **`text-embedding-3-small`, 1536 dimensions**.

| Role | Maximum output tokens | Temperature | Other settings |
| --- | ---: | --- | --- |
| Classification | 500 | Omitted, unchanged | `store=false` |
| Each planner decision | 700 | 0 | `store=false` |
| Agent synthesis | 3,000 | 0 | `store=false` |
| Standalone recommendation | 2,500 | 0 | `store=false` |
| Query embedding | No generation | Not applicable | `encoding_format=float` |

All evaluation SDK calls use a 30-second timeout and zero retries through the
fixed `https://api.openai.com/v1` endpoint. Transport retries are also zero.
Although standalone provider factory defaults elsewhere allow retries, the paired
runner injects its shared **zero-retry** client. No provider factory is substituted.
The existing environment-proxy routing is reused, without recording proxy URLs.

Standalone prompts, generation settings, payload construction, evidence validation
and accepted/rejected behavior remain unchanged. Relative to the original Phase
5B commit `a2747747d5df9c03700a79d14d523c8fd65ac400`, Phase 5C.1 already changed
three standalone invariant **error identifiers** to application-owned codes.
That diagnostic-only historical difference is retained; the existing schema parity
and contract tests establish compatibility. It is not a new baseline prompt or
acceptance-policy change in this preparation checkpoint.

### Retrieval, operational data and budgets

The retrieval query remains `Subject: {subject}\n\nDescription: {description}`.
There is one query embedding per pair, cosine search with top-k 3, no distance
threshold, no reranking, and the existing chunker/index configuration. The
protocol contains the chunker version, all 36 section IDs and index manifest.

| Fingerprint | SHA-256 |
| --- | --- |
| Frozen Phase 5A KB input | `15c5cad5f09acaef99789aeb79393dcef516051383c73d9972fa424b9bc16beb` |
| Operational seed | `6d6fd5398bfbed35dbb881a4a9b1aa984823839a6a85d01d578fdd5df4061918` |
| Phase 5A dataset | `ff6c5debedb882a563a260dbbfaaca97e509aafff5f3f0dceff6b8a7f23da447` |
| Index corpus hash | `9cf025aca9693e28583bc25a21b9db5b4a188817cfdcef1a7eb87a0ec6f2aa49` |
| KB database rows including vectors/metadata | `55e24635f534c778b2667143a58ec09f7ad62ac90f3cff15873de13fb6b0b8ea` |
| Prior full database verification snapshot | `8113e3a4af5a02090a5ef2cb4b33ef95e04ecc3a5efc44191f471366650941f4` |

The last two hashes use different existing serialization algorithms; they are
not expected to equal each other. The protocol includes individual operational
table hashes from the verified `future-004` preflight, including its source-file
checksum. There are **79 operational records** across eight tables and **36 KB
chunks/vectors** from twelve documents. The Phase 5C.4 before/after verification
establishes that those records remain unchanged. This preparation reuses that
evidence; it did not query or fingerprint the database again.

Per investigation, limits remain **four planner decisions, four lookup attempts,
120 seconds of cooperative elapsed-time checks, 24,000 operational characters**,
and the graph's recursion backstop of 32. The same six read-only tools, scope
validation, deduplication and restricted database credentials remain in effect.
The elapsed limit is not a hard cancellation of an in-flight request.

## Eight predeclared attempts

Order is fixed before observing any new outputs. Two rounds interleave the four
scenarios; neither round depends on the previous quality result.

| Attempt directory | Scenario | Current escalation expectation | Expected operational coverage |
| --- | --- | --- | --- |
| `01-vpn-future-condition` | vpn-future-condition | No current trigger | Account EMP-001, devices EMP-001, incidents SVC-001 |
| `02-vpn-confirmed` | vpn-confirmed | Current documented handoff | Same three lookups |
| `03-irrelevant-incident` | irrelevant-incident | No current handoff | Incidents SVC-003 |
| `04-unsupported-procedure` | unsupported-procedure | Undetermined; no supported procedure | None required |
| `05-vpn-future-condition` | vpn-future-condition | No current trigger | Same three lookups |
| `06-vpn-confirmed` | vpn-confirmed | Current documented handoff | Same three lookups |
| `07-irrelevant-incident` | irrelevant-incident | No current handoff | Incidents SVC-003 |
| `08-unsupported-procedure` | unsupported-procedure | Undetermined; no supported procedure | None required |

The inputs/labels come from the unchanged, checksum-verified Phase 5A cases.
Expect **14 required evidence items** across the eight slots. Required incident
lookup arguments include `limit=5`, matching the frozen labels. Coverage remains
an evaluator expectation, never an instruction to force a tool sequence.

Within every pair, both arms get the exact same subject and description. The
standalone entry point receives a deep copy of the graph's validated KB results,
with identical order, content and metadata. Only the agent gets classification
context and read-only operational observations. Model input builders never receive
labels, expected outputs, reviewer notes, this protocol or the budget ledger.
Separate attempts retrieve independently; across-attempt KB identity is not
assumed. Each pair retains its shared evidence hash and retrieval status.

This is a comparison of two systems with different prompts, contracts, evidence
access and output budgets, not an isolated ablation. Review standalone against
the evidence it actually receives; do not penalize it for unavailable operational
observations. A common retrieval miss is an end-to-end limitation and is reported
separately from generation quality.

## Metrics, denominators and gates

Never collapse the following into one success score. Every scheduled slot remains
in `pilot.json`; started-but-unrecorded and not-started slots are explicit. Every
recorded pair retains both accepted and rejected/failed arm outcomes. No best-of,
repair, replacement attempt, automatic retry, or automatic resume is permitted.

| Measure | Denominator / interpretation |
| --- | --- |
| API transport and HTTP status | Actual dispatched metered requests, split by stage and arm. Transport exception, non-2xx, and HTTP 200 are distinct. A blocked admission is not an API request. |
| Planner | Decision count, executed/failed/blocked/duplicate lookups, expected-evidence coverage, authored redundant/unnecessary lookup IDs. Report per case and covered/14 across the declared matrix; zero-required cases have N/A coverage. |
| Synthesis acceptance | Accepted model-driven synthesis / actual synthesis attempts, plus six declared supported slots. Distinguish SDK parse, application contract/citation rejection, refusal/incomplete, provider failure and not invoked. |
| Delivery | Accepted canonical output per arm / all eight planned slots, with accepted supported answers and deterministic abstentions separate. Missing/rejected outputs fail delivery; they are not abstentions. |
| Current escalation | Confusion matrix on accepted, assessable outputs only; rejected/unavailable outputs are **unassessable**, never true negatives. Report assessable count, all-attempt label matches and confirmed-handoff delivery/2 separately. Precision = TP/(TP+FP), recall = TP/(TP+FN); undefined denominators remain null. |
| Premature escalation | Current handoff on future-condition cases / two planned slots; also report accepted future-case count. Failed outputs cannot satisfy the no-premature-handoff gate. |
| Citations | Existing current-step valid-ID count/citation count and covered steps/current steps. Zero steps yields null, not 100%. Other V3 citations pass canonical validation but still require entailment review. |
| Future guidance / trigger basis | Record typed presence and structural acceptance separately from human judgment. Guidance never contributes to current escalation metrics; basis membership alone does not establish its trigger. |
| Documentation gap | Correct documentation terminal and no-action abstention / two unsupported slots; separately count clarify, irrelevant-ID demands, missing outputs and invented procedures. False escalation on abstention remains undetermined, not a safety finding. |
| Manual quality | V2 worksheet, atomic claims and explicit pass/fail/not-applicable/pending per applicable dimension. Report number reviewed, pending and unavailable; no automatic semantic grade. |
| Resources | Actual request counts, known input/output/embedding/cache tokens, unknown-usage count, stage and pair latency, known-usage cost estimate and conservative reservations. Actual billed cost remains unavailable. |

The controller reuses existing `summarize()` metrics over recorded rows, using
distinct derived attempt IDs without rewriting the per-pair originals. Its field
name `mechanical_metrics_recorded_pairs_only` makes that denominator explicit.
For the declared gates, unrecorded slots must also be reported against eight;
do not use the recorded-only subset to claim all-attempt delivery or coverage.
Existing aggregate `recall_over_all_positive_attempts` is a delivery-inclusive
measure; it must not be confused with recall among assessable recommendations.

Predeclared review gates, applied independently to both systems where applicable:

- All six supported agent synthesis slots deliver accepted, supported reports.
  An abstention or model request not reached fails this delivery gate.
- Both unsupported agent slots use the documentation-gap terminal, deterministic
  insufficient-evidence/no-current-action output, no irrelevant clarification,
  and zero synthesis calls. Both standalone slots must safely abstain.
- Both confirmed slots in each arm justify a current handoff; both future slots
  deliver accepted recommendations without a premature handoff. Irrelevant
  incidents must not establish causality or escalation.
- Agent expected operational coverage reaches 14/14, with zero authored redundant
  or unnecessary lookups. Any deviation is reviewed and disclosed, not relabelled.
- All delivered citation IDs are valid and current steps covered. No safety,
  scope or write regression; all outputs remain advisory with human review required.
- Human review finds no unsupported diagnosis/authentication/version/live-state
  claims; exact KB branches and prerequisites apply; no unjustified repetition of
  completed actions; current trigger evidence is entailed; attribution and source
  timestamps are explicit; missing information is useful; summaries are complete.

The worksheet preserves `entailment`, `attribution`, `snapshot_freshness`,
`applicability`, `completed_vs_proposed`, `trigger_established`,
`practical_usefulness`, and `summary_completeness` as pending. Failed outputs have
no invented claim rows. Keep the generated worksheet immutable and record human
annotations in a separate local review copy linked to its checksum.

### Historical comparison

Use the tracked `evaluation/phase5b_baseline.py` procedure and its checksum
manifest for the existing baseline. Do not regenerate or replace archived
`reports/phase5c/baseline-001` evidence. That verification was already passed and
was not repeated here.

Preserve **seven saved Phase 5B pairs**: two transport-failure attempts plus five
post-connectivity pairs. The four post-connectivity supported synthesis attempts
include all three rejections: acceptance is **1/4**, not 1/1. The fifth
post-connectivity pair is unsupported; standalone accepted all five. Across all
seven pairs there are 42 recorded API attempts, including six without known usage;
the post-connectivity subset has 36 HTTP 200 requests and 105,647 known tokens.
Those cohort denominators remain unchanged. The new eight-slot pilot is a
development pilot over inspected cases, not a held-out benchmark or evidence of
a statistically established reliability improvement.

## Request, token and cost controls

Verified from the actual graph/providers and paired entry point:

`1 classification + 1 embedding + up to 4 planner + up to 1 synthesis + up to 1 standalone = 8 requests/pair`.

Thus eight pairs permit **at most 64 requests** (56 generation + eight embedding).
Deterministic terminals and failures can reduce that number. The sum of configured
maximum generated tokens is at most `8 * (500 + 4*700 + 3000 + 2500) = 70,400`.
Inputs, especially repeated planner context, are not bounded by output-token caps.

Official standard pricing checked 2026-10-31:
[GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini)
costs $0.40/M input tokens, $0.10/M cached input, and $1.60/M output;
[text-embedding-3-small](https://developers.openai.com/api/docs/models/text-embedding-3-small)
costs $0.02/M input tokens. No cache savings are assumed for admission or estimates.
No hosted tool charges apply: the tools are local read-only functions.

The five post-connectivity baseline pairs used 99,643 generation input tokens,
5,856 output tokens and 148 embedding tokens; uncached pricing estimates
**$0.04922976**, not an observed bill. Averaging both historical future-condition
attempts (including both rejected syntheses), then scaling each scenario to two
attempts gives approximately **161,875 tokens / $0.07492** under the old contracts.
For the larger v6/V3 candidate, plan for **180,000-300,000 total tokens and roughly
$0.10-$0.20**. This range is an estimate, not measured candidate usage or a quality
prediction. Planner paths, schemas, guidance length, caching and failures vary.

Proposed aggregate admission limits: **64 requests, 400,000 accounted tokens,
$0.50 accounted USD**. These are fixed in the preparation protocol and controller.

- Before dispatch, reserve the entire serialized request byte count plus 4,096
  tokens of overhead, and the unchanged provider output cap. This overcounts
  normal text/schema tokenization; it does not truncate or modify model inputs.
- Persist a safe reservation before sending. Admit only if request count,
  accounted tokens plus reservation, and estimated USD plus reservation fit.
- After a response with complete consistent usage, replace the reservation with
  reported counts priced at uncached rates. Invalid structured content is still
  paid usage and is never refunded simply because validation failed.
- Missing/invalid usage or a transport failure retains the full reservation and
  stops all subsequent network dispatch. If usage exceeds its reservation, retain
  the larger accounting and stop; do not continue on an invalid estimate.
- At a limit, block before HTTP. Normal production error handling returns a partial
  or failed result with existing evidence intact. Finish local artifact handling,
  mark untouched slots not-started, and do not start another pair. Do not retry or
  resume without new approval. Interruptions and integrity failures also stop.

**These are hard local admission ceilings on accounting, not a guaranteed ceiling
on the provider's final invoice or exact remote tokens.** Serialized bytes plus
overhead is a conservative estimate, not a provider-certified token bound. An
already-dispatched request cannot be revoked; unknown usage can still be billed.
Prices, taxes and other account traffic are outside this controller. Cost from
reported usage is labelled estimated; `cost_usd` in original telemetry remains
null. If approval requires an absolute billed-dollar guarantee, this controller
alone is insufficient and live execution must remain blocked pending a suitable
account-side arrangement. It must not silently claim such a guarantee.

## Minimal runner changes and verification

No files under `app/`, prompts, schemas, graph, tools, model settings, frozen
fixtures or original reports changed. The preparation adds:

- `evaluation/phase5c5_protocol.json`: configuration/provenance/matrix, no secrets.
- `evaluation/phase5c_pilot.py`: strict freeze/preflight, one aggregate admission
  ledger, eight attempt directories, and existing metric aggregation.
- One optional `meter` injection in `evaluation/live_investigation.run_paid`.
  Its default transport, production composition, inputs, errors, worksheets and
  existing CLI behavior stay unchanged.
- `tests/investigation/test_pilot_readiness.py` and two focused tests in
  `test_live_evaluation.py`.
- This report and the cross-reference in `docs/phase5c.md`.

The original **1,004 passing tests**, including **82 PostgreSQL integration tests
and 21 schema parity checks**, remain valid evidence for the unchanged application.
No full-suite rerun, database query/fingerprinting, baseline reconsolidation or
live API request was needed. The environment/lockfile stayed unchanged.

**122 distinct targeted tests passed**, all using mock HTTP/no application DB:

1. Controller plus existing live evaluator: **82 passed**.
2. After adding derived collection metrics, controller plus existing proxy and
   synthesis diagnostic tests: **70 passed** (31 controller tests overlap).
3. After adding the final source/environment freeze checks, only the affected
   controller tests were rerun: **31 passed**.
4. Final review distinguished interrupted artifacts with no recorded pair from
   completed pair records, and added the denominator regression: **32 controller
   tests passed**. The other targeted results remain applicable.

The 34 new tests cover request/token/cost admission, missing usage, conservative
reservations, redaction, configuration changes, output paths, default dry-run,
mocked DB preflight, paired failures and preserved graph evidence. The dry-run
command also succeeded directly, recording zero API calls and no database access.
Re-running all PostgreSQL tests would not validate this HTTP admission controller;
the existing reader/query behavior and integrity evidence are reused.

## Data, privacy and execution

Every new output directory must be fresh and strictly inside
`reports/phase5c/live/`; path traversal, redirected output roots and existing paths
reject before clients or DB readers are constructed. The controller never writes
under Phase 5A inputs, `reports/phase5b/` or archived Phase 5C baseline directories.
Within the new run only, atomic checkpoints update `pilot.json`; each attempt has
its own unchanged paired report and pending V2 worksheet, with checksums recorded.
Root collection completion means only that all attempts were recorded, not that
recommendations were accepted or semantically correct.

The `.env*` files, credentials, caches and entire `reports/` tree remain ignored.
Only fictional evaluation inputs may be used. Model payloads are not added to
logs; the new ledger contains counts, fixed stages and safe attempt IDs only.
Existing reviewable reports intentionally contain fictional ticket/evidence and
accepted recommendations, and remain local/uncommitted. Headers, keys, proxy
credentials, rejected raw output, SDK response bodies and arbitrary exception
messages are not retained in the new diagnostics. `store=false` remains in use.

Paid execution performs the existing restricted-reader DB preflight and compares
its full table/vector fingerprints and index manifest against the frozen protocol.
Each existing paired-run finalizer verifies DB integrity again; a failure stops
the controller. No administrative fallback, seeding, schema setup or data writes
are permitted. This check occurs at execution, rather than being repeated now.
Hard process termination or a disk failure may prevent the in-memory graph result
from being flushed; already-persisted attempt slots and pre-dispatch reservations
must be retained as incomplete, not reconstructed or discarded.

Reproduce preparation from the repository root, with no API or DB calls:

```powershell
uv run --locked --offline python -m evaluation.phase5c_pilot --dry-run
```

Optional future read-only database preflight, still no model API calls:

```powershell
uv run --locked --offline --env-file .env.ops --env-file .env.kb python -m evaluation.phase5c_pilot --dry-run --check-db
```

**Proposed live command — do not execute until explicitly approved:**

```powershell
uv run --locked --offline --env-file .env --env-file .env.ops --env-file .env.kb python -m evaluation.phase5c_pilot --allow-paid --output-dir reports/phase5c/live/pilot-001
```

`uv --offline` prevents package downloads, not API requests. `--allow-paid` is the
explicit execution opt-in. Use existing local proxy configuration; do not change
repository proxy settings. No separate paid probe is part of this protocol.

Remaining risks: manual entailment/applicability cannot be certified by citations
or typed trigger references; no output has yet measured v6 quality; temporal
snapshots remain unverified; shared retrieval can miss a necessary procedure;
two attempts per scenario cannot establish general reliability; account access,
quota and network availability are untested in this checkpoint. The official
[deprecation notice](https://developers.openai.com/api/docs/deprecations)
currently schedules GPT-4.1 mini removal for January 14, 2027. Keep the frozen
model for this comparison; if unavailable, record the failure and seek review
rather than substituting a model or changing generation settings.
