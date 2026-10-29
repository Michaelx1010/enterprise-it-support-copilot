"""Future guidance contracts and authored replays, never live-model quality claims."""

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
from openai.lib._pydantic import to_strict_json_schema
from pydantic import ValidationError
import pytest

from app.investigation.graph import run_investigation
from app.investigation.schemas import InvestigationResult, InvestigationSynthesis
from app.investigation.scripted import ScriptedPlanner
from app.investigation.synthesis_draft import InvestigationSynthesisDraftV1, InvestigationSynthesisDraftV2, InvestigationSynthesisDraftV3
from app.providers.openai_synthesis import OpenAISynthesis
from app.providers.synthesis import SynthesisError
from evaluation.investigation_e2e import review_items
from evaluation.investigation_synthesis import ReplayProvider, evaluate, load_cases, summarize
from evaluation.live_investigation import project_report
from evaluation.live_telemetry import MeteredTransport, usage_totals
from evaluation.synthesis_diagnostics import ObservedSynthesis, error_details

CASES = load_cases(Path('evaluation/investigation_conditional_guidance.jsonl'))


@pytest.fixture
def future_report(synthesis_report):
    value = deepcopy(synthesis_report)
    value['conditional_guidance'] = [{
        'condition': 'Gateway errors persist after a reconnect.',
        'action': 'If the gateway error persists, provide the error code to Network Support.',
        'references': deepcopy(value['steps'][0]['references']),
        'missing_evidence': 'Whether the error persists after a reconnect.',
    }]
    return value


@pytest.mark.parametrize('case', CASES, ids=lambda c: c.id)
def test_authored_cases_through_sdk_and_canonical_replay(case, as_synthesis_draft, planner_client, planner_response):
    before = case.model_dump_json()
    calls = []
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body['text']['format']['name'] == 'InvestigationSynthesisDraftV3'
        assert 'review_notes' not in body['input'][1]['content']
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(as_synthesis_draft(case.candidate))))
    result = evaluate(case, OpenAISynthesis(planner_client(handler)))
    legacy = evaluate(case, ReplayProvider(case.candidate))
    assert result['outcome'] == legacy['outcome']
    if result['report']:
        assert {k: v for k, v in result['report'].items() if k != 'trigger_basis'} == {k: v for k, v in legacy['report'].items() if k != 'trigger_basis'}
    assert result['outcome'] == case.expected_replay and len(calls) == 1
    assert case.model_dump_json() == before
    if result['outcome'] == 'accepted':
        report = InvestigationSynthesis.model_validate(result['report'])
        assert report.escalation_required == any(s.step_type == 'escalation' for s in report.steps)
        assert report.model_dump(mode='json') == case.candidate | {'trigger_basis': as_synthesis_draft(case.candidate)['trigger_basis']}
        if case.manual_verdict == 'acceptable':
            assert report.escalation_required == case.expected_escalation
            assert report.status == case.expected_status
        # The three negative controls deliberately pass mechanics, not semantic review.
        else: assert case.manual_verdict == 'incorrect'
        if not report.steps:
            assert report.status == 'insufficient_evidence' and not report.escalation_required
            assert report.escalation_reason is None and report.conditional_guidance


def test_offline_scores_separate_negative_controls_and_failures():
    results = [evaluate(c, ReplayProvider(c.candidate)) for c in CASES]
    metrics = summarize(CASES, results)
    assert metrics['cases'] == 9 and metrics['accepted'] == 7 and metrics['rejected_or_failed'] == 2
    assert metrics['escalation_label_matches'] == {'count': 6, 'accepted_cases': 7}
    assert metrics['unsupported_abstentions'] == {'count': 1, 'accepted_cases': 1}
    assert sum(c.manual_verdict == 'incorrect' for c in CASES) == 3
    assert 'do not measure groundedness' in metrics['manual_review']


@pytest.mark.parametrize('mode', ['validation', 'serialization', 'sdk'])
def test_v1_schema_is_unchanged_and_v2_is_explicitly_required(mode):
    def schema(model):
        return to_strict_json_schema(model) if mode == 'sdk' else model.model_json_schema(mode=mode)
    old, new = schema(InvestigationSynthesisDraftV1), schema(InvestigationSynthesisDraftV2)
    expected = ('21ea04537730fe93991770ce07179a8614369b163ba6cc1713e1664fdd37fd03' if mode == 'sdk'
                else '7805c036770c6b0a73060e67239ac8804596a54b5a761bf9f668b8a236d8f02e')
    assert sha256(json.dumps(old, sort_keys=True).encode()).hexdigest() == expected
    assert set(new['properties']) == set(old['properties']) | {'conditional_guidance'}
    assert set(new['required']) == set(new['properties'])
    assert new['properties']['schema_version']['const'] == 'investigation-synthesis-draft-v2'
    assert 'escalation_required' not in new['properties'] and new['additionalProperties'] is False
    for key in set(old['properties']) - {'schema_version'}:
        assert old['properties'][key] == new['properties'][key]
    for key, value in old['$defs'].items(): assert new['$defs'][key] == value


