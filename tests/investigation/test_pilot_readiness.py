"""Offline admission/collection tests. These are not live model-quality results."""

from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest

from evaluation import phase5c_pilot as pilot


@pytest.fixture
def protocol():
    return json.loads(pilot.PROTOCOL.read_text(encoding='utf-8'))


def payload():
    return {'model': 'gpt-4.1-mini-2025-04-14', 'input': 'private-ticket-SENTINEL',
            'text': {'format': {'name': 'PlannerResponseV2'}},
            'max_output_tokens': 700, 'temperature': 0, 'store': False}


def response(usage=None):
    return httpx.Response(200, json={'usage': usage or {'input_tokens': 10, 'output_tokens': 2, 'total_tokens': 12}})


@pytest.mark.parametrize('key,value,reason', [
    ('max_requests', 1, 'request_limit'), ('max_tokens', 1, 'token_limit'), ('max_usd', '0.000001', 'cost_limit'),
])
def test_limits_block_before_network_without_changing_payload(protocol, key, value, reason):
    protocol['budget'][key] = value
    requests = []
    def handler(request):
        requests.append(request)
        return response()
    budget = pilot.PilotBudget(protocol)
    meter = pilot.BudgetedTransport(httpx.MockTransport(handler), budget, '01-vpn-future-condition')
    with httpx.Client(transport=meter) as client:
        if key == 'max_requests':
            client.post(pilot.API_BASE_URL + '/responses', json=payload(), headers={'Authorization': 'secret-SENTINEL'})
            assert json.loads(requests[0].content) == payload()
        with pytest.raises(pilot.BudgetStop):
            client.post(pilot.API_BASE_URL + '/responses', json=payload())
    assert len(requests) == len(meter.calls) == (1 if key == 'max_requests' else 0)
    assert budget.stop_reason == reason
    assert 'SENTINEL' not in json.dumps(budget.snapshot()) + json.dumps(meter.calls)


@pytest.mark.parametrize('failure', ['missing', 'malformed', 'http_error', 'transport', 'oversize'])
def test_uncertain_or_excess_usage_stops_following_requests_and_retains_attempt(protocol, failure):
    def handler(request):
        if failure == 'transport':
            raise httpx.ConnectError('password-SENTINEL private model output')
        if failure == 'http_error':
            return httpx.Response(503, json={'error': 'secret-SENTINEL'})
        if failure == 'oversize':
            return response({'input_tokens': 999999, 'output_tokens': 2, 'total_tokens': 1000001})
        return httpx.Response(200, json={'usage': None if failure == 'missing' else
                                       {'input_tokens': 'secret-SENTINEL', 'total_tokens': 99}})
    budget = pilot.PilotBudget(protocol)
    meter = pilot.BudgetedTransport(httpx.MockTransport(handler), budget, '01-vpn-future-condition')
    with httpx.Client(transport=meter) as client:
        try:
            client.post(pilot.API_BASE_URL + '/responses', json=payload())
        except httpx.ConnectError:
            assert failure == 'transport'
        with pytest.raises(pilot.BudgetStop):
            client.post(pilot.API_BASE_URL + '/responses', json=payload())
    assert len(meter.calls) == len(budget.entries) == 1
    assert budget.entries[0]['accounted_tokens'] > 0  # Missing usage is never zero-cost.
    assert budget.stop_reason == ('usage_exceeded_reservation' if failure == 'oversize' else 'usage_unavailable')
    assert 'SENTINEL' not in json.dumps(budget.snapshot()) + json.dumps(meter.calls)


def test_reservation_checkpoint_precedes_network_and_settlement_does_not_count_cache_twice(protocol):
    snapshots = []
    budget = pilot.PilotBudget(protocol)
    budget.checkpoint = lambda: snapshots.append(deepcopy(budget.snapshot()))
    def handler(request):
        assert snapshots[-1]['entries'][0]['status'] == 'reserved_dispatch_unknown'
        return response({'input_tokens': 10, 'output_tokens': 2, 'total_tokens': 12,
                         'input_tokens_details': {'cached_tokens': 5}})
    meter = pilot.BudgetedTransport(httpx.MockTransport(handler), budget, '01-vpn-future-condition')
    with httpx.Client(transport=meter) as client:
        client.post(pilot.API_BASE_URL + '/responses', json=payload())
    assert budget.snapshot()['accounted_tokens'] == 12
    assert budget.snapshot()['accounted_usd'] == '0.0000072'
    assert len(snapshots) == 2


