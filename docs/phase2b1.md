# Phase 2B.1: recommendation reliability

## Preserved baseline

Phase 2B was tested (117 passed), committed, and pushed normally to `origin/main`
as `eb50233a583ba0a6a2ceb381ebefbdc3adfc680a` with message
`feat: add grounded RAG recommendations and evaluation`. The working tree was
clean after that push. Secret env files, local DB artifacts, caches, and generated
reports were excluded. No history was rewritten. Phase 2B.1 is a separate,
uncommitted review increment.

The original `evaluation/recommendation.jsonl` and `docs/phase2b.md` are preserved.
Its 16 cases are development/regression cases, already used in prompt iteration;
they are not an independent test set. The baseline report remains at
`reports/recommendation_evaluation.json` (prompt v2).

## Root-cause analysis

Inspection used the saved ticket, retrieved passages, output, and existing code.
The six highlighted cases all retrieved useful guidance. None justifies changing
the KB, retrieval ranking, embeddings, or adding a distance cutoff.

| Case | Failure and likely origin |
| --- | --- |
| `supported-01` | Folder-owner handoff labeled troubleshooting: model interpretation of step type. VPN reconnect borrowed from the all-internal-resources-fail branch: procedural applicability error within a retrieved section. Summary promoted reported connectivity to confirmation: generation error. |
| `supported-04` | Valid location-comparison advice mixed with a speculative Network Support handoff for a different condition. Prompt failed to separate present action from a possible later escalation. A correct false flag did not establish correct content. |
| `ambiguous-01` | Relevant owner/access-request routes were retrieved, but missing product/role details caused total abstention. Prompt interpretation confused details needed to submit a request with evidence needed to recommend the route. |
| `escalation-01` | Security contact was present in text but typed troubleshooting; fallback channel also lost its button-unavailable condition. Type semantics and condition preservation failed. |
| `escalation-03` | Local action and immediate Security contact were combined under troubleshooting. The flag agreed structurally with the wrong step type. |
| `escalation-04` | Correct Endpoint Support routing, but the summary inferred a certificate repair/compliance resolution not specified by the source. No claim-level summary validator exists. |

Schema and application limits contributed: the enums initially lacked field-level
semantic descriptions; cross-field validators can enforce type/flag agreement but
cannot infer a handoff from its meaning. Citation validation establishes only ID
membership. It cannot prove applicability, causation, or textual support. These
limits are preserved and disclosed; no keyword relabeling or semantic-checker
component is introduced.

The new 12-case baseline additionally rejected three model outputs with validation
type `value_error`. The report records no raw invalid outputs, so it cannot identify
the precise violated invariant. Rejections are reported separately from accepted
output quality and are never counted as correct abstentions.

## Focused changes

- `app/rag/prompts.py`: prompt v4 prioritizes applicability and explicit negative
  facts; distinguishes missing request details from an unknown problem; defines
  handoffs by their purpose, including employee-initiated reports/requests; requires
  reported symptom wording in summaries; and includes eight complete teaching
  examples. Examples use isolated fictional procedures and `demo-*` IDs, not live
  KB content or evaluation tickets. Their IDs are rejected if copied into answers.
- `app/rag/schemas.py`: field descriptions clarify step types, applicability,
  summary attribution, and escalation semantics. Output fields, limits, required
  status/step/flag/reason consistency checks, and citation validation are unchanged.
- `evaluation/recommendation.py`: adds escalation precision, recall, false-negative
  IDs, all-positive-attempt recall, separate schema/provider failure rates, prompt
  and schema hashes, and pending manual-review fields for applicability, summary
  accuracy, and unsupported claims.
- `evaluation/recommendation_dev.jsonl`, `recommendation_heldout.jsonl`, and
  `recommendation_splits.json`: new frozen case sets and preparation protocol.
- `tests/test_recommendation_reliability.py`: denominator/failure accounting,
  dataset integrity, teaching example contracts, example-citation leakage, and
  explicit tests demonstrating that citation validity is not semantic validation.

