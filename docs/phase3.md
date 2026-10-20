# Phase 3: synthetic operational data and read-only investigation

Implemented on 2026-10-19 (Asia/Shanghai), following Phase 2B.1 commit
`ee28272178e91c3ad69a998fcd85b4a5974c00bf`. Phase 3 was approved for finalization
on 2026-10-20. No Phase 4 orchestration, automatic tool selection, model integration,
web API, frontend, or new Python dependencies are introduced.

## Architecture

```text
Explicit CLI command / typed Python caller
  -> Pydantic input validation
  -> restricted OperationalDB connection
  -> fixed parameterized SELECTs in a repeatable-read, read-only transaction
  -> Pydantic result, record IDs and observation/update timestamps
```

The existing PostgreSQL Docker service hosts an isolated `ops` schema in the
application database. `public.kb_chunks`, its embeddings, retrieval behavior,
classification, recommendation prompts, and Phase 2B.1 evaluations are unchanged.
Operational records contain recorded facts, the KB contains procedures, and the
LLM produces advisory recommendations. Phase 3 does not connect these paths.

| File | Responsibility |
| --- | --- |
| `app/operations/schema.sql` | Eight tables, constraints and indexes |
| `records.py` | Typed seed records and identifier definitions |
| `seed_data.json`, `seed.py` | Versioned fictional snapshot, validation and conflict-safe insertion |
| `db.py` | Administrative initialization/provisioning and restricted runtime connection |
| `reader_permissions.sql` | Explicit reader grants and connection defaults |
| `schemas.py` | Inputs, allowlisted fact projections and six concrete result models |
| `queries.py` | Fixed SELECT statements; only values are bound as parameters |
| `tools.py` | Six ordinary Python investigation functions |
| `cli.py` | Administrative commands and explicit developer lookups |

Only CLI dispatch, package-data configuration, `.env.example`, and documentation
change outside the new package/tests. `records.py` is the one additional module
relative to the proposal: seed records include fields intentionally excluded from
tool responses, so their models are separate from public tool contracts.

## Database and deterministic fixtures

The `northstar-v1` fixture contains **79 records**, observed/updated at
`2026-10-16T08:00:00Z`. Identifiers, timestamps and values are committed JSON;
there is no random record generation at startup or relative-to-today seed logic.
All email addresses use `northstar.example`. No passwords, MFA codes, recovery
tokens, license keys, or real employee records are stored in the fixture.

| Table | Rows | Relationships and important fields |
| --- | ---: | --- |
| employees | 10 | Employee PK, optional manager self-FK, unique fictional email, department, employment status |
| accounts | 9 | Account PK, unique employee FK/username; enabled/locked/disabled, password-expired flag, MFA state, observation/login/lock times |
| devices | 12 | Device PK, unique asset tag, nullable employee owner FK, lifecycle/compliance/OS/client information, last-seen time |
| software_products | 5 | Product PK, edition, license requirement, owner team |
| software_entitlements | 12 | Employee/product composite PK and FKs; separate access and license states, optional expiry and approver FK/time |
| services | 6 | Service PK, unique name, owner team |
| service_incidents | 5 | Incident PK, service FK, recorded status/severity/impact, start/resolution times |
| support_tickets | 20 | Ticket PK, employee FK, optional device/service/incident relationships, Phase 1 category/priority, reported symptoms and historical outcome |

All tables have explicit `created_at` and `updated_at`; updates cannot precede
creation. SQL constrains identifier formats, nonblank bounded text, allowed state
values, uniqueness, lock-state timestamps, approval pairs, and resolution-state
timestamps. Foreign keys restrict deletion rather than cascading employee removal.
The ticket's device need not still belong to its reporting employee: current
assignment is not an ownership history. Tickets may refer to unassigned devices.

Incident/service integrity is enforced by both:

```sql
CHECK (incident_id IS NULL OR service_id IS NOT NULL),
FOREIGN KEY (incident_id, service_id)
    REFERENCES ops.service_incidents(incident_id, service_id)
```

The target pair has a unique constraint. The explicit CHECK closes the nullable
column case that a composite foreign key alone would permit. Tickets may have
neither reference, or a known service without an incident. An incident requires
its matching service; unknown or mismatched pairs are rejected by PostgreSQL.

