"""Real PostgreSQL constraints and isolation; cleanup only in a separate test DB."""

import os
import json
import secrets

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
import pytest

from app.kb.store import PgvectorStore
from app.operations.db import OperationalDataError, initialize
from app.operations.seed import seed
from app.operations.db import OperationalDB, provision_reader
from app.operations import schemas as s, tools

pytestmark = pytest.mark.integration


class RedactedDSN(str):
    """Prevent pytest argument representations from disclosing local credentials."""

    def __repr__(self):
        return '<redacted database connection>'


@pytest.fixture
def ops_url():
    url = RedactedDSN(os.getenv('TEST_DATABASE_URL', ''))
    if not url:
        pytest.skip('Set TEST_DATABASE_URL to a separate disposable database.')
    settings = conninfo_to_dict(url)
    if not settings.get('dbname', '').endswith('_test'):
        pytest.fail('Refusing operational tests outside a _test database.')
    app_url = os.getenv('DATABASE_URL', '')
    if app_url and settings.get('dbname') == conninfo_to_dict(app_url).get('dbname'):
        pytest.fail('Test database must differ from application database.')
    with psycopg.connect(url) as conn:
        conn.execute('DROP SCHEMA IF EXISTS ops CASCADE')
    initialize(url)
    seed(url)
    yield url
    with psycopg.connect(url) as conn:
        conn.execute('DROP SCHEMA ops CASCADE')


def snapshot(url):
    with psycopg.connect(url) as conn:
        tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='ops' ORDER BY tablename").fetchall()
        return {name: conn.execute(sql.SQL('SELECT row_to_json(t)::text FROM ops.{} t ORDER BY 1').format(sql.Identifier(name))).fetchall()
                for (name,) in tables}


def test_initialization_and_seed_are_idempotent(ops_url):
    before = snapshot(ops_url)
    initialize(ops_url)
    assert all(count == 0 for count in seed(ops_url).values())
    assert snapshot(ops_url) == before
    assert {name: len(rows) for name, rows in before.items()} == {
        'employees': 10, 'accounts': 9, 'devices': 12, 'software_products': 5,
        'software_entitlements': 12, 'services': 6, 'service_incidents': 5, 'support_tickets': 20,
    }


@pytest.mark.parametrize('incident,service,valid', [
    ('INC-001', None, False), ('INC-999', None, False),
    ('INC-001', 'SVC-002', False), ('INC-999', 'SVC-001', False),
    (None, 'SVC-999', False), ('INC-001', 'SVC-001', True),
    (None, 'SVC-001', True), (None, None, True),
])
def test_nullable_incident_service_combinations(ops_url, incident, service, valid):
    with psycopg.connect(ops_url) as conn:
        if valid:
            conn.execute("UPDATE ops.support_tickets SET incident_id=%s,service_id=%s WHERE ticket_id='TKT-001'", (incident, service))
        else:
            with pytest.raises(psycopg.IntegrityError):
                conn.execute("UPDATE ops.support_tickets SET incident_id=%s,service_id=%s WHERE ticket_id='TKT-001'", (incident, service))
            conn.rollback()


@pytest.mark.parametrize('statement', [
    "UPDATE ops.devices SET assigned_employee_id='EMP-999' WHERE device_id='DEV-001'",
    "UPDATE ops.employees SET manager_id=employee_id WHERE employee_id='EMP-001'",
    "UPDATE ops.accounts SET locked_at=NULL WHERE account_id='ACC-002'",
    "UPDATE ops.accounts SET employee_id='EMP-001' WHERE account_id='ACC-002'",
    "UPDATE ops.software_entitlements SET approved_at=NULL WHERE employee_id='EMP-004'",
    "UPDATE ops.service_incidents SET resolved_at=NULL WHERE incident_id='INC-002'",
    "UPDATE ops.service_incidents SET resolved_at='2020-01-01Z' WHERE incident_id='INC-002'",
    "UPDATE ops.support_tickets SET status='resolved' WHERE ticket_id='TKT-001'",
    "UPDATE ops.devices SET compliance_status='safe' WHERE device_id='DEV-001'",
    "DELETE FROM ops.employees WHERE employee_id='EMP-001'",
])
def test_database_rejects_invalid_relationships_and_states(ops_url, statement):
    with psycopg.connect(ops_url) as conn:
        with pytest.raises(psycopg.IntegrityError):
            conn.execute(statement)
        conn.rollback()


def test_seed_conflict_rolls_back_missing_rows_and_preserves_unrelated_data(ops_url):
    with psycopg.connect(ops_url) as conn:
        conn.execute("DELETE FROM ops.accounts WHERE account_id='ACC-001'")
        conn.execute("UPDATE ops.support_tickets SET subject='Changed locally' WHERE ticket_id='TKT-020'")
        conn.execute("INSERT INTO ops.services SELECT 'SVC-999','Unrelated service',owner_team,created_at,updated_at FROM ops.services LIMIT 1")
    before = snapshot(ops_url)
    with pytest.raises(OperationalDataError, match='differs'):
        seed(ops_url)
    assert snapshot(ops_url) == before