No changes to model choice, provider implementation, classification, ingestion,
retrieval, KB content, or SQL. No new dependencies or application components.

### Conditional escalation policy

`escalation_required` describes a handoff recommended for the current reported
situation. A documented handoff is recommended when its trigger is reported met.
When a prerequisite diagnostic has not been tried, recommend that documented
diagnostic first; do not add a hypothetical handoff. When the trigger is unknown,
ask a clarifying question and give any other applicable documented action.
Conditions within the chosen procedure (such as reboot only when prompted) remain
explicit. This avoids encoding an uncertain future handoff as required now.

An employee submitting an access request or pressing a Security reporting button
still performs an escalation: it asks another responsible party to act. A local
check without that handoff is troubleshooting. Lack of information for a request
does not prohibit recommending its documented route. An abstention's false flag
still means undetermined; it is not a safety judgment. These semantic instructions
can fail even when structural validation passes.

## Evaluation protocol

Before changing the prompt/schema, prepared and hashed 12 new development cases
and eight held-out cases. Development includes paired unmet/met escalation triggers,
application permissions with missing details, differing share errors, account and
Security routes, and unsupported requests with misleading authentication/recovery
neighbors. Held-out examples cover other combinations of mail, remote access,
verification, print identity, and unsupported policies.

Files are separate; no new split field or selection framework is necessary. The
manifest freezes normalized UTF-8/LF dataset hashes, and offline tests reject drift,
duplicate IDs, or exact duplicate tickets. Held-out labels were authored before
tuning and are not sent to the model. They share author and corpus with development:
this is a withheld execution set, not an independently collected benchmark.

Run protocol: baseline on new development cases; revise prompt/schema using
development findings; run v3 then v4 on new development and original regression cases;
freeze revision; evaluate held-out once without subsequent tuning. The original
baseline is historical, so comparisons also have run-to-run variability. All runs
use top-k 3, the same 36-chunk pgvector index, `text-embedding-3-small` (1,536
dimensions), and `gpt-4.1-mini-2025-04-14`, temperature 0, max output 2,500 tokens.

Precision = TP / (TP + FP), recall = TP / (TP + FN), calculated on accepted outputs.
No denominator means null. Rejected/failed cases are explicitly unscored, not true
negatives. All-positive-attempt recall = TP / all cases labeled expected escalation,
including failed/rejected attempts, to expose availability losses. Schema rejection
rate counts `invalid_output`; provider failure rate counts generation-stage failures
such as API errors/refusal/incomplete output. Retrieval failures remain separately
visible. Every rate uses all attempted cases in its split unless otherwise stated.

Citation validity/coverage and abstention definitions remain those in Phase 2B.
Perfect accepted citation metrics are mechanically guaranteed, not a quality score.
Manual fields start pending. Qualitative inspection must compare every action and
summary to the ticket and cited passages, checking conditions, identities/approvals,
unsupported claims, missed usable evidence, and step-type semantics.

V3 addressed handoff flags and the unnecessary access-request abstention, but
development inspection found premature conditional handoffs, repeated completed
checks, and invented repair/approval details. V4 adds three contrasting examples
for different branches within one passage, an unknown error with an inapplicable
crash procedure, and a routing-only source without a documented repair method.
It also strengthens action/reason field descriptions. This second revision is
development-only; held-out results are not used for further tuning.

## Reproduction

The prepared machine uses two ignored env files. These commands make paid calls;
no ingestion or recommended action is performed.

```powershell
uv run --env-file .env --env-file .env.db python -m app.cli recommend-evaluate --dataset evaluation/recommendation_dev.jsonl --output reports/phase2b1_dev_revised.json
uv run --env-file .env --env-file .env.db python -m app.cli recommend-evaluate --dataset evaluation/recommendation.jsonl --output reports/phase2b1_regression_revised.json
uv run --env-file .env --env-file .env.db python -m app.cli recommend-evaluate --dataset evaluation/recommendation_heldout.jsonl --output reports/phase2b1_heldout.json
uv run --env-file .env.db --extra dev python -m pytest
```

