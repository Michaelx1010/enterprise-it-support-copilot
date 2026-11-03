# Command-line reference

[Portfolio overview](../README.md) · [Documentation map](README.md)

The CLI remains available independently of Streamlit. Commands below run from the
repository root in Windows CMD with Python 3.11+ and `uv` installed. Use
`uv run --locked python -m app.cli --help` for the command groups. The application
does not automatically load `.env`; `uv --env-file` loads explicitly named local
files. Keep secret values local and out of Git.

## Dataset exploration (no model calls)

```cmd
uv run --locked python -m app.cli download
uv run --locked python -m app.cli inspect
```

Download needs internet access but no API key. It reads the pinned
`Console-AI/IT-helpdesk-synthetic-tickets` dataset at revision
`165693849d955c6da4c00bc8be8e541afec0514e`, writes `data/raw/tickets.csv` and
refuses to overwrite an existing file. Inspection writes
`reports/dataset_profile.md`, including source/checksum, schema, category and
priority distributions, missing values, duplicates and text lengths. Both output
locations are ignored by Git.

The loader preserves blank cells and literal text such as `NA`; it does not fill
missing labels or drop rows. To inspect a different CSV with the required columns:

```cmd
uv run --locked python -m app.cli inspect --data path/to/tickets.csv --output reports/custom_profile.md
```

## Ticket classification (paid)

Set `OPENAI_API_KEY` locally using the names in [`.env.example`](../.env.example).
The classification model defaults to `gpt-4.1-mini-2025-04-14` and can be configured
through `OPENAI_MODEL`.

```cmd
uv run --locked --env-file .env python -m app.cli classify --subject "VPN connection failure" --description "My VPN disconnects repeatedly and I cannot access internal tools to work."
```

Only the subject and description are used as ticket input. The output is a
validated category, priority and concise summary; valid structure does not prove
correct classification. The project rubric is an assumption because the dataset
does not provide a detailed labeling guide or reference summaries.

The provider boundary is small: [`app/classification.py`](../app/classification.py)
builds the prompt, [`app/schemas.py`](../app/schemas.py) owns the contract,
[`app/providers/base.py`](../app/providers/base.py) defines the provider protocol,
and [`app/providers/openai.py`](../app/providers/openai.py) contains SDK-specific
code. Alternative providers can implement that protocol; they are not shipped here.

## Retrieval and standalone RAG

Follow [KB setup and search](phase2a.md) to create and ingest the fictional
Markdown corpus. [Standalone recommendations](phase2b.md) and the
[reliability review](phase2b1.md) document paid generation and evaluation commands.
Retrieval is independently testable. Standalone recommendations use KB evidence
without forcing classification or operational tools into the path.

Each action cites retrieved chunks. A supported action may be a documented
escalation even when the underlying issue remains unresolved. An
`insufficient_evidence` response has no current steps; its false escalation flag
does not establish that escalation is unnecessary or the issue is safe.

## Investigation

This scripted example needs no API key or database:

```cmd
uv run --locked python -m app.cli investigate scripted --script examples/investigation-scripted.json
```

It replays classification, retrieval and lookup fixtures through the guarded
graph. [The graph guide](phase4.md) explains scripted and PostgreSQL modes;
[the tools guide](phase3.md) covers restricted readers and operational contracts.

For live planning, first prepare the separate restricted readers and API settings
described in [the planner guide](phase4b1.md):

```cmd
uv run --locked --env-file .env --env-file .env.ops --env-file .env.kb python -m app.cli investigate live --request examples/investigation-request.json
```

This makes paid classification, embedding and planner requests. Adding
`--synthesize` enables at most one additional synthesis attempt:

```cmd
uv run --locked --env-file .env --env-file .env.ops --env-file .env.kb python -m app.cli investigate live --request examples/investigation-request.json --synthesize
```

`OPENAI_PLANNER_MODEL` and `OPENAI_SYNTHESIS_MODEL` independently configure those
providers. Output preserves available evidence, tool outcomes and partial failures.
Human review is required, but no approval workflow, account change or handoff is
executed. Current schema/prompt versions are listed in the [documentation map](README.md).

## Tests and evaluation

For local development, install test dependencies with `uv sync --locked --extra
dev`. Offline tests use mocked model responses; PostgreSQL tests require explicitly
configured test databases and restricted roles described in the phase guides.
See [recorded verification](portfolio-evaluation.md#previously-recorded-verification)
for the existing results rather than assuming a new run has occurred.

The paired runner can describe its inputs without API calls:

```cmd
uv run --locked --offline python -m evaluation.live_investigation --dry-run
```

Read [the evaluation guide](phase5b.md) before any paid invocation. Fixture replay
and historical live results are separate; the frozen Phase 5C.5 controller belongs
to the old candidate and is intentionally incompatible with the current one.
