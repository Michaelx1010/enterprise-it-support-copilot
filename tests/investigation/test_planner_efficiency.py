"""Offline labelled decision comparisons; mocked HTTP is not a model-quality eval."""

from copy import deepcopy
from dataclasses import replace
import json

import httpx
import pytest

from app.investigation.graph import run_investigation
from app.investigation.scripted import ScriptedClassifier, ScriptedEmbedder
from app.providers.openai_planner import OpenAIPlanner
from app.rag.recommendation import build_query
from app.schemas import TicketClassification
from evaluation.planner_efficiency import evidence_coverage, load_cases, rate_choice


CASES = load_cases()
COMPARISONS = [(case, candidate) for case in CASES for candidate in case.candidates]


@pytest.fixture
def compare(inv_dependencies, inv_results, planner_client, planner_response):
    def run(case, candidate):
        decisions = [d.model_dump(mode='json') for d in case.prior_lookups]
        decisions.append(candidate.decision.model_dump(mode='json'))
        if candidate.decision.kind == 'lookup' and len(decisions) < 4:
            decisions.append({'kind': 'finish'})
        requests = []

        def handler(request):
            body = json.loads(request.content)
            requests.append(json.loads(body['input'][1]['content']))
            return httpx.Response(200, json=planner_response(decisions[len(requests) - 1]))

        def fixture_lookup(tool, arguments):
            result = deepcopy(inv_results[tool])
            if tool == 'get_device_details':
                result['queried_at'] = '2026-10-22T08:00:00Z'
                if case.id == 'specific_record_recheck':
                    result['device']['os_version'] = 'corrected-fixture-version'
                    result['device']['updated_at'] = '2026-10-22T07:00:00Z'
            if tool == 'get_active_service_incidents' and arguments.service_id == 'SVC-002':
                result['service']['service_id'] = 'SVC-002'
                result['service']['name'] = 'Fictional second service'
                result['incidents'] = []
            return result

        deps = replace(
            inv_dependencies, phase='4B.1', fixture_lookup=fixture_lookup,
            classifier=ScriptedClassifier(TicketClassification(
                category='Network', priority='Medium', summary=case.request.ticket.subject)),
            embedder=ScriptedEmbedder(build_query(case.request.ticket), inv_dependencies.embedder.spec, [1., 0., 0.]),
            planner=OpenAIPlanner(planner_client(handler)))
        result = run_investigation(case.request, dependencies=deps)
        return result, requests
    return run


@pytest.mark.parametrize('case,candidate', COMPARISONS,
                         ids=[f'{case.id}-{candidate.rating}' for case, candidate in COMPARISONS])
def test_labelled_choices_use_real_graph_and_mocked_sdk(compare, case, candidate):
    result, requests = compare(case, candidate)
    payload = requests[len(case.prior_lookups)]
    assert payload['prompt_version'] == 'investigation-planner-v3'
    assert payload['control']['remaining_decisions'] == 4 - len(case.prior_lookups)
    assert len(payload['untrusted_evidence']['operational_observations']) == len(case.prior_lookups)
    assert payload['control']['service_ids'] == case.request.service_ids
    assert payload['untrusted_evidence']['ticket'] == case.request.ticket.model_dump()
    assert 'candidates' not in payload and 'required_evidence' not in payload
    assert 'review_notes' not in payload  # Answer labels are never planner input.
    assert rate_choice(case, candidate.decision.model_dump(mode='json')) == candidate.rating
    assert len(requests) <= 4 and result.human_review_required and not result.mutating_actions_executed
    assert result.recommendation is None and result.synthesis_status == 'not_run'
    if candidate.rating == 'budget_risk':
        assert result.status == 'partial' and result.stop_reason == 'decision_budget'
    elif case.id == 'second_service_gap' and candidate.rating == 'redundant':
        assert result.status == 'partial' and result.stop_reason == 'duplicate_lookup'
        assert result.lookup_attempts == 1  # Existing guard remains authoritative.
    else:
        assert result.status == 'completed' and result.errors == []
    if candidate.rating == 'preferred':
        expected = 2 / 3 if case.id == 'terminal_budget' else 1.0
        assert evidence_coverage(case, result)['ratio'] == expected