The earlier development baseline is `reports/phase2b1_dev_baseline.json`; re-running
the current code does not recreate the baseline prompt. Use the preserved Phase 2B
commit to reproduce that implementation. Generated reports remain ignored. Full
source metadata, text, and distances remain available in each report for inspection.

## Development results — 2026-10-16

| Run | Accepted | Schema rejected | Escalation TP/TN/FP/FN | Precision | Recall on accepted | Recall over all positives |
| --- | ---: | ---: | --- | ---: | ---: | ---: |
| Original 16, Phase 2B v2 | 16/16 | 0 | 2/10/0/4 | 100% | 33.3% | 33.3% |
| Original 16, v3 | 16/16 | 0 | 6/9/1/0 | 85.7% | 100% | 100% |
| Original 16, final v4 | 16/16 | 0 | 6/9/1/0 | 85.7% | 100% | 100% |
| New development 12, v2 | 9/12 | 3 (25%) | 2/4/1/2 | 66.7% | 50% | 28.6% |
| New development 12, v3 | 12/12 | 0 | 7/4/1/0 | 87.5% | 100% | 100% |
| New development 12, final v4 | 12/12 | 0 | 7/4/1/0 | 87.5% | 100% | 100% |

Provider failures were zero in these runs. The new-development baseline had three
unscored escalation-positive cases (`dev-02`, `dev-04`, `dev-09`), so its accepted
recall is higher than its all-positive-attempt recall. Final false positives are
`ambiguous-03` (original set) and `dev-03` (new set); there are no final false negatives.
Improved recall trades off against the original set's precision and a new harmful
interpretation of an ambiguous case. It is not an unqualified quality improvement.

| Run | Incorrect abstentions / answerable | Unsupported abstentions | Valid IDs / citations | Covered / total steps |
| --- | ---: | ---: | ---: | ---: |
| Original baseline v2 | 1/10 | 4/4 | 22/22 | 20/20 |
| Original final v4 | 0/10 | 4/4 | 22/22 | 20/20 |
| New development baseline v2 | 0/10 | 2/2 | 14/14 | 14/14 |
| New development final v4 | 0/10 | 2/2 | 17/17 | 16/16 |

The unsupported metric excludes ambiguous-but-unanswerable cases. Consequently
4/4 unsupported abstentions does **not** conceal or excuse the incorrect supported
answer on `ambiguous-03`. Its labels, text, and false-positive escalation remain
visible. Perfect ID metrics cannot distinguish these failures.

### Qualitative review: original regression cases

This is assistant inspection of the saved evidence and outputs during implementation,
not an independent human grade. Automated reports retain pending human-review fields.
All 16 final outputs were inspected; findings below include both improvements and
limitations, without deriving a semantic accuracy percentage from citation IDs.

