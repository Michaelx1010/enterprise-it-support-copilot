# Enterprise IT Support Copilot

An incremental AI Engineer portfolio project. Phase 1 explores a synthetic IT
helpdesk dataset and classifies a ticket's subject and description into a validated
`category`, `priority`, and concise `summary`.

Milestone 2A adds a fictional Markdown knowledge base, OpenAI embeddings,
PostgreSQL/pgvector search, and retrieval evaluation. See
[the milestone 2A guide](docs/phase2a.md) for setup, architecture, and commands.
Grounded recommendation generation has not been implemented.

## Setup

Requires Python 3.11 or newer. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Alternatively, with [uv](https://docs.astral.sh/uv/), use the committed lockfile:

```powershell
uv sync --locked --extra dev
```

The examples below use Windows PowerShell and the virtual environment directly,
so activating it is optional. On macOS/Linux, use `.venv/bin/python` instead.

Dependencies are Pydantic (schemas), pandas (ticket exploration), the OpenAI SDK
(initial provider), psycopg and pgvector (KB storage), and pytest (development
tests). Phase 1 commands do not require a running database.

## Download and inspect the data

```powershell
.\.venv\Scripts\python.exe -m app.cli download
.\.venv\Scripts\python.exe -m app.cli inspect
```

The first command downloads `data/raw/tickets.csv` from a pinned Hugging Face
revision and refuses to overwrite an existing file. The second writes
`reports/dataset_profile.md` locally. It requires no API key and makes no model
calls. Raw CSV files, generated reports, and rendered HTML previews are ignored
by Git. The dataset source and checksum are recorded in the generated report.

To inspect another local CSV with the same required columns:

```powershell
.\.venv\Scripts\python.exe -m app.cli inspect --data path/to/tickets.csv --output reports/custom_profile.md
```

The loader preserves blank cells and literal text such as `NA`; it does not drop
rows, fill missing labels, or silently relabel tickets. Inspection reports missing
and unknown labels. Classification requires nonblank subject and description.

## Classify one ticket

Export `OPENAI_API_KEY` in your local shell. Do not commit credentials or paste
them into source files. `.env.example` lists supported settings; this application
does **not** automatically load `.env` files.

```powershell
$env:OPENAI_API_KEY = "<your API key>"
$env:OPENAI_MODEL = "gpt-4.1-mini-2025-04-14"
.\.venv\Scripts\python.exe -m app.cli classify --subject "VPN connection failure" --description "My VPN disconnects repeatedly and I cannot access internal tools to work."
```

This command makes a paid API request. The model setting is optional and defaults
to the snapshot shown above. Choose a model available to your account that supports
the Responses API and Structured Outputs. No batch classification runs implicitly.

Illustrative output (not a recorded live model result):

```json
{
  "category": "Network",
  "priority": "High",
  "summary": "Repeated VPN disconnections prevent access to internal work tools."
}
```

The adapter uses `client.responses.parse(text_format=TicketClassification)` to
request a strict JSON schema and parse it with Pydantic. All three fields are
required, category and priority have fixed allowed values, extra fields are
rejected, and summaries must contain 1–400 characters after trimming whitespace.
The prompt asks for a single sentence; sentence count is not enforced by a parser.
Only subject and description are sent, along with the shared instructions and
schema. Emails or other text embedded in those two fields remain part of the input.

Refusals, incomplete or missing structured output, validation failures, and API
failures are reported as errors, with a nonzero CLI exit status. There is no
fabricated fallback classification or JSON-repair loop. The SDK has a 30-second
request timeout and up to two transient-error retries. Response storage is disabled
with `store=False`; this is not a claim of zero provider retention.

## Provider boundary

```text
CLI -> classify_ticket(subject, description, provider=...)
    -> shared instructions + validated ticket text
    -> ClassificationProvider.generate(...)
    -> validated TicketClassification
```

- `app/schemas.py`: provider-independent inputs and output labels.
- `app/classification.py`: prompt construction and shared validation.
- `app/providers/base.py`: one-method protocol and a common failure type.
- `app/providers/openai.py`: SDK, credentials, model choice, and OpenAI errors.
- `app/data.py`: pinned download and CSV loading.
- `app/profiling.py`: descriptive exploration; no classification calls.
- `app/cli.py`: command parsing and provider selection.

To use Hugging Face or a local model later, implement `generate(instructions=...,
ticket_text=...) -> TicketClassification` and inject that adapter at the CLI or
calling code. The new adapter is responsible for translating model output into
the shared schema or raising `ClassificationError`. The classification pipeline
does not need to change. Those adapters are deliberately not implemented yet.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Tests are offline and need no API key. They cover label and summary validation,
blank inputs, a substitute provider, CSV preservation and profiling, CLI errors,
and the real OpenAI SDK's schema serialization and parsing via a mock HTTP
transport. These checks establish application behavior, not live model quality
or account/model availability.

## Dataset and limitations

Source: [Console-AI/IT-helpdesk-synthetic-tickets](https://huggingface.co/datasets/Console-AI/IT-helpdesk-synthetic-tickets)
(upstream license metadata: MIT), revision
`165693849d955c6da4c00bc8be8e541afec0514e`.

The inspected dataset has 500 synthetic tickets, 11 categories, and four priorities
(`Low`, `Medium`, `High`, `Urgent`). Categories and priorities are imbalanced:
Software accounts for 46.2% of tickets; Medium and High together account for 98.4%.
No reference summaries are supplied. See the generated report for the full schema,
distributions, missing values, duplicates, and text lengths.

The category descriptions and priority rubric in the prompt are explicit project
assumptions: the dataset does not supply a detailed labeling guide. Related issues
can span categories, and valid structured output does not guarantee correct labels
or factual summaries. No accuracy claim is made in Phase 1. Milestone 2A evaluates
retrieval separately. Recommendation generation, tools, LangGraph, FastAPI,
application containerization, and a frontend remain later work in
[`PROJECT_BRIEF.md`](PROJECT_BRIEF.md).

API references: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)
and [GPT-4.1 mini model documentation](https://developers.openai.com/api/docs/models/gpt-4.1-mini).
