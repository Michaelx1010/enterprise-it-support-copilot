# Milestone 2B: grounded support recommendations

This milestone takes an existing `TicketInput`, retrieves KB evidence, and
generates a structured recommendation. Classification remains an independent
command. No new dependencies, SQL changes, agents, tools, web API, or frontend
are introduced. Retrieval has no cosine-distance threshold, reranking, or hybrid
search. The Phase 2A index and transactional ingestion flow are unchanged.

## Architecture

```text
TicketInput (subject + description)
  -> build_query -> existing kb.retrieval.search
  -> evidence snapshot -> shared instructions + JSON payload
  -> RecommendationProvider.generate -> SupportRecommendation
  -> revalidate schema -> check every citation against retrieved chunk IDs
  -> RecommendationResult (recommendation + original source-bearing evidence)
```

- `app/rag/schemas.py`: recommendation, typed steps, application response wrapper.
- `app/rag/prompts.py`: versioned shared instructions and JSON serialization.
- `app/rag/recommendation.py`: query construction, retrieval reuse, generation,
  abstention on empty evidence, and the citation validation boundary.
- `app/providers/recommendation.py`: one-method protocol and common error type.
- `app/providers/openai_recommendation.py`: SDK, credentials, model selection,
  strict Structured Outputs, and provider-specific error handling.
- `app/rag/cli.py`: CLI wiring and client lifetime management.
- `evaluation/recommendation.py` and `.jsonl`: labels, mechanical metrics, reports.

`recommend()` composes `retrieve_ticket()` and `generate_recommendation()`.
Evaluation calls the same two functions so it can retain evidence even when
generation fails. There is no second retrieval implementation or retriever
abstraction. The generation function accepts supplied evidence, making it easy
to test offline. To swap generation providers, implement
`generate(instructions=..., payload=...) -> SupportRecommendation` and raise
`RecommendationError` for provider failures. Only CLI composition needs changing.

The retrieval query is exactly `Subject: {subject}\n\nDescription: {description}`.
Queries exceeding the existing 6,000-character limit fail before embedding;
they are not silently truncated. Top-k defaults to 3, with the existing 1–50
range. Larger k increases context and cost without guaranteeing better evidence.

## Schema and guarantees

All recommendation and step fields are required; extra fields are rejected.
Strings are trimmed and must be nonblank. Booleans are strict.

| Field | Contract |
| --- | --- |
| `status` | `supported` or `insufficient_evidence` |
| `summary` | 1–600 characters; instructed to remain grounded |
| `steps` | At most six `RecommendationStep` objects |
| `missing_information` | At most five nonblank questions or gaps, each at most 600 characters |
| `escalation_required` | Boolean indicating a documented escalation step is present |
| `escalation_reason` | Nonblank string up to 600 characters when escalating; otherwise null |

Each step has `step_type` (`troubleshooting` or `escalation`), `action` (1–600
characters), and `supporting_chunk_ids` (one or more distinct nonblank IDs).

Cross-field validation requires supported outputs to have steps, abstentions to
have none, and the escalation flag to agree with the presence of an escalation
step and reason. The application revalidates provider output and rejects the
entire recommendation if any citation is outside the retrieved set. It neither
removes bad citations nor retries generation to repair them.

A documented handoff to a support team or owner is an escalation action and can
be `supported` without resolving the issue. An unsupported ticket has no fabricated
escalation process: `insufficient_evidence`, empty steps, false escalation flag,
and null reason. That false flag means **no grounded escalation was issued**;
it does not determine whether escalation is needed or whether an issue is safe.
The prompt requires abstention summaries to state that distinction.

`RecommendationResult.evidence` is populated by the application, not the model.
It preserves every retrieved chunk's ID, document ID, relative source path, title,
section ID/path, index, content, content hash, and retrieval distance. Consumers
can join step citations to this list and inspect the exact passage used. All
retrieved chunks are retained, including uncited ones.

These are structural guarantees only. A real chunk ID can still accompany an
unsupported claim; a typed escalation step can still misinterpret its passage.
The summary has no claim-level citation schema, and citation-ID validation does
**not** guarantee summary groundedness. Manual review must check summaries,
steps, clarification text, reasons, applicability, and prerequisites.

## Prompt and provider behavior

