"""Explicit tool contracts. Observed synthetic facts are never live verification."""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StrictBool, StringConstraints, model_validator

from app.operations.records import (
    Device, EmployeeID, SoftwareID, DeviceID, ServiceID, IncidentID, TicketID, Incident,
    Entitlement, Software, Service, Model, ShortText, Title, Summary,
)
from app.schemas import Category, Priority


class EmployeeInput(Model):
    employee_id: EmployeeID


class DeviceInput(Model):
    device_id: DeviceID


class EntitlementInput(EmployeeInput):
    software_id: SoftwareID


class RecentTicketsInput(EmployeeInput):
    limit: int = Field(default=10, ge=1, le=50, strict=True)
    since: AwareDatetime | None = None


class ActiveIncidentsInput(Model):
    service_id: ServiceID | None = None
    limit: int = Field(default=20, ge=1, le=50, strict=True)


class EmployeeFacts(Model):
    employee_id: EmployeeID
    display_name: ShortText
    department: ShortText
    manager_id: EmployeeID | None
    employment_status: Literal['active', 'leave', 'departed']
    updated_at: AwareDatetime


# Dedicated allowlisted projections: no employee email, username, or raw ticket description.
class AccountFacts(Model):
    account_id: Annotated[str, StringConstraints(pattern=r'^ACC-[0-9]{3}$')]
    employee_id: EmployeeID
    account_status: Literal['enabled', 'locked', 'disabled']
    password_expired: StrictBool
    mfa_status: Literal['enrolled', 'not_enrolled', 'recovery_required']
    locked_at: AwareDatetime | None
    last_successful_login_at: AwareDatetime | None
    observed_at: AwareDatetime
    updated_at: AwareDatetime


class DeviceFacts(Device):
    pass


class SoftwareFacts(Software):
    pass


class EntitlementFacts(Entitlement):
    pass


class ServiceFacts(Service):
    pass


class IncidentFacts(Incident):
    pass


class TicketFacts(Model):
    ticket_id: TicketID
    employee_id: EmployeeID
    device_id: DeviceID | None
    service_id: ServiceID | None
    incident_id: IncidentID | None
    subject: Title
    category: Category
    priority: Priority
    status: Literal['open', 'in_progress', 'resolved', 'closed']
    opened_at: AwareDatetime
    resolved_at: AwareDatetime | None
    resolution_summary: Summary | None
    updated_at: AwareDatetime


class EntityReference(Model):
    entity_type: Literal['employee', 'device', 'software', 'service']
    entity_id: str = Field(min_length=1, max_length=20)


class Result(Model):
    status: Literal['ok', 'not_found']
    missing_entities: list[EntityReference]
    queried_at: AwareDatetime
    data_kind: Literal['synthetic_snapshot'] = 'synthetic_snapshot'
    live_verified: Literal[False] = False

    @model_validator(mode='after')
    def consistent_missing(self) -> Self:
        if (self.status == 'not_found') != bool(self.missing_entities):
            raise ValueError('Missing entities must agree with result status.')
        return self


class EmployeeAccountResult(Result):
    employee: EmployeeFacts | None
    account: AccountFacts | None

    @model_validator(mode='after')
    def valid_relationship(self) -> Self:
        if (self.employee is None) != (self.status == 'not_found'):
            raise ValueError('Employee presence must agree with status.')
        if self.account and (not self.employee or self.account.employee_id != self.employee.employee_id):
            raise ValueError('Account employee mismatch.')
        return self


class EmployeeDevicesResult(Result):
    employee: EmployeeFacts | None
    devices: list[DeviceFacts]

    @model_validator(mode='after')
    def valid_relationship(self) -> Self:
        if (self.employee is None) != (self.status == 'not_found'):
            raise ValueError('Employee presence must agree with status.')
        if any(not self.employee or d.assigned_employee_id != self.employee.employee_id for d in self.devices):
            raise ValueError('Device owner mismatch.')
        return self


class DeviceDetailsResult(Result):
    device: DeviceFacts | None
    owner: EmployeeFacts | None

    @model_validator(mode='after')
    def valid_relationship(self) -> Self:
        if (self.device is None) != (self.status == 'not_found'):
            raise ValueError('Device presence must agree with status.')
        if self.owner and (not self.device or self.owner.employee_id != self.device.assigned_employee_id):
            raise ValueError('Owner mismatch.')
        if self.device and bool(self.device.assigned_employee_id) != bool(self.owner):
            raise ValueError('Missing assigned owner.')
        return self


class SoftwareEntitlementResult(Result):
    employee: EmployeeFacts | None
    software: SoftwareFacts | None
    entitlement: EntitlementFacts | None
    license_expired: StrictBool | None

    @model_validator(mode='after')
    def valid_relationship(self) -> Self:
        if (self.employee is None or self.software is None) != (self.status == 'not_found'):
            raise ValueError('Requested entity presence must agree with status.')
        row = self.entitlement
        if row and (not self.employee or not self.software or row.employee_id != self.employee.employee_id or row.software_id != self.software.software_id):
            raise ValueError('Entitlement reference mismatch.')
        expected = row.license_expires_at <= self.queried_at if row and row.license_status == 'assigned' and row.license_expires_at else None
        if self.license_expired != expected:
            raise ValueError('Expiry calculation mismatch.')
        return self


class RecentTicketsResult(Result):
    employee: EmployeeFacts | None
    tickets: list[TicketFacts]
    has_more: StrictBool

    @model_validator(mode='after')
    def valid_relationship(self) -> Self:
        if (self.employee is None) != (self.status == 'not_found'):
            raise ValueError('Employee presence must agree with status.')
        if any(not self.employee or t.employee_id != self.employee.employee_id for t in self.tickets):
            raise ValueError('Ticket employee mismatch.')
        if self.has_more and not self.tickets:
            raise ValueError('Truncation without records.')
        return self


class ActiveIncidentsResult(Result):
    service: ServiceFacts | None
    incidents: list[IncidentFacts]
    has_more: StrictBool

    @model_validator(mode='after')
    def valid_relationship(self) -> Self:
        if self.status == 'not_found' and (self.service or self.incidents or self.has_more):
            raise ValueError('Unknown service must have no records.')
        if any(i.status == 'resolved' or (self.service and i.service_id != self.service.service_id) for i in self.incidents):
            raise ValueError('Incident status or service mismatch.')
        if self.has_more and not self.incidents:
            raise ValueError('Truncation without records.')
        return self
