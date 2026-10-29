"""Typed trigger evidence checks, not a source-entailment or freshness judge."""

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
from openai.lib._pydantic import to_strict_json_schema
from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticCustomError
import pytest

from app.investigation.graph import run_investigation
from app.investigation.schemas import InvestigationResult, InvestigationSynthesis, validate_synthesis_references
from app.investigation.scripted import ScriptedPlanner
from app.investigation.synthesis_draft import (
    InvestigationSynthesisDraftV1, InvestigationSynthesisDraftV2, InvestigationSynthesisDraftV3,
)
from app.providers.openai_synthesis import OpenAISynthesis
from app.providers.synthesis import SynthesisError
from evaluation.investigation_e2e import review_items
from evaluation.investigation_synthesis import ReplayProvider, evaluate, load_cases, summarize
from evaluation.live_investigation import project_report
from evaluation.live_telemetry import MeteredTransport, usage_totals
from evaluation.synthesis_diagnostics import ObservedSynthesis, error_details

CASES = load_cases(Path('evaluation/investigation_trigger_basis.jsonl'))


@pytest.mark.parametrize('case', CASES, ids=lambda c: c.id)
def test_v3_sdk_and_explicit_draft_replay_agree(case, planner_client, planner_response):
    original = case.model_dump_json()
    def handler(request):
        body = json.loads(request.content)
        assert body['text']['format']['name'] == 'InvestigationSynthesisDraftV3'
        assert 'review_notes' not in body['input'][1]['content']
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(case.candidate)))
    meter = MeteredTransport(httpx.MockTransport(handler))
    observed = ObservedSynthesis(OpenAISynthesis(planner_client(meter.handle_request)))
    result = evaluate(case, observed)
    assert result == evaluate(case, ReplayProvider(case.candidate, draft_v3=True))
    assert result['outcome'] == case.expected_replay
    assert case.model_dump_json() == original
    assert len(meter.calls) == 1 and meter.calls[0]['stage'] == 'synthesis'
    assert usage_totals(meter.calls)['requests_without_total_tokens'] == 1
    if result['report']:
        report = InvestigationSynthesis.model_validate(result['report'])
        assert report.escalation_required == any(s.step_type == 'escalation' for s in report.steps)
        assert bool(report.trigger_basis) == report.escalation_required
        if case.manual_verdict == 'acceptable':
            assert report.status == case.expected_status
            assert report.escalation_required == case.expected_escalation
        else:
            # Populated typed evidence is not proof of causality or a current trigger.
            assert case.manual_verdict == 'incorrect' and report.escalation_required


def test_evaluation_denominators_and_semantic_negative_controls():
    results = [evaluate(c, ReplayProvider(c.candidate, draft_v3=True)) for c in CASES]
    metrics = summarize(CASES, results)
    assert metrics['cases'] == 14 and metrics['accepted'] == 7 and metrics['rejected_or_failed'] == 7
    assert metrics['escalation_label_matches'] == {'count': 5, 'accepted_cases': 7}
    assert metrics['unsupported_abstentions'] == {'count': 1, 'accepted_cases': 1}
    assert {c.id for c in CASES if c.manual_verdict == 'incorrect'} == {
        'stale-incident-current-causality', 'unrelated-account-trigger'}
    assert 'do not measure groundedness' in metrics['manual_review']


@pytest.mark.parametrize('model,regular,sdk', [
    (InvestigationSynthesisDraftV1, '7805c036770c6b0a73060e67239ac8804596a54b5a761bf9f668b8a236d8f02e',
     '21ea04537730fe93991770ce07179a8614369b163ba6cc1713e1664fdd37fd03'),
    (InvestigationSynthesisDraftV2, '3aa89c23fd9b1ef54aa4f39db20a00a02d8bf067f752892a04d0a16e822e8f17',
     '245fc0da69aa83562f7a454d6d8be43b80616678eacaf72fa5af4cbfbc305794'),
])
@pytest.mark.parametrize('mode', ['validation', 'serialization', 'sdk'])
def test_historical_wire_schema_hashes_unchanged(model, regular, sdk, mode):
    schema = to_strict_json_schema(model) if mode == 'sdk' else model.model_json_schema(mode=mode)
    assert sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest() == (sdk if mode == 'sdk' else regular)


