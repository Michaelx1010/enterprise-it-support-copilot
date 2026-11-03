# Local functional demo

This single-user portfolio interface uses Streamlit to call the existing Python
investigation graph. It adds no API server, tool, schema, prompt, database migration
or persistence layer. Planner V2 / prompt v5 and synthesis Draft V4 / prompt v8
remain unchanged, as do standalone RAG and all CLI commands.

## Start from Windows CMD

Install Python 3.11+ and `uv`, clone the repository and open CMD in its root:

```cmd
uv run --locked --extra demo python -m streamlit run streamlit_app.py
```

The optional `demo` extra installs Streamlit (locked at 1.66.1). The server binds
to **127.0.0.1:8501**; open that address in a browser. Stop it with **Ctrl+C**.
The committed Streamlit configuration disables usage telemetry and detailed browser
exception displays. It does not contain credentials. Existing locked backend
package versions are retained.

## No-cost examples

Choose **Scripted examples**, select a scenario, then **Run investigation**:

- **VPN: first connection failure** shows three replayed lookups, current reconnect
  guidance and a separate conditional Network Support handoff.
- **VPN: persistent error after retry** shows a current handoff based on the
  ticket-reported trigger and documented policy, with typed supporting references.
- **Cafeteria: unsupported restoration request** shows a deterministic documentation
  gap without unrelated identifier requests or invented actions.

Examples need neither credentials nor a database. Ticket inputs are fixed in this
mode so an authored result cannot be mistaken for an investigation of edited text.
They run the real LangGraph workflow, guardrails and validators with scripted
classification, ranking, planning, operational lookups and synthesis. They are
**authored demonstrations, not recorded live-model successes or quality scores**.
Their run timestamps reflect local replay; source query/update timestamps remain
historical and unverified. Fixture distances are not measured semantic search.

`examples/demo-scenarios.json` contains the authored inputs/responses and fictional
lookup snapshots copied from the tracked Phase 5A `vpn-confirmed` fixture. KB text
loads from `knowledge_base/`. A fresh clone needs no ignored report, pilot output,
worksheet or archive. Frozen fixtures are neither modified nor loaded at runtime.

## Optional paid live workflow

Prepare the existing OpenAI configuration, ingested PostgreSQL/pgvector KB and
seeded fictional operational database first. Follow [Phase 2A](phase2a.md),
[Phase 3](phase3.md) and [Phase 4](phase4.md) for setup and restricted reader
provisioning. The demo never initializes, seeds or writes database data.

Use the same local, ignored configuration as the live CLI:

- `.env`: `OPENAI_API_KEY` and optional existing model settings.
- `.env.ops`: `OPS_DATABASE_URL`, using the restricted operational reader.
- `.env.kb`: `KB_READER_DATABASE_URL`, using the separate restricted KB reader.

There is no administrative `DATABASE_URL` fallback. No credentials are entered
through the browser or displayed. In CMD:

```cmd
set IT_SUPPORT_DEMO_LIVE=1
uv run --locked --extra demo --env-file .env --env-file .env.ops --env-file .env.kb python -m streamlit run streamlit_app.py
```

Select **Live investigation**, enter a fictional ticket and only relevant scoped
identifiers, check the paid-use confirmation, then click **Run investigation**.
Examples of formats are `EMP-001`, `SVC-001`, `SW-001`; service/software lists use
commas. Missing optional IDs do not automatically block a run. Never enter passwords,
API keys or real sensitive ticket data. Ticket/evidence content is sent to OpenAI.

The environment opt-in and per-submission confirmation are both checked by the
adapter. Loading the page, switching tabs, editing fields or rerendering does not
dispatch investigation requests. A result stays in that browser session until a new
submission or mode/scenario switch; there is no durable or multi-user storage.
Each submit is a new run, including after clarification; this is not graph resume.

The live adapter composes the same providers/readers as `investigate live
--synthesize`, then calls `run_investigation`. Model defaults, prompts, four planner
decisions, four lookup attempts, one synthesis attempt, timeout/size guards and
zero-retry model clients are preserved. The graph deadline is checked between
stages and is not a hard wall-clock cancellation. This demo does not implement the
historical pilot's request/token/dollar controller or promise a spending cap.

