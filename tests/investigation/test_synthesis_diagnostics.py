"""Evaluation diagnostics observe production rejection, never repair or retry it."""

from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError
from pydantic_core import PydanticCustomError

from app.investigation.graph import run_investigation
from app.investigation.schemas import InvestigationSynthesis
from app.investigation.synthesis_draft import InvestigationSynthesisDraftV1
from app.providers.openai_synthesis import OpenAISynthesis
from app.providers.synthesis import SynthesisError
from evaluation.investigation_e2e import RagReplay
from evaluation.live_investigation import project_report, run_pair, select_cases
from evaluation.live_telemetry import MeteredTransport
from evaluation.synthesis_diagnostics import ObservedSynthesis, error_details


@pytest.mark.parametrize('failure, expected_type, expected_loc', [
    ('json', 'json_invalid', []),
    ('missing', 'missing', ['summary']),
    ('text_limit', 'string_too_long', ['summary', 'text']),
    ('extra_key', 'extra_forbidden', ['summary', '<redacted>']),
    ('duplicate_refs', 'value_error', ['summary']),
    ('escalation_flag', 'extra_forbidden', ['escalation_required']),
    ('escalation_reason', 'escalation_reason_mismatch', []),
    ('abstention_steps', 'status_steps_mismatch', []),
    ('reason_without_kb', 'escalation_reason_missing_kb', []),
])
def test_sdk_parse_runs_application_contracts_safely(planner_client, planner_response, synthesis_report,
        as_synthesis_draft, failure, expected_type, expected_loc):
    candidate = as_synthesis_draft(synthesis_report)
    if failure == 'missing': del candidate['summary']
    if failure == 'text_limit': candidate['summary']['text'] = 'DO_NOT_LOG' * 80
    if failure == 'extra_key': candidate['summary']['DO_NOT_LOG_key'] = 'DO_NOT_LOG_input'
    if failure == 'duplicate_refs': candidate['summary']['references'] *= 2
    if failure == 'escalation_flag': candidate['escalation_required'] = True
    if failure == 'escalation_reason': candidate['escalation_reason'] = deepcopy(candidate['summary'])
    if failure == 'abstention_steps': candidate['status'] = 'insufficient_evidence'
    if failure == 'reason_without_kb':
        candidate['steps'][0]['step_type'] = 'escalation'
        candidate['escalation_reason'] = deepcopy(candidate['summary'])
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=planner_response(raw_text='{DO_NOT_LOG' if failure == 'json' else json.dumps(candidate)))
    observer = ObservedSynthesis(OpenAISynthesis(planner_client(handler)))
    with pytest.raises(SynthesisError) as error:
        observer.generate(instructions='DO_NOT_LOG_prompt', payload='DO_NOT_LOG_evidence')
    assert error.value.code == 'invalid_output'
    assert len(calls) == 1 and not observer.returned
    assert len(observer.events) == 1
    event = observer.events[0]
    assert event['stage'] == 'sdk_parse' and event['exception_type'] == 'pydantic_validation_error'
    assert event['errors'][0]['type'] == expected_type and event['errors'][0]['loc'] == expected_loc
    assert 'DO_NOT_LOG' not in json.dumps(observer.events)
    assert not any(k in event['errors'][0] for k in ('msg', 'ctx', 'input', 'url'))


class ParsedClient:
    """Fake SDK boundary after parsing, for provider revalidation/shape checks."""
    def __init__(self, parsed, *, unexpected_item=False, failure=None):
        self.responses = self
        self.parsed, self.unexpected_item, self.failure = parsed, unexpected_item, failure
        self.calls = 0
        self.options = None

    def with_options(self, **options):
        self.options = options
        return self

    def parse(self, **kwargs):
        self.calls += 1
        if self.failure:
            raise self.failure
        output = [SimpleNamespace(type='message', content=[SimpleNamespace(type='output_text')])]
        if self.unexpected_item:
            output.append(SimpleNamespace(type='function_call'))
        return SimpleNamespace(status='completed', output=output, output_parsed=self.parsed)


@pytest.mark.parametrize('failure, stage, exception', [
    ('contract', 'provider_revalidation', 'pydantic_validation_error'),
    ('wrong_type', 'provider_revalidation', 'value_error'),
    ('shape', 'provider_response_validation', 'unavailable'),
    ('sdk_value', 'sdk_parse', 'value_error'),
    ('sdk_type', 'sdk_parse', 'type_error'),
])
def test_sdk_return_is_distinct_from_later_rejection(synthesis_report, as_synthesis_draft, failure, stage, exception):
    parsed = InvestigationSynthesisDraftV1.model_validate(as_synthesis_draft(synthesis_report))
    if failure == 'contract': parsed.status = 'insufficient_evidence'
    client = ParsedClient('DO_NOT_LOG' if failure == 'wrong_type' else parsed,
        unexpected_item=failure == 'shape',
        failure=ValueError('DO_NOT_LOG') if failure == 'sdk_value' else TypeError('DO_NOT_LOG') if failure == 'sdk_type' else None)
    observer = ObservedSynthesis(OpenAISynthesis(client))
    with pytest.raises(SynthesisError) as error:
        observer.generate(instructions='DO_NOT_LOG', payload='DO_NOT_LOG')
    assert error.value.code == 'invalid_output' and client.calls == 1
    assert client.options == {'timeout': 30., 'max_retries': 0}
    event = observer.events[-1]
    assert event['stage'] == stage and event['exception_type'] == exception
    assert 'DO_NOT_LOG' not in json.dumps(observer.events)
    if failure == 'contract':
        assert event['errors'][0]['type'] == 'status_steps_mismatch' and event['errors'][0]['loc'] == []
        assert observer.events[0] == {'stage': 'sdk_parse', 'outcome': 'returned'}


