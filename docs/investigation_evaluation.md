# Phase 5A: investigation evaluation, current versus conditional escalation

This increment builds evaluation infrastructure for the reported second live
Phase 4B.2 result. It changes no production prompt, schema, graph, provider,
operational tool, KB document or database record. The reported remaining problem
is premature escalation despite improved claim grounding. The raw second-run
artifact was not supplied here; there is no independently rescored live output.

## Reproducible controlled comparison

```powershell
uv run --locked python -m evaluation.investigation_e2e
```

This command runs 12 paired scenarios entirely offline and prints JSON. It has
no live switch, OpenAI client, database connection or credential loading. The
implementation run is also saved locally under ignored
`reports/investigation_e2e_replay.json`; that generated report is not source data.

| File | Purpose |
| --- | --- |
| `evaluation/investigation_e2e.jsonl` | Fictional tickets, explicit scope, selected existing chunks, operational fixtures, scripted decisions/responses, labels and review notes |
| `evaluation/investigation_e2e_manifest.json` | Frozen dataset, KB and committed operational seed hashes; fixed fixture observation-query time |
| `evaluation/investigation_e2e.py` | Existing workflow orchestration, paired scoring and pending manual review worksheets |
| `tests/investigation/test_e2e_evaluation.py` | Replay integrity, negative controls, denominators, failures, scope and reproducibility tests |

Inputs are inspected development fixtures, not a held-out benchmark. The manifest
rejects dataset/KB/seed drift before and after a run. Results record prompt versions
and application/evaluator source hashes. Text hashes normalize checkout line
endings to LF. Review labels before deliberately updating any
frozen input hash. Fixed query time is `2026-10-23T08:00:00Z`; record observation,
update and last-seen times remain those of the existing seed. Graph run timestamps
vary between executions; inputs, decisions, evidence and mechanical scores are
reproducible. Query time is not a claim of live observation.

The agent arm runs the actual LangGraph workflow, classifier entry point, retrieval
entry point, scope/argument/budget guards, observation validation, synthesis
validation and result assembly. It injects the existing scripted classifier,
embedder, ranked-result store and lookup replay adapters. Classification is a fixed
fixture and is not scored. Retrieved distances are zero placeholders, not measured
similarities. This exercises application control flow end to end; it does **not**
measure semantic retrieval, real SQL execution or model reasoning.

The standalone arm calls the existing Phase 2B `recommend` pipeline with the same
ticket, identical selected KB chunks/order and a separately authored response.
It receives no operational observations. No agent conclusion is copied into its
input. Existing recommendation aggregation supplies escalation and abstention
metrics, and the planner-efficiency evaluator supplies required-evidence coverage.
Neither response is generated from evaluation labels at run time.

The operational fixture results are projections of the committed Phase 3 seed;
tests compare their record fields against those source records. They are not
new operational records or claims about the current application database. The
set uses account, device-list, device-detail and service-incident lookups; it is
not coverage of every tool or every support category.

## Scenarios and expectations

| Case | Investigation and expected current behavior |
| --- | --- |
| `vpn-confirmed` | Repeated Corporate gateway error after reconnect; inspect account/device/VPN incident, then documented handoff is justified |
| `vpn-future-condition` | First failure, no retry; inspect the same evidence, give a current diagnostic, leave the future handoff unrequired |
| `account-confirmed` | Several applications reject credentials; account/identity incident evidence complements the ticket's documented Identity Support route |
| `lost-authenticator` | Lost registered phone; account snapshot cannot replace identity verification; documented service-desk recovery is justified |
| `irrelevant-incident` | Browser email works but desktop sync fails; VPN incident is allowed by explicit scope but unnecessary and not a cause |
| `stale-vpn-snapshot` | Old investigating-status VPN incident; current status and connection to this user remain unverified |
| `missing-account-record` | Existing EMP-010 has no account row; ticket still establishes the multi-application handoff; missing data is not a diagnosis |
| `unsupported-procedure` | Cafeteria transaction restoration with software-installation KB neighbors; abstain and ask for applicable documentation |
| `empty-retrieval` | VPN ticket with deliberately empty KB results; abstain even after account lookup; whole corpus remains answerable |
| `redundant-device-detail` | Detail lookup repeats the listed device while requested VPN incident evidence is omitted; detect both waste and coverage loss |
| `clarify-unknown-system` | Unknown Q17 without an application/symptom; clarify instead of inventing an application-crash branch |
| `disabled-but-ambiguous` | Historical disabled-account snapshot plus one unidentified client failure; multi-application KB trigger is not established |

