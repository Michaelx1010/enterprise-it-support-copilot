"""Versioned wire contract, canonical parity, and one-attempt failure preservation."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
from openai.lib._pydantic import to_strict_json_schema
from pydantic import ValidationError
import pytest

from app.investigation.graph import run_investigation
from app.investigation.schemas import InvestigationSynthesis
from app.investigation.scripted import ScriptedPlanner
from app.investigation.synthesis_draft import CURRENT_DRAFT_VERSION, InvestigationSynthesisDraftV2
from app.providers.openai_synthesis import OpenAISynthesis
from app.providers.synthesis import SynthesisError
from evaluation.investigation_synthesis import ReplayProvider, evaluate, load_cases
from evaluation.live_investigation import project_report
from evaluation.live_telemetry import MeteredTransport, usage_totals
from evaluation.synthesis_diagnostics import ObservedSynthesis, error_details


@pytest.mark.parametrize('mode', ['validation', 'serialization', 'sdk'])
def test_wire_difference_is_only_version_and_removed_boolean(mode):
    def schema(model):
        return to_strict_json_schema(model) if mode == 'sdk' else model.model_json_schema(mode=mode)
    canonical, draft = schema(InvestigationSynthesis), schema(InvestigationSynthesisDraftV2)
    shared = set(canonical['properties']) - {'escalation_required'}
    assert set(draft['properties']) == shared | {'schema_version'}
    assert set(draft['required']) == shared | {'schema_version'}
    assert draft['properties']['schema_version']['const'] == CURRENT_DRAFT_VERSION
    assert draft['additionalProperties'] is False
    assert draft['$defs'] == canonical['$defs']
    assert {key: draft['properties'][key] for key in shared} == {key: canonical['properties'][key] for key in shared}


CASES = [case for case in load_cases(Path('evaluation/investigation_synthesis_semantics.jsonl'))
         if case.id in ('established-escalation', 'escalation-grounded', 'unknown-trigger-abstention',
                        'authentication-grounded', 'escalation-unsupported')]


@pytest.mark.parametrize('case', CASES, ids=lambda case: case.id)
def test_sdk_draft_preserves_canonical_and_scripted_projection(case, as_synthesis_draft,
        planner_client, planner_response):
    # These authored legacy fixtures remain immutable. No adapter runs on live legacy outputs.
    before = deepcopy(case.candidate)
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(as_synthesis_draft(case.candidate))))
    live = evaluate(case, OpenAISynthesis(planner_client(handler)))
    scripted = evaluate(case, ReplayProvider(case.candidate))
    assert live == scripted
    assert live['report'] == before | {'conditional_guidance': []}
    assert before == case.candidate
    assert project_report(live['report']) == project_report(before)
    assert len(calls) == 1 and calls[0]['text']['format']['name'] == 'InvestigationSynthesisDraftV2'
    if case.id == 'escalation-unsupported':
        # A falsely typed current handoff still needs semantic review. No keyword rule.
        assert live['report']['escalation_required'] and case.manual_verdict == 'incorrect'
    else:
        assert live['report']['escalation_required'] == case.expected_escalation


@pytest.mark.parametrize('variant,code,location', [
    ('missing_version', 'missing', ['schema_version']),
    ('wrong_version', 'literal_error', ['schema_version']),
    ('removed_false', 'extra_forbidden', ['escalation_required']),
    ('removed_true', 'extra_forbidden', ['escalation_required']),
    ('supported_without_steps', 'status_steps_mismatch', []),
    ('abstention_with_steps', 'status_steps_mismatch', []),
    ('current_without_reason', 'escalation_reason_mismatch', []),
    ('reason_without_current', 'escalation_reason_mismatch', []),
    ('reason_without_kb', 'escalation_reason_missing_kb', []),
    ('step_without_kb', 'value_error', ['steps', 0]),
    ('conditional_guidance', 'list_type', ['conditional_guidance']),
    ('trigger_basis', 'extra_forbidden', ['<redacted>']),
])
def test_inconsistent_drafts_reject_without_repair_or_diagnostic_leak(synthesis_report,
        as_synthesis_draft, planner_client, planner_response, variant, code, location):
    candidate = as_synthesis_draft(synthesis_report)
    reason = {'text': 'PRIVATE reason', 'references': deepcopy(candidate['steps'][0]['references'])}
    if variant == 'missing_version': del candidate['schema_version']
    elif variant == 'wrong_version': candidate['schema_version'] = 'PRIVATE unknown version'
    elif variant.startswith('removed_'): candidate['escalation_required'] = variant == 'removed_true'
    elif variant == 'supported_without_steps': candidate['steps'] = []
    elif variant == 'abstention_with_steps': candidate['status'] = 'insufficient_evidence'
    elif variant == 'current_without_reason': candidate['steps'][0]['step_type'] = 'escalation'
    elif variant == 'reason_without_current': candidate['escalation_reason'] = reason
    elif variant == 'reason_without_kb':
        candidate['steps'][0]['step_type'] = 'escalation'
        candidate['escalation_reason'] = {'text': 'PRIVATE reason', 'references': [{'kind': 'ticket'}]}
    elif variant == 'step_without_kb': candidate['steps'][0]['references'] = [{'kind': 'ticket'}]
    else: candidate[variant] = 'PRIVATE future checkpoint'
    original = deepcopy(candidate)
    with pytest.raises(ValidationError) as caught:
        InvestigationSynthesisDraftV2.model_validate(candidate)
    safe = error_details(caught.value)
    assert safe['errors'][0]['type'] == code and safe['errors'][0]['loc'] == location
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(candidate)))
    observed = ObservedSynthesis(OpenAISynthesis(planner_client(handler)))
    with pytest.raises(SynthesisError, match='invalid_output'):
        observed.generate(instructions='PRIVATE prompt', payload='PRIVATE ticket')
    assert len(calls) == 1 and not observed.returned
    assert observed.events[0]['stage'] == 'sdk_parse'
    assert observed.events[0]['errors'] == safe['errors']
    assert 'PRIVATE' not in json.dumps(observed.events)
    assert candidate == original


@pytest.mark.parametrize('step_type', ['troubleshooting', 'escalation'])
def test_flag_uses_only_typed_steps_never_action_or_uncertainty_text(synthesis_report, as_synthesis_draft, step_type):
    candidate = as_synthesis_draft(synthesis_report)
    candidate['steps'][0]['step_type'] = step_type
    candidate['steps'][0]['action'] = 'A fixed authored action with no escalation keywords.'
    candidate['uncertainties'][0]['text'] = 'A future escalation condition has not been established.'
    candidate['escalation_reason'] = ({'text': 'An authored current reason.',
        'references': deepcopy(candidate['steps'][0]['references'])} if step_type == 'escalation' else None)
    canonical = InvestigationSynthesisDraftV2.model_validate(candidate).to_canonical()
    assert canonical.escalation_required is (step_type == 'escalation')
    assert canonical.model_dump(exclude={'escalation_required'}) == {k: v for k, v in candidate.items() if k != 'schema_version'}


@pytest.mark.parametrize('mode', ['legacy_type', 'mutated_version', 'mutated_reason'])
def test_provider_revalidates_sdk_objects_and_rejects_legacy_wire_type(synthesis_report, as_synthesis_draft, mode):
    parsed = InvestigationSynthesisDraftV2.model_validate(as_synthesis_draft(synthesis_report))
    if mode == 'legacy_type': parsed = InvestigationSynthesis.model_validate(synthesis_report)
    elif mode == 'mutated_version': parsed.schema_version = 'invalid'
    else: parsed.escalation_reason = parsed.summary
    response = SimpleNamespace(status='completed', output_parsed=parsed,
        output=[SimpleNamespace(type='message', content=[SimpleNamespace(type='output_text')])])
    client = Mock()
    client.with_options.return_value = client
    client.responses.parse.return_value = response
    with pytest.raises(SynthesisError, match='invalid_output'):
        OpenAISynthesis(client).generate(instructions='rules', payload='evidence')
    assert client.responses.parse.call_count == 1
    assert client.responses.parse.call_args.kwargs['text_format'] is InvestigationSynthesisDraftV2


@pytest.mark.parametrize('failure,code', [
    (None, None), ('reason', 'synthesis_invalid_output'),
    ('unknown_kb', 'synthesis_invalid_citation'), ('unknown_lookup', 'synthesis_invalid_citation'),
    ('http', 'synthesis_provider_failure'),
])
def test_draft_graph_keeps_partial_evidence_errors_and_metering(inv_request, inv_dependencies,
        synthesis_report, as_synthesis_draft, planner_client, planner_response, failure, code):
    decisions = [
        {'kind': 'lookup', 'tool': 'get_employee_account_status', 'arguments': {'employee_id': 'EMP-001'}},
        {'kind': 'lookup', 'tool': 'get_employee_devices', 'arguments': {'employee_id': 'EMP-001'}},
        {'kind': 'lookup', 'tool': 'get_active_service_incidents', 'arguments': {'service_id': 'SVC-001', 'limit': 5}},
        {'kind': 'finish'},
    ]
    deps = replace(inv_dependencies, planner=ScriptedPlanner(decisions),
        classifier=Mock(generate=Mock(side_effect=RuntimeError('PRIVATE classifier error'))))
    baseline = run_investigation(inv_request, dependencies=deps)
    candidate = as_synthesis_draft(synthesis_report)
    if failure == 'reason': candidate['steps'][0]['step_type'] = 'escalation'
    elif failure == 'unknown_kb': candidate['steps'][0]['references'][0]['chunk_id'] = 'not-retrieved'
    elif failure == 'unknown_lookup': candidate['summary']['references'].append(
        {'kind': 'operational_observation', 'lookup_id': 'not-executed'})
    def handler(request):
        if failure == 'http': return httpx.Response(503, json={'error': {'message': 'PRIVATE API error'}})
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(candidate)))
    meter = MeteredTransport(httpx.MockTransport(handler))
    observed = ObservedSynthesis(OpenAISynthesis(planner_client(meter.handle_request)))
    result = run_investigation(inv_request, dependencies=replace(deps, synthesis=observed))
    assert result.status == baseline.status == 'partial' and result.stop_reason == baseline.stop_reason == 'finish'
    for field in ('classification', 'kb_evidence', 'operational_evidence', 'lookup_trace',
                  'missing_fields', 'planner_decisions', 'lookup_attempts'):
        assert getattr(result, field) == getattr(baseline, field)
    assert result.planner_decisions == 4 and result.lookup_attempts == 3
    assert result.errors[:len(baseline.errors)] == baseline.errors
    assert result.human_review_required and not result.mutating_actions_executed
    assert result.synthesis_attempts == len(meter.calls) == 1
    assert meter.calls[0]['stage'] == 'synthesis'
    assert usage_totals(meter.calls) == {'requests': 1, 'known_total_tokens': 0,
        'requests_without_total_tokens': 1, 'cost_usd': None}
    assert result.synthesis_status == ('failed' if failure else 'completed')
    assert (result.recommendation is None) == bool(failure)
    if code: assert result.errors[-1].code == code
    else: assert not result.recommendation.escalation_required
    assert [event.node for event in result.graph_trace][-2:] == ['synthesize', 'assemble']
    diagnostics = observed.finish(result)
    assert diagnostics[-1]['stage'] == ('sdk_parse' if failure in ('reason', 'http') else 'application_validation')
    assert 'PRIVATE' not in result.model_dump_json() + json.dumps(diagnostics) + json.dumps(meter.calls)


@pytest.mark.parametrize('schema_name', ['InvestigationSynthesis', 'InvestigationSynthesisDraftV1', 'InvestigationSynthesisDraftV2'])
def test_telemetry_identifies_both_synthesis_contract_generations(schema_name):
    meter = MeteredTransport(httpx.MockTransport(lambda request: httpx.Response(200,
        json={'usage': {'total_tokens': 7}, 'model': 'fixture-model'})))
    with httpx.Client(transport=meter) as client:
        client.post('https://api.openai.com/v1/responses', json={'text': {'format': {'name': schema_name}}})
    assert len(meter.calls) == 1 and meter.calls[0]['stage'] == 'synthesis'
    assert usage_totals(meter.calls)['known_total_tokens'] == 7
