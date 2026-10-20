"""Administrative setup and independently restricted runtime connections."""

from hashlib import sha256
from importlib.resources import files
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import secrets

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

SETUP_LOCK = 310019


class OperationalDataError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class OperationalDataIntegrityError(OperationalDataError):
    def __init__(self) -> None:
        super().__init__('invalid_stored_data', 'Operational records violate the expected contract.')


def admin_url() -> str:
    value = os.getenv('DATABASE_URL', '')
    if not value.strip():
        raise OperationalDataError('configuration_error', 'Set DATABASE_URL for administrative setup.')
    return value


def catalog_signature(conn: psycopg.Connection) -> str:
    """Detect drift in this small schema without adding a migration framework."""
    rows = conn.execute("""
        SELECT 'column', c.relname, a.attname,
               format_type(a.atttypid, a.atttypmod) || ':' || a.attnotnull::text
        FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='ops' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
        UNION ALL
        SELECT 'constraint', c.relname, k.conname, pg_get_constraintdef(k.oid)
        FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='ops'
        UNION ALL
        SELECT 'index', tablename, indexname, indexdef FROM pg_indexes WHERE schemaname='ops'
        ORDER BY 1,2,3,4
    """).fetchall()
    return sha256(json.dumps(rows).encode()).hexdigest()


def initialize(database_url: str) -> None:
    script = files('app.operations').joinpath('schema.sql').read_text(encoding='utf-8')
    prefix = 'northstar-ops-v1:' + sha256(script.encode()).hexdigest() + ':'
    try:
        with psycopg.connect(database_url, connect_timeout=10) as conn:
            conn.execute('SELECT pg_advisory_xact_lock(%s)', (SETUP_LOCK,))
            existing = conn.execute("SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname='ops'").fetchone()
            if existing:
                if existing[0] != prefix + catalog_signature(conn):
                    raise OperationalDataError('schema_mismatch', 'Existing ops schema differs; review an explicit migration.')
            else:
                conn.execute(script)
                conn.execute(sql.SQL('COMMENT ON SCHEMA ops IS {}').format(sql.Literal(prefix + catalog_signature(conn))))
    except psycopg.Error:
        raise OperationalDataError('database_error', 'Operational schema initialization failed.') from None


def assert_reader(conn: psycopg.Connection, role: str | None = None) -> None:
    """Fail closed on broad credentials; this is not employee authorization."""
    if role is None:
        identity = conn.execute('SELECT session_user AS name, current_user AS effective').fetchone()
        if identity['name'] != identity['effective']:
            raise OperationalDataError('unsafe_credentials', 'Operational login must not impersonate another role.')
        role = identity['name']
    flags = conn.execute("""SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls AS unsafe
                            FROM pg_roles WHERE rolname=%s""", (role,)).fetchone()
    memberships = conn.execute("""SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
                                  WHERE r.rolname=%s LIMIT 1""", (role,)).fetchone()
    if not flags or flags['unsafe'] or memberships:
        raise OperationalDataError('unsafe_credentials', 'Operational tools require a restricted reader role without memberships.')
    # Also reject inherited PUBLIC privileges, ownership and grants outside ops.
    tables = conn.execute("""SELECT n.nspname, c.relname,
        has_table_privilege(%s,c.oid,'SELECT') AS full_read,
        has_any_column_privilege(%s,c.oid,'SELECT') AS can_read,
        (has_table_privilege(%s,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
         OR has_any_column_privilege(%s,c.oid,'INSERT,UPDATE,REFERENCES')) AS can_write
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE c.relkind IN ('r','p','v','m','f')
        AND n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%%'
        AND n.nspname NOT LIKE 'pg_temp_%%'""", (role, role, role, role)).fetchall()
    from app.operations.records import TABLE_MODELS
    allowed = set(TABLE_MODELS)
    seen = set()
    for row in tables:
        expected = row['nspname'] == 'ops' and row['relname'] in allowed
        if row['can_write'] or (row['can_read'] and not expected):
            raise OperationalDataError('unsafe_credentials', 'Reader has unexpected table privileges; review grants.')
        if expected and row['full_read']:
            seen.add(row['relname'])
    creates = conn.execute("""SELECT 1 FROM pg_namespace
        WHERE nspname NOT LIKE 'pg_temp_%%' AND nspname NOT LIKE 'pg_toast%%'
        AND has_schema_privilege(%s,oid,'CREATE') LIMIT 1""", (role,)).fetchone()
    db_create = conn.execute("SELECT has_database_privilege(%s,current_database(),'CREATE') AS allowed", (role,)).fetchone()
    definer = conn.execute("""SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE p.prosecdef AND n.nspname NOT IN ('pg_catalog','information_schema')
        AND has_function_privilege(%s,p.oid,'EXECUTE') LIMIT 1""", (role,)).fetchone()
    if seen != allowed or creates or db_create['allowed'] or definer:
        raise OperationalDataError('unsafe_credentials', 'Reader grants are missing or permit schema creation.')