| Cases | Final v4 findings versus baseline |
| --- | --- |
| `supported-01` | Genuine improvement: owner request is escalation, wrong VPN reconnect branch is gone, summary attributes connectivity to the ticket. Owner/service-desk approval boundary retained. |
| `supported-02` | Appropriate Work Offline/restart and diagnostic recording. Summary now explicitly reports symptoms. An unnecessary question about signing out/in remains despite no password change. |
| `supported-03` | Software Center advice preserves conditional reboot and failure recording. No invented installers or premature handoff. |
| `supported-04` | Summary attribution improved; substantive failure remains: hypothetical Network Support contact is still embedded in a troubleshooting step without its trigger being established. The correct false flag does not detect that defect. |
| `unsupported-01`–`04` | All abstain, have no steps, and explicitly leave escalation undetermined. No fabricated game-console citation despite the injected request. Some clarification questions remain less useful than asking simply for relevant documentation. |
| `ambiguous-01` | Incorrect abstention fixed; owner/service-portal routes labeled escalation. Remaining overreach: promises the owner "will approve" and broadens conditional license guidance, rather than preserving approval discretion and scope. |
| `ambiguous-02` | Appropriate comparison first, then conditional desktop actions. Summary is attributed; no forced diagnosis. |
| `ambiguous-03` | Regression: assumes an unidentified failure is a crash, recommends crash actions and future escalation, and invents recurrence in escalation_reason. Valid cited crash text does not establish applicability. Both v3 and v4 failed despite the new contrasting example. |
| `ambiguous-04` | Correct abstention and useful system/request questions, but summary still omits explicit undetermined-escalation wording. False is not a safety assessment; schema does not enforce the sentence. |
| `escalation-01` | Handoff typing and phishing-button fallback condition improved. Last handoff still expands optional session/enrollment assistance and cites only the passage without immediate-channel wording; full-claim citation support remains incomplete even though both relevant passages were retrieved. |
| `escalation-02` | Service desk handoff and identity-before-revocation boundary preserved. Actions are bundled rather than separated into atomic local/handoff steps; no bypass or invented number. |
| `escalation-03` | Security handoffs now typed escalation, trusted-device/Security-direction and no-secret conditions preserved. Several local and handoff actions remain bundled in one step. |
| `escalation-04` | Summary no longer invents a repair plan, but the action still expands routing into certificate renewal. This moves an unsupported inference from summary to step rather than fully solving it. |

### Qualitative review: new development cases

| Cases | Final v4 findings |
| --- | --- |
| `dev-01` | Premature baseline handoff removed. Only own-job cancellation/retry and documented display checks remain. |
| `dev-02` | Previously rejected output now has a grounded Endpoint Support handoff. Still repeats a question about colleagues despite that fact being given. |
| `dev-03` | False positive persists: gives future Identity Support contact and falsely states that retry already failed. The initial same-phone diagnostic is valid, but the handoff/reason is not applicable yet. |
| `dev-04` | Previously rejected output now escalates correctly, without repeating completed clock/account checks (v3 repeated them). |
| `dev-05` | Correct Storage Support route with no permission-change or VPN-refresh branch. Some redundant checks and wording that implies verification remain. |
| `dev-06` | No abstention; owner and service-portal steps typed escalation. Still overstates owner/license approval responsibility and broadens licensed-product conditions. |
| `dev-07` | Appropriate initial restart/update only, without premature escalation. Less complete than baseline: diagnostic details are omitted. |
| `dev-08` | Recurrence handoff is correct; v4 no longer repeats the completed restart/update check. Diagnostic collection and handoff are bundled. |
| `dev-09` | Previously rejected output now routes to Identity Support without diagnosing locked/disabled status; retains no-password/no-MFA-code boundary. |
| `dev-10` | Correctly selects the unavailable-button fallback and types it escalation, without suggesting credential-entry actions. |
| `dev-11`–`12` | Abstain on payroll and chat-recovery requests despite misleading neighbors. No fabricated handoff. Payroll clarification still asks part of the unanswered policy question. |

V4 therefore shows actual gains in some handoffs, symptom attribution, and branch
selection, beyond schema acceptance. It does not reliably solve conditional
applicability, approval semantics, atomic steps, or complete claim support.

## Held-out evaluation and final validation

V4 prompt and schema hashes were frozen in the split manifest at
2026-10-16 18:41:26 Asia/Shanghai, before the held-out call. The eight held-out
cases were then evaluated once; their report matches both frozen hashes. No
prompt, schema, labels, or retrieval changes followed outcome inspection.

| Held-out measure | Result |
| --- | ---: |
| Accepted outputs | 8/8 |
| Schema rejections / provider failures | 0/8 / 0/8 |
| Escalation TP/TN/FP/FN | 4/4/0/0 |
| Escalation precision / recall | 100% / 100% |
| Incorrect abstentions / answerable cases | 0/6 |
| Unsupported abstentions | 2/2 |
| Citation validity | 10/10 |
| Step citation coverage | 10/10 |

