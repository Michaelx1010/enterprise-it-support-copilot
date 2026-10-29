"""Real restricted logins and graph execution; only a separate _test DB is initialized."""

from dataclasses import replace
import json
import os
from pathlib import Path
import secrets

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
import pytest

from app.investigation.graph import run_investigation
from app.investigation.kb_access import KBAccessError, ReadOnlyKBStore, provision_kb_reader
from app.investigation.scripted import ScriptedEmbedder, ScriptedPlanner
from app.kb.documents import load_chunks
from app.kb.store import PgvectorStore
from app.operations.db import OperationalDB, initialize, provision_reader
from app.operations.seed import seed
from app.providers.embeddings import EmbeddingSpec
from app.rag.recommendation import build_query

pytestmark = pytest.mark.integration
SPEC = EmbeddingSpec(provider='fixture', model='phase4-integration', dimensions=1536)
VECTOR = [1.0] + [0.0] * 1535


class RedactedDSN(str):
    def __repr__(self):
        return '<redacted database connection>'


def snapshot(url):
    with psycopg.connect(url) as conn:
        tables = conn.execute("SELECT schemaname,tablename FROM pg_tables WHERE schemaname='ops' OR (schemaname='public' AND tablename='kb_chunks') ORDER BY 1,2").fetchall()
        return {f'{schema}.{table}': conn.execute(sql.SQL('SELECT row_to_json(t)::text FROM {}.{} t ORDER BY 1').format(sql.Identifier(schema), sql.Identifier(table))).fetchall()
                for schema, table in tables}


@pytest.fixture(scope='module')
def investigation_db():
    url = RedactedDSN(os.getenv('TEST_DATABASE_URL', ''))
    if not url:
        pytest.skip('Set TEST_DATABASE_URL to a separate disposable database.')
    name = conninfo_to_dict(url).get('dbname', '')
    app = os.getenv('DATABASE_URL', '')
    if not name.endswith('_test') or (app and name == conninfo_to_dict(app).get('dbname')):
        pytest.fail('Refusing investigation tests outside a separate _test database.')
    with psycopg.connect(url) as conn:
        conn.execute('DROP SCHEMA IF EXISTS ops CASCADE')
    initialize(url)
    seed(url)
    store = PgvectorStore(url)
    store.initialize()
    chunks = load_chunks(Path('knowledge_base'))[:3]
    store.replace(chunks, [VECTOR, [0., 1.] + [0.] * 1534, [0., 0., 1.] + [0.] * 1533], SPEC)
    before = snapshot(url)
    yield url
    assert snapshot(url) == before, 'Investigation tests must leave operational and KB data unchanged.'
    with psycopg.connect(url) as conn:
        conn.execute('DROP SCHEMA ops CASCADE')
        conn.execute('DELETE FROM public.kb_chunks')


@pytest.fixture
def reader_pair(investigation_db, tmp_path):
    token = secrets.token_hex(4)
    ops_role = 'northstar_ops_test_' + token + '_reader'
    kb_role = 'northstar_kb_test_' + token + '_reader'
    paths = [tmp_path / '.env.ops', tmp_path / '.env.kb']
    created = []
    try:
        provision_reader(investigation_db, paths[0], role=ops_role)
        created.append(ops_role)
        provision_kb_reader(investigation_db, paths[1], role=kb_role)
        created.append(kb_role)
        ops_url, kb_url = [RedactedDSN(json.loads(p.read_text().split('=', 1)[1])) for p in paths]
        yield OperationalDB(ops_url), ReadOnlyKBStore(kb_url), ops_url, kb_url, kb_role
    finally:
        with psycopg.connect(investigation_db, autocommit=True) as conn:
            for role in reversed(created):
                conn.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
                conn.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))


def decisions(*items):
    return [{'kind': 'lookup', 'tool': tool, 'arguments': args} for tool, args in items] + [{'kind': 'finish'}]


