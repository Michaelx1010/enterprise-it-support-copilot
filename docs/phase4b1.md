# Phase 4B.1: live investigation planning

Phase 4B.1 connects an OpenAI planner to the existing Phase 4A graph. The model
chooses one of the six operational lookups, observes the validated result, then
chooses another lookup, `finish`, or `clarify`. The scripted planner remains
available. No recommendation or synthesis model is connected.

## Plan review and adjustments

The existing Phase 4B plan is recorded in [docs/phase4.md](phase4.md). Its fixed
graph, bounded decision loop, deterministic guard and separate later synthesis
step remain the architecture. There was no separate Phase 4B implementation plan
file in the repository. The changes needed for this milestone were:

- Move the existing `Planner` protocol and `PlannerView` from `graph.py` into
  `app/investigation/planner.py`. Existing imports through `graph.py` still work.
- Extend the planner view with validated lookup history, component errors and
  remaining decision/lookup counts. It remains a deep copy of application state.
- Add a closed, typed model-output envelope because the scripted decision's
  unrestricted argument dictionary is unsuitable for strict Structured Outputs.
- Add an explicit live CLI entry point. It reuses the existing classification and
  embedding adapters with a shared client and zero retries, rather than requiring
  a developer to supply a classification and query vector for every live ticket.
- Tag live CLI results `phase=4B.1`; scripted results retain `phase=4A`.

There are no new dependencies. The classifier, embedding implementation, KB SQL,
operational tools, scope policy, recommendation prompts and evaluation behavior
are unchanged. No schema migration or new database provisioning is required beyond
the restricted readers already described in Phase 4A.

## Implementation

```text
existing graph plan node
  -> Planner.decide(view, index)
  -> OpenAIPlanner: fresh evidence snapshot + strict response schema
  -> validate PlannerResponse and convert to the existing Decision format
  -> existing graph decision validation
  -> existing allowlist / arguments / scope / deduplication / budget guard
  -> existing read-only tool and result validation
  -> next plan node with the new observation
```

| File | Responsibility |
| --- | --- |
| `app/investigation/planner.py` | Provider-independent protocol/view, typed decision envelope, fixed instructions and payload construction |
| `app/providers/openai_planner.py` | OpenAI SDK calls, independent model configuration and sanitized response errors |
| `app/investigation/graph.py` | Supplies history and remaining budgets; keeps the same nodes, edges, execution guard and completion rules |
| `app/investigation/cli.py` | Explicit `live` entry point; existing scripted/provisioning commands remain |
| `examples/investigation-request.json` | Fictional ticket and explicit structured scope for local use |
| `tests/investigation/test_openai_planner.py` | Real SDK parsing over mocked HTTP, schema, failure and multi-step guard tests |
| `tests/investigation/test_live_investigation_cli.py` | Live-command wiring with mocked API and database boundaries |

The adapter implements the existing one-method planner protocol directly. There
is no second agent framework, rule-based substitute planner, general tool executor,
or automatic repair loop. The SDK is confined to the provider module. A future
provider can implement the same protocol without changing tool dispatch.

The model returns one object, for example:

```json
{
  "decision": {
    "kind": "lookup",
    "tool": "get_employee_devices",
    "arguments": {"employee_id": "EMP-001"}
  }
}
```

The response schema has eight alternatives: one typed variant per tool, plus
`finish` and `clarify`. It reuses existing input models; ticket/incident list
variants require explicit limits of 1–5, and ticket lookups require a nullable
`since` field. Unknown tools, extra arguments, malformed IDs, invalid list limits,
unrecognized clarification fields and recommendation text are rejected.