Indexes cover employee managers, device owners, entitlement products/approvers,
service incident filtering, employee ticket ordering, and ticket foreign keys.
There is no ORM, migration library, procurement model, seat inventory, installation
inventory, or authentication-event store.

Seed validation additionally rejects management cycles, missing relationships,
license-requirement mismatches, inconsistent timestamps and duplicate primary
identifiers. Management acyclicity and cross-table license conventions are seed
checks, not general database guarantees for arbitrary administrative writes.
`updated_at` is explicit recorded data; no automatic trigger refreshes it.

### Example scenarios

- Maya Chen (`EMP-001`): two devices, recurring VPN tickets, and an old phone
  check-in. The old timestamp does not make its recorded lifecycle inactive.
- Noah Patel (`EMP-002`): recorded lockout and prior lockout tickets. No inference
  that a particular device caused the lockout.
- Elena Ruiz (`EMP-003`): enabled account with MFA recovery required.
- Owen Brooks (`EMP-004`): assigned Atlas Design license, access pending, and
  noncompliant managed laptop.
- Priya Shah (`EMP-005`): application access granted but license unassigned.
- Lucas Reed (`EMP-006`): departed employee, disabled account and revoked license.
- `EMP-007`: an assigned license whose recorded expiry has passed.
- `EMP-010`: employee exists but account, devices and tickets are absent.
- `DEV-012`: valid unassigned device.
- Corporate VPN: active `INC-001` and resolved historical `INC-002`. Email is
  monitoring, Identity has an identified incident, and the print incident is resolved.

Application access, license allocation, installation, activation, and ability to
sign in are distinct. Only the first two are modeled by entitlement records.
An incident and a ticket sharing a service is not a causal diagnosis.

## Setup and repeatability

Use the existing local database service. On the prepared machine:

```powershell
docker compose --env-file .env.db up -d --wait --pull never
uv run --env-file .env.db python -m app.cli ops init
uv run --env-file .env.db python -m app.cli ops seed
uv run --env-file .env.db python -m app.cli ops provision-reader --env-file .env.ops
```

The `--pull never` option uses this machine's existing image. For a fresh machine,
follow the Phase 2A PostgreSQL setup and supply administrative `DATABASE_URL` through
an ignored env file; no OpenAI credentials are needed for Phase 3.

`init` creates only `ops` in one transaction. It records a normalized SQL digest
and catalog fingerprint in the schema comment. Repeated initialization verifies
column types/nullability, constraints and indexes. An unknown or changed schema
fails rather than silently applying DDL. This is a single-version drift check,
not a production migration system or tamper-proof security control.

`seed` validates the bundled fixture, then locks operational tables and inserts in
dependency order in a transaction. Identical existing records are unchanged;
missing records are inserted. Any conflicting fixture row aborts the entire
transaction, including earlier inserts. Unrelated records remain. Both commands
share an advisory transaction lock; seed also blocks concurrent table writers.
Neither command contains an operational DELETE/TRUNCATE/reset path or calls KB
ingestion. Setup must be run explicitly; reads never initialize or seed implicitly.

### Restricted reader provisioning

`provision-reader` is an **administrative bootstrap command**, not an investigation
tool. It creates the fixed login `northstar_ops_reader` with a generated password,
no elevated role flags, no role memberships and only SELECT on the eight ops tables.
It grants database CONNECT and schema USAGE, and sets read-only, statement timeout,
and `pg_catalog` search-path defaults. No KB grants or default grants on future
tables are added. Existing KB privileges and rows are not modified.

The generated connection configuration is written exclusively to a **new** ignored
`.env.ops` file. The program does not print the password/connection string, accept
a password CLI argument, read the OpenAI key, overwrite a local file, or rotate an
existing role. Provisioning checks privileges before committing. File creation
failure rolls the role transaction back; ordinary database commit failure removes
the newly created file. A process/machine crash between filesystem and database
commit can still require manual reconciliation: the two resources are not atomic.

Re-running provisioning reports `reader_exists`; reuse the existing file. A lost
credential requires an explicit administrative rotation, not automatic recreation.
The runtime connection string may be libpq conninfo rather than a URI; psycopg
accepts both. Load it explicitly with uv. The local file retains normal OS directory
permissions: this is not an encrypted secret store or a hardened filesystem ACL.

