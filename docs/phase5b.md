# Phase 5B: controlled live paired evaluation

This increment adds an opt-in evaluator, not a change to the application. No
production prompt, schema, escalation rule, graph edge, provider or tool is
modified. No live API call was made during implementation. Mocked test results
measure integration and scoring behavior, not model quality.

## Pilot and comparison

The runner selects exactly these existing Phase 5A scenarios (or an explicit
subset), verifying the frozen manifest, corpus, seed and dataset hashes first:

| Scenario | Expected escalation now | Main question for review |
| --- | --- | --- |
| `vpn-confirmed` | Yes | The ticket reports persistent gateway errors after a retry. Is the applicable documented handoff supported? |
| `vpn-future-condition` | No | Does a single failure become a premature handoff or an invented failed retry? |
| `irrelevant-incident` | No | Does the agent prioritize email evidence and avoid attributing desktop sync failure to unrelated VPN incidents? |
| `unsupported-procedure` | No established procedure | Does it abstain from inventing cafeteria payment recovery instructions? False does not establish safety. |

Frozen Phase 5A responses, scripted decisions, lookup results, review notes and
expected labels are **never model inputs**. Only the original ticket and explicit
scope enter the graph. Phase 5A negative-control responses remain useful in
offline tests; their errors are not predictions of what a live model will do.

For each case, the runner calls the unchanged `run_investigation` with existing
OpenAI classification, embedding, planner and synthesis providers and the restricted
database readers. It then takes that result's validated KB results, in their exact
order with text, metadata and distances, and calls the existing standalone
`generate_recommendation` on the same `TicketInput`. This is the generation entry
point used by Phase 2B's `recommend`; retrieval is deliberately shared once.
The standalone provider sees only the ticket and the normal KB payload. Only the
agent gets scoped operational lookups and their observations. The graph also
retains its normal classification context. No additional routing logic is added.

This compares two existing **systems**, not a controlled ablation of one prompt:
the prompts, output contracts, available operational evidence and token budgets
differ. Models are independently configurable. All four pilot answerability labels
apply to the full KB; live retrieval can differ from Phase 5A's authored evidence
subsets. The output records reference-chunk overlap for inspection, not as a
new retrieval-quality score. A reviewer must assess the actual retrieved evidence.
An answerable-case abstention after a retrieval miss remains an end-to-end error;
it is not automatically a generation-grounding failure.

## Files and execution

| File | Responsibility |
| --- | --- |
| `evaluation/live_investigation.py` | Selection, preflight, production pipeline composition, paired scoring, output/checkpoints |
| `evaluation/live_telemetry.py` | HTTP request timing and safe usage accounting around unchanged SDK providers |
| `tests/investigation/test_live_evaluation.py` | Mocked production API responses, sharing, failures, opt-in and output checks |
| `tests/investigation/test_postgres.py` | Real restricted-reader audit and paired pgvector/tool integration checks |

No new dependencies are required. The runner is a separate evaluation module;
existing application CLI commands and deterministic Phase 5A replay are unchanged.

Run from the repository root in PowerShell. Local configuration is already covered
by `.gitignore`; do not put credentials on the command line. The SDK reads the local
key only when paid execution constructs a client. Dry-run does not check the key,
provider model access, quota or network connectivity.

No database or API access:

```powershell
uv run --locked --offline python -m evaluation.live_investigation --dry-run
```

Read-only database preflight, still **zero API calls**:

```powershell
uv run --locked --offline --env-file .env.ops --env-file .env.kb python -m evaluation.live_investigation --dry-run --check-db
```

Preflight requires explicit `OPS_DATABASE_URL` and `KB_READER_DATABASE_URL`.
There is no administrative fallback, initialization, seeding, role provisioning
or index replacement. It exercises existing privilege checks, validates the index
embedding configuration, and compares every operational record and KB chunk's
content/metadata to the frozen seed/corpus. Vectors and all stored columns are
included in before/after SHA-256 fingerprints. A partial or different corpus
fails preflight. It does not prove semantic correctness of existing embeddings.

**Only after explicit approval for the later paid pilot**, run all four cases:

```powershell
uv run --locked --offline --env-file .env --env-file .env.ops --env-file .env.kb python -m evaluation.live_investigation --allow-paid --output-dir reports/phase5b/pilot-001
```

For an approved one-case pilot instead:

```powershell
uv run --locked --offline --env-file .env --env-file .env.ops --env-file .env.kb python -m evaluation.live_investigation --allow-paid --scenario vpn-future-condition --output-dir reports/phase5b/future-001
```

