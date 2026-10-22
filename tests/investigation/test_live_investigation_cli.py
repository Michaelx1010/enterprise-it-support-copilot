"""Live-command wiring over fake DB boundaries and mocked SDK HTTP only."""

import json
from unittest.mock import Mock

import httpx
import pytest

from app.cli import main
from app.investigation.kb_access import ReadOnlyKBStore
from app.investigation.policy import TOOLS
from app.operations.db import OperationalDB
from app.providers.openai_planner import OpenAIPlanner


@pytest.fixture
def request_file(tmp_path, inv_request):
    path = tmp_path / 'request.json'
    path.write_text(inv_request.model_dump_json(), encoding='utf-8')
    return path


@pytest.fixture
def live_boundaries(monkeypatch, inv_dependencies, inv_results):
    store = Mock()
    store.manifest.return_value = {'embedding': {'provider': 'openai', 'model': 'text-embedding-3-small', 'dimensions': 1536}}
    store.search.return_value = inv_dependencies.store.results
    db = object()
    monkeypatch.setattr(ReadOnlyKBStore, 'from_environment', Mock(return_value=store))
    monkeypatch.setattr(OperationalDB, 'from_environment', Mock(return_value=db))
    function = Mock(return_value=inv_results['get_employee_devices'])
    old = TOOLS['get_employee_devices']
    monkeypatch.setitem(TOOLS, 'get_employee_devices', (old[0], old[1], function))
    monkeypatch.setenv('OPENAI_MODEL', 'classification-only')
    monkeypatch.setenv('OPENAI_EMBEDDING_MODEL', 'text-embedding-3-small')
    return store, db, function


@pytest.mark.parametrize('ending,exit_code,status', [('finish', 0, 'completed'), ('clarify', 0, 'completed'), ('error', 2, 'partial')])
def test_live_cli_reuses_existing_adapters_and_closes_client(request_file, live_boundaries, planner_client, planner_response, monkeypatch, capsys, ending, exit_code, status):
    requests = []
    planner_calls = 0
    def handler(request):
        nonlocal planner_calls
        body = json.loads(request.content)
        requests.append((request.url.path, body))
        if request.url.path.endswith('/embeddings'):
            return httpx.Response(200, json={'object': 'list', 'data': [{'object': 'embedding', 'index': 0, 'embedding': [1.] + [0.] * 1535}], 'model': 'text-embedding-3-small', 'usage': {'prompt_tokens': 1, 'total_tokens': 1}})
        if body['text']['format']['name'] == 'TicketClassification':
            return httpx.Response(200, json=planner_response(raw_text=json.dumps({'category': 'Network', 'priority': 'Medium', 'summary': 'VPN cannot connect.'})))
        planner_calls += 1
        if planner_calls == 1:
            return httpx.Response(200, json=planner_response({'kind': 'lookup', 'tool': 'get_employee_devices', 'arguments': {'employee_id': 'EMP-001'}}))
        if ending == 'error':
            return httpx.Response(429, json={'error': {'message': 'CANARY-SECRET', 'type': 'api_error'}})
        decision = {'kind': 'finish'} if ending == 'finish' else {'kind': 'clarify', 'missing_fields': ['ticket_details']}
        return httpx.Response(200, json=planner_response(decision))
    client = planner_client(handler)
    planner = OpenAIPlanner(client, model='planner-only')
    monkeypatch.setattr(OpenAIPlanner, 'from_environment', Mock(return_value=planner))
    assert main(['investigate', 'live', '--request', str(request_file)]) == exit_code
    output = capsys.readouterr()
    data = json.loads(output.out)
    assert data['planner'] == 'openai' and data['planner_model'] == 'planner-only'
    assert data['backend'] == 'postgres' and data['query_embedding'] == data['classification'] == 'openai'
    result = data['result']
    assert result['phase'] == '4B.1' and result['status'] == status
    assert result['lookup_attempts'] == 1 and result['planner_decisions'] == 2
    assert result['recommendation'] is None and result['synthesis_status'] == 'not_run'
    assert len(requests) == 4 and client.is_closed() and planner.client.is_closed()
    assert requests[0][1]['model'] == 'classification-only'
    store, db, function = live_boundaries
    store.search.assert_called_once()
    assert function.call_args.kwargs == {'db': db}
    assert 'CANARY' not in output.out + output.err