`OPS_DATABASE_URL` is mandatory for tools and never falls back to `DATABASE_URL`.
Each runtime connection checks login flags, memberships, table/column privileges,
schema/database creation privileges and executable non-system SECURITY DEFINER
functions. An admin login, writable role, extra KB read grant, or incompatible
environment fails closed. Restriction failures are not missing-record results.

The credentials cannot write ops tables or select KB data even if their default
transaction-read-only setting is disabled. Tools additionally execute within a
repeatable-read/read-only transaction with a five-second statement timeout and
five-second connect timeout. Values are parameterized; no caller controls SQL,
table names, columns, arbitrary filters, or commands.

## Tool contracts and CLI

All six functions take the indicated Pydantic input and keyword-only
`db: OperationalDB`, returning a concrete Pydantic result. Inputs reject extra
fields, invalid identifiers and bounds; whitespace is trimmed. Input models are
revalidated at the function boundary. IDs are case-sensitive (`EMP-001`, `DEV-001`,
`SW-001`, `SVC-001`); limits are strict integers, not strings or booleans. Timestamp
inputs must include a timezone.

| Function | Input | Result payload | SQL tables |
| --- | --- | --- | --- |
| get_employee_account_status | EmployeeInput: employee_id | employee, account | employees, accounts |
| get_employee_devices | EmployeeInput: employee_id | employee, devices | employees, devices |
| get_device_details | DeviceInput: device_id | device, owner | devices, employees |
| check_software_entitlement | EntitlementInput: employee_id, software_id | employee, software, entitlement, license_expired | employees, software_products, software_entitlements |
| get_recent_support_tickets | RecentTicketsInput: employee_id, limit=10 (1–50), since=null | employee, tickets, has_more | employees, support_tickets |
| get_active_service_incidents | ActiveIncidentsInput: service_id=null, limit=20 (1–50) | service, incidents, has_more | services, service_incidents |

Every output also includes:

```text
status: "ok" | "not_found"
missing_entities: [{entity_type: "employee" | "device" | "software" | "service", entity_id: str}]
queried_at: timezone-aware database transaction timestamp
data_kind: "synthetic_snapshot"
live_verified: false
```

Full field types and required/nullability rules are in `schemas.py` and `records.py`.
Device, software, entitlement, service and incident facts retain `created_at` in
addition to `updated_at`. Account facts retain `observed_at`, lock time and last
successful login; device facts retain last-seen time. Ticket facts require
`opened_at` and preserve recorded resolution details. Employee emails, usernames,
and raw ticket descriptions are not in tool output projections. SQL reader access
is table-level, however: this output minimization is not a column-level privacy ACL.

Results distinguish:

- Unknown requested parent: `not_found` and explicit missing entity reference(s).
- Existing employee with no account: `ok`, `account=null`.
- Existing employee with no devices/tickets: `ok`, empty list.
- Known employee/product with no assignment: `ok`, `entitlement=null`.
- Unassigned device: `ok`, `owner=null`.
- Known service without recorded active incidents: `ok`, empty list.
- No service filter: `service=null`, with all matching incident records.

Tickets sort by opened time descending and ticket ID ascending. `since` is
inclusive. Incidents sort by start time descending and incident ID ascending;
only investigating/identified/monitoring states are returned. Both bounded lists
fetch one extra row to report truncation via `has_more`. There is no paging cursor;
the deliberately small employee device list is returned in full, sorted by ID.

`license_expired` compares an assigned license's recorded expiry against
`queried_at` (equal means expired). No expiry/assignment produces null. This does
not change the recorded license status or determine current authorization.

```powershell
uv run --env-file .env.ops python -m app.cli ops account EMP-002
uv run --env-file .env.ops python -m app.cli ops devices EMP-001
uv run --env-file .env.ops python -m app.cli ops device DEV-012
uv run --env-file .env.ops python -m app.cli ops entitlement EMP-004 SW-001
uv run --env-file .env.ops python -m app.cli ops tickets EMP-001 --limit 5 --since 2026-10-01T00:00:00Z
uv run --env-file .env.ops python -m app.cli ops incidents --service-id SVC-001
```

Python callers can use `get_employee_account_status(EmployeeInput(employee_id=
"EMP-002"), db=OperationalDB.from_environment())`; no model client is involved.

Lookup success and missing records exit zero with JSON on stdout. Pydantic input
errors exit 2 with sanitized JSON on stderr. Configuration, database, permission,
and stored-data contract errors exit 1 with stable codes and fixed messages.
Raw driver exceptions, credentials and invalid input values are not emitted by
the operation handler. Standard argparse syntax/unknown-command errors use its
normal usage text and exit 2, not a JSON envelope.

