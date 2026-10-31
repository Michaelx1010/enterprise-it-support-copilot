"""Mocked production providers exercise paired evaluation, never live quality."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import httpx
from openai import OpenAI
import pytest

from app.investigation.graph import Dependencies
from app.investigation.scripted import ReplayLookups, ReplayStore
from app.kb.documents import load_chunks
from app.kb.schemas import SearchResult
from app.providers.embeddings import EmbeddingSpec
from app.providers.openai import OpenAIProvider
from app.providers.openai_embeddings import OpenAIEmbeddings
from app.providers.openai_planner import OpenAIPlanner
from app.providers.openai_recommendation import OpenAIRecommendation
from app.providers.openai_synthesis import OpenAISynthesis
from evaluation import live_investigation as live
from evaluation.live_telemetry import MeteredTransport, usage_totals


@pytest.fixture
def paired_api(planner_response, as_synthesis_draft):
    clients = []

    def create(case, mutate=None):
        requests = []
        decisions = iter(case.decisions)
        def handler(request):
            payload = json.loads(request.content)
            requests.append(payload)
            if request.url.path.endswith('/embeddings'):
                body = {'object': 'list', 'model': 'text-embedding-3-small',
                        'data': [{'object': 'embedding', 'index': 0, 'embedding': [1.] + [0.] * 1535}],
                        'usage': {'prompt_tokens': 12, 'total_tokens': 12}}
                stage = 'embedding'
            else:
                stage = payload['text']['format']['name']
                if stage == 'TicketClassification':
                    candidate = case.classification.model_dump()
                elif stage == 'PlannerResponseV2':
                    candidate = {'schema_version': 'investigation-planner-response-v2', 'decision': next(decisions)}
                elif stage == 'InvestigationSynthesisDraftV3':
                    candidate = as_synthesis_draft(case.agent_response)
                else:
                    candidate = deepcopy(case.rag_response)
                body = planner_response(raw_text=json.dumps(candidate))
                body['usage'] = {'input_tokens': 30, 'output_tokens': 20, 'total_tokens': 50,
                                 'input_tokens_details': {'cached_tokens': 5},
                                 'output_tokens_details': {'reasoning_tokens': 0}}
            return mutate(stage, body, payload) if mutate else httpx.Response(200, json=body)

        meter = MeteredTransport(httpx.MockTransport(handler))
        client = OpenAI(api_key='test-placeholder', max_retries=0,
                        http_client=httpx.Client(transport=meter))
        clients.append(client)
        spec = EmbeddingSpec(provider='openai', model='text-embedding-3-small', dimensions=1536)
        chunks = {c.chunk_id: c for c in load_chunks(Path('knowledge_base'))}
        store = ReplayStore(spec, [SearchResult(chunk=chunks[key], distance=i / 10) for i, key in enumerate(case.kb_chunk_ids)])
        deps = Dependencies(classifier=OpenAIProvider(client), embedder=OpenAIEmbeddings(client), store=store,
                            planner=OpenAIPlanner(client), synthesis=OpenAISynthesis(client), phase='4B.1',
                            fixture_lookup=ReplayLookups(case.lookups))
        return deps, OpenAIRecommendation(client), meter, requests, handler
    yield create
    for client in clients:
        client.close()


@pytest.mark.parametrize('case', live.select_cases(), ids=lambda c: c.id)
def test_four_pilots_use_production_providers_and_identical_evidence(case, paired_api):
    deps, rag, meter, requests, _ = paired_api(case)
    row = live.run_pair(case, dependencies=deps, standalone=rag, meter=meter)
    assert row['agent']['outcome'] == row['standalone']['outcome'] == 'accepted'
    assert row['agent_result']['status'] == 'completed'
    assert not row['agent_result']['mutating_actions_executed']
    assert row['agent_result']['human_review_required']
    assert [e['result'] for e in row['agent_result']['kb_evidence']] == row['shared_kb']
    bodies = {r['text']['format']['name']: json.loads(r['input'][1]['content'])
              for r in requests if 'text' in r and r['text']['format']['name'] != 'TicketClassification'}
    agent, standalone = bodies['InvestigationSynthesisDraftV3'], bodies['SupportRecommendation']
    assert standalone['ticket'] == agent['untrusted_evidence']['ticket'] == case.request.ticket.model_dump()
    for a, b in zip(agent['untrusted_evidence']['kb_procedures'], standalone['evidence'], strict=True):
        assert {key: a['result']['chunk'][key] for key in b} == b
    assert set(standalone) == {'ticket', 'evidence'}
    assert all(key not in json.dumps(bodies) for key in ('expected_escalation', 'review_notes', 'rag_response', 'agent_response'))
    assert len([r for r in requests if 'dimensions' in r]) == 1
    assert row['planner_decisions'][-1]['decision'] == {'kind': 'finish'}
    assert row['planner']['coverage']['ratio'] in (1., None)
    assert row['usage']['requests'] <= 8
    assert row['usage']['known_total_tokens'] == 50 * (len(requests) - 1) + 12
    assert row['usage']['cost_usd'] is None and row['usage']['requests_without_total_tokens'] == 0
    assert all(c['latency_seconds'] >= 0 for c in row['api_calls'])
    assert row['manual_review']['status'] == 'pending'
    assert all(c['snapshot_freshness'] is None and c['trigger_established'] is None
               for c in row['manual_review']['agent_claims'])


@pytest.mark.parametrize('invalid', [False, True])
def test_paired_future_guidance_is_reviewable_but_not_a_current_escalation(paired_api, invalid):
    from evaluation.investigation_synthesis import load_cases

    case = live.select_cases(['vpn-future-condition'])[0].model_copy(deep=True)
    authored = load_cases(Path('evaluation/investigation_conditional_guidance.jsonl'))[0]
    case.agent_response = deepcopy(authored.candidate)
    case.agent_response['uncertainties'] = [{
        'text': 'Operational evidence consists of recorded snapshots, not verified live state.',
        'references': [{'kind': 'investigation_context'}],
    }]
    if invalid:
        case.agent_response['conditional_guidance'][0]['references'][0]['chunk_id'] = 'not-retrieved'
    deps, rag, meter, _, _ = paired_api(case)
    row = live.run_pair(case, dependencies=deps, standalone=rag, meter=meter)
    assert row['agent']['outcome'] == ('rejected' if invalid else 'accepted')
    assert row['standalone']['outcome'] == 'accepted'
    assert len(row['agent_result']['operational_evidence']) == 3
    assert len([call for call in row['api_calls'] if call['stage'] == 'synthesis']) == 1
    if invalid:
        assert row['agent_result']['recommendation'] is None
        assert row['agent_result']['errors'][-1]['code'] == 'synthesis_invalid_citation'
        assert row['synthesis_diagnostics'][-1]['stage'] == 'application_validation'
    else:
        assert row['agent_result']['recommendation']['conditional_guidance']
        assert 'conditional_guidance' not in row['agent']['recommendation']
        assert not row['agent']['recommendation']['escalation_required']
        assert live.summarize([row])['agent']['premature_escalation_ids'] == []
        future = [item for item in row['manual_review']['agent_claims']
                  if item['location'] == 'conditional_guidance.0']
        assert len(future) == 1 and future[0]['trigger_established'] is None


@pytest.mark.parametrize('case_id', ['unsupported-procedure', 'vpn-future-condition'])
def test_paired_documentation_terminal_has_no_synthesis_request_and_preserves_metrics(case_id, paired_api):
    case = live.select_cases([case_id])[0].model_copy(deep=True)
    gap = {'kind': 'insufficient_evidence', 'gap_kind': 'documentation'}
    case.decisions = [gap]  # Development response only; frozen labels/inputs stay unchanged.
    deps, rag, meter, requests, _ = paired_api(case)
    row = live.run_pair(case, dependencies=deps, standalone=rag, meter=meter)
    assert row['agent']['outcome'] == row['standalone']['outcome'] == 'accepted'
    assert row['agent_result']['stop_reason'] == 'insufficient_evidence'
    assert row['agent_result']['recommendation']['steps'] == []
    assert row['agent_result']['recommendation']['trigger_basis'] is None
    assert not row['agent']['recommendation']['escalation_required']
    assert row['agent_result']['missing_fields'] == [] and row['agent_result']['synthesis_attempts'] == 0
    assert row['planner_decisions'][0]['decision'] == gap
    assert len(requests) == row['usage']['requests'] == 4
    assert [call['stage'] for call in row['api_calls']] == ['classification', 'embedding', 'planner', 'recommendation']
    assert row['synthesis_diagnostics'] == []
    assert row['manual_review']['status'] == 'pending'
    assert [e['result'] for e in row['agent_result']['kb_evidence']] == row['shared_kb']
    if case_id == 'vpn-future-condition':
        # Explicit semantic negative control: the available retry is answerable.
        # Acceptance/valid citations do not make this premature abstention correct.
        assert case.kb_answerable and row['agent']['recommendation']['status'] == 'insufficient_evidence'
        assert row['standalone']['recommendation']['status'] == 'supported'


@pytest.mark.parametrize('invalid', [False, True])
def test_paired_current_trigger_is_reviewable_without_changing_escalation_projection(paired_api, invalid):
    from evaluation.investigation_synthesis import load_cases

    case = live.select_cases(['vpn-confirmed'])[0].model_copy(deep=True)
    basis = deepcopy(load_cases(Path('evaluation/investigation_trigger_basis.jsonl'))[0].candidate['trigger_basis'])
    case.agent_response['trigger_basis'] = basis
    if invalid: basis['policy_references'][0]['chunk_id'] = 'not-retrieved'
    deps, rag, meter, _, _ = paired_api(case)
    row = live.run_pair(case, dependencies=deps, standalone=rag, meter=meter)
    assert row['standalone']['outcome'] == 'accepted'
    assert len(row['agent_result']['operational_evidence']) == 3
    assert len([c for c in row['api_calls'] if c['stage'] == 'synthesis']) == 1
    if invalid:
        assert row['agent']['outcome'] == 'rejected' and row['agent_result']['recommendation'] is None
        assert row['synthesis_diagnostics'][-1]['stage'] == 'application_validation'
        assert live.summarize([row])['agent']['escalation']['unscored_rejected_or_failed'] == 1
    else:
        assert row['agent']['outcome'] == 'accepted' and row['agent']['recommendation']['escalation_required']
        assert 'trigger_basis' not in row['agent']['recommendation']
        assert row['agent_result']['recommendation']['trigger_basis'] == basis
        item = next(i for i in row['manual_review']['agent_claims'] if i['location'] == 'trigger_basis.0')
        assert item['value'] == basis and item['trigger_established'] is None and item['entailment'] is None


@pytest.mark.parametrize('stage, failure, outcome', [
    ('InvestigationSynthesisDraftV3', 'http', 'failed'), ('InvestigationSynthesisDraftV3', 'schema', 'rejected'),
    ('InvestigationSynthesisDraftV3', 'citation', 'rejected'), ('SupportRecommendation', 'http', 'failed'),
    ('SupportRecommendation', 'schema', 'rejected'), ('SupportRecommendation', 'citation', 'rejected'),
])
def test_failures_preserve_evidence_and_are_not_successful_abstentions(paired_api, stage, failure, outcome):
    def mutate(current, body, payload):
        if current == stage:
            if failure == 'http':
                return httpx.Response(500, json={'error': {'message': 'DO-NOT-LOG credentials'}})
            candidate = json.loads(body['output'][0]['content'][0]['text'])
            if failure == 'schema':
                candidate['steps'] = []
            elif stage == 'InvestigationSynthesisDraftV3':
                candidate['steps'][0]['references'][0]['chunk_id'] = 'invented'
            else:
                candidate['steps'][0]['supporting_chunk_ids'] = ['invented']
            body['output'][0]['content'][0]['text'] = json.dumps(candidate)
        return httpx.Response(200, json=body)
    case = live.select_cases(['vpn-confirmed'])[0]
    deps, rag, meter, requests, _ = paired_api(case, mutate)
    row = live.run_pair(case, dependencies=deps, standalone=rag, meter=meter)
    arm = 'agent' if stage == 'InvestigationSynthesisDraftV3' else 'standalone'
    assert row[arm]['outcome'] == outcome and row[arm]['recommendation'] is None
    assert len(row['agent_result']['operational_evidence']) == 3
    assert len(row['shared_kb']) == 2
    assert row['usage']['requests'] == len(requests) == 8  # No SDK retries, even on HTTP 500.
    assert 'DO-NOT-LOG' not in json.dumps(row)
    score = live.summarize([row])[arm]
    assert score['unsupported_abstention']['abstained'] == 0
    assert score['escalation']['recall_over_all_positive_attempts'] == 0
    assert score['escalation']['unscored_rejected_or_failed'] == 1


def test_negative_control_not_misrepresented_as_semantic_success(paired_api):
    case = live.select_cases(['vpn-future-condition'])[0]
    deps, rag, meter, *_ = paired_api(case)
    row = live.run_pair(case, dependencies=deps, standalone=rag, meter=meter)
    metrics = live.summarize([row])
    assert metrics['agent']['accepted_citations']['citation_validity'] == 1
    assert metrics['agent']['premature_escalation_ids'] == [case.id]
    assert row['manual_review']['current_escalation_trigger_supported'] is None


@pytest.mark.parametrize('failure', ['retrieval', 'classification', 'planner', 'clarify', 'blocked', 'budget'])
def test_partial_workflows_keep_production_semantics(paired_api, failure):
    case = live.select_cases(['vpn-future-condition'])[0]
    if failure == 'clarify':
        case.decisions = [{'kind': 'clarify', 'missing_fields': ['ticket_details']}]
    if failure == 'blocked':
        case.decisions = [{'kind': 'lookup', 'tool': 'get_employee_account_status', 'arguments': {'employee_id': 'EMP-002'}}]
    if failure == 'budget':
        case.decisions = case.decisions[:3] + [{'kind': 'lookup', 'tool': 'get_device_details', 'arguments': {'device_id': 'DEV-001'}}]
    def mutate(stage, body, payload):
        if (failure, stage) in (('classification', 'TicketClassification'), ('planner', 'PlannerResponseV2')):
            return httpx.Response(500, json={'error': {'message': 'DO-NOT-LOG'}})
        return httpx.Response(200, json=body)
    deps, rag, meter, *_ = paired_api(case, mutate)
    if failure == 'retrieval':
        class BrokenStore:
            def manifest(self): raise RuntimeError('DO-NOT-LOG')
        deps = replace(deps, store=BrokenStore())
    row = live.run_pair(case, dependencies=deps, standalone=rag, meter=meter)
    assert 'DO-NOT-LOG' not in json.dumps(row)
    if failure == 'clarify':
        assert row['agent_result']['stop_reason'] == 'clarify'
        assert row['agent_result']['synthesis_attempts'] == 0
        assert row['agent']['recommendation']['status'] == 'insufficient_evidence'
    elif failure == 'retrieval':
        assert row['agent']['outcome'] == row['standalone']['outcome'] == 'failed'
        assert not row['shared_retrieval_succeeded']
        assert not any(c['arm'] == 'standalone' for c in row['api_calls'])
        assert row['agent_result']['recommendation']['status'] == 'insufficient_evidence'
    else:
        assert row['agent_result']['status'] == 'partial'
        assert row['shared_kb']
    if failure == 'blocked':
        assert row['agent_result']['lookup_attempts'] == 0
        assert row['planner_decisions'][0]['decision']['arguments'] is None
    assert row['agent_result']['planner_decisions'] <= 4
    assert row['agent_result']['lookup_attempts'] <= 4


def test_successful_empty_retrieval_is_distinct_from_failure(paired_api):
    case = live.select_cases(['unsupported-procedure'])[0]
    deps, rag, meter, *_ = paired_api(case)
    deps.store.results = []
    row = live.run_pair(case, dependencies=deps, standalone=rag, meter=meter)
    assert row['shared_retrieval_succeeded']
    for arm in ('agent', 'standalone'):
        assert row[arm]['outcome'] == 'accepted'
        assert row[arm]['recommendation']['status'] == 'insufficient_evidence'
    assert all(c['stage'] not in ('synthesis', 'recommendation') for c in row['api_calls'])


@pytest.mark.parametrize('args', [[], ['--dry-run'], ['--scenario', 'vpn-confirmed']])
def test_default_and_dry_run_create_no_client_or_db(args, monkeypatch, capsys):
    def forbidden(*a, **k): pytest.fail('Preflight must not construct clients or database readers.')
    monkeypatch.setattr(live, 'OpenAI', forbidden)
    monkeypatch.setattr(live.ReadOnlyKBStore, 'from_environment', forbidden)
    monkeypatch.setattr(live.OperationalDB, 'from_environment', forbidden)
    assert live.main(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['api_calls'] == 0 and not output['database_checked']
    assert output['max_api_requests'] == 8 * len(output['scenario_ids'])


@pytest.mark.parametrize('ids', [[], ['vpn-confirmed', 'vpn-confirmed'], ['stale-vpn-snapshot'], ['unknown']])
def test_case_selection_is_small_unique_and_frozen(ids):
    with pytest.raises(ValueError): live.select_cases(ids)


@pytest.mark.parametrize('args', [
    ['--allow-paid'], ['--allow-paid', '--output-dir', '.env'],
    ['--allow-paid', '--output-dir', 'reports'], ['--allow-paid', '--output-dir', 'reports/../docs/run'],
])
def test_invalid_output_paths_fail_before_models_or_db(args, monkeypatch, capsys):
    def forbidden(*a, **k): pytest.fail('Invalid arguments must fail before external access.')
    monkeypatch.setattr(live, 'OpenAI', forbidden)
    monkeypatch.setattr(live.ReadOnlyKBStore, 'from_environment', forbidden)
    assert live.main(args) == 1
    assert json.loads(capsys.readouterr().err)['error'] == 'input_validation_failed'


def test_existing_output_not_overwritten(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / 'reports' / 'old'
    path.mkdir(parents=True)
    (path / 'paired.json').write_text('preserve', encoding='utf-8')
    monkeypatch.setattr(live, 'select_cases', lambda ids: [])
    assert live.main(['--allow-paid', '--output-dir', str(path)]) == 1
    assert (path / 'paired.json').read_text() == 'preserve'


def test_paid_entry_requires_opt_in_even_when_called_directly(tmp_path):
    with pytest.raises(ValueError):
        live.run_paid([], {}, store=None, db=None, directory=tmp_path, checked={'database_checked': True})
    with pytest.raises(ValueError):
        live.run_paid([], {}, store=None, db=None, directory=tmp_path,
                      checked={'database_checked': False}, allow_paid=True)


@pytest.mark.parametrize('usage', [None, {}, {'total_tokens': 'secret', 'prompt_tokens': -1, 'api_key': 'secret'}])
def test_missing_usage_is_unknown_not_zero(usage):
    meter = MeteredTransport(httpx.MockTransport(lambda request: httpx.Response(200, json={'usage': usage})))
    with httpx.Client(transport=meter) as client:
        client.post('https://fixture.invalid/embeddings', json={'model': 'test', 'input': 'private ticket'})
    assert usage_totals(meter.calls)['requests_without_total_tokens'] == 1
    assert 'secret' not in json.dumps(meter.calls)
    assert 'private ticket' not in json.dumps(meter.calls)


def test_transport_errors_record_latency_without_raw_error():
    def fail(request): raise httpx.ConnectError('DO-NOT-LOG database credentials')
    meter = MeteredTransport(httpx.MockTransport(fail))
    with httpx.Client(transport=meter) as client, pytest.raises(httpx.ConnectError):
        client.post('https://fixture.invalid/responses', json={'model': 'test'})
    assert meter.calls[0]['error'] == 'transport_failure'
    assert meter.calls[0]['latency_seconds'] >= 0
    assert 'DO-NOT-LOG' not in json.dumps(meter.calls)


@pytest.mark.parametrize('changed, interrupted', [(False, False), (True, False), (False, True)])
def test_run_artifacts_checkpoint_and_verify_data(tmp_path, monkeypatch, paired_api, changed, interrupted):
    case = live.select_cases(['unsupported-procedure'])[0]
    deps, rag, unused_meter, requests, handler = paired_api(case)
    monkeypatch.setenv('OPENAI_API_KEY', 'test-placeholder')
    monkeypatch.setattr(live.httpx, 'HTTPTransport', lambda **kwargs: httpx.MockTransport(handler))
    monkeypatch.setattr(live, 'database_audit', lambda *args: {'same': not changed})
    original_dependencies = live.Dependencies
    monkeypatch.setattr(live, 'Dependencies', lambda **kwargs: original_dependencies(**kwargs, fixture_lookup=deps.fixture_lookup))
    if interrupted:
        def stop(*args, **kwargs): raise KeyboardInterrupt()
        monkeypatch.setattr(live, 'run_pair', stop)
    checked = {'database_checked': True, 'database_snapshot': {'same': True}, 'scenario_ids': [case.id]}
    code = live.run_paid([case], live.model_settings(), store=deps.store, db=None,
                         directory=tmp_path, checked=checked, allow_paid=True)
    report = json.loads((tmp_path / 'paired.json').read_text())
    worksheet = json.loads((tmp_path / 'manual-review.json').read_text())
    assert report['mode'] == 'live_paired_evaluation'  # Mocked API here; not a live quality claim.
    assert report['database_unchanged'] is not changed
    assert code == (2 if changed or interrupted else 0)
    assert worksheet['status'] == report['semantic_quality_review'] == 'pending'
    assert 'test-placeholder' not in json.dumps(report)
    if not interrupted:
        assert len(worksheet['cases']) == len(report['cases']) == 1
        assert report['usage']['requests'] == len(requests) == 5
        assert report['mechanical_metrics']['unreviewed_cases'] == 1
    else:
        assert report['errors'] == ['interrupted']
        assert report['cases'] == []
        assert report['live_model_requests_attempted'] == 0
        assert report['unrecorded_scenario_ids'] == [case.id]


@pytest.mark.parametrize('mismatch', ['index', 'records', None])
def test_database_preflight_is_no_api_and_fail_closed(monkeypatch, mismatch):
    class Store:
        def manifest(self):
            return {'embedding': {'provider': 'openai', 'model': 'wrong' if mismatch == 'index' else 'text-embedding-3-small',
                                  'dimensions': 1536}}
    monkeypatch.setattr(live, 'OpenAI', lambda **kwargs: pytest.fail('Preflight must never create OpenAI clients.'))
    monkeypatch.setattr(live, 'database_audit', lambda *args: {'table': {'matches_frozen_inputs': mismatch != 'records'}})
    if mismatch:
        with pytest.raises(ValueError):
            live.preflight(live.select_cases(), live.model_settings(), store=Store(), db=object())
    else:
        report = live.preflight(live.select_cases(), live.model_settings(), store=Store(), db=object())
        assert report['database_checked'] and report['api_calls'] == 0


def test_invalid_model_configuration_stops_preflight(monkeypatch):
    monkeypatch.setenv('OPENAI_SYNTHESIS_MODEL', ' ')
    with pytest.raises(ValueError): live.model_settings()


def test_db_preflight_does_not_fall_back_to_admin_credentials(monkeypatch, capsys):
    monkeypatch.setenv('DATABASE_URL', 'DO-NOT-LOG admin credentials')
    monkeypatch.delenv('KB_READER_DATABASE_URL', raising=False)
    monkeypatch.delenv('OPS_DATABASE_URL', raising=False)
    monkeypatch.setattr(live, 'OpenAI', lambda **kwargs: pytest.fail('Preflight must not create clients.'))
    assert live.main(['--check-db']) == 1
    captured = capsys.readouterr()
    assert 'DO-NOT-LOG' not in captured.err
    assert json.loads(captured.err)['error'] == 'database_preflight_failed'