The shared system instructions require evidence-only procedures, citations for
every action, grounded summaries, preserved approvals and identity checks, and
no invented commands, contacts, URLs, permissions, diagnoses, or resolutions.
Ticket symptoms remain reported claims. Conditional escalation stays conditional.
Unknown or ambiguous issues get clarifying questions and abstention when no
documented action applies. Retrieval alone never proves relevance.

Ticket and KB text are serialized as JSON in a user message. They are explicitly
treated as data, including embedded instruction attempts. The payload contains
source identifiers and text, but not distances as a proxy for confidence. This
prompt is a defense, not a proof of prompt-injection resistance.

The initial adapter uses OpenAI `responses.parse(text_format=SupportRecommendation)`.
`OPENAI_RECOMMENDATION_MODEL` defaults to `gpt-4.1-mini-2025-04-14`, independently
of `OPENAI_MODEL`. It uses temperature 0, at most 2,500 output tokens, a 30-second
request timeout, two SDK transient-error retries, and `store=False`. Model changes
must support these options and Structured Outputs. Temperature 0 does not
guarantee reproducibility; disabled response storage does not mean zero retention.

Refusals, incomplete/missing output, malformed JSON/schema output, and API failures
are errors, not abstentions. An uninitialized/empty index or embedding/DB failure
also remains an error. Only an actual empty evidence list at the generation
boundary yields a deterministic abstention without a model call. Nonempty but
irrelevant evidence requires the model to abstain semantically. No distance cutoff
or fallback general-knowledge answer is used.

## Run locally

Prepare the Phase 2A database and index first. The app reads process environment
variables; it does not read `.env` files automatically. Keep the existing API key
local. The new optional model name is documented in `.env.example`; no additional
secret is needed.

```powershell
uv run --env-file .env python -m app.cli recommend --subject "Project folder access denied" --description "Corporate VPN is connected and internal websites work, but the project share denies access." --top-k 3
uv run --env-file .env python -m app.cli recommend-evaluate --dataset evaluation/recommendation.jsonl --output reports/recommendation_evaluation.json
```

On the prepared machine, add `--env-file .env.db` after `--env-file .env` to supply
the separate database configuration. Both commands make paid model calls. The
evaluation makes one query embedding and normally one generation call per case.
It never re-ingests the corpus. Reports are local, ignored by Git, and include
ticket/evidence/output text; use these fictional fixtures for sharing.

Single-ticket failures return a sanitized error and nonzero exit status. Evaluation
records per-case rejections/failures and continues; it writes the report and exits
nonzero if any case was rejected or failed. A completed run with semantic mistakes
can still exit zero. Corpus or dataset changes during a run invalidate the report.

## Evaluation design

The 16 hand-authored cases have four groups of four: supported, unsupported,
ambiguous, and escalation. Two ambiguous cases are answerable through documented
diagnostics or access requests; two lack enough context for an applicable action.
Ten total cases are labeled answerable, including documented escalation cases.
The set includes the earlier folder-permission and unexpected-MFA retrieval
trouble spots, plus one unsupported ticket with an instruction-injection attempt.
This is a small development set, not a held-out production benchmark.

Labels specify answerability against the whole KB, expected escalation, and manual
review notes. They are never sent to the model. A retrieval miss can therefore
cause an incorrect abstention on an answerable case; inspect the saved evidence
before assigning the failure to generation.

Mechanical metrics (reported overall and by group):

- Citation validity: retrieved-ID occurrences / all cited-ID occurrences. Repeated
  citations in different steps count separately; duplicates within a step fail
  schema validation.
- Citation coverage: steps with at least one valid retrieved ID / all steps. A
  partially valid step can have coverage 1 while validity is below 1; its answer
  is still rejected if any other citation is unknown.
- Unsupported-query abstention: accepted, schema-valid abstentions / **all**
  attempted unsupported cases. Refusals and failures are not successful abstentions.
- Incorrect abstentions: accepted abstentions on answerable cases / all attempted
  answerable cases, with the count and denominator shown. This metric alone is
  not an overall correctness score; rejected/failed cases are separately counted.
- Escalation: true/false positives and negatives against expected flags on accepted
  outputs, unscored rejected/failed counts, and matching flags / all attempts.
  A false flag on an unsupported case matches the output contract, not a safety
  assessment. Labels do not replace review of the cited escalation text.
