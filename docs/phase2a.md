# Milestone 2A: retrieval before generation

This milestone implements ingestion, semantic search, and a small retrieval
evaluation. There is no recommendation model, agent, tool execution, or web app.
Existing ticket classification remains independent.

## Corpus

`knowledge_base/` contains 12 fictional Northstar IT documents, each with three
sections. They are portfolio fixtures, not verified organizational policies.
Topics intentionally overlap: VPN versus Wi-Fi versus remote desktop; passwords
versus MFA versus lockouts; installation versus permissions versus licensing;
and email authentication versus phishing. Procedures include prerequisites and
escalation boundaries to make the retrieved evidence useful for later generation.

Only Markdown documents under the selected KB directory are indexed. Use one
leading H1 title and H2/H3 section headings. Heading paths must produce unique
section IDs within each document. Fenced code is not interpreted as headings.
Setext headings, front matter, HTML, and Markdown extensions are not parsed.

Short sections remain intact. Sections longer than 2,000 characters split near
1,500 characters, preferring paragraph boundaries, with up to approximately 200
characters of overlap within that section. Long blocks may split at whitespace;
this is not a token-aware or full Markdown syntax-aware chunker. Metadata is
preserved on every resulting chunk. The initial 36 sections all fit in one chunk
each; long-section behavior is covered with offline fixtures.

## Dependencies and local setup

The only added Python dependencies are `psycopg[binary]` and `pgvector`.
PostgreSQL runs as a single local Docker Compose service with a persistent volume.
The port is bound to localhost and defaults to 55432. The Python application
continues to run in its virtual environment.

```powershell
uv sync --locked --extra dev
```

Keep credentials in ignored local env files. `.env.example` lists the names;
fill `OPENAI_API_KEY`, `POSTGRES_PASSWORD`, and `DATABASE_URL` locally. A database
URL has the form `postgresql://USER:PASSWORD@127.0.0.1:55432/DATABASE` (URL-encode
special characters). Do not commit or print completed connection strings.

The application still reads process environment variables, not env files itself.
Use uv's explicit `--env-file` option to load local configuration:

```powershell
docker compose --env-file .env up -d --wait
uv run --env-file .env python -m app.cli kb init
uv run --env-file .env python -m app.cli kb ingest
uv run --env-file .env python -m app.cli kb search "VPN is connected but my project folder says access denied" --top-k 3
uv run --env-file .env python -m app.cli kb evaluate
```

On the prepared development machine, `.env.db` holds separately generated local
database credentials. Use `docker compose --env-file .env.db ...` and
`uv run --env-file .env --env-file .env.db ...` there. Neither file is tracked.
The later env file supplies database settings; the API key remains in `.env`.
Do not run `docker compose config` in shared logs: it can reveal expanded secrets.

The default image is `pgvector/pgvector:0.8.1-pg17`. During local validation,
Docker Hub downloads stalled, so the prepared machine uses the cached PostgreSQL
16.10 image plus PostgreSQL's official `postgresql-16-pgvector` 0.8.7 package.
`.env.db` selects `PGVECTOR_IMAGE=it-support-pgvector:16-local` and a separate
`KB_VOLUME_NAME=it-support-kb-pg16-data`. The generated build context is in ignored
`reports/db-build/`. New machines can use the default published image without
this workaround; do not reuse the PostgreSQL 16 volume with PostgreSQL 17.

`kb init` enables the vector extension and creates the dedicated `kb_chunks`
table. `kb ingest` makes paid embedding calls and **replaces the complete KB
index**, including removal of deleted documents. It never modifies ticket data.
Every ingestion re-embeds the corpus; no embedding cache is implemented.
An empty/malformed corpus fails rather than clearing the table. All vectors are
prepared and validated before a transaction deletes old rows and inserts the
new snapshot. Insertion failures roll back the entire replacement. Concurrent
ingestions serialize on the table lock. Search sees a consistent committed
snapshot and uses deterministic chunk-ID tie-breaking.

## Architecture

```text
Markdown -> document chunks -> embedding provider -> PostgreSQL transaction
Query    -> embedding provider -> exact pgvector search -> source-bearing results
Labeled queries -> same search function -> metrics and distance report
```

- `app/kb/documents.py`: Markdown loading, deterministic chunk IDs, content hashes.
- `app/kb/schemas.py`: chunk metadata and search result models.
- `app/providers/embeddings.py`: one-method embedding protocol and vector checks.
- `app/providers/openai_embeddings.py`: SDK, model configuration, batched input,
  response ordering, and provider error handling.
- `app/kb/schema.sql` and `store.py`: SQL schema, full replacement, exact search.
- `app/kb/ingest.py` and `retrieval.py`: application workflows independent of SDK calls.
- `app/kb/cli.py`: KB-specific CLI wiring, leaving Phase 1 command handling intact.
- `evaluation/retrieval.py`: labels, metrics, and run report.

The initial embedder is `text-embedding-3-small` with 1,536 dimensions. Each
embedded passage includes its title, heading path, and body. Results return the
body, document ID, relative source path, heading path, section ID, chunk ID,
position, content hash, and cosine distance. Lower distance means nearer; scores
are not confidence probabilities.

The database uses `vector(1536)` and exact cosine-distance ordering (`<=>`), with
no HNSW/IVFFlat index and no relevance threshold. Model identity and dimensions
must agree between query and stored embeddings. A new embedding provider only
needs `spec` and `embed(texts)`; it requires re-ingestion even if its dimensions
match. Different dimensions require a schema change. No generic repository or
multi-provider registry is introduced.

