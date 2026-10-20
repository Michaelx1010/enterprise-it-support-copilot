CREATE SCHEMA ops;
REVOKE ALL ON SCHEMA ops FROM PUBLIC;

CREATE TABLE ops.employees (
    employee_id TEXT PRIMARY KEY CHECK (employee_id ~ '^EMP-[0-9]{3}$'),
    display_name TEXT NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 120),
    email TEXT NOT NULL UNIQUE CHECK (length(email) BETWEEN 3 AND 200),
    department TEXT NOT NULL CHECK (length(btrim(department)) BETWEEN 1 AND 120),
    manager_id TEXT REFERENCES ops.employees(employee_id),
    employment_status TEXT NOT NULL CHECK (employment_status IN ('active','leave','departed')),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL CHECK (updated_at >= created_at),
    CHECK (manager_id IS NULL OR manager_id <> employee_id)
);
CREATE INDEX employees_manager_idx ON ops.employees(manager_id);

CREATE TABLE ops.accounts (
    account_id TEXT PRIMARY KEY CHECK (account_id ~ '^ACC-[0-9]{3}$'),
    employee_id TEXT NOT NULL UNIQUE REFERENCES ops.employees(employee_id),
    username TEXT NOT NULL UNIQUE CHECK (length(btrim(username)) BETWEEN 1 AND 120),
    account_status TEXT NOT NULL CHECK (account_status IN ('enabled','locked','disabled')),
    password_expired BOOLEAN NOT NULL,
    mfa_status TEXT NOT NULL CHECK (mfa_status IN ('enrolled','not_enrolled','recovery_required')),
    locked_at TIMESTAMPTZ,
    last_successful_login_at TIMESTAMPTZ,
    observed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL CHECK (updated_at >= created_at),
    CHECK ((account_status = 'locked') = (locked_at IS NOT NULL)),
    CHECK (locked_at IS NULL OR locked_at <= observed_at),
    CHECK (last_successful_login_at IS NULL OR last_successful_login_at <= observed_at)
);

CREATE TABLE ops.devices (
    device_id TEXT PRIMARY KEY CHECK (device_id ~ '^DEV-[0-9]{3}$'),
    asset_tag TEXT NOT NULL UNIQUE CHECK (length(btrim(asset_tag)) BETWEEN 1 AND 80),
    assigned_employee_id TEXT REFERENCES ops.employees(employee_id),
    device_type TEXT NOT NULL CHECK (device_type IN ('laptop','desktop','phone')),
    model TEXT NOT NULL CHECK (length(btrim(model)) BETWEEN 1 AND 120),
    os_name TEXT NOT NULL CHECK (length(btrim(os_name)) BETWEEN 1 AND 120),
    os_version TEXT NOT NULL CHECK (length(btrim(os_version)) BETWEEN 1 AND 120),
    lifecycle_status TEXT NOT NULL CHECK (lifecycle_status IN ('active','repair','retired')),
    compliance_status TEXT NOT NULL CHECK (compliance_status IN ('compliant','noncompliant','unknown')),
    vpn_client_version TEXT CHECK (length(btrim(vpn_client_version)) BETWEEN 1 AND 120),
    last_seen_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL CHECK (updated_at >= created_at)
);
CREATE INDEX devices_owner_idx ON ops.devices(assigned_employee_id);

CREATE TABLE ops.software_products (
    software_id TEXT PRIMARY KEY CHECK (software_id ~ '^SW-[0-9]{3}$'),
    name TEXT NOT NULL UNIQUE CHECK (length(btrim(name)) BETWEEN 1 AND 120),
    edition TEXT NOT NULL CHECK (length(btrim(edition)) BETWEEN 1 AND 120),
    requires_license BOOLEAN NOT NULL,
    owner_team TEXT NOT NULL CHECK (length(btrim(owner_team)) BETWEEN 1 AND 120),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL CHECK (updated_at >= created_at)
);