def test_seed_inserts_missing_rows_without_deleting_unrelated_data(ops_url):
    with psycopg.connect(ops_url) as conn:
        conn.execute("DELETE FROM ops.accounts WHERE account_id='ACC-001'")
        conn.execute("INSERT INTO ops.services SELECT 'SVC-999','Unrelated service',owner_team,created_at,updated_at FROM ops.services LIMIT 1")
    assert seed(ops_url)['accounts'] == 1
    assert len(snapshot(ops_url)['services']) == 7


def test_schema_drift_is_not_silently_accepted(ops_url):
    with psycopg.connect(ops_url) as conn:
        conn.execute('ALTER TABLE ops.devices ADD COLUMN surprise TEXT')
    with pytest.raises(OperationalDataError, match='migration'):
        initialize(ops_url)


def test_setup_leaves_kb_bytes_and_vector_unchanged(ops_url):
    PgvectorStore(ops_url).initialize()
    with psycopg.connect(ops_url) as conn:
        conn.execute("""INSERT INTO public.kb_chunks VALUES
            ('ops-sentinel','doc','sentinel.md','Sentinel','section','Section',0,'Preserve me','hash','fake','fake',%s)
            ON CONFLICT (chunk_id) DO NOTHING""", ('[' + ','.join(['1'] + ['0'] * 1535) + ']',))
        before = conn.execute('SELECT row_to_json(k)::text FROM public.kb_chunks k ORDER BY chunk_id').fetchall()
    try:
        initialize(ops_url)
        seed(ops_url)
        with psycopg.connect(ops_url) as conn:
            assert conn.execute('SELECT row_to_json(k)::text FROM public.kb_chunks k ORDER BY chunk_id').fetchall() == before
    finally:
        with psycopg.connect(ops_url) as conn:
            conn.execute("DELETE FROM public.kb_chunks WHERE chunk_id='ops-sentinel'")


@pytest.fixture
def reader(ops_url, tmp_path):
    role = 'northstar_ops_test_' + secrets.token_hex(4) + '_reader'
    env_file = tmp_path / '.env.ops'
    provision_reader(ops_url, env_file, role=role)
    url = RedactedDSN(json.loads(env_file.read_text().split('=', 1)[1]))
    yield OperationalDB(url), url, role
    with psycopg.connect(ops_url, autocommit=True) as conn:
        conn.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
        conn.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))


def test_all_six_tools_and_snapshot_metadata(reader):
    db, _, _ = reader
    result = tools.get_employee_account_status(s.EmployeeInput(employee_id='EMP-002'), db=db)
    assert result.account.account_status == 'locked'
    assert result.account.observed_at.isoformat() == '2026-10-16T08:00:00+00:00'
    assert result.live_verified is False and result.data_kind == 'synthetic_snapshot'
    result = tools.get_employee_devices(s.EmployeeInput(employee_id='EMP-001'), db=db)
    assert [d.device_id for d in result.devices] == ['DEV-001', 'DEV-010']
    assert result.devices[1].lifecycle_status == 'active'  # stale last_seen is not a live-status inference
    result = tools.get_device_details(s.DeviceInput(device_id='DEV-012'), db=db)
    assert result.status == 'ok' and result.owner is None
    result = tools.check_software_entitlement(s.EntitlementInput(employee_id='EMP-004', software_id='SW-001'), db=db)
    assert result.entitlement.access_status == 'pending' and result.entitlement.license_status == 'assigned'
    result = tools.get_recent_support_tickets(s.RecentTicketsInput(employee_id='EMP-001', limit=2), db=db)
    assert [t.ticket_id for t in result.tickets] == ['TKT-001', 'TKT-017'] and result.has_more
    result = tools.get_active_service_incidents(s.ActiveIncidentsInput(), db=db)
    assert [i.incident_id for i in result.incidents] == ['INC-001', 'INC-003', 'INC-004']


def test_missing_parents_children_and_empty_filters(reader):
    db, _, _ = reader
    assert tools.get_employee_account_status(s.EmployeeInput(employee_id='EMP-999'), db=db).status == 'not_found'
    result = tools.get_employee_account_status(s.EmployeeInput(employee_id='EMP-010'), db=db)
    assert result.status == 'ok' and result.account is None
    assert tools.get_employee_devices(s.EmployeeInput(employee_id='EMP-010'), db=db).devices == []
    assert tools.get_device_details(s.DeviceInput(device_id='DEV-999'), db=db).status == 'not_found'
    result = tools.check_software_entitlement(s.EntitlementInput(employee_id='EMP-010', software_id='SW-001'), db=db)
    assert result.status == 'ok' and result.entitlement is None and result.license_expired is None
    result = tools.check_software_entitlement(s.EntitlementInput(employee_id='EMP-999', software_id='SW-999'), db=db)
    assert len(result.missing_entities) == 2
    assert tools.get_recent_support_tickets(s.RecentTicketsInput(employee_id='EMP-010'), db=db).tickets == []
    assert tools.get_recent_support_tickets(s.RecentTicketsInput(employee_id='EMP-001', since='2030-01-01T00:00:00Z'), db=db).tickets == []
    result = tools.get_active_service_incidents(s.ActiveIncidentsInput(service_id='SVC-006'), db=db)
    assert result.status == 'ok' and result.incidents == []
    assert tools.get_active_service_incidents(s.ActiveIncidentsInput(service_id='SVC-999'), db=db).status == 'not_found'


