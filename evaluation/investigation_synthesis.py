"""Offline response replay, not a live-model quality score or an LLM judge."""

import json
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from app.investigation.schemas import InvestigationSynthesis
from app.investigation.synthesis_draft import InvestigationSynthesisDraftV3
from app.investigation.synthesis import generate_synthesis
from app.operations.records import Model
from app.providers.synthesis import SynthesisError, SynthesisProvider


class SynthesisCase(Model):
    id: str
    ticket: str
    kb: dict[str, str]
    observations: dict[str, str]
    candidate: dict | None
    expected_status: Literal['supported', 'insufficient_evidence']
    expected_escalation: bool
    expected_replay: Literal['accepted', 'invalid_output', 'invalid_citation', 'provider_failure']
    manual_verdict: Literal['acceptable', 'incorrect', 'not_reviewable']
    review_notes: str


def load_cases(path: Path = Path('evaluation/investigation_synthesis.jsonl')) -> list[SynthesisCase]:
    cases = [SynthesisCase.model_validate_json(line)
             for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not cases or len({case.id for case in cases}) != len(cases):
        raise ValueError('Cases must be nonempty and have unique IDs.')
    return cases


class ReplayProvider:
    def __init__(self, candidate: dict | None, *, draft_v3: bool = False):
        self.candidate = candidate
        self.draft_v3 = draft_v3

    def generate(self, *, instructions: str, payload: str) -> InvestigationSynthesis:
        if self.candidate is None:
            raise SynthesisError('provider_failure')
        try:
            if self.draft_v3:
                return InvestigationSynthesisDraftV3.model_validate(self.candidate).to_canonical()
            return InvestigationSynthesis.model_validate(self.candidate)
        except ValidationError:
            raise SynthesisError('invalid_output') from None


def evaluate(case: SynthesisCase, provider: SynthesisProvider) -> dict:
    # Compact evaluation sources are fictional, not application database records.
    payload = json.dumps({'investigation_context': {'incomplete': False},
        'untrusted_evidence': {'ticket': case.ticket, 'kb_procedures': case.kb,
                               'operational_observations': case.observations}})
    try:
        report = generate_synthesis(payload, kb_ids=set(case.kb), lookup_ids=set(case.observations),
                                    # Compact authored observations represent successful snapshots.
                                    # Failed/not_found tool outcomes are tested through the real graph.
                                    trigger_lookup_ids=set(case.observations),
                                    provider=provider)
    except SynthesisError as exc:
        return {'id': case.id, 'outcome': exc.code, 'report': None}
    return {'id': case.id, 'outcome': 'accepted', 'report': report.model_dump(mode='json')}


def summarize(cases: list[SynthesisCase], results: list[dict]) -> dict:
    by_id = {result['id']: result for result in results}
    if len(by_id) != len(results) or set(by_id) != {case.id for case in cases}:
        raise ValueError('Each evaluation case requires exactly one result.')
    accepted = [case for case in cases if by_id[case.id]['outcome'] == 'accepted']
    unsupported = [case for case in accepted if case.expected_status == 'insufficient_evidence']
    answerable = [case for case in accepted if case.expected_status == 'supported']
    # Only validated reports contribute citation metrics; failures are counted separately.
    # These are ID-membership/coverage checks, NEVER entailment or correctness scores.
    references = items = 0
    for case in accepted:
        report = InvestigationSynthesis.model_validate(by_id[case.id]['report'])
        items += len(report.cited_items())
        references += sum(len(item.references) for item in report.cited_items())
    return {
        'cases': len(cases), 'accepted': len(accepted),
        'rejected_or_failed': len(cases) - len(accepted),
        'accepted_citation_validity': {'valid': references, 'total': references},
        'accepted_citation_coverage': {'cited_items': items, 'total_items': items},
        'unsupported_abstentions': {'count': sum(by_id[c.id]['report']['status'] == 'insufficient_evidence' for c in unsupported), 'accepted_cases': len(unsupported)},
        'incorrect_abstentions': {'count': sum(by_id[c.id]['report']['status'] == 'insufficient_evidence' for c in answerable), 'accepted_answerable_cases': len(answerable)},
        'escalation_label_matches': {'count': sum(by_id[c.id]['report']['escalation_required'] == c.expected_escalation for c in accepted), 'accepted_cases': len(accepted)},
        'manual_review': 'Use case rubrics; automated ID checks do not measure groundedness or applicability.',
    }


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Offline synthesis response replay; never calls a model.')
    parser.add_argument('--cases', type=Path, default=Path('evaluation/investigation_synthesis.jsonl'))
    parser.add_argument('--draft-v3', action='store_true', help='Explicit V3 draft replay; no legacy fallback or model call.')
    args = parser.parse_args()
    cases = load_cases(args.cases)
    results = [evaluate(case, ReplayProvider(case.candidate, draft_v3=args.draft_v3)) for case in cases]
    print(json.dumps({'mode': 'offline_response_replay', 'metrics': summarize(cases, results),
                      'authored_controls': {
                          'source': 'fixture labels, not measured live-model quality',
                          **{label: sum(c.manual_verdict == label for c in cases)
                             for label in ('acceptable', 'incorrect', 'not_reviewable')},
                      },
                      'outcomes': [{'id': r['id'], 'outcome': r['outcome'],
                                    'authored_manual_verdict': c.manual_verdict}
                                   for c, r in zip(cases, results, strict=True)]}, indent=2))