@pytest.mark.parametrize('items', [
    [('get_employee_devices', {'employee_id': 'EMP-001'}), ('get_device_details', {'device_id': 'DEV-001'})],
    [('get_employee_account_status', {'employee_id': 'EMP-001'}), ('get_recent_support_tickets', {'employee_id': 'EMP-001'})],
    [('check_software_entitlement', {'employee_id': 'EMP-001', 'software_id': 'SW-001'}), ('get_active_service_incidents', {'service_id': 'SVC-001'})],
])
def test_real_graph_all_six_tools_and_pgvector_preserve_data(investigation_db, reader_pair, inv_request, inv_dependencies, items):
    db, store, *_ = reader_pair
    before = snapshot(investigation_db)
    deps = replace(inv_dependencies, db=db, store=store, fixture_lookup=None,
                   embedder=ScriptedEmbedder(build_query(inv_request.ticket), SPEC, VECTOR), planner=ScriptedPlanner(decisions(*items)))
    result = run_investigation(inv_request, dependencies=deps)
    assert result.status == 'completed', result.errors
    assert result.lookup_attempts == 2 and len(result.operational_evidence) == 2
    assert len(result.kb_evidence) == 3 and result.kb_evidence[0].result.distance == pytest.approx(0)
    assert all(not e.observation.result.live_verified for e in result.operational_evidence)
    assert snapshot(investigation_db) == before


@pytest.mark.parametrize('statement', [
    'SELECT * FROM ops.employees', 'SELECT * FROM ops.accounts',
    'UPDATE public.kb_chunks SET content=content', 'DELETE FROM public.kb_chunks',
    'TRUNCATE public.kb_chunks', 'CREATE TABLE public.forbidden (id INT)',
    'UPDATE ops.accounts SET password_expired=true',
])
def test_kb_reader_cannot_write_or_read_ops_even_without_readonly_default(reader_pair, statement):
    _, _, _, url, _ = reader_pair
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute('SET default_transaction_read_only=off')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(statement)


def test_kb_connection_readonly_and_no_write_api(reader_pair):
    store = reader_pair[1]
    with store._connection() as conn:
        assert conn.execute('SHOW transaction_read_only').fetchone()['transaction_read_only'] == 'on'
        assert conn.execute('SHOW transaction_isolation').fetchone()['transaction_isolation'] == 'repeatable read'
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute('UPDATE public.kb_chunks SET content=content')
    with pytest.raises(KBAccessError):
        store.initialize()
    with pytest.raises(KBAccessError):
        store.replace([], [], SPEC)


@pytest.mark.parametrize('grant', [
    'GRANT SELECT ON ops.employees TO {}',
    'GRANT SELECT (employee_id) ON ops.employees TO {}',
    'GRANT UPDATE (content) ON public.kb_chunks TO {}',
    'GRANT pg_read_all_data TO {}',
])
def test_kb_runtime_rejects_broadened_grants(investigation_db, reader_pair, grant):
    store, role = reader_pair[1], reader_pair[4]
    with psycopg.connect(investigation_db) as conn:
        conn.execute(sql.SQL(grant).format(sql.Identifier(role)))
    with pytest.raises(KBAccessError):
        store.manifest()


def test_admin_or_ops_credentials_rejected_for_kb(investigation_db, reader_pair):
    for url in [investigation_db, reader_pair[2]]:
        with pytest.raises(KBAccessError):
            ReadOnlyKBStore(url).manifest()


def test_graph_preserves_kb_when_operations_credentials_are_wrong(investigation_db, reader_pair, inv_request, inv_dependencies):
    deps = replace(inv_dependencies, db=OperationalDB(investigation_db), store=reader_pair[1], fixture_lookup=None,
                   embedder=ScriptedEmbedder(build_query(inv_request.ticket), SPEC, VECTOR),
                   planner=ScriptedPlanner(decisions(('get_employee_devices', {'employee_id': 'EMP-001'}))))
    result = run_investigation(inv_request, dependencies=deps)
    assert result.status == 'partial' and result.stop_reason == 'lookup_failed'
    assert result.kb_evidence and not result.operational_evidence
    assert result.lookup_trace[0].executed and result.lookup_attempts == 1


def test_provisioning_refuses_existing_role_and_never_overwrites_file(investigation_db, reader_pair, tmp_path):
    path = tmp_path / '.env.existing'
    path.write_text('local marker', encoding='utf-8')
    role = 'northstar_kb_test_' + secrets.token_hex(4) + '_reader'
    with pytest.raises(KBAccessError):
        provision_kb_reader(investigation_db, path, role=role)
    assert path.read_text() == 'local marker'
    with psycopg.connect(investigation_db) as conn:
        assert conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone() is None
    with pytest.raises(KBAccessError):
        provision_kb_reader(investigation_db, tmp_path / '.env.new', role=reader_pair[4])
    assert not (tmp_path / '.env.new').exists()


