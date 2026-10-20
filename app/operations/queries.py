"""Fixed SELECTs only; values are always passed as SQL parameters."""

from psycopg import Connection

EMPLOYEE_COLUMNS = 'employee_id,display_name,department,manager_id,employment_status,updated_at'
ACCOUNT_COLUMNS = 'account_id,employee_id,account_status,password_expired,mfa_status,locked_at,last_successful_login_at,observed_at,updated_at'
DEVICE_COLUMNS = 'device_id,asset_tag,assigned_employee_id,device_type,model,os_name,os_version,lifecycle_status,compliance_status,vpn_client_version,last_seen_at,created_at,updated_at'
SOFTWARE_COLUMNS = 'software_id,name,edition,requires_license,owner_team,created_at,updated_at'
ENTITLEMENT_COLUMNS = 'employee_id,software_id,access_status,license_status,license_expires_at,approved_by_employee_id,approved_at,created_at,updated_at'
SERVICE_COLUMNS = 'service_id,name,owner_team,created_at,updated_at'
TICKET_COLUMNS = 'ticket_id,employee_id,device_id,service_id,incident_id,subject,category,priority,status,opened_at,resolved_at,resolution_summary,updated_at'
INCIDENT_COLUMNS = 'incident_id,service_id,title,impact_summary,status,severity,started_at,resolved_at,created_at,updated_at'


def employee(conn: Connection, employee_id: str) -> dict | None:
    return conn.execute(f'SELECT {EMPLOYEE_COLUMNS} FROM ops.employees WHERE employee_id=%s', (employee_id,)).fetchone()


def account(conn: Connection, employee_id: str) -> dict | None:
    return conn.execute(f'SELECT {ACCOUNT_COLUMNS} FROM ops.accounts WHERE employee_id=%s', (employee_id,)).fetchone()


def devices(conn: Connection, employee_id: str) -> list[dict]:
    return conn.execute(f'SELECT {DEVICE_COLUMNS} FROM ops.devices WHERE assigned_employee_id=%s ORDER BY device_id', (employee_id,)).fetchall()


def device(conn: Connection, device_id: str) -> dict | None:
    return conn.execute(f'SELECT {DEVICE_COLUMNS} FROM ops.devices WHERE device_id=%s', (device_id,)).fetchone()


def software(conn: Connection, software_id: str) -> dict | None:
    return conn.execute(f'SELECT {SOFTWARE_COLUMNS} FROM ops.software_products WHERE software_id=%s', (software_id,)).fetchone()


def entitlement(conn: Connection, employee_id: str, software_id: str) -> dict | None:
    return conn.execute(f'SELECT {ENTITLEMENT_COLUMNS} FROM ops.software_entitlements WHERE employee_id=%s AND software_id=%s', (employee_id, software_id)).fetchone()


def tickets(conn: Connection, employee_id: str, limit: int, since) -> list[dict]:
    return conn.execute(f'''SELECT {TICKET_COLUMNS} FROM ops.support_tickets
        WHERE employee_id=%s AND (%s::timestamptz IS NULL OR opened_at >= %s::timestamptz)
        ORDER BY opened_at DESC,ticket_id LIMIT %s''', (employee_id, since, since, limit + 1)).fetchall()


def service(conn: Connection, service_id: str) -> dict | None:
    return conn.execute(f'SELECT {SERVICE_COLUMNS} FROM ops.services WHERE service_id=%s', (service_id,)).fetchone()


def incidents(conn: Connection, service_id: str | None, limit: int) -> list[dict]:
    return conn.execute(f'''SELECT {INCIDENT_COLUMNS} FROM ops.service_incidents
        WHERE status IN ('investigating','identified','monitoring')
        AND (%s::text IS NULL OR service_id=%s)
        ORDER BY started_at DESC,incident_id LIMIT %s''', (service_id, service_id, limit + 1)).fetchall()