The schema uses an object root with a nested `anyOf`, all properties required and
closed objects. This follows the official [Structured Outputs schema requirements](https://developers.openai.com/api/docs/guides/structured-outputs).
The adapter uses `client.responses.parse(text_format=PlannerResponse)`. It does
not send an API `tools` declaration: the model proposes a structured decision and
the application controls execution. No rationale or hidden reasoning transcript
is requested or stored.

## Prompt, context and safety

The fixed system instructions describe the six lookups, scope rules, missing/stale
data, duplicate avoidance, finishing, clarification and the remaining budgets.
The user message is a JSON snapshot containing:

- `control`: explicit employee/software/service scope, eligible device IDs,
  decision index, remaining decisions/lookups, validated lookup history and fixed
  component error codes.
- `untrusted_evidence`: ticket, classification, retrieved KB procedures and
  operational observations, kept in distinct fields with their source metadata.

Each call receives the latest snapshot. There is no server-side conversation ID
or previous-response chain. The prompt version is `investigation-planner-v1`.
Operational timestamps and `live_verified=false` remain visible. The model is
instructed to treat all record prose, KB text and ticket content as data, and not
to interpret historical resolutions as policy or old records as current facts.

Instructions do not enforce authorization. The unchanged deterministic gate
still permits only the request's employee; software/service IDs must be explicit;
device IDs must come from that employee's successful device-list lookup. An
otherwise valid model decision for another employee is blocked without execution.
Names, managers, owners, approvers, ticket relationships and injected prose cannot
extend scope. The response schema cannot authorize a tool call.

The unchanged limits are four planner decisions, four lookup attempts, 24,000
serialized operational-context characters, a 120-second between-node deadline,
and a graph recursion backstop of 32. `remaining_decisions` includes the current
decision. The model is instructed to finish or clarify on its final decision; if
it instead spends that decision on a lookup, the graph still enforces exhaustion
and returns a partial result. The prompt does not replace any budget check.

Each planner request has a 30-second SDK timeout, 700 output-token cap,
`temperature=0`, `store=False` and **zero retries**, including when a caller injects
a client configured with retries. These settings bound attempts, not total cost or
guaranteed wall-clock duration. The 120-second deadline does not forcibly cancel
an in-flight request. External LangSmith tracing remains disabled by the graph.

Incomplete responses, refusals, missing/invalid structured output, multiple output
decisions, unexpected API tool calls, API errors and timeouts fail without repair.
The provider uses fixed diagnostic codes; the graph preserves the Phase 4A
`planner_failed` error and stop semantics. Earlier validated evidence and lookup
traces remain available. No exception body, rejected model text or credential is
included in the result. Valid out-of-scope proposals reach the guard and retain
its existing specific rejection code.

`completed`, `partial` and `failed` retain their Phase 4A meanings. `clarify` returns
the existing structured `missing_fields` labels and ends the run. It does not
pause or persist execution. Every result still has `human_review_required=true`,
`mutating_actions_executed=false`, `synthesis_status=not_run` and
`recommendation=null`. Human review is an indicator, not implemented authorization.

## CLI and configuration

The scripted command remains offline:

```powershell
uv run --locked python -m app.cli investigate scripted --script examples/investigation-scripted.json
```

For live use, first complete the Phase 4A restricted-reader setup. Configure
`OPENAI_API_KEY` locally and, optionally, `OPENAI_PLANNER_MODEL`; the planner
defaults to the project's existing `gpt-4.1-mini-2025-04-14` snapshot. Its setting
is independent of `OPENAI_MODEL` and `OPENAI_RECOMMENDATION_MODEL`.
`OPENAI_EMBEDDING_MODEL` must match the existing KB index. Availability of the
configured model for a particular account was not tested with a paid request.

The following command **makes paid API requests** when run with valid credentials:

```powershell
uv run --locked --env-file .env --env-file .env.ops --env-file .env.kb python -m app.cli investigate live --request examples/investigation-request.json
```

`.env` supplies the API configuration; `.env.ops` and `.env.kb` supply the separate
restricted readers. The command does not use `DATABASE_URL` as a fallback. Missing
reader settings or invalid input are rejected before provider construction. File
and ticket-size limits apply. Reader permissions are audited on actual database
access, so later connection/grant failures follow the existing partial-result
rules. No admin setup runs automatically from the live command.

The live command invokes classification once, retrieves once using the existing
embedding adapter, and permits up to four planner calls: at most six model/API
attempts with the zero-retry shared client. The existing standalone classification
and recommendation commands keep their own prior retry settings. The live command
closes its client on normal completion and failure.

The CLI labels the planner, classifier and query embedding as `openai`, the backend
as `postgres`, and records the configured planner model. Exit codes remain 0 for
completed, 2 for partial, and 1 for failed/setup errors. Redirect reports only to
an ignored local path such as `reports/`.

Live use sends the ticket, classification, retrieved KB text/metadata, and the
validated operational observations needed for the next planner decision to OpenAI.
This project uses fictional records; the payload is not a general PII scrubber for
production data. `store=False` is not a claim of zero provider retention. Local
reader credentials and the API key are not prompt fields. The graph's local scope
gate is not authenticated end-user authorization or a database row-security policy.

## Verification and limitations

The complete suite passed with **391 tests** in **35.51 seconds**: all **327
existing tests** plus **64 new tests**. This comprises **324 offline tests and 67
PostgreSQL integration tests**. No tests were skipped. All API responses were
mocked; no paid model calls were made and no local API key was read or printed.
An automatic test fixture rejects unmocked HTTP transport in investigation tests.

New checks cover all eight decision variants, the SDK-generated strict schema,
tool/input rejection, finish/clarify, latest observations in successive model
requests, remaining budgets, context limits, canonical duplicates, injected
historical text, deterministic scope, refusals, malformed/ambiguous output,
timeouts, rate limits, zero retries, independent model configuration, safe error
messages and live CLI client cleanup.

Three new PostgreSQL tests drive all six original operational functions through
mocked model responses and real restricted readers, alongside real pgvector
retrieval using deterministic test vectors. Full-suite before/after snapshots
confirmed all **79 application operational records and 36 KB chunks**, including
metadata and vectors, were unchanged. No temporary test reader roles remained.

```powershell
uv run --locked --extra dev python -m pytest -m "not integration" --tb=short
uv run --locked --env-file .env.db --extra dev python -m pytest --tb=short
```

These tests verify contracts, orchestration and enforcement. They do not verify
live model relevance, latency, account access, server-side schema acceptance or
decision quality. The mocked multi-step scenario demonstrates that a later API
request receives earlier tool results; it is not a live-model evaluation. A paid
smoke test/evaluation requires separate user approval and was not performed here.

No synthesis, final support recommendation, autonomous escalation, writes,
persistence, approval workflow, web API or frontend was added. Phase 4B.2 remains
separate work requiring review of this milestone first.
