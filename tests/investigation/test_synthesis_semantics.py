"""Smoke-test-derived semantic review fixtures, not an automated entailment judge."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.investigation.graph import run_investigation
from app.investigation.schemas import InvestigationSynthesis
from app.investigation.scripted import ReplayStore
from app.investigation.synthesis import INSTRUCTIONS, PROMPT_VERSION
from app.kb.documents import load_chunks
from app.kb.schemas import SearchResult
from app.providers.openai_planner import OpenAIPlanner
from app.providers.openai_synthesis import OpenAISynthesis
from evaluation.investigation_synthesis import ReplayProvider, evaluate, load_cases, summarize

CASES = load_cases(Path('evaluation/investigation_synthesis_semantics.jsonl'))


@pytest.mark.parametrize('case', CASES, ids=lambda case: case.id)
def test_smoke_error_and_grounded_contrast_replays(case, planner_client, planner_response, as_synthesis_draft):
    calls = []
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body['input'][0]['content'] == INSTRUCTIONS
        assert json.loads(body['input'][1]['content'])['untrusted_evidence']['operational_observations'] == case.observations
        schema = body['text']['format']['schema']
        assert 'establish' in schema['properties']['escalation_reason']['description']
        assert 'installed versions' in schema['properties']['findings']['description']
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(as_synthesis_draft(case.candidate))))
    result = evaluate(case, OpenAISynthesis(planner_client(handler)))
    assert len(calls) == 1 and result['outcome'] == case.expected_replay == 'accepted'
    assert result['report'] == case.candidate | {'conditional_guidance': []}
    # Incorrect fixtures intentionally remain accepted: IDs/types cannot prove entailment.
    assert case.manual_verdict in ('acceptable', 'incorrect')


def test_contrasts_keep_evidence_identical_and_metrics_separate():
    by_id = {case.id: case for case in CASES}
    for topic in ('authentication', 'version', 'tunnel', 'incident', 'escalation'):
        bad, good = [by_id[topic + suffix] for suffix in ('-unsupported', '-grounded')]
        assert (bad.ticket, bad.kb, bad.observations) == (good.ticket, good.kb, good.observations)
        assert bad.manual_verdict == 'incorrect' and good.manual_verdict == 'acceptable'
    results = [evaluate(case, ReplayProvider(case.candidate)) for case in CASES]
    metrics = summarize(CASES, results)
    assert metrics['accepted'] == 14 and metrics['rejected_or_failed'] == 0
    assert sum(case.manual_verdict == 'incorrect' for case in CASES) == 5
    assert metrics['escalation_label_matches'] == {'count': 13, 'accepted_cases': 14}
    assert metrics['unsupported_abstentions'] == {'count': 1, 'accepted_cases': 1}
    assert metrics['incorrect_abstentions'] == {'count': 0, 'accepted_answerable_cases': 13}


@pytest.mark.parametrize('case_id', ['escalation-grounded', 'established-escalation', 'unknown-trigger-abstention'])
def test_current_and_future_handoffs_preserve_escalation_invariants(case_id):
    case = next(case for case in CASES if case.id == case_id)
    report = InvestigationSynthesis.model_validate(case.candidate)
    assert report.escalation_required == case.expected_escalation
    assert report.status == case.expected_status
    assert report.escalation_required == any(step.step_type == 'escalation' for step in report.steps)
    assert report.escalation_required == (report.escalation_reason is not None)
    inconsistent = deepcopy(case.candidate)
    inconsistent['escalation_required'] = not report.escalation_required
    with pytest.raises(ValidationError):
        InvestigationSynthesis.model_validate(inconsistent)


def test_three_lookups_then_synthesis_preserves_observations_and_budgets(
        inv_request, inv_dependencies, planner_client, planner_response, as_synthesis_draft):
    # Reconstruct the smoke-test workflow with mocked decisions and an authored report.
    decisions = [
        {'kind': 'lookup', 'tool': 'get_employee_account_status', 'arguments': {'employee_id': 'EMP-001'}},
        {'kind': 'lookup', 'tool': 'get_employee_devices', 'arguments': {'employee_id': 'EMP-001'}},
        {'kind': 'lookup', 'tool': 'get_active_service_incidents', 'arguments': {'service_id': 'SVC-001', 'limit': 5}},
        {'kind': 'finish'},
    ]
    chunks = [SearchResult(chunk=chunk, distance=0.1) for chunk in load_chunks(Path('knowledge_base'))
              if chunk.source_path.endswith('vpn-access.md')][:3]
    assert chunks
    planner_calls, synthesis_payloads = [], []
    def handler(request):
        body = json.loads(request.content)
        payload = json.loads(body['input'][1]['content'])
        if body['text']['format']['name'] == 'PlannerResponse':
            choice = decisions[len(planner_calls)]
            planner_calls.append(payload)
            return httpx.Response(200, json=planner_response(choice))
        synthesis_payloads.append(payload)
        assert payload['prompt_version'] == PROMPT_VERSION == 'investigation-synthesis-v4'
        assert body['input'][0]['content'] == INSTRUCTIONS
        report = deepcopy(next(c.candidate for c in CASES if c.id == 'escalation-grounded'))
        # Preserve real fixture timestamps in prose rather than copying the compact eval dates.
        report['uncertainties'][0] = {'text': 'Recorded operational snapshots are not verified live state.',
                                     'references': [{'kind': 'investigation_context'}]}
        for item in [report['summary'], *report['steps'], *report['uncertainties']]:
            for ref in item['references']:
                if ref['kind'] == 'kb_chunk': ref['chunk_id'] = chunks[0].chunk.chunk_id
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(as_synthesis_draft(report))))
    client = planner_client(handler)
    result = run_investigation(inv_request, dependencies=replace(inv_dependencies,
        store=ReplayStore(inv_dependencies.store.spec, chunks), planner=OpenAIPlanner(client),
        synthesis=OpenAISynthesis(client), phase='4B.1'))
    assert result.status == 'completed' and result.synthesis_status == 'completed'
    assert result.planner_decisions == len(planner_calls) == 4
    assert result.lookup_attempts == 3 and result.synthesis_attempts == len(synthesis_payloads) == 1
    assert result.recommendation.escalation_required is False
    assert not result.mutating_actions_executed and result.human_review_required
    sent = synthesis_payloads[0]['untrusted_evidence']
    assert sent['operational_observations'] == [e.model_dump(mode='json') for e in result.operational_evidence]
    assert sent['kb_procedures'] == [e.model_dump(mode='json') for e in result.kb_evidence]
    assert [e.observation.tool for e in result.operational_evidence] == [d['tool'] for d in decisions[:3]]