@pytest.mark.parametrize('statement', [
    "UPDATE ops.accounts SET account_status='disabled' WHERE account_id='ACC-001'",
    'DELETE FROM ops.support_tickets', 'TRUNCATE ops.devices CASCADE',
    "INSERT INTO ops.services SELECT 'SVC-999','Forbidden',owner_team,created_at,updated_at FROM ops.services LIMIT 1",
    'ALTER TABLE ops.devices ADD COLUMN forbidden TEXT',
    'SELECT * FROM public.kb_chunks', 'DELETE FROM public.kb_chunks',
    'CREATE TABLE ops.forbidden (id INT)',
])
def test_actual_reader_credentials_cannot_write_or_access_kb(ops_url, reader, statement):
    PgvectorStore(ops_url).initialize()
    _, url, _ = reader
    with psycopg.connect(url, autocommit=True) as conn:
        # Disabling the default proves GRANT boundaries, not just read-only transaction defaults.
        conn.execute('SET default_transaction_read_only=off')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(statement)


def test_tool_transaction_is_read_only(reader):
    db, _, _ = reader
    with db.connection() as conn:
        assert conn.execute('SHOW transaction_read_only').fetchone()['transaction_read_only'] == 'on'
        assert conn.execute('SHOW transaction_isolation').fetchone()['transaction_isolation'] == 'repeatable read'
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("UPDATE ops.accounts SET password_expired=true")
        conn.rollback()


def test_runtime_rejects_administrative_credentials(ops_url):
    with pytest.raises(OperationalDataError) as error:
        with OperationalDB(ops_url).connection():
            pass
    assert error.value.code == 'unsafe_credentials'


@pytest.mark.parametrize('privilege', ['SELECT', 'SELECT (content)'])
def test_runtime_rejects_accidental_kb_read_grant(ops_url, reader, privilege):
    PgvectorStore(ops_url).initialize()
    db, _, role = reader
    with psycopg.connect(ops_url) as conn:
        conn.execute(sql.SQL('GRANT {} ON public.kb_chunks TO {}').format(sql.SQL(privilege), sql.Identifier(role)))
    with pytest.raises(OperationalDataError) as error:
        tools.get_employee_account_status(s.EmployeeInput(employee_id='EMP-001'), db=db)
    assert error.value.code == 'unsafe_credentials'


def test_reader_setup_refuses_existing_role_without_rotating_credentials(ops_url, reader, tmp_path):
    _, _, role = reader
    path = tmp_path / '.env.another'
    with pytest.raises(OperationalDataError) as error:
        provision_reader(ops_url, path, role=role)
    assert error.value.code == 'reader_exists' and not path.exists()


def test_runtime_rejects_role_membership(ops_url, reader):
    db, _, role = reader
    with psycopg.connect(ops_url) as conn:
        conn.execute(sql.SQL('GRANT pg_read_all_data TO {}').format(sql.Identifier(role)))
    with pytest.raises(OperationalDataError) as error:
        tools.get_employee_account_status(s.EmployeeInput(employee_id='EMP-001'), db=db)
    assert error.value.code == 'unsafe_credentials'


def test_reader_provisioning_never_overwrites_files_or_existing_role(ops_url, tmp_path):
    role = 'northstar_ops_test_' + secrets.token_hex(4) + '_reader'
    path = tmp_path / '.env.ops'
    path.write_text('existing local content')
    with pytest.raises(OperationalDataError):
        provision_reader(ops_url, path, role=role)
    assert path.read_text() == 'existing local content'
    with psycopg.connect(ops_url) as conn:
        assert conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone() is None


def test_tools_do_not_change_ops_or_kb(ops_url, reader):
    PgvectorStore(ops_url).initialize()
    before = snapshot(ops_url)
    with psycopg.connect(ops_url) as conn:
        kb_before = conn.execute('SELECT row_to_json(k)::text FROM public.kb_chunks k ORDER BY chunk_id').fetchall()
    test_all_six_tools_and_snapshot_metadata(reader)
    assert snapshot(ops_url) == before
    with psycopg.connect(ops_url) as conn:
        assert conn.execute('SELECT row_to_json(k)::text FROM public.kb_chunks k ORDER BY chunk_id').fetchall() == kb_before
