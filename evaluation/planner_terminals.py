"""Authored terminal-choice replay, not a measurement of live planner quality."""

import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from app.investigation.graph import run_investigation
from app.investigation.schemas import ClarifyDecision, DocumentationGapDecision, FinishDecision, InvestigationRequest
from app.investigation.scripted import InvestigationScript, script_dependencies
from app.kb.documents import load_chunks
from app.kb.schemas import SearchResult
from app.operations.records import Model
from app.providers.embeddings import EmbeddingSpec
from app.schemas import TicketClassification


class TerminalCase(Model):
    id: str = Field(min_length=1)
    request: InvestigationRequest
    kb_chunk_ids: list[str] = Field(max_length=3)
    decision: FinishDecision | ClarifyDecision | DocumentationGapDecision
    expected_terminal: Literal['finish', 'clarify', 'insufficient_evidence']
    expected_missing_fields: list[str]
    manual_verdict: Literal['correct', 'incorrect']
    review_notes: str = Field(min_length=1)


def load_cases(path: Path = Path('evaluation/planner_terminals.jsonl')) -> list[TerminalCase]:
    cases = [TerminalCase.model_validate_json(line)
             for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not cases or len({c.id for c in cases}) != len(cases):
        raise ValueError('Terminal cases require unique IDs.')
    return cases


def case_script(case: TerminalCase) -> InvestigationScript:
    chunks = {chunk.chunk_id: chunk for chunk in load_chunks(Path('knowledge_base'))}
    # No expected outcomes/review labels enter provider context. Classification,
    # vectors, ranks and decisions are authored fixtures, never model measurements.
    return InvestigationScript(
        request=case.request,
        classification=TicketClassification(category='Software', priority='Medium',
                                            summary=case.request.ticket.subject),
        embedding_spec=EmbeddingSpec(provider='fixture', model='terminal-replay-v1', dimensions=3),
        query_vector=[1., 0., 0.], decisions=[case.decision.model_dump(mode='json')],
        kb_results=[SearchResult(chunk=chunks[key], distance=i / 10)
                    for i, key in enumerate(case.kb_chunk_ids)],
    )


def evaluate(case: TerminalCase) -> dict:
    script = case_script(case)
    result = run_investigation(script.request, dependencies=script_dependencies(script))
    matches = (result.stop_reason == case.expected_terminal
               and result.missing_fields == case.expected_missing_fields)
    return {'id': case.id, 'mechanically_completed': result.status == 'completed',
            'terminal': result.stop_reason, 'missing_fields': result.missing_fields,
            'matches_authored_expectation': matches, 'manual_verdict': case.manual_verdict,
            'review_notes': case.review_notes,
            'planner_decisions': result.planner_decisions, 'lookup_attempts': result.lookup_attempts}


def main() -> None:
    rows = [evaluate(case) for case in load_cases()]
    print(json.dumps({
        'mode': 'deterministic_fixture_replay', 'live_model_quality': 'unmeasured',
        'cases': len(rows), 'mechanically_completed': sum(r['mechanically_completed'] for r in rows),
        'matches_authored_expectation': sum(r['matches_authored_expectation'] for r in rows),
        'accepted_semantic_negative_controls': sum(r['mechanically_completed'] and r['manual_verdict'] == 'incorrect' for r in rows),
        'results': rows,
    }, indent=2))


if __name__ == '__main__':
    main()