@pytest.mark.parametrize('model,regular,sdk', [
    (InvestigationSynthesis, 'c316de82bb0e66472a60a13e68de6edc1ba43a18274e2a81b9d62a05e0747027',
     '39377a92d1ae523b66bbb37f22231764e6e45f3fa2f80153a5446592075b5df1'),
    (InvestigationResult, 'ec6148bff85c39fe28f5018eb12b8679f39158aeae1e4ec92cbb53a4b85e4cf4',
     '22cb2207e50fdba826dfc1e48f5a4291d168573c26144498ff6c177c23330ecc'),
])
@pytest.mark.parametrize('mode', ['validation', 'serialization', 'sdk'])
def test_public_schema_adds_only_declared_trigger_field(model, regular, sdk, mode):
    schema = to_strict_json_schema(model) if mode == 'sdk' else model.model_json_schema(mode=mode)
    report = schema if model is InvestigationSynthesis else schema['$defs']['InvestigationSynthesis']
    field = report['properties'].pop('trigger_basis')
    assert field['anyOf'] == [{'$ref': '#/$defs/EscalationTriggerBasis'}, {'type': 'null'}]
    assert ('trigger_basis' in report['required']) == (mode == 'sdk')
    if mode == 'sdk': report['required'].remove('trigger_basis')
    else: assert field['default'] is None
    definition = schema['$defs'].pop('EscalationTriggerBasis')
    assert set(definition['properties']) == set(definition['required']) == {
        'policy_references', 'factual_references', 'explanation'}
    assert sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest() == (sdk if mode == 'sdk' else regular)


@pytest.mark.parametrize('version', [1, 2])
def test_explicit_historical_loading_is_compatible_but_live_has_no_fallback(version, planner_client, planner_response):
    canonical = InvestigationSynthesisDraftV3.model_validate(CASES[0].candidate).to_canonical().model_dump()
    canonical.pop('trigger_basis')
    historical = deepcopy(canonical)
    historical.pop('escalation_required')
    if version == 1: historical.pop('conditional_guidance')
    historical['schema_version'] = f'investigation-synthesis-draft-v{version}'
    cls = InvestigationSynthesisDraftV1 if version == 1 else InvestigationSynthesisDraftV2
    assert cls.model_validate(historical).to_canonical().trigger_basis is None
    assert ReplayProvider(canonical).generate(instructions='', payload='').escalation_required
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(historical)))
    with pytest.raises(SynthesisError, match='invalid_output'):
        OpenAISynthesis(planner_client(handler)).generate(instructions='', payload='')
    assert len(calls) == 1


@pytest.mark.parametrize('variant', ['missing_key', 'null_current', 'wrong_version', 'removed_flag',
    'noncurrent_basis', 'future_only_basis', 'supported_no_steps', 'insufficient_with_steps',
    'missing_reason', 'reason_without_kb'])
def test_v3_rejects_contradictions_without_repair(variant):
    value = deepcopy(CASES[0].candidate)
    if variant == 'missing_key': del value['trigger_basis']
    elif variant == 'null_current': value['trigger_basis'] = None
    elif variant == 'wrong_version': value['schema_version'] = 'investigation-synthesis-draft-v2'
    elif variant == 'removed_flag': value['escalation_required'] = True
    elif variant == 'noncurrent_basis':
        value['steps'][0]['step_type'] = 'troubleshooting'; value['escalation_reason'] = None
    elif variant == 'future_only_basis':
        value = deepcopy(CASES[3].candidate); value['trigger_basis'] = deepcopy(CASES[0].candidate['trigger_basis'])
    elif variant == 'supported_no_steps': value['steps'] = []
    elif variant == 'insufficient_with_steps': value['status'] = 'insufficient_evidence'
    elif variant == 'missing_reason': value['escalation_reason'] = None
    else: value['escalation_reason']['references'] = [{'kind': 'ticket'}]
    before = deepcopy(value)
    with pytest.raises(ValidationError): InvestigationSynthesisDraftV3.model_validate(value)
    assert value == before


@pytest.mark.parametrize('group', ['policy_references', 'factual_references'])
@pytest.mark.parametrize('variant', ['missing', 'empty', 'duplicate', 'wrong_kind', 'context', 'extra', 'too_many'])
def test_reference_groups_are_nonempty_typed_unique_and_bounded(group, variant):
    value = deepcopy(CASES[0].candidate)
    basis = value['trigger_basis']
    if variant == 'missing': del basis[group]
    elif variant == 'empty': basis[group] = []
    elif variant == 'duplicate': basis[group] *= 2
    elif variant == 'wrong_kind': basis[group] = deepcopy(basis['factual_references' if group == 'policy_references' else 'policy_references'])
    elif variant == 'context': basis[group] = [{'kind': 'investigation_context'}]
    elif variant == 'extra': basis[group][0]['PRIVATE_FIELD'] = 'PRIVATE_VALUE'
    else: basis[group] *= 9
    with pytest.raises(ValidationError) as caught: InvestigationSynthesisDraftV3.model_validate(value)
    assert 'PRIVATE' not in json.dumps(error_details(caught.value))