CREATE TABLE ops.software_entitlements (
    employee_id TEXT NOT NULL REFERENCES ops.employees(employee_id),
    software_id TEXT NOT NULL REFERENCES ops.software_products(software_id),
    access_status TEXT NOT NULL CHECK (access_status IN ('granted','pending','revoked')),
    license_status TEXT NOT NULL CHECK (license_status IN ('assigned','unassigned','revoked','not_required')),
    license_expires_at TIMESTAMPTZ,
    approved_by_employee_id TEXT REFERENCES ops.employees(employee_id),
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL CHECK (updated_at >= created_at),
    PRIMARY KEY (employee_id, software_id),
    CHECK ((approved_by_employee_id IS NULL) = (approved_at IS NULL)),
    CHECK (license_expires_at IS NULL OR license_status = 'assigned')
);
CREATE INDEX entitlements_product_idx ON ops.software_entitlements(software_id);
CREATE INDEX entitlements_approver_idx ON ops.software_entitlements(approved_by_employee_id);

CREATE TABLE ops.services (
    service_id TEXT PRIMARY KEY CHECK (service_id ~ '^SVC-[0-9]{3}$'),
    name TEXT NOT NULL UNIQUE CHECK (length(btrim(name)) BETWEEN 1 AND 120),
    owner_team TEXT NOT NULL CHECK (length(btrim(owner_team)) BETWEEN 1 AND 120),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL CHECK (updated_at >= created_at)
);

CREATE TABLE ops.service_incidents (
    incident_id TEXT PRIMARY KEY CHECK (incident_id ~ '^INC-[0-9]{3}$'),
    service_id TEXT NOT NULL REFERENCES ops.services(service_id),
    title TEXT NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 200),
    impact_summary TEXT NOT NULL CHECK (length(btrim(impact_summary)) BETWEEN 1 AND 1000),
    status TEXT NOT NULL CHECK (status IN ('investigating','identified','monitoring','resolved')),
    severity TEXT NOT NULL CHECK (severity IN ('low','medium','high','critical')),
    started_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL CHECK (updated_at >= created_at),
    UNIQUE (incident_id, service_id),
    CHECK ((status = 'resolved') = (resolved_at IS NOT NULL)),
    CHECK (resolved_at IS NULL OR resolved_at >= started_at)
);
CREATE INDEX incidents_service_status_idx ON ops.service_incidents(service_id, status, started_at DESC, incident_id);

CREATE TABLE ops.support_tickets (
    ticket_id TEXT PRIMARY KEY CHECK (ticket_id ~ '^TKT-[0-9]{3}$'),
    employee_id TEXT NOT NULL REFERENCES ops.employees(employee_id),
    device_id TEXT REFERENCES ops.devices(device_id),
    service_id TEXT REFERENCES ops.services(service_id),
    incident_id TEXT,
    subject TEXT NOT NULL CHECK (length(btrim(subject)) BETWEEN 1 AND 200),
    description TEXT NOT NULL CHECK (length(btrim(description)) BETWEEN 1 AND 2000),
    category TEXT NOT NULL CHECK (category IN ('Software','Account','Network','Security','Communication','Hardware','RemoteWork','Training','Infrastructure','Licensing','Performance')),
    priority TEXT NOT NULL CHECK (priority IN ('Low','Medium','High','Urgent')),
    status TEXT NOT NULL CHECK (status IN ('open','in_progress','resolved','closed')),
    opened_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    resolution_summary TEXT CHECK (length(btrim(resolution_summary)) BETWEEN 1 AND 1000),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL CHECK (updated_at >= created_at),
    -- MATCH SIMPLE alone would skip the composite FK when service_id is NULL.
    CHECK (incident_id IS NULL OR service_id IS NOT NULL),
    FOREIGN KEY (incident_id, service_id) REFERENCES ops.service_incidents(incident_id, service_id),
    CHECK ((status IN ('resolved','closed')) = (resolved_at IS NOT NULL)),
    CHECK (resolved_at IS NULL OR resolved_at >= opened_at),
    CHECK (resolution_summary IS NULL OR resolved_at IS NOT NULL)
);
CREATE INDEX tickets_employee_opened_idx ON ops.support_tickets(employee_id, opened_at DESC, ticket_id);
CREATE INDEX tickets_device_idx ON ops.support_tickets(device_id);
CREATE INDEX tickets_service_idx ON ops.support_tickets(service_id);
CREATE INDEX tickets_incident_idx ON ops.support_tickets(incident_id, service_id);
