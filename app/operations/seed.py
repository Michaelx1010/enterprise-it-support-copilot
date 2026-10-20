"""Insert deterministic fixtures, refusing conflicts rather than overwriting data."""

from importlib.resources import files
import json

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from pydantic import ValidationError
from pydantic import AwareDatetime, TypeAdapter

from app.operations.db import OperationalDataError, SETUP_LOCK
from app.operations.records import KEYS, TABLE_MODELS


def load_seed() -> dict:
    payload = json.loads(files('app.operations').joinpath('seed_data.json').read_text(encoding='utf-8'))
    if set(payload) != {'version', 'snapshot_at', 'tables'} or payload['version'] != 'northstar-v1':
        raise ValueError('Unexpected seed version or fields.')
    if set(payload['tables']) != set(TABLE_MODELS):
        raise ValueError('Seed table set differs from schema.')
    TypeAdapter(AwareDatetime).validate_python(payload['snapshot_at'])
    tables = {name: [model.model_validate(row) for row in payload['tables'][name]]
              for name, model in TABLE_MODELS.items()}
    for name, rows in tables.items():
        keys = [tuple(getattr(row, key) for key in KEYS[name]) for row in rows]
        if len(keys) != len(set(keys)):
            raise ValueError('Duplicate seed identifier.')
    employees = {row.employee_id: row for row in tables['employees']}
    for employee in employees.values():
        seen = set()
        current = employee
        while current:
            if current.employee_id in seen:
                raise ValueError('Management cycle.')
            seen.add(current.employee_id)
            current = employees[current.manager_id] if current.manager_id else None
    products = {row.software_id: row for row in tables['software_products']}
    for row in tables['software_entitlements']:
        if products[row.software_id].requires_license == (row.license_status == 'not_required'):
            raise ValueError('License requirement mismatch.')
    devices = {row.device_id for row in tables['devices']}
    services = {row.service_id for row in tables['services']}
    incidents = {row.incident_id: row for row in tables['service_incidents']}
    for name, rows in tables.items():
        for row in rows:
            for field in ('employee_id', 'assigned_employee_id', 'approved_by_employee_id'):
                value = getattr(row, field, None)
                if value is not None and value not in employees:
                    raise ValueError('Unknown employee reference.')
            if getattr(row, 'service_id', None) is not None and row.service_id not in services:
                raise ValueError('Unknown service reference.')
    for row in tables['accounts']:
        if (row.account_status == 'locked') != (row.locked_at is not None):
            raise ValueError('Lock timestamp mismatch.')
        if any(t and t > row.observed_at for t in (row.locked_at, row.last_successful_login_at)):
            raise ValueError('Observation precedes event.')
    for row in tables['software_entitlements']:
        if (row.approved_at is None) != (row.approved_by_employee_id is None):
            raise ValueError('Incomplete approval.')
        if row.license_expires_at and row.license_status != 'assigned':
            raise ValueError('Expiry without assigned license.')
    for row in tables['support_tickets']:
        if row.device_id and row.device_id not in devices:
            raise ValueError('Unknown device reference.')
        if row.incident_id and incidents[row.incident_id].service_id != row.service_id:
            raise ValueError('Incident service mismatch.')
        if row.resolution_summary and row.resolved_at is None:
            raise ValueError('Resolution without timestamp.')
    for row in [*tables['support_tickets'], *tables['service_incidents']]:
        if (row.status in ('resolved', 'closed')) != (row.resolved_at is not None):
            raise ValueError('Resolution state mismatch.')
        start = getattr(row, 'opened_at', None) or row.started_at
        if row.resolved_at and row.resolved_at < start:
            raise ValueError('Resolution precedes opening.')
    return tables


def seed(database_url: str) -> dict[str, int]:
    try:
        tables = load_seed()
    except (ValueError, KeyError, ValidationError):
        raise OperationalDataError('invalid_seed', 'Synthetic fixture validation failed.') from None
    try:
        with psycopg.connect(database_url, connect_timeout=10, row_factory=dict_row) as conn:
            conn.execute('SELECT pg_advisory_xact_lock(%s)', (SETUP_LOCK,))
            # Block competing writes for the duration of comparison and insertion.
            for name in tables:
                conn.execute(sql.SQL('LOCK TABLE ops.{} IN SHARE ROW EXCLUSIVE MODE').format(sql.Identifier(name)))
            counts = {}
            for name, records in tables.items():
                counts[name] = 0
                for record in records:
                    values = record.model_dump()
                    where = sql.SQL(' AND ').join(sql.SQL('{}=%s').format(sql.Identifier(key)) for key in KEYS[name])
                    old = conn.execute(sql.SQL('SELECT * FROM ops.{} WHERE {}').format(sql.Identifier(name), where),
                                       tuple(values[key] for key in KEYS[name])).fetchone()
                    if old is not None:
                        if old != values:
                            raise OperationalDataError('seed_conflict', 'Existing fixture record differs; no records were overwritten.')
                        continue
                    conn.execute(sql.SQL('INSERT INTO ops.{} ({}) VALUES ({})').format(
                        sql.Identifier(name), sql.SQL(',').join(map(sql.Identifier, values)),
                        sql.SQL(',').join(sql.Placeholder() for _ in values)), tuple(values.values()))
                    counts[name] += 1
            return counts
    except psycopg.Error:
        raise OperationalDataError('database_error', 'Synthetic seed transaction failed and was rolled back.') from None