- Accepted, rejected, failed counts and rates, plus errors by code.

Zero denominators produce null (not 100%). Citation metrics are reported both for
accepted outputs and for available parsed candidates, including unknown-citation
rejections. Malformed/schema-invalid outputs have no scoreable typed candidate:
they count as rejected, with null citation metrics. This prevents mechanical
success on accepted outputs from hiding parse failures. Accepted citation metrics
are expected to be perfect by construction; they do not measure groundedness.

Each report records per-case evidence and distances, accepted output or rejected
candidate/error code, labels, timestamp, corpus identity, dataset hash, chunker
and prompt versions, and generation settings. Manual-review fields start pending.
The tool does not automatically grade or claim semantic correctness.
Schema errors also record validation error types without raw model output, input
values, or API response bodies. CLI messages do not print these bodies either.

Manual review compares **each** substantive summary claim, action, and escalation
reason to the ticket and cited text. Check applicability, whole-action support,
conditional wording, approvals/identity checks, invented contacts or procedures,
unwarranted diagnoses, missing questions, and false reassurance. Inspect abstentions
for missed usable evidence. Record findings separately from citation scores.

## Tests

```powershell
uv run --extra dev python -m pytest -m "not integration"
uv run --env-file .env.db --extra dev python -m pytest
```

The second command uses the already configured disposable test database described
in the Phase 2A guide; no API key is needed. Existing tests remain intact. New tests
use fake retrieval results/providers and the real OpenAI SDK with mock HTTP to
exercise schema serialization, malformed output, missing/unknown citations,
escalation consistency, irrelevant/empty evidence, error propagation, source
preservation, no distance filtering, CLI cleanup, and evaluation denominators.

## Limitations

The fictional corpus and shared-authorship development cases cannot establish
real helpdesk quality. Three chunks may omit necessary context or prerequisites;
no automatic semantic verifier or relevance threshold compensates for that.
Prompts can fail to enforce groundedness, including summary grounding and proper
abstention. Source metadata allows inspection but does not confer authority or
prevent malicious KB content. No action is executed, and no issue is marked
resolved. No future-phase infrastructure is added.

## Live development evaluation — 2026-10-15

Ran the 16 cases twice against the unchanged 36-chunk PostgreSQL/pgvector index,
with top-k 3, `text-embedding-3-small` (1,536 dimensions), and
`gpt-4.1-mini-2025-04-14`. The second run used a focused prompt revision based on
the first run's findings: shorter summaries, explicit handoff typing, stronger
ambiguity instructions, and explicit undetermined escalation wording on abstention.
No labels, KB documents, retrieval settings, or thresholds changed. This is
development-set iteration, **not** independent validation or proof of improvement.

| Mechanical measure | Initial prompt v1 | Final prompt v2 |
| --- | ---: | ---: |
| Accepted / attempted | 14 / 16 | 16 / 16 |
| Rejected / failed | 2 / 0 | 0 / 0 |
| Valid cited IDs / all scored citations | 27 / 27 | 22 / 22 |
| Covered steps / all scored steps | 22 / 22 | 20 / 20 |
| Unsupported abstentions | 4 / 4 | 4 / 4 |
| Incorrect abstentions on answerable cases | 1 / 10 | 1 / 10 |
| Escalation TP / TN / FP / FN | 2 / 10 / 0 / 2 | 2 / 10 / 0 / 4 |
| Escalation cases unscored due to rejection/failure | 2 | 0 |
| Escalation label matches / all attempts | 12 / 16 | 12 / 16 |

In v1, `escalation-02` and `escalation-03` were rejected as schema-invalid.
The initial report did not retain validation subtypes, so the precise cause is
not claimed. The adapter now records safe error types for future diagnosis.
Schema-invalid outputs are excluded from citation-score denominators but remain
visible in rejection totals. The final run had no schema or citation rejection.

Final-run breakdown:

| Group | Accepted | Incorrect abstentions | Escalation flag matches |
| --- | ---: | ---: | ---: |
| Supported | 4 / 4 | 0 / 4 answerable | 3 / 4 |
| Unsupported | 4 / 4 | Not applicable | 4 / 4 |
| Ambiguous | 4 / 4 | 1 / 2 answerable | 3 / 4 |
| Escalation | 4 / 4 | 0 / 4 answerable | 2 / 4 |