Database connection/query failures raise `OperationalDataError`; malformed stored
outputs raise `OperationalDataIntegrityError`. These never become empty successful
results, missing entities, or fabricated fallback records.

## Snapshot freshness and security limits

The fixed October 16 records do not become live facts when queried later.
`queried_at` is retrieval time, not source verification time. A recorded enabled
account may no longer be enabled; a monitoring incident may since have resolved;
an old check-in does not prove a device is offline or unhealthy. There is no
automatic expiration, inferred safety, or live reconciliation of these states.
The output exposes timestamps and the synthetic marker for callers to interpret.

Read-only access is not employee-level authorization. There is no authenticated
end-user, RBAC policy per employee, row-level security, tenant boundary, access
audit service, or identity verification. Knowing an employee ID is not permission
to access their records. A holder of the local reader credential can inspect all
ops rows. Manager links confer no authorization. The database role is cluster-wide;
the runtime grant audit covers the connected database, not every database/server.
System catalogs and ordinary PostgreSQL PUBLIC capabilities are not removed.
The checks are defense in depth for this local schema, not a general PostgreSQL
security audit; administrators can change grants, tables and server behavior.

The Compose database remains localhost-bound. Credentials are local plaintext,
not an enterprise secret manager. Query result strings are synthetic, not a
general-purpose PII scrubber for arbitrary production text. No results are sent
to an LLM. Future integration requires identity/authorization design and explicit
separation of operational facts from procedural KB evidence; it is not implemented.

## Verification

Phase 3A was verified before starting the tools: **25 tests passed**, covering the
new seed checks and real PostgreSQL initialization, constraints, nullable incident
pairs, idempotence, conflict rollback and KB sentinel preservation. The application
database was then initialized and seeded twice; all **36 KB rows, metadata and
vectors** were byte-for-byte unchanged in a serialized snapshot comparison.

Final full-suite validation on 2026-10-19: **229 passed in 25.49 seconds**, with
no failures or skips: **184 offline tests + 45 real PostgreSQL integration tests**.
This preserves all **132 existing tests**, adding **97 Phase 3 tests** (56 offline
and 41 database checks). PostgreSQL 16.10/pgvector 0.8.7 runs in the existing local
container. All six CLI commands and an unknown-employee lookup passed local smoke
checks using only the restricted reader configuration.

The first full run found a keyword collision between the device's `model` field
and the validation helper argument; making the helper's class argument positional
fixed it. A pytest failure representation also exposed a local test-database DSN.
The local administrative database credential was rotated, generated temporary
reader roles were removed by cleanup, and fixture DSN representations are now
redacted. The final run used short tracebacks and passed. No OpenAI key was read,
printed, rotated, or used. These diagnostics are not committed reports.

```powershell
uv run --extra dev python -m pytest -m "not integration"
uv run --env-file .env.db --extra dev python -m pytest --tb=short
```

Integration tests require a separate database ending in `_test`, distinct from
the application database. Only that test database's ops schema is recreated.
Test reader roles have unique names, real login credentials, and are removed at
fixture cleanup. The existing four pgvector tests remain unchanged. No paid API
calls occur in these tests.

Automatic checks cover relational constraints, valid/missing/invalid lookups,
multiple records, filtered/truncated ordering, missing entitlements, date bounds,
snapshot preservation, malformed records, sanitized failures, no credential
fallback, permission boundaries after disabling read-only defaults, transaction
read-only settings, rejected admin/membership/KB-column grants, provisioning
rollback, repeatable setup and isolation from KB tables. They establish mechanics
on the synthetic fixtures, not real-system freshness, data completeness, security
certification, causal diagnosis, or recommendation quality.

Finalization verification on 2026-10-20: **229 passed in 29.19 seconds**, including
all 45 real PostgreSQL integration tests. An application-database snapshot before
and after the suite confirmed that all 36 KB rows, metadata and vectors were
unchanged; no temporary test reader roles remained. The rotated database settings
were consistent and authenticated successfully, the restricted reader worked,
and a canary verified the redacted DSN representation. Publishable-file checks
found no credentials, populated secret settings, local env files or generated
diagnostic artifacts. `.env`, `.env.db`, `.env.ops` and reports remain ignored.