def test_smoke_comparison_exposes_coverage_loss_without_treating_it_as_policy_failure(compare):
    case = next(c for c in CASES if c.id == 'vpn_service_gap')
    scores = {}
    for candidate in case.candidates:
        result, _ = compare(case, candidate)
        assert result.status == 'completed' and result.errors == []
        scores[candidate.rating] = evidence_coverage(case, result)
        if candidate.rating == 'redundant':
            listing = result.operational_evidence[1].observation.result
            details = result.operational_evidence[2].observation.result
            assert details.device == listing.devices[0] and details.owner == listing.employee
            assert details.queried_at != listing.queried_at
            assert not details.live_verified
    assert scores['preferred'] == {'covered': 3, 'expected': 3, 'ratio': 1.0}
    for rating in ('redundant', 'unnecessary', 'premature_finish'):
        assert scores[rating] == {'covered': 2, 'expected': 3, 'ratio': 2 / 3}


def test_device_details_remain_usable_for_specific_record_change(compare):
    case = next(c for c in CASES if c.id == 'specific_record_recheck')
    result, _ = compare(case, case.candidates[0])
    listing = result.operational_evidence[0].observation.result
    details = result.operational_evidence[1].observation.result
    assert details.device.os_version != listing.devices[0].os_version
    assert result.status == 'completed' and result.lookup_attempts == 2
    assert not details.live_verified


def test_rating_depends_on_context_and_includes_tool_arguments():
    cases = {case.id: case for case in CASES}
    detail = {'kind': 'lookup', 'tool': 'get_device_details', 'arguments': {'device_id': 'DEV-001'}}
    assert rate_choice(cases['vpn_service_gap'], detail) == 'redundant'
    assert rate_choice(cases['specific_record_recheck'], detail) == 'preferred'
    incident = {'kind': 'lookup', 'tool': 'get_active_service_incidents',
                'arguments': {'service_id': 'SVC-001', 'limit': 5}}
    assert rate_choice(cases['vpn_service_gap'], incident) == 'preferred'
    assert rate_choice(cases['inventory_complete'], incident) == 'unnecessary'
    assert rate_choice(cases['second_service_gap'], incident) == 'redundant'
    incident['arguments']['service_id'] = 'SVC-002'
    assert rate_choice(cases['second_service_gap'], incident) == 'preferred'
    incident['arguments']['service_id'] = 'SVC-003'
    assert rate_choice(cases['second_service_gap'], incident) == 'unreviewed'


def test_coverage_requires_validated_evidence_not_just_an_attempt(compare):
    case = next(c for c in CASES if c.id == 'vpn_service_gap')
    result, _ = compare(case, case.candidates[0])
    # Simulate a failed service read using a valid result/trace contract.
    data = result.model_dump()
    data['operational_evidence'] = data['operational_evidence'][:2]
    data['lookup_trace'][2].update(status='error', evidence=None, code='lookup_failed')
    data.update(status='partial', stop_reason='lookup_failed', errors=[{'stage': 'lookup', 'code': 'lookup_failed'}])
    failed = type(result).model_validate(data)
    assert evidence_coverage(case, failed)['ratio'] == 2 / 3


@pytest.mark.parametrize('mutation', ['duplicate_id', 'duplicate_choice', 'no_preferred'])
def test_evaluation_rejects_ambiguous_labels(tmp_path, mutation):
    data = CASES[0].model_dump(mode='json')
    lines = [data]
    if mutation == 'duplicate_id':
        lines.append(data)
    elif mutation == 'duplicate_choice':
        data['candidates'].append(data['candidates'][0])
    else:
        data['candidates'][0]['rating'] = 'unnecessary'
    path = tmp_path / 'cases.jsonl'
    path.write_text('\n'.join(json.dumps(line) for line in lines), encoding='utf-8')
    with pytest.raises(ValueError):
        load_cases(path)