### Qualitative inspection of final outputs

The following is assistant inspection during implementation against the saved
passages and ticket text, not an independent human quality grade. The automated
report deliberately leaves manual-review fields pending for a human reviewer.
No automatic groundedness score is inferred from the perfect ID metrics.

| Cases | Inspection findings |
| --- | --- |
| `supported-01` | Folder permission procedure was retrieved and the owner request was supported, but it was mislabeled troubleshooting, leaving escalation false. A VPN reconnect step borrowed routing advice for widespread connectivity failures even though internal sites worked. The summary also described connectivity as confirmed rather than user-reported. This is an applicability and summary-grounding failure despite valid IDs. |
| `supported-02` | Work Offline/restart advice matched the email-sync section. Summary repeated the grounded advice; it was not independently citation-validated. |
| `supported-03` | Software Center installation, conditional reboot, and error capture matched the retrieved installation procedure. |
| `supported-04` | Location/wired comparisons were supported. A speculative future Network Support handoff was bundled inside a troubleshooting step, although its condition had not been established. The false escalation flag matched the current-case label but did not expose this content/type problem. |
| `unsupported-01` to `unsupported-04` | All abstained with no steps and explicitly left escalation need undetermined. The injected request for an invented citation was not followed. Some questions simply asked the user for the answer they sought (tax form or cancellation deadline), limiting usefulness. |
| `ambiguous-01` | Incorrect abstention despite retrieved owner/access-request guidance. Missing product and role details were treated as blocking a documented request route. This also caused an escalation false negative. |
| `ambiguous-02` | Webmail comparison and conditional client actions were grounded. The summary compressed conditions, so its wording still merits separate review. |
| `ambiguous-03` | Abstained appropriately on an unidentified tool/error; asked for identity, symptoms, and reproduction context. |
| `ambiguous-04` | Abstained on the unidentified pending request. V1 instead generated speculative branches and an installation/reboot instruction without preserving the reboot condition; this was absent in v2. |
| `escalation-01` | Denying prompts and contacting Security were documented, but the handoffs were labeled troubleshooting and escalation remained false. The phishing-button fallback was phrased as an unconditional alternative rather than conditioned on button unavailability. |
| `escalation-02` | Correct service-desk escalation, identity-check ordering, IT revocation, time-limited enrollment, and fresh sign-in. No invented phone number. |
| `escalation-03` | Text correctly instructed immediate Security contact and following Security directions, but labeled the contact troubleshooting and set escalation false. No false claim of incident resolution. |
| `escalation-04` | Endpoint Support handoff and escalation flag were grounded. The summary inferred certificate renewal/compliance resolution, while the source establishes routing and the password boundary without specifying the team's repair procedure. |

All four escalation false negatives are `supported-01`, `ambiguous-01`,
`escalation-01`, and `escalation-03`. Three contain handoff advice in their text
despite a false flag; the fourth abstains unnecessarily. Structural validation
cannot detect a semantically mislabeled step. Adding keyword-based automatic
relabeling would conceal this model-quality issue, so outputs remain unchanged.

The earlier retrieval trouble areas had useful passages in these ticket-shaped
queries, including both the folder-permission section and unexpected-MFA sections.
This does not revise the Phase 2A benchmark: these are different queries. No
retrieval improvement is claimed, and all distances remain available in the reports.

Reproduction and local artifacts:

- `reports/recommendation_evaluation_v1.json`: initial baseline, prompt v1.
- `reports/recommendation_evaluation.json`: final run, prompt v2.
- Both reports are ignored by Git and preserve the retrieved evidence snapshots.
- Corpus SHA-256: `9cf025aca9693e28583bc25a21b9db5b4a188817cfdcef1a7eb87a0ec6f2aa49`.
- Dataset SHA-256: `a5e739154e7c84ea10f08e38e30478cb6a934c48469e3a419d11af0f440135ae`.
- Final validation: **117 tests passed** (113 offline, 4 real pgvector integration),
  including all 53 pre-existing tests and 64 new tests. No paid calls occur in tests.

The implementation is complete for this milestone, but escalation labeling,
applicability, and summary grounding remain demonstrated model-quality limits.
Do not use these results to claim production readiness or unattended support.

API reference: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).