@pytest.mark.parametrize('failure', [None, 'sdk_contract', 'citation', 'application_contract', 'application_type'])
def test_paired_artifact_keeps_diagnostics_separate_and_preserves_behavior(inv_request, inv_dependencies,
        synthesis_report, as_synthesis_draft, planner_client, planner_response, failure):
    candidate = as_synthesis_draft(synthesis_report)
    if failure == 'sdk_contract': candidate['status'] = 'insufficient_evidence'
    if failure == 'citation': candidate['steps'][0]['references'][0]['chunk_id'] = 'not-retrieved'
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(candidate)))
    provider = OpenAISynthesis(planner_client(handler))
    if failure in ('application_contract', 'application_type'):
        class Fake:
            def generate(self, **kwargs):
                value = InvestigationSynthesis.model_validate(synthesis_report)
                value.escalation_required = True
                return value if failure == 'application_contract' else {'DO_NOT_LOG': 'unvalidated'}
        provider = Fake()
    deps = replace(inv_dependencies, synthesis=provider)
    case = select_cases(['vpn-future-condition'])[0].model_copy(update={'request': inv_request})
    meter = MeteredTransport(httpx.MockTransport(lambda r: pytest.fail('No telemetry HTTP call expected.')))
    row = run_pair(case, dependencies=deps, standalone=RagReplay(project_report(synthesis_report)), meter=meter)
    assert row['standalone']['outcome'] == 'accepted'
    assert row['shared_kb'] and row['agent_result']['synthesis_attempts'] == 1
    assert len(calls) == (0 if failure in ('application_contract', 'application_type') else 1)
    assert row['agent']['outcome'] == ('accepted' if failure is None else 'rejected')
    events = row['synthesis_diagnostics']
    if failure == 'sdk_contract':
        assert events[-1]['stage'] == 'sdk_parse'
    elif failure:
        assert events[-1]['stage'] == 'application_validation' and events[-1]['details_available'] is False
    else:
        assert events[-1] == {'stage': 'application_validation', 'outcome': 'accepted'}
    # Unobserved production flow has identical accepted/rejected behavior and codes.
    baseline = run_investigation(inv_request, dependencies=deps)
    assert baseline.status == row['agent_result']['status']
    assert [e.model_dump() for e in baseline.errors] == row['agent_result']['errors']
    assert baseline.synthesis_status == row['agent_result']['synthesis_status']
    assert 'synthesis_diagnostics' not in row['agent_result']
    assert 'DO_NOT_LOG' not in json.dumps(row['synthesis_diagnostics'])


def test_diagnostic_types_and_paths_are_allowlisted_and_bounded():
    error = ValidationError.from_exception_data('DO_NOT_LOG_title', [
        {'type': PydanticCustomError('DO_NOT_LOG_type', 'DO_NOT_LOG_message'),
         'loc': ('summary', 'DO_NOT_LOG_path', -9, 999999, *(['text'] * 20)), 'input': 'DO_NOT_LOG_input'}
        for _ in range(25)])
    details = error_details(error)
    assert details['error_count'] == 25 and len(details['errors']) == 20
    assert details['errors_truncated']
    assert details['errors'][0]['type'] == 'other_validation_error'
    assert details['errors'][0]['loc'][:4] == ['summary', '<redacted>', '<redacted>', '<redacted>']
    assert details['errors'][0]['location_truncated']
    assert len(details['errors'][0]['loc']) == 12
    assert 'DO_NOT_LOG' not in json.dumps(details)


@pytest.mark.parametrize('mode, code', [('refusal', 'refusal'), ('incomplete', 'incomplete'), ('http', 'provider_failure')])
def test_nonvalidation_failures_remain_distinct(planner_client, planner_response, synthesis_report, as_synthesis_draft, mode, code):
    calls = []
    def handler(request):
        calls.append(request)
        body = planner_response(raw_text=json.dumps(as_synthesis_draft(synthesis_report)), refusal=mode == 'refusal',
                                status='incomplete' if mode == 'incomplete' else 'completed')
        return httpx.Response(503, json={'error': {'message': 'DO_NOT_LOG'}}) if mode == 'http' else httpx.Response(200, json=body)
    observer = ObservedSynthesis(OpenAISynthesis(planner_client(handler)))
    with pytest.raises(SynthesisError) as error:
        observer.generate(instructions='private prompt', payload='private evidence')
    assert error.value.code == code and len(calls) == 1
    assert observer.events[-1]['stage'] == ('sdk_parse' if mode == 'http' else 'provider_response_validation')
    assert 'DO_NOT_LOG' not in json.dumps(observer.events)
