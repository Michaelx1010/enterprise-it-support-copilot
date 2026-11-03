# Evaluation results and limitations

[Portfolio overview](../README.md) · [Documentation map](README.md)

This summary separates historical live observations, offline contract checks and
unmeasured current live performance. The pilot figures and preliminary AI-assisted
review findings below come from the project owner's Phase 5C.5 `pilot-002` summary,
supplied for this presentation milestone. Independent human-review worksheets
remain pending. Original reports and manual worksheets remain unchanged in ignored
local storage; they are not published or recomputed here. The tracked protocol
provides configuration provenance, not a substitute for those result artifacts.

## Historical live comparison

The frozen application candidate was
`495b24a8f1410f2a88e402474721b16121b134be`, using synthesis Draft V3,
`investigation-planner-v4` and `investigation-synthesis-v6`. The
[protocol](../evaluation/phase5c5_protocol.json) records the exact configuration:
generation used `gpt-4.1-mini-2025-04-14`; embeddings used
`text-embedding-3-small`. See the [readiness record](phase5c5-readiness.md) for
limits, provenance and the accounting caveats.

There were **eight predeclared paired attempts**, two each for
`vpn-future-condition`, `vpn-confirmed`, `irrelevant-incident` and
`unsupported-procedure`. Within each pair both arms received identical ticket
inputs and retrieved KB evidence. Only the agent could inspect operational data.
This compares different capabilities and request budgets, not a cost-matched
ablation or a held-out benchmark.

| Measure | Agent | Standalone RAG |
| --- | --- | --- |
| Structurally delivered reports / all planned pairs | **5/8**, including two deterministic clarification reports | **8/8** |
| Model synthesis accepted / supported attempts | **3/6** | Different recommendation contract; no agent-synthesis score assigned |
| Required operational evidence observations / expected observations | **14/14** | Not applicable |

The other three agent syntheses were SDK parsing rejections with
`status_steps_mismatch`. The rejected raw responses were not retained, so the
precise contradictions are unknown. A rejected recommendation is unavailable for
semantic assessment; it must not count as a correct negative escalation or a
successful abstention. Evidence coverage is an observation count, not an answer
quality score.

Preliminary AI-assisted review flagged **two irrelevant clarifications** on the
documentation-gap attempts and **one missed current handoff out of two
confirmed-escalation attempts**. These findings await independent human review;
the two deterministic reports in the delivery numerator must not be treated as
evidence of useful documentation-gap handling. No aggregate semantic pass rate,
escalation precision or statistical reliability claim is inferred here.

The earlier `pilot-001` stopped after a transport failure. Its failed and
not-started slots remain preserved separately; they are not model-quality evidence
and are not silently substituted into or removed from the pilot-002 denominator.
The original Phase 5B attempts likewise retain their own historical denominators.

## Current implementation is not a new live result

The subsequent implementation uses **InvestigationSynthesisDraftV4**, planner
prompt **v5** and synthesis prompt **v8**. V4 removes model-authored status and
derives canonical status from the existing current-step list. Escalation still
derives from current escalation-typed steps; conditional future guidance remains
separate. Canonical validation remains authoritative, without step repair or retries.
Focused instructions address relevant clarification, established escalation
conditions and KB-authorized future guidance.

These changes have offline verification but **no new live paired evaluation**.
An answerable request with zero current steps can still be an incorrect abstention.
Fixture acceptance does not show that the model will choose the right steps or
citations. The current agent is not claimed to outperform standalone RAG.

## Previously recorded verification

| Record | Result | Scope and source |
| --- | --- | --- |
| Backend full-suite baseline | **1,057 passed**, including 82 PostgreSQL integration tests and 21 schema parity checks | [Draft V4 checkpoint](phase5c.md#post-pilot-reliability-checkpoint-derived-synthesis-status-2026-11-01) |
| Later focused semantic guidance | **184 targeted passes in aggregate**, including nine authored development cases and 21 schema parity checks | [Prompt refinement record](phase5c.md#focused-semantic-guidance-improvement-2026-11-02) |
| Streamlit MVP finalization | **17 focused passes in aggregate** | [Demo verification](demo.md#focused-verification), plus recorded browser review |

These overlapping results are not summed. They were previously run and are reused
for this documentation-only milestone. No backend suite, database fingerprinting
or paid model evaluation was repeated to prepare the portfolio.

## How to interpret the evaluation

Mechanical checks cover schema acceptance, reference validity and coverage,
expected lookup coverage, redundant lookups, abstention labels and current
escalation labels. Future guidance is not a current handoff. Missing or rejected
outputs stay visible in denominators and are unassessable where appropriate.

Human review separately assesses claim entailment, source attribution, snapshot
freshness, procedural applicability, completed-action repetition, escalation
justification and summary usefulness. Valid reference IDs do not establish that
the evidence supports a claim. Manual worksheet fields remain pending until a
reviewer grades them; structural success never fills in a semantic pass.

For details, see [Phase 5A replay methodology](investigation_evaluation.md), the
[paired live runner](phase5b.md) and the [Phase 5C checkpoint record](phase5c.md).
The tracked [Phase 5B baseline verifier](../evaluation/phase5b_baseline.py) and
[checksum manifest](../evaluation/phase5b_baseline_manifest.json) require the
locally archived historical reports described there. Frozen inputs and original
reports were not changed for this presentation.

The small fictional corpus, authored development cases, repeated scenario types
and unequal operational capabilities limit generalization. Measuring the revised
candidate requires separately approved live runs and manual semantic review;
passing software tests alone is not that measurement.