def test_legacy_reports_default_empty_without_mutation(synthesis_report, as_synthesis_draft):
    before = deepcopy(synthesis_report)
    old_draft = InvestigationSynthesisDraftV1.model_validate(as_synthesis_draft(before, version=1))
    legacy = InvestigationSynthesis.model_validate(before)
    assert old_draft.to_canonical() == legacy
    assert legacy.conditional_guidance == []
    assert legacy.model_dump(exclude={'conditional_guidance', 'trigger_basis'}) == before == synthesis_report
    assert ReplayProvider(before).generate(instructions='', payload='') == legacy
    legacy.conditional_guidance.append(None)
    assert InvestigationSynthesis.model_validate(before).conditional_guidance == []


@pytest.mark.parametrize('variant', ['v1', 'v2', 'missing_guidance', 'null_guidance', 'wrong_version', 'removed_flag', 'trigger_basis'])
def test_live_v3_has_no_legacy_fallback_or_malformed_trigger_fields(synthesis_report, as_synthesis_draft,
        planner_client, planner_response, variant):
    candidate = as_synthesis_draft(synthesis_report, version=1 if variant == 'v1' else 2 if variant == 'v2' else 3)
    if variant == 'missing_guidance': del candidate['conditional_guidance']
    elif variant == 'null_guidance': candidate['conditional_guidance'] = None
    elif variant == 'wrong_version': candidate['schema_version'] = 'private-invalid-version'
    elif variant == 'removed_flag': candidate['escalation_required'] = False
    elif variant == 'trigger_basis': candidate['trigger_basis'] = 'private-future-field'
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(candidate)))
    with pytest.raises(SynthesisError, match='invalid_output'):
        OpenAISynthesis(planner_client(handler)).generate(instructions='', payload='')
    assert len(calls) == 1


@pytest.mark.parametrize('field', ['condition', 'action', 'missing_evidence'])
@pytest.mark.parametrize('value', [None, '', 'x' * 601])
def test_future_text_constraints_are_required_bounded_and_redacted(future_report, as_synthesis_draft, field, value):
    candidate = as_synthesis_draft(future_report)
    candidate['conditional_guidance'][0][field] = value
    with pytest.raises(ValidationError) as caught: InvestigationSynthesisDraftV3.model_validate(candidate)
    safe = error_details(caught.value)
    assert safe['errors'][0]['loc'] == ['conditional_guidance', 0, field]
    assert not any(k in safe['errors'][0] for k in ('msg', 'input', 'ctx', 'url'))
    del candidate['conditional_guidance'][0][field]
    with pytest.raises(ValidationError) as missing: InvestigationSynthesisDraftV3.model_validate(candidate)
    assert error_details(missing.value)['errors'][0]['type'] == 'missing'


@pytest.mark.parametrize('variant', ['missing', 'empty', 'duplicate', 'ticket', 'observation', 'extra', 'too_many'])
def test_only_distinct_kb_references_are_allowed(future_report, as_synthesis_draft, variant):
    candidate = as_synthesis_draft(future_report)
    entry = candidate['conditional_guidance'][0]
    if variant == 'missing': del entry['references']
    elif variant == 'empty': entry['references'] = []
    elif variant == 'duplicate': entry['references'] *= 2
    elif variant == 'ticket': entry['references'] = [{'kind': 'ticket'}]
    elif variant == 'observation': entry['references'] = [{'kind': 'operational_observation', 'lookup_id': 'lookup-1'}]
    elif variant == 'extra': entry['references'][0]['PRIVATE_KEY'] = 'PRIVATE_VALUE'
    else: entry['references'] = [{'kind': 'kb_chunk', 'chunk_id': str(i)} for i in range(9)]
    with pytest.raises(ValidationError) as caught: InvestigationSynthesisDraftV3.model_validate(candidate)
    assert 'PRIVATE' not in json.dumps(error_details(caught.value))


@pytest.mark.parametrize('variant,code', [
    ('supported_without_steps', 'status_steps_mismatch'), ('abstention_with_steps', 'status_steps_mismatch'),
    ('reason_without_current', 'escalation_reason_mismatch'), ('current_without_reason', 'escalation_reason_mismatch'),
    ('reason_without_kb', 'escalation_reason_missing_kb'),
])
def test_future_guidance_cannot_mask_canonical_contradictions(future_report, as_synthesis_draft, variant, code):
    candidate = as_synthesis_draft(future_report)
    if variant == 'supported_without_steps': candidate['steps'] = []
    elif variant == 'abstention_with_steps': candidate['status'] = 'insufficient_evidence'
    elif variant == 'reason_without_current': candidate['escalation_reason'] = deepcopy(candidate['summary'])
    elif variant == 'current_without_reason': candidate['steps'][0]['step_type'] = 'escalation'
    else:
        candidate['steps'][0]['step_type'] = 'escalation'
        candidate['escalation_reason'] = deepcopy(candidate['summary'])
    before = deepcopy(candidate)
    with pytest.raises(ValidationError) as caught: InvestigationSynthesisDraftV3.model_validate(candidate)
    assert error_details(caught.value)['errors'][0]['type'] == code
    assert candidate == before