@pytest.mark.parametrize('change', ['model', 'output', 'temperature', 'store', 'tools', 'schema', 'endpoint', 'stream'])
def test_changed_request_configuration_never_reaches_transport(protocol, change):
    body, url = payload(), pilot.API_BASE_URL + '/responses'
    if change == 'endpoint': url = 'https://example.invalid/responses'
    elif change == 'schema': body['text']['format']['name'] = 'Unknown'
    else:
        key = {'output': 'max_output_tokens'}.get(change, change)
        body[key] = {'model': 'new-model', 'output': 701, 'temperature': 1,
                     'store': True, 'tools': [], 'stream': True}[change]
    budget = pilot.PilotBudget(protocol)
    meter = pilot.BudgetedTransport(httpx.MockTransport(lambda r: pytest.fail('No network')), budget, 'test')
    with httpx.Client(transport=meter) as client, pytest.raises(pilot.BudgetStop):
        client.post(url, json=body)
    assert not meter.calls and not budget.entries
    assert budget.stop_reason == 'request_configuration_changed'


def test_embedding_accounting_uses_input_only(protocol):
    budget = pilot.PilotBudget(protocol)
    meter = pilot.BudgetedTransport(httpx.MockTransport(lambda r: httpx.Response(200, json={
        'usage': {'prompt_tokens': 20, 'total_tokens': 20}})), budget, 'test')
    with httpx.Client(transport=meter) as client:
        client.post(pilot.API_BASE_URL + '/embeddings', json={'model': 'text-embedding-3-small',
                    'dimensions': 1536, 'encoding_format': 'float', 'input': ['private input']})
    assert budget.snapshot()['accounted_tokens'] == 20
    assert budget.snapshot()['accounted_usd'] == '4E-7'


def test_dry_run_is_reproducible_with_no_sdk_or_database(protocol, monkeypatch, capsys):
    monkeypatch.setattr(pilot, 'load_protocol', lambda: protocol)  # Exercise downstream flow with archived configuration.
    def forbidden(*a, **kw): pytest.fail('Dry-run must not use DB, SDK or HTTP')
    monkeypatch.setattr(pilot.live, 'OpenAI', forbidden)
    monkeypatch.setattr(pilot.live.ReadOnlyKBStore, 'from_environment', forbidden)
    monkeypatch.setattr(pilot.live.OperationalDB, 'from_environment', forbidden)
    assert pilot.main(['--dry-run']) == 0
    first = capsys.readouterr().out
    assert pilot.main([]) == 0
    assert first == capsys.readouterr().out
    result = json.loads(first)
    assert result['api_calls'] == 0 and not result['database_checked']
    assert result['max_api_requests'] == 64 and len(result['attempts']) == 8


@pytest.mark.parametrize('mismatch', [False, True])
def test_database_preflight_reuses_existing_reader_checks_without_http(protocol, monkeypatch, capsys, mismatch):
    monkeypatch.setattr(pilot, 'load_protocol', lambda: protocol)
    monkeypatch.setattr(pilot.live, 'OpenAI', lambda **kw: pytest.fail('No SDK'))
    monkeypatch.setattr(pilot.live.ReadOnlyKBStore, 'from_environment', lambda: object())
    monkeypatch.setattr(pilot.live.OperationalDB, 'from_environment', lambda: object())
    def preflight(cases, models, *, store, db):
        assert store is not None and db is not None and len(cases) == 4
        return {'database_checked': True, 'limits': protocol['graph_limits'], 'max_api_requests': 32,
                'index': protocol['retrieval']['index'],
                'database_snapshot': {} if mismatch else protocol['database_snapshot']}
    monkeypatch.setattr(pilot.live, 'preflight', preflight)
    assert pilot.main(['--dry-run', '--check-db']) == (1 if mismatch else 0)
    assert ('database_checked' in capsys.readouterr().out) is not mismatch


@pytest.mark.parametrize('path', ['reports/phase5b/future-003', 'reports/phase5c/baseline-001',
                                  'reports/phase5c/live', '../escape', '.env'])