## Evaluation

`evaluation/retrieval.jsonl` has 12 development queries, 8 held-out queries, and
4 unsupported queries. Labels are relevant section IDs, validated against the
stored corpus before any evaluation embedding calls. Changing filenames or
headings can require relabeling.

For the first three retrieved chunks:

- Hit@3 is 1 when at least one relevant section appears, otherwise 0.
- Recall@3 is the number of distinct relevant sections retrieved divided by all
  labeled relevant sections. Duplicate chunks from one section count once.
- Report means separately for development and held-out cases. Unsupported
  queries have null metrics and never enter either denominator.

All top-three distances are saved for **both answerable and unsupported queries**.
The report also summarizes nearest-result distances per split. No query is
rejected by distance. Unsupported queries will still return nearest neighbors;
this is expected and is not proof that the KB can answer them.

Reports go to ignored `reports/retrieval_evaluation.json`, including per-query
ranked IDs, source paths, distances, metrics, embedding identity, corpus hash,
chunker version, query-file hash, and timestamp. The corpus is checked again at
the end to reject runs that changed midway. Inspect misses and distance overlap
before considering any threshold. Do not tune on held-out cases and then describe
the same cases as untouched validation.

## Tests

```powershell
uv run --extra dev python -m pytest -m "not integration"
```

Offline tests cover metadata, fenced headings, long sections, response ordering,
bad vectors, query validation, provider/model mismatch, failed embedding batches,
and metric denominators. Fake embeddings test mechanics, not semantic quality.

Database integration tests use real pgvector and deterministic vectors. Create a
separate disposable database named `it_support_test` (with the configured local
user) and set `TEST_DATABASE_URL` locally. With the default Compose user:

```powershell
docker compose --env-file .env exec -T db createdb -U it_support it_support_test
uv run --env-file .env --extra dev python -m pytest -m integration
```

Use the `.env.db` variants on the prepared machine. Tests skip unless
`TEST_DATABASE_URL` is supplied, and refuse database names not ending in `_test`.
They replace/clear only that test database's dedicated `kb_chunks` table. Tests
check actual cosine ordering, source round-tripping, repeated replacement,
stale-row removal, rollback after an insert fails, and model mismatch.

## Limitations and next milestone

This is a small, English, synthetic corpus and a manually authored query set.
Queries and documents share vocabulary and authorship; even high scores do not
establish real helpdesk performance. Labels identify useful sections, not every
possibly related passage. No reranking, keyword hybrid search, permissions-aware
retrieval, production migration tooling, or incremental indexing is included.
Real private documents would need an approved data-handling policy before being
sent to an external embedding provider.

## Initial live baseline — 2026-10-12

Measured against real PostgreSQL 16.10 with pgvector 0.8.7, using OpenAI
`text-embedding-3-small` (1,536 dimensions), 12 documents, and 36 chunks. The
first evaluation was inspected without changing labels, queries, or retrieval
configuration afterward. The tiny held-out split shares the corpus author's
vocabulary and is not an independent production benchmark.

| Split | Queries | Hit@3 | Recall@3 | Nearest cosine distance, min–max |
| --- | ---: | ---: | ---: | ---: |
| Development | 12 | 91.67% | 91.67% | 0.2626–0.5542 |
| Held out | 8 | 100.00% | 93.75% | 0.2723–0.4955 |
| Unsupported | 4 | Not applicable | Not applicable | 0.6988–0.7498 |

The answerable-query aggregate is Hit@3 = 95.00%, Recall@3 = 92.50%.
Unsupported queries are excluded. Every result's distance is retained in the
local JSON report, not just the nearest-result summaries above.

Two cases need attention before grounded recommendations:

- `dev-06`: the top result was VPN guidance, followed by a missing-share-path
  section and connection-failure guidance. The specifically labeled folder
  permission procedure was absent. The top VPN section does contain a useful
  permission-routing hint, so the strict section labels also limit interpretation
  of this miss. The baseline labels were left unchanged.
- `test-05`: unexpected approval notifications returned account-lockout guidance
  before the phishing/MFA section. One of the two relevant sections was present
  (Hit@3 = 1, Recall@3 = 0.5). Rank one alone would be misleading here.

Unsupported-query distances are larger in this run, but four examples are too
few to calibrate a relevance threshold. No distance filtering was introduced.
The unsupported nearest results are unrelated procedures, not usable answers.

Reproduction identifiers:

- Corpus SHA-256: `9cf025aca9693e28583bc25a21b9db5b4a188817cfdcef1a7eb87a0ec6f2aa49`
- Evaluation file SHA-256: `f77cb10642e30902eac1c31e674f762ba2ddd22710d9d34b6705c51d61d17788`
- Chunker: `headings-v1-1500-2000-overlap200`
- Python 3.12.7; OpenAI SDK 2.54.0; psycopg 3.3.6; pgvector Python 0.5.1.
- Validation: 49 offline tests passed (including all 22 Phase 1 tests), plus
  4 real pgvector integration tests passed in a separate disposable database.

Recommendation generation remains a separate milestone after real pgvector
retrieval and the initial evaluation have been inspected. No recommendation
schema, prompt, adapter, or automatic fallback answer is added in 2A.

References: [OpenAI embeddings](https://developers.openai.com/api/docs/guides/embeddings),
[pgvector](https://github.com/pgvector/pgvector), and
[pgvector Python](https://github.com/pgvector/pgvector-python).