def test_postgres_cli_uses_both_real_readers(reader_pair, inv_request, inv_dependencies, monkeypatch, tmp_path, capsys):
    from app.cli import main

    monkeypatch.setenv('OPS_DATABASE_URL', reader_pair[2])
    monkeypatch.setenv('KB_READER_DATABASE_URL', reader_pair[3])
    payload = {
        'request': inv_request.model_dump(mode='json'), 'classification': inv_dependencies.classifier.result.model_dump(),
        'embedding_spec': SPEC.model_dump(), 'query_vector': VECTOR,
        'decisions': decisions(('get_employee_devices', {'employee_id': 'EMP-001'})),
    }
    path = tmp_path / 'script.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    assert main(['investigate', 'scripted', '--script', str(path), '--backend', 'postgres']) == 0
    data = json.loads(capsys.readouterr().out)
    assert data['backend'] == 'postgres' and data['result']['status'] == 'completed'
    assert len(data['result']['operational_evidence'][0]['observation']['result']['devices']) == 2


@pytest.mark.parametrize('items', [
    [('get_employee_devices', {'employee_id': 'EMP-001'}), ('get_device_details', {'device_id': 'DEV-001'})],
    [('get_employee_account_status', {'employee_id': 'EMP-001'}), ('get_recent_support_tickets', {'employee_id': 'EMP-001', 'limit': 5, 'since': None})],
    [('check_software_entitlement', {'employee_id': 'EMP-001', 'software_id': 'SW-001'}), ('get_active_service_incidents', {'service_id': 'SVC-001', 'limit': 5})],
])
def test_mocked_llm_with_real_pgvector_and_all_operational_tools(investigation_db, reader_pair, inv_request, inv_dependencies, planner_client, planner_response, items):
    import httpx
    from app.providers.openai_planner import OpenAIPlanner

    requests = []
    choices = decisions(*items)
    def handler(request):
        payload = json.loads(json.loads(request.content)['input'][1]['content'])
        index = len(requests)
        requests.append(payload)
        assert len(payload['untrusted_evidence']['operational_observations']) == index
        return httpx.Response(200, json=planner_response(choices[index]))
    before = snapshot(investigation_db)
    deps = replace(inv_dependencies, db=reader_pair[0], store=reader_pair[1], fixture_lookup=None,
                   embedder=ScriptedEmbedder(build_query(inv_request.ticket), SPEC, VECTOR),
                   planner=OpenAIPlanner(planner_client(handler)), phase='4B.1')
    result = run_investigation(inv_request, dependencies=deps)
    assert result.status == 'completed' and result.phase == '4B.1'
    assert result.lookup_attempts == 2 and len(requests) == 3
    assert result.kb_evidence[0].result.distance == pytest.approx(0)
    assert all(not e.observation.result.live_verified for e in result.operational_evidence)
    if items[0][0] == 'get_employee_devices':
        assert requests[1]['control']['available_device_ids'] == ['DEV-001', 'DEV-010']
    assert snapshot(investigation_db) == before