`uv --offline` disables package downloading; it does **not** disable the model API.
The evaluator's default/dry-run mode is what prevents model calls. `--allow-paid`
and `--dry-run` are mutually exclusive. Scenario flags can be repeated for distinct
pilot cases; duplicates and non-pilot IDs are rejected before external access.
Paid execution always includes database preflight. Output must be a new directory
strictly inside ignored `reports/`; existing reports are never overwritten by a
new run. A later repeat must use a new directory name. API requests use the official
OpenAI endpoint; custom `OPENAI_BASE_URL` endpoints are not used by this pilot.

Models use existing environment variables:

| Role | Variable | Default |
| --- | --- | --- |
| Classification | `OPENAI_MODEL` | `gpt-4.1-mini-2025-04-14` |
| Query embedding | `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small`, 1536 dimensions |
| Planner | `OPENAI_PLANNER_MODEL` | `gpt-4.1-mini-2025-04-14` |
| Agent synthesis | `OPENAI_SYNTHESIS_MODEL` | `gpt-4.1-mini-2025-04-14` |
| Standalone recommendation | `OPENAI_RECOMMENDATION_MODEL` | `gpt-4.1-mini-2025-04-14` |

The existing cap is four planner decisions/four lookup attempts and a 120-second
cooperative graph deadline. Each SDK request has a 30-second timeout and **zero
retries**. Each case makes at most eight API requests: one classification, one
embedding, four planner calls, one synthesis, one standalone generation. Four cases
therefore allow at most 32 requests. This is a request-count bound, not a dollar cap
or a hard wall-clock interrupt. Existing response token caps and temperature
settings remain unchanged. Classification omits temperature; the other generation
providers use zero. Input tokens, provider availability and model pricing vary.

## Artifacts, scoring and review

### Proxy routing and unauthenticated connectivity

The failed `future-001` and `future-002` pilots recorded transport failures with
no HTTP status or token usage. Review found that the explicit custom transport
disabled HTTPX's automatic environment-proxy mounting. The evaluator now resolves
`HTTPS_PROXY`, falling back to `ALL_PROXY`, and supplies the selected proxy to the
inner HTTP transport **inside** the telemetry wrapper. Lowercase equivalents and
hostname/domain/`*` exclusions in `NO_PROXY` are supported through Python's standard
environment proxy helpers. Without an applicable proxy it connects directly;
`HTTP_PROXY` alone does not route this fixed HTTPS destination. Environment-only
settings are used, not Windows registry proxy configuration. HTTP(S) proxies such
as Clash's HTTP listener require no extra dependencies; SOCKS requires HTTPX's
optional SOCKS support, which this project does not add.

HTTPX transport and SDK retries remain zero. The API endpoint and certificate
verification remain unchanged. Proxy URLs, credentials and raw exception messages
are never included in diagnostics. A failed proxy connection does not fall back
to a direct connection. Dry-run and database preflight remain free of model API
requests and do not perform this separate connectivity check.

To check connectivity without an API key or paid request, use the same transport:

```powershell
$env:HTTPS_PROXY = 'http://127.0.0.1:7897'
uv run --locked --offline python -m evaluation.live_telemetry --check-connectivity
```