def test_output_paths_exclude_original_reports_and_local_configuration(path):
    with pytest.raises(ValueError): pilot.safe_directory(Path(path))


def test_existing_new_pilot_directory_cannot_be_reused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / 'reports/phase5c/live/pilot-001'
    directory.mkdir(parents=True)
    with pytest.raises(ValueError): pilot.safe_directory(directory)


def test_paid_execution_requires_explicit_opt_in(protocol, tmp_path):
    with pytest.raises(ValueError):
        pilot.execute(protocol, {'database_checked': True}, store=None, db=None, directory=tmp_path)


@pytest.mark.parametrize('stop_after_first', [False, True, 'incomplete'])
def test_batch_keeps_every_declared_slot_and_never_retries_model_rejections(protocol, tmp_path, monkeypatch, stop_after_first):
    called = []
    monkeypatch.setattr(pilot, 'openai_transport', lambda: pilot.MeteredTransport(httpx.MockTransport(lambda r: response())))
    def run(cases, models, *, store, db, directory, checked, allow_paid, meter):
        called.append((cases[0].id, meter.budget, meter.attempt_id))
        assert allow_paid and checked['scenario_ids'] == [cases[0].id]
        assert models == protocol['models']
        # Simulate a rejected recommendation: retain it and continue, never retry.
        case = cases[0]
        rejected = pilot.live.scoring_row(case, None, [], {'stage': 'generation', 'code': 'invalid_output'})
        pair = {'id': case.id, 'trigger_status': case.trigger_status, 'agent': deepcopy(rejected),
                'standalone': deepcopy(rejected), 'manual_review': {'status': 'pending'},
                'agent_result': {'status': 'partial', 'stop_reason': 'finish'},
                'planner': {'coverage': {'covered': 0, 'expected': len(case.required_evidence)},
                            'redundant_lookup_ids': [], 'unnecessary_lookup_ids': []}}
        pilot.write_json(directory / 'paired.json', {'api_calls': [], 'errors': [],
                         'cases': [] if stop_after_first == 'incomplete' else [pair]})
        pilot.write_json(directory / 'manual-review.json', {'status': 'pending'})
        if stop_after_first is True: meter.budget.stop_reason = 'usage_unavailable'
        return 2
    monkeypatch.setattr(pilot.live, 'run_paid', run)
    code = pilot.execute(protocol, {'database_checked': True}, store=None, db=None, directory=tmp_path, allow_paid=True)
    result = json.loads((tmp_path / 'pilot.json').read_text())
    assert len(result['attempts']) == 8 and result['manual_review'] == 'pending'
    assert len(called) == (1 if stop_after_first else 8)
    assert len({id(c[1]) for c in called}) == 1  # One aggregate budget, not eight resets.
    assert len({c[2] for c in called}) == len(called)
    assert all(r['exit_code'] == 2 for r in result['attempts'] if r['state'] == 'recorded')
    assert code == (2 if stop_after_first else 0)  # Collection completion is not a semantic grade.
    assert sum(r['state'] == 'not_started' for r in result['attempts']) == (7 if stop_after_first else 0)
    recorded = 0 if stop_after_first == 'incomplete' else (1 if stop_after_first else 8)
    assert result['recorded_pairs'] == recorded
    assert len(result['unrecorded_attempt_ids']) == 8 - recorded
    for arm in ('agent', 'standalone'):
        metrics = result['mechanical_metrics_recorded_pairs_only'][arm]
        assert metrics['rejected'] == metrics['escalation']['unscored_rejected_or_failed'] == recorded
        assert metrics['escalation']['true_negative'] == 0


def test_frozen_model_override_fails_safely(monkeypatch, capsys):
    monkeypatch.setenv('OPENAI_MODEL', 'private-SENTINEL')
    assert pilot.main(['--dry-run']) == 1
    assert 'SENTINEL' not in capsys.readouterr().out


def test_frozen_v3_pilot_rejects_changed_application_without_http(monkeypatch, capsys):
    monkeypatch.setattr(pilot.live, "OpenAI", lambda **kw: pytest.fail("No SDK"))
    assert pilot.main(["--dry-run"]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "pilot_configuration_or_execution_failed"