@pytest.mark.parametrize('invalid', [False, True])
@pytest.mark.parametrize('conditional', [False, True])
def test_grounded_synthesis_uses_actual_readonly_evidence(investigation_db, reader_pair, inv_request,
        inv_dependencies, planner_client, planner_response, synthesis_report, as_synthesis_draft, invalid, conditional):
    import httpx
    from app.providers.openai_synthesis import OpenAISynthesis

    calls = []
    def handler(request):
        payload = json.loads(json.loads(request.content)['input'][1]['content'])
        calls.append(payload)
        kb = payload['untrusted_evidence']['kb_procedures'][0]
        observation = payload['untrusted_evidence']['operational_observations'][0]
        synthesis_report['steps'][0]['references'][0]['chunk_id'] = 'fabricated' if invalid and not conditional else kb['reference']['chunk_id']
        synthesis_report['steps'][0]['action'] = kb['result']['chunk']['content'].split('. ')[0] + '.'
        synthesis_report['findings'] = [{'text': 'The recorded account is enabled; this is not verified live state.',
                                         'references': [observation['reference']]}]
        assert observation['observation']['result']['account']['observed_at']
        assert not observation['observation']['result']['live_verified']
        if conditional:
            # Contract/source-membership exercise, not a semantic-quality score.
            synthesis_report['conditional_guidance'] = [{
                'condition': 'If the documented issue recurs.', 'action': 'If it recurs, follow the documented procedure.',
                'references': [{'kind': 'kb_chunk', 'chunk_id': 'fabricated' if invalid else kb['reference']['chunk_id']}],
                'missing_evidence': 'Whether this issue recurs.',
            }]
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(as_synthesis_draft(synthesis_report))))
    before = snapshot(investigation_db)
    deps = replace(inv_dependencies, db=reader_pair[0], store=reader_pair[1], fixture_lookup=None,
        embedder=ScriptedEmbedder(build_query(inv_request.ticket), SPEC, VECTOR),
        planner=ScriptedPlanner(decisions(('get_employee_account_status', {'employee_id': 'EMP-001'}))),
        synthesis=OpenAISynthesis(planner_client(handler)))
    result = run_investigation(inv_request, dependencies=deps)
    assert result.status == ('partial' if invalid else 'completed')
    assert result.synthesis_status == ('failed' if invalid else 'completed')
    assert result.phase == '4B.2' and result.synthesis_attempts == len(calls) == 1
    assert result.lookup_attempts == 1 and len(result.operational_evidence) == 1
    if conditional and not invalid:
        assert result.recommendation.conditional_guidance and not result.recommendation.escalation_required
    assert result.kb_evidence[0].result.distance == pytest.approx(0)
    assert snapshot(investigation_db) == before


def test_live_evaluation_readonly_audit_detects_incomplete_corpus(investigation_db, reader_pair):
    from evaluation.live_investigation import database_audit

    before = snapshot(investigation_db)
    first = database_audit(reader_pair[1], reader_pair[0])
    assert first == database_audit(reader_pair[1], reader_pair[0])
    assert all(row['matches_frozen_inputs'] for name, row in first.items() if name.startswith('ops.'))
    # This integration fixture deliberately indexes three chunks, not the frozen 36.
    assert first['public.kb_chunks']['rows'] == 3
    assert not first['public.kb_chunks']['matches_frozen_inputs']
    assert snapshot(investigation_db) == before


@pytest.mark.parametrize('variant', ['ok', 'unknown_observation', 'unknown_policy', 'not_found'])
def test_v3_trigger_uses_only_successful_restricted_observations(investigation_db, reader_pair, inv_request,
        inv_dependencies, planner_client, planner_response, synthesis_report, as_synthesis_draft, variant):
    import httpx
    from app.providers.openai_synthesis import OpenAISynthesis

    employee = 'EMP-999' if variant == 'not_found' else 'EMP-001'
    request = inv_request.model_copy(update={'employee_id': employee})
    calls = []
    def handler(api_request):
        payload = json.loads(json.loads(api_request.content)['input'][1]['content'])
        calls.append(payload)
        evidence = payload['untrusted_evidence']
        kb = evidence['kb_procedures'][0]['reference']
        observation = evidence['operational_observations'][0]
        assert observation['observation']['result']['status'] == ('not_found' if variant == 'not_found' else 'ok')
        assert observation['observation']['result']['live_verified'] is False
        synthesis_report['steps'][0].update(step_type='escalation', references=[kb])
        synthesis_report['escalation_required'] = True
        synthesis_report['escalation_reason'] = {'text': 'Authored contract test only; human review must establish applicability.', 'references': [kb]}
        synthesis_report['trigger_basis'] = {
            'policy_references': [kb if variant != 'unknown_policy' else {'kind': 'kb_chunk', 'chunk_id': 'invented'}],
            'factual_references': [observation['reference'] if variant != 'unknown_observation' else {'kind': 'operational_observation', 'lookup_id': 'invented'}],
            'explanation': 'Authored reference-membership claim, not a semantic-quality result. The operational snapshot is not verified live state.',
        }
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(as_synthesis_draft(synthesis_report))))
    before = snapshot(investigation_db)
    deps = replace(inv_dependencies, db=reader_pair[0], store=reader_pair[1], fixture_lookup=None,
        embedder=ScriptedEmbedder(build_query(request.ticket), SPEC, VECTOR),
        planner=ScriptedPlanner(decisions(('get_employee_account_status', {'employee_id': employee}))),
        synthesis=OpenAISynthesis(planner_client(handler)))
    result = run_investigation(request, dependencies=deps)
    assert result.synthesis_attempts == len(calls) == 1
    assert result.lookup_attempts == 1 and len(result.operational_evidence) == 1
    assert result.kb_evidence and result.lookup_trace[0].executed
    if variant == 'ok':
        assert result.synthesis_status == 'completed' and result.recommendation.trigger_basis
    else:
        assert result.status == 'partial' and result.recommendation is None
        assert result.errors[-1].code == 'synthesis_invalid_citation'
    assert snapshot(investigation_db) == before


