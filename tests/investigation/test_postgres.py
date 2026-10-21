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
