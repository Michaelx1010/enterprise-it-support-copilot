"""Fixed response replays distinguish mechanical checks from manual correctness."""

import json

import httpx
import pytest

from app.providers.openai_synthesis import OpenAISynthesis
from evaluation.investigation_synthesis import ReplayProvider, evaluate, load_cases, summarize


@pytest.mark.parametrize('case', load_cases(), ids=lambda case: case.id)
def test_reviewed_cases_through_mocked_structured_outputs(case, planner_client, planner_response):
    calls = []
    def handler(request):
        calls.append(request)
        if case.candidate is None:
            return httpx.Response(500, json={'error': {'message': 'unavailable'}})
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(case.candidate)))
    result = evaluate(case, OpenAISynthesis(planner_client(handler)))
    assert result['outcome'] == case.expected_replay
    assert len(calls) == 1
    if result['outcome'] == 'accepted':
        assert result['report'] is not None
        # An accepted, manually incorrect fixture exposes the limit of ID checks.
        assert case.manual_verdict in ('acceptable', 'incorrect')
    else:
        assert result['report'] is None


def test_mechanical_metrics_do_not_hide_failures_or_claim_groundedness():
    cases = load_cases()
    results = [evaluate(case, ReplayProvider(case.candidate)) for case in cases]
    metrics = summarize(cases, results)
    assert metrics['cases'] == 11 and metrics['accepted'] == 8
    assert metrics['rejected_or_failed'] == 3
    assert metrics['unsupported_abstentions'] == {'count': 2, 'accepted_cases': 2}
    assert metrics['incorrect_abstentions'] == {'count': 1, 'accepted_answerable_cases': 6}
    assert metrics['escalation_label_matches'] == {'count': 7, 'accepted_cases': 8}
    assert metrics['accepted_citation_validity']['valid'] == metrics['accepted_citation_validity']['total']
    assert sum(c.manual_verdict == 'incorrect' for c in cases) == 4
    assert 'do not measure groundedness' in metrics['manual_review']


def test_evaluation_refuses_missing_results():
    with pytest.raises(ValueError):
        summarize(load_cases(), [])
