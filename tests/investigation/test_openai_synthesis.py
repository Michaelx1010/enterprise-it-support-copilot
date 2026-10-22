"""Actual SDK request/response parsing over mocked HTTP, never paid calls."""

from copy import deepcopy
import json
import traceback

import httpx
import pytest

from app.investigation.schemas import InvestigationSynthesis
from app.providers.openai_synthesis import OpenAISynthesis, MAX_OUTPUT_TOKENS
from app.providers.synthesis import SynthesisError


def test_sdk_schema_and_independent_settings(planner_client, planner_response, synthesis_report, monkeypatch):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(synthesis_report)))
    monkeypatch.setenv('OPENAI_SYNTHESIS_MODEL', 'synthesis-only')
    monkeypatch.setenv('OPENAI_PLANNER_MODEL', 'planner-only')
    client = planner_client(handler, max_retries=5)
    provider = OpenAISynthesis.from_environment(client)
    result = provider.generate(instructions='trusted rules', payload='untrusted data')
    assert isinstance(result, InvestigationSynthesis)
    body = requests[0]
    assert body['model'] == 'synthesis-only' and body['store'] is False
    assert body['max_output_tokens'] == MAX_OUTPUT_TOKENS and body['temperature'] == 0
    assert provider.client.timeout == 30 and provider.client.max_retries == 0
    assert 'tools' not in body and 'previous_response_id' not in body
    assert body['input'] == [{'role': 'system', 'content': 'trusted rules'}, {'role': 'user', 'content': 'untrusted data'}]
    schema = body['text']['format']['schema']
    def check(node):
        if isinstance(node, dict):
            assert 'oneOf' not in node and 'discriminator' not in node and 'default' not in node
            if node.get('type') == 'object':
                assert node['additionalProperties'] is False
                assert set(node['required']) == set(node['properties'])
            for child in node.values(): check(child)
        elif isinstance(node, list):
            for child in node: check(child)
    check(schema)
    monkeypatch.setenv('OPENAI_SYNTHESIS_MODEL', ' ')
    with pytest.raises(ValueError, match='blank'): OpenAISynthesis.from_environment(client)


@pytest.mark.parametrize('options,code', [
    ({'refusal': True}, 'refusal'), ({'empty': True}, 'missing_output'),
    ({'status': 'incomplete'}, 'incomplete'), ({'status': 'failed'}, 'incomplete'),
    ({'raw_text': '{'}, 'invalid_output'), ({'raw_text': '{}'}, 'invalid_output'),
])
def test_bad_responses_are_sanitized(planner_client, planner_response, synthesis_report, options, code):
    body = planner_response(**({'raw_text': json.dumps(synthesis_report)} | options))
    provider = OpenAISynthesis(planner_client(lambda request: httpx.Response(200, json=body)))
    with pytest.raises(SynthesisError) as error:
        provider.generate(instructions='rules', payload='data')
    assert error.value.code == code


@pytest.mark.parametrize('variant', ['two_messages', 'two_outputs', 'tool_call'])
def test_ambiguous_responses_rejected(planner_client, planner_response, synthesis_report, variant):
    body = planner_response(raw_text=json.dumps(synthesis_report))
    if variant == 'two_messages': body['output'].append(deepcopy(body['output'][0]))
    elif variant == 'two_outputs': body['output'][0]['content'] *= 2
    else: body['output'].append({'type': 'function_call', 'call_id': 'bad', 'name': 'reset_account', 'arguments': '{}'})
    provider = OpenAISynthesis(planner_client(lambda request: httpx.Response(200, json=body)))
    with pytest.raises(SynthesisError, match='invalid_output'):
        provider.generate(instructions='rules', payload='data')


@pytest.mark.parametrize('failure', [401, 429, 500, 'timeout', 'connection'])
def test_one_attempt_no_error_body_leak(planner_client, failure):
    calls = []
    def handler(request):
        calls.append(request)
        if failure == 'timeout': raise httpx.ReadTimeout('CANARY-SECRET', request=request)
        if failure == 'connection': raise httpx.ConnectError('CANARY-SECRET', request=request)
        return httpx.Response(failure, json={'error': {'message': 'CANARY-SECRET', 'type': 'api_error'}})
    provider = OpenAISynthesis(planner_client(handler, max_retries=5))
    with pytest.raises(SynthesisError) as error:
        provider.generate(instructions='rules', payload='data')
    assert error.value.code == 'provider_failure' and len(calls) == 1
    assert 'CANARY' not in ''.join(traceback.format_exception(error.value))
