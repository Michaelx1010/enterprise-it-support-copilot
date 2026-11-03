# Documentation map

[Portfolio overview](../README.md) · [Run the demo](demo.md) ·
[Evaluation summary](portfolio-evaluation.md)

The current application uses PlannerResponseV2 with planner prompt v5 and
InvestigationSynthesisDraftV4 with synthesis prompt v8. It includes a local
Streamlit interface and keeps standalone RAG available independently.

| Area | Start here | What to look for |
| --- | --- | --- |
| Demonstration | [Local demo](demo.md) | No-cost examples, explicit paid opt-in, evidence display and limitations |
| Architecture | [Investigation graph](phase4.md), [live planner](phase4b1.md), [synthesis](phase4b2.md) | Bounded loop, scope guards, error preservation and provider boundaries |
| Retrieval | [KB retrieval](phase2a.md) | Markdown chunks, embeddings, pgvector, transactional ingestion and retrieval metrics |
| Standalone RAG | [Recommendations](phase2b.md), [reliability review](phase2b1.md) | Cited steps, abstention and mechanical versus manual evaluation |
| Operational data | [Read-only tools](phase3.md) | Synthetic schema, restricted roles, six tool contracts and snapshot timestamps |
| Current contracts | [Reliability checkpoints](phase5c.md#post-pilot-reliability-checkpoint-derived-synthesis-status-2026-11-01) | Draft V4 compatibility and the later focused prompt changes |
| Evaluation | [Portfolio results](portfolio-evaluation.md), [fixture methodology](investigation_evaluation.md), [paired runner](phase5b.md) | Historical measured results, replay controls, denominators and manual review |
| Command line | [CLI reference](cli.md) | Dataset exploration, classification, RAG and investigation entry points |

## Reading the engineering history

The phase guides preserve decisions and verification at successive checkpoints.
Their older prompt versions, test counts and statements about future work describe
that point in development. Use the portfolio overview and the final sections of
[Phase 5C](phase5c.md) for the current implementation; do not treat earlier counts
as additional tests or historical proposals as implemented features.

The [Phase 5C.5 readiness record](phase5c5-readiness.md) and
[frozen protocol](../evaluation/phase5c5_protocol.json) belong to the earlier V3
candidate. The historical controller intentionally rejects a changed application;
it is not a ready-to-run evaluation protocol for the current V4 implementation.
Original pilot outputs, worksheets and archives remain local and ignored by Git.
Historical verification procedures need those archived files and are not expected
to work from a fresh clone alone.

[PROJECT_BRIEF.md](../PROJECT_BRIEF.md) is the original incremental roadmap.
Its later API/deployment ideas are not claims about features shipped in this repo.