class OperationalDB:
    def __init__(self, database_url: str) -> None:
        if not database_url.strip():
            raise OperationalDataError('configuration_error', 'Set OPS_DATABASE_URL with restricted reader credentials.')
        self._database_url = database_url

    @classmethod
    def from_environment(cls) -> 'OperationalDB':
        return cls(os.getenv('OPS_DATABASE_URL', ''))

    @contextmanager
    def connection(self):
        try:
            with psycopg.connect(self._database_url, connect_timeout=5, row_factory=dict_row) as conn:
                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                conn.execute("SET LOCAL statement_timeout = '5s'")
                conn.execute('SET LOCAL search_path = pg_catalog')
                assert_reader(conn)
                yield conn
        except psycopg.Error:
            raise OperationalDataError('database_error', 'Operational database request failed.') from None


def provision_reader(database_url: str, env_file: Path, *, role: str = 'northstar_ops_reader') -> None:
    """Administrative bootstrap only. Never prints or overwrites credentials."""
    if not re.fullmatch(r'northstar_ops_(?:test_[a-f0-9]{8}_)?reader', role):
        raise OperationalDataError('configuration_error', 'Unexpected operational reader role name.')
    if not env_file.name.startswith('.env.') or env_file.name == '.env.example':
        raise OperationalDataError('configuration_error', 'Use an ignored .env.* file for reader credentials.')
    password = secrets.token_urlsafe(32)
    wrote_file = False
    try:
        with psycopg.connect(database_url, connect_timeout=10, row_factory=dict_row) as conn:
            conn.execute('SELECT pg_advisory_xact_lock(%s)', (SETUP_LOCK,))
            if conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
                raise OperationalDataError('reader_exists', 'Reader role already exists; reuse its local credentials or perform an explicit credential rotation.')
            database = conn.execute('SELECT current_database() AS name').fetchone()['name']
            conn.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS').format(
                sql.Identifier(role), sql.Literal(password)))
            grants = files('app.operations').joinpath('reader_permissions.sql').read_text(encoding='utf-8')
            conn.execute(sql.SQL(grants).format(database=sql.Identifier(database), reader=sql.Identifier(role)))
            assert_reader(conn, role)
            settings = conninfo_to_dict(database_url)
            settings.update(user=role, password=password, dbname=database)
            # A quoted libpq conninfo value is accepted by psycopg and uv env-file loading.
            value = make_conninfo(**settings)
            with env_file.open('x', encoding='utf-8') as output:
                wrote_file = True
                output.write('OPS_DATABASE_URL=' + json.dumps(value) + '\n')
    except (psycopg.Error, OSError):
        if wrote_file:
            env_file.unlink(missing_ok=True)
        raise OperationalDataError('provisioning_failed', 'Reader provisioning failed; check admin access and use a new local env file.') from None