@pytest.mark.parametrize('payload', [
    {}, {'ticket': {'subject': '', 'description': 'x'}},
    {'ticket': {'subject': 'x', 'description': 'x' * 6000}},
    {'ticket': {'subject': 'x', 'description': 'x'}, 'employee_id': 'some name'},
    {'ticket': {'subject': 'x', 'description': 'x'}, 'decisions': [{'kind': 'finish'}]},
])
def test_bad_request_never_constructs_live_provider(tmp_path, monkeypatch, capsys, payload):
    factory = Mock(side_effect=AssertionError('Must not create provider'))
    monkeypatch.setattr(OpenAIPlanner, 'from_environment', factory)
    path = tmp_path / 'request.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    assert main(['investigate', 'live', '--request', str(path)]) == 1
    assert json.loads(capsys.readouterr().err)['error']['code'] == 'investigation_setup_failed'
    factory.assert_not_called()


def test_missing_reader_does_not_fall_back_to_admin_or_construct_provider(request_file, monkeypatch, capsys):
    monkeypatch.delenv('KB_READER_DATABASE_URL', raising=False)
    monkeypatch.delenv('OPS_DATABASE_URL', raising=False)
    monkeypatch.setenv('DATABASE_URL', 'CANARY-ADMIN')
    factory = Mock()
    monkeypatch.setattr(OpenAIPlanner, 'from_environment', factory)
    assert main(['investigate', 'live', '--request', str(request_file)]) == 1
    assert 'CANARY' not in capsys.readouterr().err
    factory.assert_not_called()


def test_construction_failure_closes_client(request_file, live_boundaries, planner_client, monkeypatch, capsys):
    client = planner_client(lambda request: pytest.fail('No request should be sent'))
    planner = OpenAIPlanner(client)
    monkeypatch.setattr(OpenAIPlanner, 'from_environment', Mock(return_value=planner))
    monkeypatch.setenv('OPENAI_MODEL', '')
    assert main(['investigate', 'live', '--request', str(request_file)]) == 1
    assert client.is_closed()
    assert json.loads(capsys.readouterr().err)['error']['code'] == 'investigation_setup_failed'


@pytest.mark.parametrize('outcome', ['supported', 'clarify', 'failure', 'invalid_citation'])
def test_opt_in_synthesis_cli(request_file, live_boundaries, planner_client, planner_response,
                             synthesis_report, monkeypatch, capsys, outcome):
    models = []
    def handler(request):
        body = json.loads(request.content)
        models.append(body['model'])
        if request.url.path.endswith('/embeddings'):
            return httpx.Response(200, json={'object': 'list', 'data': [{'object': 'embedding', 'index': 0, 'embedding': [1.] + [0.] * 1535}], 'model': 'text-embedding-3-small', 'usage': {'prompt_tokens': 1, 'total_tokens': 1}})
        name = body['text']['format']['name']
        if name == 'TicketClassification':
            return httpx.Response(200, json=planner_response(raw_text=json.dumps({'category': 'Network', 'priority': 'Medium', 'summary': 'VPN cannot connect.'})))
        if name == 'PlannerResponse':
            decision = {'kind': 'clarify', 'missing_fields': ['ticket_details']} if outcome == 'clarify' else {'kind': 'finish'}
            return httpx.Response(200, json=planner_response(decision))
        assert name == 'InvestigationSynthesis' and body['model'] == 'independent-synthesis'
        if outcome == 'failure': return httpx.Response(500, json={'error': {'message': 'CANARY', 'type': 'api_error'}})
        if outcome == 'invalid_citation': synthesis_report['steps'][0]['references'][0]['chunk_id'] = 'fake'
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(synthesis_report)))
    client = planner_client(handler)
    monkeypatch.setattr(OpenAIPlanner, 'from_environment', Mock(return_value=OpenAIPlanner(client, model='planner-only')))
    monkeypatch.setenv('OPENAI_SYNTHESIS_MODEL', 'independent-synthesis')
    code = main(['investigate', 'live', '--request', str(request_file), '--synthesize'])
    output = capsys.readouterr()
    data = json.loads(output.out)
    result = data['result']
    assert data['synthesis_model'] == 'independent-synthesis' and result['phase'] == '4B.2'
    assert result['planner_decisions'] == 1 and result['lookup_attempts'] == 0
    assert code == (2 if outcome in ('failure', 'invalid_citation') else 0)
    assert result['synthesis_attempts'] == (0 if outcome == 'clarify' else 1)
    assert models.count('independent-synthesis') == (0 if outcome == 'clarify' else 1)
    assert len(models) == (3 if outcome == 'clarify' else 4)
    assert (result['recommendation'] is None) == (outcome in ('failure', 'invalid_citation'))
    assert client.is_closed() and 'CANARY' not in output.out + output.err