class TriggerEnvelope(BaseModel):
    report: InvestigationSynthesisDraftV3


@pytest.mark.parametrize('text', [None, '', ' ', 'PRIVATE' * 100])
def test_explanation_constraints_and_nested_diagnostic_redaction(text):
    value = deepcopy(CASES[0].candidate)
    value['trigger_basis']['explanation'] = text
    with pytest.raises(ValidationError) as caught: TriggerEnvelope.model_validate({'report': value})
    safe = error_details(caught.value)
    assert safe['errors'][0]['loc'] == ['<redacted>', 'trigger_basis', 'explanation']
    assert not any(k in safe['errors'][0] for k in ('input', 'ctx', 'msg', 'url'))
    assert 'PRIVATE' not in json.dumps(safe)


def test_current_projection_ignores_basis_and_worksheet_retains_it():
    report = InvestigationSynthesisDraftV3.model_validate(CASES[4].candidate).to_canonical()
    raw = report.model_dump(mode='json')
    legacy = {k: v for k, v in raw.items() if k not in ('trigger_basis', 'conditional_guidance')}
    assert project_report(raw) == project_report(legacy)
    items = review_items(raw, agent=True)
    basis = [item for item in items if item['location'] == 'trigger_basis.0']
    assert len(basis) == 1 and basis[0]['value'] == raw['trigger_basis']
    assert basis[0]['entailment'] is None and basis[0]['trigger_established'] is None
    assert any(item['location'] == 'conditional_guidance.0' for item in items)
    assert not any(item['location'] == 'trigger_basis.0' for item in review_items(project_report(raw), agent=False))


@pytest.mark.parametrize('failure', [None, 'not_found', 'database', 'blocked', 'unknown_kb', 'unknown_lookup',
                                   'null_basis', 'provider', 'missing_limitations'])
def test_trigger_failures_preserve_graph_evidence_and_attempts(inv_request, inv_dependencies, inv_results,
        synthesis_report, as_synthesis_draft, planner_client, planner_response, failure):
    decisions = [
        {'kind': 'lookup', 'tool': 'get_employee_account_status', 'arguments': {'employee_id': 'EMP-001'}},
        {'kind': 'lookup', 'tool': 'get_employee_devices', 'arguments': {'employee_id': 'EMP-999' if failure == 'blocked' else 'EMP-001'}},
        {'kind': 'finish'},
    ]
    def lookup(tool, request):
        if tool == 'get_employee_devices' and failure == 'database': raise RuntimeError('PRIVATE database error')
        value = deepcopy(inv_results[tool])
        if tool == 'get_employee_devices' and failure == 'not_found':
            value.update(status='not_found', employee=None, devices=[],
                         missing_entities=[{'entity_type': 'employee', 'entity_id': 'EMP-001'}])
        return value
    deps = replace(inv_dependencies, planner=ScriptedPlanner(decisions), fixture_lookup=lookup,
        classifier=Mock(generate=Mock(side_effect=RuntimeError('PRIVATE classifier error'))))
    baseline = run_investigation(inv_request, dependencies=deps)
    report = deepcopy(synthesis_report)
    report['steps'][0]['step_type'] = 'escalation'; report['escalation_required'] = True
    report['escalation_reason'] = {'text': 'Authored mechanical test claim, not a semantic endorsement.',
                                 'references': deepcopy(report['steps'][0]['references'])}
    candidate = as_synthesis_draft(report)
    candidate['trigger_basis']['factual_references'] = [{'kind': 'operational_observation', 'lookup_id': 'lookup-2'}]
    if failure == 'unknown_kb': candidate['trigger_basis']['policy_references'][0]['chunk_id'] = 'not-retrieved'
    elif failure == 'unknown_lookup': candidate['trigger_basis']['factual_references'][0]['lookup_id'] = 'not-executed'
    elif failure == 'null_basis': candidate['trigger_basis'] = None
    elif failure == 'missing_limitations': candidate['uncertainties'] = []
    def handler(request):
        if failure == 'provider': return httpx.Response(500, json={'error': {'message': 'PRIVATE'}})
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(candidate)))
    meter = MeteredTransport(httpx.MockTransport(handler))
    observed = ObservedSynthesis(OpenAISynthesis(planner_client(meter.handle_request)))
    result = run_investigation(inv_request, dependencies=replace(deps, synthesis=observed))
    assert result.status == baseline.status == 'partial'
    for field in ('classification', 'kb_evidence', 'operational_evidence', 'lookup_trace', 'planner_decisions', 'lookup_attempts'):
        assert getattr(result, field) == getattr(baseline, field)
    assert result.errors[:len(baseline.errors)] == baseline.errors
    assert result.synthesis_attempts == len(meter.calls) == 1
    assert meter.calls[0]['stage'] == 'synthesis' and usage_totals(meter.calls)['requests_without_total_tokens'] == 1
    assert result.human_review_required and not result.mutating_actions_executed
    if failure:
        assert result.recommendation is None and result.synthesis_status == 'failed'
        code = {'null_basis': 'invalid_output', 'provider': 'provider_failure', 'missing_limitations': 'missing_limitations'}.get(failure, 'invalid_citation')
        assert result.errors[-1].code == 'synthesis_' + code
    else:
        assert result.recommendation.trigger_basis and result.recommendation.escalation_required
    assert 'PRIVATE' not in json.dumps(observed.finish(result)) + result.model_dump_json() + json.dumps(meter.calls)
    # Outer canonical loading independently rejects evidence from not_found observations.
    if failure == 'not_found':
        raw = result.model_dump()
        raw.update(synthesis_status='completed', recommendation=InvestigationSynthesisDraftV3.model_validate(candidate).to_canonical().model_dump())
        with pytest.raises(ValidationError, match='invalid_citation'): InvestigationResult.model_validate(raw)