Where a trusted local proxy is required, set `HTTPS_PROXY` in this CMD process
before launching (for example, `set HTTPS_PROXY=http://127.0.0.1:7897` only if that
listener is configured). No persistent Git/proxy settings are changed. Restarting
without `IT_SUPPORT_DEMO_LIVE=1` disables live execution.

## Reading results and limitations

The **Recommendation** tab separates current actions from conditional future
guidance and shows the escalation reason, typed trigger basis, missing information,
uncertainty and required human review. An insufficient-evidence escalation flag of
false means **undetermined**, not unnecessary or safe. Proposed handoffs and changes
are never performed by the application.

The **Evidence** tab maps readable `KB 1` / `OPS 1` citations back to section text,
source paths, chunk IDs and complete structured snapshot facts/timestamps. Ticket
reports, recorded observations and policies are labelled separately. Current
conditions, supported software versions and incident causality cannot be inferred
from inventory flags or historical timestamps.

The **Activity & limitations** tab preserves ordered lookup outcomes, validated
scope, graph trace and safe error codes. A synthesis rejection leaves no fabricated
recommendation and retains collected evidence. When retrieval fails and the backend
constructs its deterministic no-KB fallback, the UI shows an unavailable report
instead of treating that fallback as policy absence or accepted delivery; the
underlying result and graph trace remain intact in session memory.

Structural citation acceptance does not prove semantic entailment. The live model
can still omit relevant actions or misjudge applicability. Human review is mandatory
but there is no approval, authorization or pause/resume workflow. The read-only
roles and scope guards are not employee authorization for a public deployment.
Keep the app on localhost; authentication, hosting and multi-user concurrency are
outside this MVP. No live API quality or provider connectivity has been tested here.

## Focused verification

```cmd
uv run --locked --extra demo --extra dev pytest tests/demo
```

Tests use Streamlit's AppTest plus mocked boundaries to check all three examples,
provider/reader/graph wiring, paid opt-in, rerender behavior, safe errors, failed
synthesis evidence retention, retrieval-fallback presentation, and reference/time
display conversion. They forbid real HTTP/database connections. Existing backend
code, frozen inputs and historical reports are unchanged; the prior 1,057-test
baseline and 184 semantic-guidance targeted passes are reused rather than repeating
the full suite or database integration checks.

Verification on 2026-11-02: **14 focused tests passed in aggregate**. The first run
passed ten adapter tests; four UI tests needed an absolute AppTest entry-point path,
and the paid-form test was adjusted to submit Streamlit's batched widget changes.
Only the affected tests were rerun. All three example reports rendered without UI
exceptions. The documented locked/offline startup served the application shell and
`/_stcore/health` with HTTP 200 on localhost. No paid requests or database connections
were made. These checks cover rendering structure and interaction semantics; visual
browser review and a separately authorized live run remain outside this verification.

Final review on 2026-11-03 used headless Microsoft Edge against the local app at
`http://127.0.0.1:8501`, including all three examples, evidence/citations, operational
snapshots, the lookup sequence and disabled paid mode. Desktop (1440px) and small
(390px) viewport screenshots were inspected. A temporary offline-only harness
rendered clarification, synthesis failure, total failure and long-content states;
it blocked model/database connections and did not change the demo service. Empty
lists, retained evidence and undetermined escalation remained visible, and long
text wrapped without document-level horizontal overflow. Screenshots and the
temporary harness stay under ignored `reports/demo-review/`, outside the commit.

The only UI correction replaces faint disabled example inputs with readable,
non-editable text. **17 focused tests passed in aggregate**, including three new
display-state cases and strengthened error-log redaction assertions. One added
assertion was corrected for Streamlit's normal whitespace trimming; only its three
related cases were rerun. No shared backend code or existing locked dependency
record changed, so the full backend baseline remains applicable. No paid workflow,
database connection, cloud deployment or live-model quality test was performed.