Assistant qualitative inspection of all eight outputs (human review remains pending):

| Cases | Findings |
| --- | --- |
| `held-01` | Appropriate offline-client check/restart; summary attributed to ticket. Adds a persistence condition to diagnostic collection that the KB does not require, a small completeness/wording issue. |
| `held-02` | Separates owner approval from post-IT-confirmation testing, preserving the prerequisite. Reason incorrectly describes unknown approval status as lack of approval. |
| `held-03` | Correct target-workstation branch and Endpoint Support route despite VPN alternatives being retrieved; no broad VPN reconnect or third-party reboot. |
| `held-04` | Correct self-service path with available verification; no unnecessary handoff or claim that reset succeeded. |
| `held-05` | Correct service-desk route, rejects manager bypass, keeps no-secret boundary. An explanatory policy statement is typed as a second escalation although it is not itself a handoff; per-ticket flag metrics do not detect that. |
| `held-06` | Appropriate Facilities/IT routing and reported symptom summary. Unnecessary print-catalog question borrows context from a neighboring procedure; both handoffs are bundled. |
| `held-07`–`08` | Correct abstention despite MFA/Wi-Fi neighbors, no fabricated backup-key or cafeteria procedure, explicit undetermined escalation. |

The held-out sample is too small and too close in authorship/domain to development
to establish statistical significance. No baseline held-out run was performed;
its perfect flags do not prove improvement relative to baseline or content-level
perfection. These cases are now inspected and cannot be treated as untouched for
future tuning.

Live usage was bounded to 76 tickets: 12 new-development baseline, 28 v3 development/
regression, 28 v4 development/regression, and eight final held-out. Each used one
query embedding and one recommendation request; SDK retries, if any, are not
counted as additional evaluation cases. No model switching or repeated held-out
sampling was used to select a favorable result.

Final tests: **132 passed**, including all original 117 tests, 15 new offline
checks, and the four existing real-pgvector integration tests. No paid calls occur
in tests. The original 16-case dataset and KB/retrieval/classifier files are unchanged.
The corpus hash matches Phase 2B:
`9cf025aca9693e28583bc25a21b9db5b4a188817cfdcef1a7eb87a0ec6f2aa49`.

Frozen prompt SHA-256:
`8fbaf1fb619b7075dfa872cf675e5c5446ac63e0f979d7a43edfec595da38275`.
Frozen schema SHA-256:
`a73ef1e090b3ca069ad58580f81caec4fed551e8a9b914d532e14719aa3a4f87`.
Dataset hashes and freeze protocol are in `evaluation/recommendation_splits.json`.

Local reports retained: the original Phase 2B report, new-development baseline,
`phase2b1_dev_v3.json`, `phase2b1_regression_v3.json`, final revised reports,
`phase2b1_heldout.json`, and `phase2b1_comparison.json` under ignored `reports/`.
The comparison uses the same aggregation function on saved outputs without making
new model calls or altering those outputs.

## Limitations and readiness

Prompt and schema-description changes remain model guidance. They do not create
deterministic semantic guarantees. Synthetic cases and tiny denominators cannot
establish statistical significance or general helpdesk performance. Few-shot
examples increase context and may bias generation. Human review is still needed,
especially for Security cases and summaries. No tool executes a recommendation.

Phase 3 in `PROJECT_BRIEF.md` is the synthetic company database/tool milestone;
LangGraph is Phase 4. This change does not start either phase. Readiness for design
does not imply readiness for autonomous execution or production use.

It is reasonable to begin a bounded Phase 3 **design** after reviewing this change,
with recommendations remaining advisory and consequential actions requiring human
review. Reliability is not sufficient for unattended execution: incorrect
applicability, invented escalation triggers, and approval/repair overstatements
remain observed failures. Phase 3 implementation requires explicit approval.

Reference: [OpenAI prompt engineering and few-shot examples](https://developers.openai.com/api/docs/guides/prompt-engineering).