def test_future_list_bound_and_mutated_sdk_return_are_revalidated(future_report, as_synthesis_draft):
    candidate = as_synthesis_draft(future_report)
    candidate['conditional_guidance'] *= 5
    with pytest.raises(ValidationError): InvestigationSynthesisDraftV3.model_validate(candidate)
    parsed = InvestigationSynthesisDraftV3.model_validate(as_synthesis_draft(future_report))
    parsed.conditional_guidance[0].references = []
    client = Mock()
    client.with_options.return_value = client
    client.responses.parse.return_value = SimpleNamespace(status='completed', output_parsed=parsed,
        output=[SimpleNamespace(type='message', content=[SimpleNamespace(type='output_text')])])
    observed = ObservedSynthesis(OpenAISynthesis(client))
    with pytest.raises(SynthesisError, match='invalid_output'): observed.generate(instructions='', payload='')
    assert observed.events[-1]['stage'] == 'provider_revalidation' and client.responses.parse.call_count == 1


@pytest.mark.parametrize('field', ['step_type', 'escalation_required', 'trigger_basis'])
def test_future_entries_cannot_contain_current_action_or_trigger_fields(future_report, as_synthesis_draft, field):
    candidate = as_synthesis_draft(future_report)
    candidate['conditional_guidance'][0][field] = 'PRIVATE'
    with pytest.raises(ValidationError) as caught: InvestigationSynthesisDraftV3.model_validate(candidate)
    assert error_details(caught.value)['errors'][0]['type'] == 'extra_forbidden'
    assert 'PRIVATE' not in json.dumps(error_details(caught.value))


@pytest.mark.parametrize('failure', [None, 'unknown_kb', 'no_kb', 'provider'])
def test_partial_graph_preserves_evidence_on_future_guidance_failure(inv_request, inv_dependencies,
        future_report, as_synthesis_draft, planner_client, planner_response, failure):
    deps = replace(inv_dependencies, classifier=Mock(generate=Mock(side_effect=RuntimeError('PRIVATE'))),
        planner=ScriptedPlanner([
            {'kind': 'lookup', 'tool': 'get_employee_devices', 'arguments': {'employee_id': 'EMP-001'}},
            {'kind': 'finish'},
        ]))
    baseline = run_investigation(inv_request, dependencies=deps)
    candidate = as_synthesis_draft(future_report)
    if failure == 'unknown_kb': candidate['conditional_guidance'][0]['references'][0]['chunk_id'] = 'not-retrieved'
    elif failure == 'no_kb': candidate['conditional_guidance'][0]['references'] = []
    def handler(request):
        if failure == 'provider': return httpx.Response(500, json={'error': {'message': 'PRIVATE'}})
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(candidate)))
    meter = MeteredTransport(httpx.MockTransport(handler))
    provider = ObservedSynthesis(OpenAISynthesis(planner_client(meter.handle_request)))
    result = run_investigation(inv_request, dependencies=replace(deps, synthesis=provider))
    assert result.status == baseline.status == 'partial'
    for field in ('kb_evidence', 'operational_evidence', 'lookup_trace', 'planner_decisions', 'lookup_attempts'):
        assert getattr(result, field) == getattr(baseline, field)
    assert result.errors[:len(baseline.errors)] == baseline.errors
    assert result.synthesis_attempts == len(meter.calls) == 1 and meter.calls[0]['stage'] == 'synthesis'
    assert usage_totals(meter.calls)['requests_without_total_tokens'] == 1
    assert result.human_review_required and not result.mutating_actions_executed
    if failure:
        assert result.recommendation is None and result.synthesis_status == 'failed'
        expected = {'unknown_kb': 'invalid_citation', 'no_kb': 'invalid_output', 'provider': 'provider_failure'}[failure]
        assert result.errors[-1].code == 'synthesis_' + expected
    else:
        assert result.synthesis_status == 'completed' and not result.recommendation.escalation_required
        assert result.recommendation.conditional_guidance
        raw = result.model_dump()
        raw['recommendation']['conditional_guidance'][0]['references'][0]['chunk_id'] = 'not-retrieved'
        with pytest.raises(ValidationError, match='invalid_citation'): InvestigationResult.model_validate(raw)
    assert 'PRIVATE' not in json.dumps(provider.finish(result)) + result.model_dump_json()


def test_projection_ignores_future_actions_but_review_worksheet_includes_them():
    for case in CASES[:4]:
        raw = deepcopy(case.candidate)
        without = {key: value for key, value in raw.items() if key != 'conditional_guidance'}
        assert project_report(raw) == project_report(without)
        assert project_report(raw)['escalation_required'] == case.expected_escalation
        future_items = [item for item in review_items(raw, agent=True) if item['location'].startswith('conditional_guidance.')]
        assert len(future_items) == len(raw['conditional_guidance'])
        assert all(item['entailment'] is None and item['trigger_established'] is None for item in future_items)
        assert not any(item['location'].startswith('conditional_guidance.') for item in review_items(project_report(raw), agent=False))
