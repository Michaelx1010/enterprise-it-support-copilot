"""Restricted KB connection for investigation; reuse existing pgvector SQL unchanged."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import secrets

from pgvector.psycopg import register_vector
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from app.kb.store import PgvectorStore


class KBAccessError(Exception):
    pass


def assert_kb_reader(conn, role=None):
    if role is None:
        identity = conn.execute('SELECT session_user AS name, current_user AS effective').fetchone()
        if identity['name'] != identity['effective']:
            raise KBAccessError('KB reader must not impersonate another role.')
        role = identity['name']
    flags = conn.execute("""SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls AS unsafe
                            FROM pg_roles WHERE rolname=%s""", (role,)).fetchone()
    memberships = conn.execute("""SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
                                  WHERE r.rolname=%s LIMIT 1""", (role,)).fetchone()
    if not flags or flags['unsafe'] or memberships:
        raise KBAccessError('KB access requires a restricted reader without memberships.')
    rows = conn.execute("""SELECT n.nspname, c.relname,
        has_table_privilege(%s,c.oid,'SELECT') AS full_read,
        has_any_column_privilege(%s,c.oid,'SELECT') AS can_read,
        (has_table_privilege(%s,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
         OR has_any_column_privilege(%s,c.oid,'INSERT,UPDATE,REFERENCES')) AS can_write
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE c.relkind IN ('r','p','v','m','f')
        AND n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%%'
        AND n.nspname NOT LIKE 'pg_temp_%%'""", (role, role, role, role)).fetchall()
    found = False
    for row in rows:
        expected = (row['nspname'], row['relname']) == ('public', 'kb_chunks')
        if row['can_write'] or (row['can_read'] and not expected):
            raise KBAccessError('KB reader has unexpected table privileges.')
        found |= expected and row['full_read']
    creates = conn.execute("""SELECT 1 FROM pg_namespace WHERE nspname NOT LIKE 'pg_temp_%%'
        AND nspname NOT LIKE 'pg_toast%%' AND has_schema_privilege(%s,oid,'CREATE') LIMIT 1""", (role,)).fetchone()
    db_create = conn.execute("SELECT has_database_privilege(%s,current_database(),'CREATE') AS allowed", (role,)).fetchone()
    definer = conn.execute("""SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE p.prosecdef AND n.nspname NOT IN ('pg_catalog','information_schema')
        AND has_function_privilege(%s,p.oid,'EXECUTE') LIMIT 1""", (role,)).fetchone()
    if not found or creates or db_create['allowed'] or definer:
        raise KBAccessError('KB reader privileges are missing or unsafe.')


class ReadOnlyKBStore(PgvectorStore):
    @classmethod
    def from_environment(cls):
        value = os.getenv('KB_READER_DATABASE_URL', '')
        if not value.strip():
            raise KBAccessError('Set KB_READER_DATABASE_URL with restricted KB-only credentials.')
        return cls(value)

    @contextmanager
    def _connection(self):
        try:
            with psycopg.connect(self.database_url, autocommit=True, connect_timeout=5, row_factory=dict_row) as conn:
                # PgvectorStore.search opens its own transaction. Session defaults also
                # protect manifest/audit queries without nesting a search savepoint.
                conn.execute('SET default_transaction_read_only=on')
                conn.execute("SET default_transaction_isolation='repeatable read'")
                conn.execute("SET statement_timeout = '5s'")
                conn.execute('SET search_path = pg_catalog, public')
                assert_kb_reader(conn)
                register_vector(conn)
                yield conn
        except psycopg.Error:
            raise KBAccessError('Restricted KB request failed.') from None

    def initialize(self):
        raise KBAccessError('Investigation cannot initialize the KB.')

    def replace(self, *args, **kwargs):
        raise KBAccessError('Investigation cannot replace the KB.')


def provision_kb_reader(database_url: str, env_file: Path, *, role='northstar_kb_reader') -> None:
    """Explicit admin bootstrap command, never available to the graph/planner."""
    if not re.fullmatch(r'northstar_kb_(?:test_[a-f0-9]{8}_)?reader', role):
        raise KBAccessError('Unexpected KB reader role name.')
    if not env_file.name.startswith('.env.') or env_file.name == '.env.example':
        raise KBAccessError('Use a new ignored .env.* file.')
    wrote = False
    try:
        with psycopg.connect(database_url, connect_timeout=5, row_factory=dict_row) as conn:
            conn.execute('SELECT pg_advisory_xact_lock(410019)')
            if conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
                raise KBAccessError('KB reader exists; reuse its credentials or explicitly rotate them.')
            password = secrets.token_urlsafe(32)
            database = conn.execute('SELECT current_database() AS name').fetchone()['name']
            conn.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS').format(sql.Identifier(role), sql.Literal(password)))
            conn.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(database), sql.Identifier(role)))
            conn.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(role)))
            conn.execute(sql.SQL('GRANT SELECT ON public.kb_chunks TO {}').format(sql.Identifier(role)))
            conn.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only=on").format(sql.Identifier(role)))
            conn.execute(sql.SQL("ALTER ROLE {} SET statement_timeout='5s'").format(sql.Identifier(role)))
            conn.execute(sql.SQL('ALTER ROLE {} SET search_path=pg_catalog,public').format(sql.Identifier(role)))
            assert_kb_reader(conn, role)
            settings = conninfo_to_dict(database_url)
            settings.update(user=role, password=password, dbname=database)
            with env_file.open('x', encoding='utf-8') as output:
                wrote = True
                output.write('KB_READER_DATABASE_URL=' + json.dumps(make_conninfo(**settings)) + '\n')
    except Exception:
        if wrote:
            env_file.unlink(missing_ok=True)
        raise KBAccessError('KB reader provisioning failed; use a new local env file and review grants.') from None