Use the proxy configured in your own shell; the assignment above is the local
Clash example. No `.env` file is needed. This sends exactly one unauthenticated
`GET https://api.openai.com/v1/models`, with a 10-second timeout and no redirects,
SDK client, authorization header, ticket or model input. It reports only safe
status/timing fields. HTTP 401 is the expected result and exit code 0; other
statuses or connection failures return 1. A 401 establishes reachability through
this transport, not API-key validity, model access, quota or paid-pilot quality.
See HTTPX's [transport documentation](https://www.python-httpx.org/advanced/transports/)
and [environment configuration](https://www.python-httpx.org/environment_variables/).

### Output and scoring

Each new output directory contains:

- `paired.json`: full ticket/scope, shared retrieved KB text/metadata/distances and
  hash, production investigation output (including timestamped observations,
  lookups, errors and graph trace), accepted recommendations, planner proposals,
  per-pair timing, source/lock/manifest fingerprints and mechanical metrics.
- `manual-review.json`: pending claim-level worksheet for both arms, with the
  original field text/references and fields for atomic claims, source entailment,
  snapshot freshness, procedural applicability, escalation trigger, missing
  information and comparative usefulness. Read alongside `paired.json`.

Request telemetry records scenario/arm/stage, requested and returned model,
actual request settings, HTTP status, latency and token counts (including cached
or reasoning tokens where returned). It never records authorization headers,
credentials, full HTTP bodies or raw exception messages. Missing usage is unknown,
not zero; totals report both known tokens and requests with missing counts.
`cost_usd` is null because these API responses do not report billed cost; no
unverified pricing estimate is supplied. Check billing separately for an approved
pilot. The embedding is counted once under the agent request sequence and is a
shared cost. Agent latency includes shared retrieval; standalone latency is
generation-only, so the two elapsed totals are not directly comparable.

Planner records contain schema-valid proposals, including finish/clarify. Lookup
arguments must also pass the existing scope/argument guard before being recorded;
blocked proposals redact their arguments. These are proposals, not proof of
execution: `lookup_trace` is authoritative about guard outcomes and actual calls.
No operational identifier expansion, new tools or relaxed budgets are introduced.

The runner reuses Phase 5A planner coverage/redundancy/unnecessary-lookup scoring,
paired summaries and Phase 2 recommendation aggregates. Agent reports are
projected into the Phase 2 shape **for mechanical step/KB citation metrics only**;
the full typed investigation report remains available. Existing production
validation checks references throughout the agent report. Neither ID validation
nor citation coverage establishes source entailment or summary correctness.

Metric denominators remain explicit:

- Citation validity is valid step-KB references / step-KB references; coverage is
  steps with a valid KB reference / steps. Zero denominators are null. Malformed
  or rejected outputs have no accepted candidate and do not inflate coverage.
- Escalation precision/recall and confusion counts use accepted reports. Recall
  over **all positive attempts** also includes failed/rejected attempts in the
  denominator. Premature escalation IDs use the frozen unconfirmed-trigger label.
- Unsupported abstention and incorrect abstention use all recorded unsupported
  and answerable cases respectively. Failures are not successful abstentions.
- Coverage uses successfully gathered expected tool evidence; redundant and
  unnecessary calls use the existing scenario labels. They are not exhaustive
  judgments of arbitrary tool relevance.
- Selected but unrecorded scenarios are listed separately after interruption;
  they are excluded from recorded-pair metric denominators. Request usage can
  include an interrupted pair without a completed row.

Failed/skipped shared retrieval prevents a standalone API request and marks both
scoring rows failed. The graph's safe fallback report and all gathered operational
evidence remain intact in `agent_result`. A genuinely successful empty search may
produce accepted deterministic abstentions with no generation calls. Clarification
retains the graph's deterministic agent abstention while standalone generation
still receives the common KB. Synthesis/standalone failures retain evidence and
fixed error codes, never a fabricated successful answer. A partial graph is
reported separately even if it has an accepted partial synthesis.

Reports are checkpointed after each completed pair and on normal interruption;
there is no resume or retry feature. Abrupt termination/disk failure can lose the
in-flight pair. Final read-only fingerprints detect persistent data changes; the
connections do not hold one transaction across the whole investigation, and cannot
detect a concurrent change that is later reverted. Mismatches or incomplete final
verification invalidate the run for quality comparisons. Exit code 0 means all
pairs completed with accepted outputs and verification passed, **not** that claims
are correct. Code 2 means partial execution/verification; code 1 means setup or
artifact failure.

Reviewers must split statements into atomic claims and independently check ticket
reports, recorded facts and inferred conclusions. Account enabled/MFA enrolled do
not establish authentication success; an installed version is not a support-policy
claim; incident snapshots are not verified current state or proof of causation.
For each escalation, identify the KB condition and the evidence establishing it
for this user now. Conditional future guidance must not be scored as justified
current escalation simply because a cited document mentions escalation. The current
production escalation contract remains unchanged during this milestone. Grounding,
freshness, applicability and hidden conditional handoffs remain pending manual
judgments, not keyword checks or claims of automated semantic verification.

## Verification and limitations

The test suite uses mocked HTTP responses, including valid citations on the
known premature-escalation negative control, and real PostgreSQL in a disposable
test database. It checks identical evidence, absence of operational/label leakage
to the standalone arm, zero API calls during dry-run, request accounting, failed
retrieval versus empty retrieval, guard/budget behavior, rejected outputs, failure
preservation, safe diagnostics, restricted credentials and unchanged data.

Verification on 2026-10-23: **601 passed**, including **74 PostgreSQL integration
tests** and **527 offline tests**. All 553 previous tests remain; this increment adds
43 offline and five integration tests. The complete-suite before/after application
snapshot check confirmed **79 operational records and 36 KB chunks/vectors unchanged**,
with zero temporary test reader roles remaining. The new `--dry-run --check-db`
also passed against the application database with zero API calls. Production
`app/` files and the frozen Phase 5A dataset, manifest and evaluator are unchanged.

Proxy correction verification: **617 tests passed**, including the existing 74
PostgreSQL integration tests and 16 new offline proxy tests. Application records
and KB vectors remained unchanged, with no temporary test roles left behind.
The actual metered connectivity check through the configured Clash HTTP proxy
returned the expected **401 in approximately 0.69 seconds** for one unauthenticated
request. No paid model calls were made and neither failed pilot was rerun.

There are no measured live-model scores in this increment. Four
development scenarios, one fixed execution order and one sample per case do not
support statistical comparisons. Provider outputs can vary even at temperature
zero. The evaluation datasets have already informed development and are not a
held-out benchmark. Mandatory human review is an indicator, not an authorization
workflow; all output remains advisory and all operational tools remain read-only.
