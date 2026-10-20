"""Six independently callable read-only functions; no model or KB dependency."""

from pydantic import ValidationError

from app.operations import queries as q
from app.operations.db import OperationalDB, OperationalDataIntegrityError
from app.operations.schemas import (
    EmployeeInput, DeviceInput, EntitlementInput, RecentTicketsInput, ActiveIncidentsInput,
    EmployeeAccountResult, EmployeeDevicesResult, DeviceDetailsResult,
    SoftwareEntitlementResult, RecentTicketsResult, ActiveIncidentsResult,
    DeviceFacts, EntitlementFacts,
)


def _metadata(conn, missing: list[dict]) -> dict:
    return {'status': 'not_found' if missing else 'ok', 'missing_entities': missing,
            'queried_at': conn.execute('SELECT transaction_timestamp() AS time').fetchone()['time']}


def _missing(kind: str, identifier: str) -> dict:
    return {'entity_type': kind, 'entity_id': identifier}


def _validated(model, /, **data):
    try:
        return model.model_validate(data)
    except ValidationError:
        raise OperationalDataIntegrityError() from None


def get_employee_account_status(request: EmployeeInput, *, db: OperationalDB) -> EmployeeAccountResult:
    request = EmployeeInput.model_validate(request.model_dump())
    with db.connection() as conn:
        employee = q.employee(conn, request.employee_id)
        account = q.account(conn, request.employee_id) if employee else None
        missing = [] if employee else [_missing('employee', request.employee_id)]
        return _validated(EmployeeAccountResult, **_metadata(conn, missing), employee=employee, account=account)


def get_employee_devices(request: EmployeeInput, *, db: OperationalDB) -> EmployeeDevicesResult:
    request = EmployeeInput.model_validate(request.model_dump())
    with db.connection() as conn:
        employee = q.employee(conn, request.employee_id)
        devices = q.devices(conn, request.employee_id) if employee else []
        missing = [] if employee else [_missing('employee', request.employee_id)]
        return _validated(EmployeeDevicesResult, **_metadata(conn, missing), employee=employee, devices=devices)


def get_device_details(request: DeviceInput, *, db: OperationalDB) -> DeviceDetailsResult:
    request = DeviceInput.model_validate(request.model_dump())
    with db.connection() as conn:
        device = q.device(conn, request.device_id)
        device = _validated(DeviceFacts, **device) if device else None
        owner = q.employee(conn, device.assigned_employee_id) if device and device.assigned_employee_id else None
        missing = [] if device else [_missing('device', request.device_id)]
        return _validated(DeviceDetailsResult, **_metadata(conn, missing), device=device, owner=owner)


def check_software_entitlement(request: EntitlementInput, *, db: OperationalDB) -> SoftwareEntitlementResult:
    request = EntitlementInput.model_validate(request.model_dump())
    with db.connection() as conn:
        employee = q.employee(conn, request.employee_id)
        software = q.software(conn, request.software_id)
        missing = ([] if employee else [_missing('employee', request.employee_id)])
        missing += [] if software else [_missing('software', request.software_id)]
        entitlement = q.entitlement(conn, request.employee_id, request.software_id) if not missing else None
        entitlement = _validated(EntitlementFacts, **entitlement) if entitlement else None
        metadata = _metadata(conn, missing)
        expired = (entitlement.license_expires_at <= metadata['queried_at']
                   if entitlement and entitlement.license_status == 'assigned' and entitlement.license_expires_at else None)
        return _validated(SoftwareEntitlementResult, **metadata, employee=employee, software=software,
                          entitlement=entitlement, license_expired=expired)


def get_recent_support_tickets(request: RecentTicketsInput, *, db: OperationalDB) -> RecentTicketsResult:
    request = RecentTicketsInput.model_validate(request.model_dump())
    with db.connection() as conn:
        employee = q.employee(conn, request.employee_id)
        tickets = q.tickets(conn, request.employee_id, request.limit, request.since) if employee else []
        missing = [] if employee else [_missing('employee', request.employee_id)]
        return _validated(RecentTicketsResult, **_metadata(conn, missing), employee=employee,
                          tickets=tickets[:request.limit], has_more=len(tickets) > request.limit)


def get_active_service_incidents(request: ActiveIncidentsInput, *, db: OperationalDB) -> ActiveIncidentsResult:
    request = ActiveIncidentsInput.model_validate(request.model_dump())
    with db.connection() as conn:
        service = q.service(conn, request.service_id) if request.service_id else None
        missing = [_missing('service', request.service_id)] if request.service_id and not service else []
        incidents = q.incidents(conn, request.service_id, request.limit) if not missing else []
        return _validated(ActiveIncidentsResult, **_metadata(conn, missing), service=service,
                          incidents=incidents[:request.limit], has_more=len(incidents) > request.limit)