@pytest.mark.parametrize('admin_arm', ['ops', 'kb'])
def test_live_evaluation_audit_rejects_admin_fallback(investigation_db, reader_pair, admin_arm):
    from app.operations.db import OperationalDataError
    from evaluation.live_investigation import database_audit

    db = OperationalDB(investigation_db) if admin_arm == 'ops' else reader_pair[0]
    store = ReadOnlyKBStore(investigation_db) if admin_arm == 'kb' else reader_pair[1]
    with pytest.raises((OperationalDataError, KBAccessError)):
        database_audit(store, db)


@pytest.mark.parametrize('invalid', [False, True])
def test_live_pair_reuses_real_retrieval_and_readonly_lookups(investigation_db, reader_pair, inv_dependencies,
        planner_response, synthesis_report, as_synthesis_draft, invalid):
    import httpx
    from openai import OpenAI
    from app.providers.openai_planner import OpenAIPlanner
    from app.providers.openai_synthesis import OpenAISynthesis
    from app.providers.openai_recommendation import OpenAIRecommendation
    from evaluation.live_investigation import run_pair, select_cases, project_report, database_audit
    from evaluation.live_telemetry import MeteredTransport

    case = select_cases(['vpn-confirmed'])[0]
    choices = iter(decisions(('get_employee_account_status', {'employee_id': 'EMP-001'})))
    actual_kb_ids = []
    def handler(request):
        raw = json.loads(request.content)
        payload = json.loads(raw['input'][1]['content'])
        schema = raw['text']['format']['name']
        if schema == 'PlannerResponse':
            body = planner_response(next(choices))
        elif schema == 'InvestigationSynthesisDraftV3':
            evidence = payload['untrusted_evidence']
            actual_kb_ids.extend(e['reference']['chunk_id'] for e in evidence['kb_procedures'])
            assert evidence['operational_observations'][0]['observation']['result']['account']['observed_at']
            assert not evidence['operational_observations'][0]['observation']['result']['live_verified']
            synthesis_report['steps'][0]['references'][0]['chunk_id'] = 'invented' if invalid else actual_kb_ids[0]
            body = planner_response(raw_text=json.dumps(as_synthesis_draft(synthesis_report)))
        else:
            assert [e['chunk_id'] for e in payload['evidence']] == actual_kb_ids
            assert set(payload) == {'ticket', 'evidence'}
            report = project_report(synthesis_report)
            report['steps'][0]['supporting_chunk_ids'] = [actual_kb_ids[0]]
            body = planner_response(raw_text=json.dumps(report))
        return httpx.Response(200, json=body)

    before = database_audit(reader_pair[1], reader_pair[0])
    meter = MeteredTransport(httpx.MockTransport(handler))
    with OpenAI(api_key='test-placeholder', max_retries=0, http_client=httpx.Client(transport=meter)) as client:
        deps = replace(inv_dependencies, db=reader_pair[0], store=reader_pair[1], fixture_lookup=None,
            embedder=ScriptedEmbedder(build_query(case.request.ticket), SPEC, VECTOR),
            planner=OpenAIPlanner(client), synthesis=OpenAISynthesis(client), phase='4B.1')
        row = run_pair(case, dependencies=deps, standalone=OpenAIRecommendation(client), meter=meter)
    assert row['agent']['outcome'] == ('rejected' if invalid else 'accepted')
    assert row['standalone']['outcome'] == 'accepted'
    assert len(row['agent_result']['operational_evidence']) == 1
    assert row['agent_result']['lookup_attempts'] == 1
    assert len(row['shared_kb']) == 3 and row['shared_retrieval_succeeded']
    assert before == database_audit(reader_pair[1], reader_pair[0])