Required lookups are per-case annotations, not a production policy requiring all
tools. Redundancy depends on prior evidence, matching arguments and the case's
information need. A device detail call is not globally redundant: a different
task could need it. Likewise an explicitly allowed service can be irrelevant to
the reported symptom. Scope permission alone does not establish usefulness.

## Separate criteria

| Dimension | Mechanical assessment | Manual assessment |
| --- | --- | --- |
| Planner evidence coverage | Validated observations matching expected tool and arguments / expected observations; zero-target cases return N/A | Whether expected evidence was sufficient and useful; reasonable alternative investigation paths |
| Investigation efficiency | Case-labelled redundant-after pairs, unnecessary lookups, duplicate proposals, blocked/failed outcomes and decision/attempt counts | Marginal information gained, omission cost and premature finish; do not reward every extra call |
| Claim grounding | Typed source-ID validation remains in the application; worksheet retains source text and references | Split compound statements into atomic claims; check each against the exact source, subject and time; attribute ticket reports and distinguish inference |
| Snapshot freshness | Source timestamps and `live_verified=false` preserved | Qualify each state claim locally; never substitute query time or old enabled/MFA flags for current diagnostic results; no arbitrary age threshold |
| Recommendation applicability | Step citation membership/coverage and status/step consistency | KB actually authorizes the action for established symptoms; preserve negative facts, branch conditions, identity checks and approvals |
| Escalation | TP/TN/FP/FN against case labels; precision, recall, false-negative IDs and premature-escalation IDs | Trigger established now, not merely present as an if-clause in KB; inspect hidden conditional handoffs in all fields, even with a false flag |
| Abstention/missing information | Accepted abstentions on evidence-unanswerable cases and incorrect abstentions on evidence-answerable cases | Is missing information targeted, non-secret and sufficient to resolve the uncertainty? Does an established handoff remain possible despite missing submission details? |

Every report includes a pending review worksheet for summary, findings,
uncertainties, steps and escalation reason (standalone has fewer fields). It does
not auto-grade free text, split claims by keywords or use an LLM judge. Reviewers
record atomic claims and mark entailment as supported/contradicted/unsupported/
not assessable, freshness as qualified/unqualified/not applicable, applicability
and trigger sufficiency separately. Record missing-information sufficiency,
hidden future handoffs and paired usefulness with reviewer identity. A blank
review is pending, never a pass. No aggregate groundedness score is claimed yet.

Abstention labels distinguish the supplied controlled evidence from whole-corpus
answerability. In `empty-retrieval`, abstention is appropriate for generation but
the evidence supply failed; do not hide it as a successful answer to the ticket.
For future live runs, record both corpus and actual-retrieval labels and review
missed relevant chunks separately.

Final label review corrected whole-corpus answerability to false for
`clarify-unknown-system` and `disabled-but-ambiguous`: missing symptom/trigger
details prevent a supported action even with the full KB. The dataset hash was
deliberately refreshed. Controlled-evidence labels and replay scores are unchanged;
`empty-retrieval` remains the explicit answerable-corpus retrieval-miss case.

Rejected/failed recommendations have no accepted recommendation and never count
as successful abstentions. Precision/recall use accepted outputs; recall over all
positive attempts additionally includes failures in its denominator. Zero
denominators produce null. Workflow completed/partial/failed counts and stop
reasons are separate: a structurally accepted report does not make a partial
investigation complete or semantically correct. The common paired citation metric
counts step KB citations only; it is not a score for all agent claims.

## Replay findings

The authored controls produce:

- Evidence coverage **16/17**; **one redundant** device-detail lookup and **one
  unnecessary** VPN incident lookup.
- Agent escalation **TP=4, TN=7, FP=1, FN=0**, precision **80%**, recall **100%**.
  The intentional premature escalation is `vpn-future-condition`.
- Standalone escalation **TP=4, TN=8, FP=0, FN=0**. This difference is authored
  to validate the paired scorer; it is **not evidence that standalone is better**.
- Both arms abstain on **4/4** evidence-unanswerable cases, with **0/8** incorrect
  abstentions on answerable cases. All 12 workflows complete; all responses pass
  structure/citation checks. Failure accounting is exercised separately in tests.
- `stale-vpn-snapshot` deliberately contains a false current-cause claim with a
  real observation ID. It is accepted mechanically and requires manual rejection.
  All 12 formal manual reviews remain pending; fixture-author notes are not an
  independent blind review.

These results test evaluator sensitivity to known problems. They do not establish
quality, improvement from prompt v1 to v2, statistical significance or reliable
abstention in a live model. No paid calls were run.

## Output-contract review: proposal only

The current `escalation_required` flag correctly describes a current handoff by
convention and is structurally consistent with escalation-typed steps and a
reason. It cannot distinguish an instruction such as "contact support if errors
persist" from a current handoff. Free-text uncertainties currently carry future
conditions, so conditional guidance has no explicit, separately testable home.
Adding more boolean consistency rules cannot establish that a trigger occurred.

Recommended minimal follow-up, **not implemented**:

1. Keep `steps` for currently applicable actions and retain the existing
   flag/step/reason invariants. Add a separate `conditional_guidance` collection
   with documented condition, possible future action, KB citations, and missing
   trigger evidence. Entries are explicitly advisory future policy context and
   never contribute to `escalation_required`.
2. For current escalation steps, consider a typed `trigger_basis` containing the
   KB condition and ticket/observation references claimed to satisfy it. Require
   well-formed source membership and KB support structurally, while documenting
   that the model's trigger assertion remains subject to semantic review.
3. Preserve `insufficient_evidence` when no current action is supported, even if
   future policy guidance exists. A false flag remains undetermined on abstention.
   Do not force conditional text into an escalation step just to preserve it.

This would change only the investigation response schema/provider prompt after
approval, with explicit compatibility tests. Keep standalone Phase 2B unchanged;
compare current actions and escalation labels across arms, and review future
guidance separately. Do not add a keyword filter, weaken citation validation,
infer a real-world trigger from a model-declared state, or add autonomous actions.

## Proposed next evaluation steps

First review these scenario labels and the proposed contract separation. Next,
with separate paid-call approval, freeze current prompts/models/budgets and run
both arms on the same tickets and the same retrieved KB chunks. Only the agent
gets operational observations. Use the restricted readers, record actual evidence,
trace, timing, provider settings, errors and data snapshots, and never reseed.
Keep retrieval quality evaluation separate from the generation comparison. An
optional second comparison with naturally independent retrieval should be labelled
as such, since retrieval differences then confound generation quality.

Have a reviewer assess claims and handoff conditions without seeing arm labels
where feasible. Review repeated cases rather than selecting a favorable sample;
agree on repetition/cost limits before any calls. Compare proposed contract changes
only after recording the baseline. Add unseen scenario families before claiming
generalization; the inspected development cases cannot be called held-out.

Exit criteria for a further implementation review: no scope/write regression,
preserved failure/evidence semantics, mechanical metrics with failure denominators,
all current/future handoffs manually checked, no unsupported live-state claims in
the reviewed sample, and documented unresolved failures. These are review gates,
not statistical guarantees of production reliability.

Validation: **553 tests passed**, preserving all 529 previous tests and adding 24
offline evaluation checks. This includes **69 PostgreSQL integration tests** and
484 offline tests. Before/after application snapshots matched for all **79
operational records** and **36 KB chunks, including vectors/metadata**; temporary
test reader roles remaining: **0**. No production application files changed.
No paid API calls, commits or pushes are part of this evaluation increment.
