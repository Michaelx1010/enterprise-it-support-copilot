from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import Mock

import psycopg
import pytest
from pydantic import ValidationError

from app.operations import schemas as s, tools, queries
from app.operations.db import OperationalDB, OperationalDataError, OperationalDataIntegrityError
from app.operations.seed import load_seed

NOW = datetime(2026, 10, 19, 8, tzinfo=timezone.utc)


class FakeDB:
    @contextmanager
    def connection(self):
        conn = Mock()
        conn.execute.return_value.fetchone.return_value = {'time': NOW}
        yield conn


@pytest.fixture
def facts(monkeypatch):
    tables = load_seed()
    def projection(name, columns, index=0):
        row = tables[name][index].model_dump()
        return {key: row[key] for key in columns.split(',')}
    values = {
        'employee': projection('employees', queries.EMPLOYEE_COLUMNS),
        'account': projection('accounts', queries.ACCOUNT_COLUMNS),
        'device': projection('devices', queries.DEVICE_COLUMNS),
        'software': projection('software_products', queries.SOFTWARE_COLUMNS),
        'entitlement': projection('software_entitlements', queries.ENTITLEMENT_COLUMNS, 3),
        'service': projection('services', queries.SERVICE_COLUMNS),
    }
    values['devices'] = [values['device'], projection('devices', queries.DEVICE_COLUMNS, 9)]
    values['tickets'] = [projection('support_tickets', queries.TICKET_COLUMNS, i) for i in (0, 1, 2)]
    values['incidents'] = [projection('service_incidents', queries.INCIDENT_COLUMNS)]
    for key, value in values.items():
        monkeypatch.setattr(queries, key, Mock(return_value=value))
    return values


CASES = [
    (tools.get_employee_account_status, s.EmployeeInput(employee_id='EMP-001')),
    (tools.get_employee_devices, s.EmployeeInput(employee_id='EMP-001')),
    (tools.get_device_details, s.DeviceInput(device_id='DEV-001')),
    (tools.check_software_entitlement, s.EntitlementInput(employee_id='EMP-001', software_id='SW-001')),
    (tools.get_recent_support_tickets, s.RecentTicketsInput(employee_id='EMP-001', limit=2)),
    (tools.get_active_service_incidents, s.ActiveIncidentsInput(service_id='SVC-001')),
]


@pytest.mark.parametrize('function,tool_input', CASES)
def test_each_tool_returns_validated_recorded_facts(function, tool_input, facts):
    result = function(tool_input, db=FakeDB())
    assert result.status == 'ok'
    assert result.queried_at == NOW
    assert result.data_kind == 'synthetic_snapshot' and result.live_verified is False
    assert 'email' not in result.model_dump_json()
    assert 'username' not in result.model_dump_json()
    assert 'description' not in result.model_dump_json()


@pytest.mark.parametrize('function,tool_input', CASES)
def test_each_tool_distinguishes_unknown_parent(function, tool_input, facts):
    for name in ('employee', 'device', 'software', 'service'):
        getattr(queries, name).return_value = None
    result = function(tool_input, db=FakeDB())
    assert result.status == 'not_found' and result.missing_entities


def test_known_employee_without_account_or_devices_is_not_unknown(facts):
    queries.account.return_value = None
    queries.devices.return_value = []
    assert tools.get_employee_account_status(CASES[0][1], db=FakeDB()).account is None
    result = tools.get_employee_devices(CASES[1][1], db=FakeDB())
    assert result.status == 'ok' and result.devices == []


def test_missing_entitlement_does_not_invent_denial_or_expiry(facts):
    queries.entitlement.return_value = None
    result = tools.check_software_entitlement(CASES[3][1], db=FakeDB())
    assert result.status == 'ok' and result.entitlement is None and result.license_expired is None


@pytest.mark.parametrize('expiry,expected', [
    (datetime(2026, 10, 19, 8, tzinfo=timezone.utc), True),
    (datetime(2027, 10, 19, 8, tzinfo=timezone.utc), False),
    (None, None),
])
def test_license_expiry_is_comparison_with_query_time_only(facts, expiry, expected):
    facts['entitlement']['license_expires_at'] = expiry
    result = tools.check_software_entitlement(CASES[3][1], db=FakeDB())
    assert result.license_expired is expected
    assert result.entitlement.license_status == 'assigned'  # no inferred live revocation


def test_malformed_expiry_is_sanitized(facts):
    facts['entitlement']['license_expires_at'] = 'not-a-date'
    with pytest.raises(OperationalDataIntegrityError):
        tools.check_software_entitlement(CASES[3][1], db=FakeDB())


def test_stale_observation_does_not_change_recorded_state(facts):
    result = tools.get_employee_account_status(CASES[0][1], db=FakeDB())
    assert result.account.observed_at < result.queried_at
    assert result.account.account_status == 'enabled'
    result = tools.get_employee_devices(CASES[1][1], db=FakeDB())
    assert result.devices[1].last_seen_at < result.queried_at
    assert result.devices[1].lifecycle_status == 'active'


def test_limit_exposes_more_records_and_preserves_query_inputs(facts):
    tool_input = s.RecentTicketsInput(employee_id='EMP-001', limit=2, since='2026-10-01T00:00:00Z')
    result = tools.get_recent_support_tickets(tool_input, db=FakeDB())
    assert len(result.tickets) == 2 and result.has_more
    assert queries.tickets.call_args.args[1:] == ('EMP-001', 2, tool_input.since)


def test_malformed_stored_output_is_error_not_missing(facts):
    queries.account.return_value = {'private': 'do not expose'}
    with pytest.raises(OperationalDataIntegrityError) as error:
        tools.get_employee_account_status(CASES[0][1], db=FakeDB())
    assert 'private' not in str(error.value)


@pytest.mark.parametrize('function,tool_input', CASES)
def test_database_failure_is_never_empty_success(function, tool_input):
    db = Mock()
    db.connection.side_effect = OperationalDataError('database_error', 'Unavailable.')
    with pytest.raises(OperationalDataError):
        function(tool_input, db=db)


def test_input_is_revalidated_before_opening_connection():
    db = Mock()
    tool_input = s.EmployeeInput.model_construct(employee_id="EMP-001'; DROP TABLE ops.employees;")
    with pytest.raises(ValidationError):
        tools.get_employee_account_status(tool_input, db=db)
    db.connection.assert_not_called()


def test_connection_exception_is_sanitized(monkeypatch):
    monkeypatch.setattr(psycopg, 'connect', Mock(side_effect=psycopg.OperationalError('secret connection string')))
    with pytest.raises(OperationalDataError) as error:
        with OperationalDB('unused').connection():
            pass
    assert error.value.code == 'database_error'
    assert 'secret' not in str(error.value)


def test_no_admin_credential_fallback(monkeypatch):
    monkeypatch.delenv('OPS_DATABASE_URL', raising=False)
    monkeypatch.setenv('DATABASE_URL', 'admin-secret')
    with pytest.raises(OperationalDataError, match='OPS_DATABASE_URL'):
        OperationalDB.from_environment()