def test_new_observation_basis_fails_closed_without_successful_id_set():
    report = InvestigationSynthesisDraftV3.model_validate(CASES[-1].candidate).to_canonical()
    with pytest.raises(ValueError, match='invalid_citation'):
        validate_synthesis_references(report, set(CASES[-1].kb), {'lookup-1'})
    validate_synthesis_references(report, set(CASES[-1].kb), {'lookup-1'}, trigger_lookup_ids={'lookup-1'})


def test_mutated_v3_sdk_object_is_revalidated():
    from types import SimpleNamespace

    parsed = InvestigationSynthesisDraftV3.model_validate(CASES[0].candidate)
    parsed.trigger_basis = None
    client = Mock(); client.with_options.return_value = client
    client.responses.parse.return_value = SimpleNamespace(status='completed', output_parsed=parsed,
        output=[SimpleNamespace(type='message', content=[SimpleNamespace(type='output_text')])])
    observed = ObservedSynthesis(OpenAISynthesis(client))
    with pytest.raises(SynthesisError, match='invalid_output'): observed.generate(instructions='', payload='')
    assert client.responses.parse.call_count == 1
    assert observed.events[-1]['stage'] == 'provider_revalidation'


def test_duplicate_operational_trigger_references_reject():
    candidate = deepcopy(CASES[-1].candidate)
    candidate['trigger_basis']['factual_references'] *= 2
    with pytest.raises(ValidationError) as caught:
        InvestigationSynthesisDraftV3.model_validate(candidate)
    assert error_details(caught.value)['errors'][0]['type'] == 'value_error'


@pytest.mark.parametrize('current', [False, True])
def test_trigger_mismatch_has_identifiable_redacted_sdk_diagnostics(current, planner_client, planner_response):
    candidate = deepcopy(CASES[0].candidate)
    if current:
        candidate['trigger_basis'] = None
    else:
        candidate['steps'][0]['step_type'] = 'troubleshooting'
        candidate['escalation_reason'] = None
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(candidate)))
    observed = ObservedSynthesis(OpenAISynthesis(planner_client(handler)))
    with pytest.raises(SynthesisError, match='invalid_output'):
        observed.generate(instructions='PRIVATE prompt', payload='PRIVATE ticket evidence')
    assert len(calls) == 1
    assert observed.events[0]['errors'] == [
        {'type': 'escalation_trigger_mismatch', 'loc': [], 'location_truncated': False}]
    assert observed.events[0]['stage'] == 'sdk_parse'
    assert 'PRIVATE' not in json.dumps(observed.events)
    with pytest.raises(ValidationError) as nested:
        TriggerEnvelope.model_validate({'report': candidate})
    assert error_details(nested.value)['errors'][0]['loc'] == ['<redacted>']


@pytest.mark.parametrize('code', ['escalation_trigger_mismatch', 'escalation_trigger_mismatch_PRIVATE', 'PRIVATE_escalation_trigger_mismatch'])
def test_only_exact_new_error_identity_is_allowlisted(code):
    error = ValidationError.from_exception_data('PRIVATE title', [{
        'type': PydanticCustomError(code, 'PRIVATE message {value}', {'value': 'PRIVATE context'}),
        'loc': ('trigger_basis', 'PRIVATE key'), 'input': 'PRIVATE model output',
    }])
    safe = error_details(error)
    assert safe['errors'][0]['type'] == (code if code == 'escalation_trigger_mismatch' else 'other_validation_error')
    assert safe['errors'][0]['loc'] == ['trigger_basis', '<redacted>']
    assert 'PRIVATE' not in json.dumps(safe)
