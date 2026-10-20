"""Typed seed records; SQL remains the authority for persisted relationships."""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator

from app.schemas import Category, Priority

EmployeeID = Annotated[str, StringConstraints(pattern=r'^EMP-[0-9]{3}$')]
DeviceID = Annotated[str, StringConstraints(pattern=r'^DEV-[0-9]{3}$')]
SoftwareID = Annotated[str, StringConstraints(pattern=r'^SW-[0-9]{3}$')]
ServiceID = Annotated[str, StringConstraints(pattern=r'^SVC-[0-9]{3}$')]
IncidentID = Annotated[str, StringConstraints(pattern=r'^INC-[0-9]{3}$')]
TicketID = Annotated[str, StringConstraints(pattern=r'^TKT-[0-9]{3}$')]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=120)]
Title = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Summary = Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Record(Model):
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode='after')
    def ordered_updates(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError('Update precedes creation.')
        return self


class Employee(Record):
    employee_id: EmployeeID
    display_name: ShortText
    email: Annotated[str, StringConstraints(min_length=3, max_length=200)]
    department: ShortText
    manager_id: EmployeeID | None
    employment_status: Literal['active', 'leave', 'departed']


class Account(Record):
    account_id: Annotated[str, StringConstraints(pattern=r'^ACC-[0-9]{3}$')]
    employee_id: EmployeeID
    username: ShortText
    account_status: Literal['enabled', 'locked', 'disabled']
    password_expired: StrictBool
    mfa_status: Literal['enrolled', 'not_enrolled', 'recovery_required']
    locked_at: AwareDatetime | None
    last_successful_login_at: AwareDatetime | None
    observed_at: AwareDatetime


class Device(Record):
    device_id: DeviceID
    asset_tag: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    assigned_employee_id: EmployeeID | None
    device_type: Literal['laptop', 'desktop', 'phone']
    model: ShortText
    os_name: ShortText
    os_version: ShortText
    lifecycle_status: Literal['active', 'repair', 'retired']
    compliance_status: Literal['compliant', 'noncompliant', 'unknown']
    vpn_client_version: ShortText | None
    last_seen_at: AwareDatetime | None


class Software(Record):
    software_id: SoftwareID
    name: ShortText
    edition: ShortText
    requires_license: StrictBool
    owner_team: ShortText


class Entitlement(Record):
    employee_id: EmployeeID
    software_id: SoftwareID
    access_status: Literal['granted', 'pending', 'revoked']
    license_status: Literal['assigned', 'unassigned', 'revoked', 'not_required']
    license_expires_at: AwareDatetime | None
    approved_by_employee_id: EmployeeID | None
    approved_at: AwareDatetime | None


class Service(Record):
    service_id: ServiceID
    name: ShortText
    owner_team: ShortText


class Incident(Record):
    incident_id: IncidentID
    service_id: ServiceID
    title: Title
    impact_summary: Summary
    status: Literal['investigating', 'identified', 'monitoring', 'resolved']
    severity: Literal['low', 'medium', 'high', 'critical']
    started_at: AwareDatetime
    resolved_at: AwareDatetime | None


class Ticket(Record):
    ticket_id: TicketID
    employee_id: EmployeeID
    device_id: DeviceID | None
    service_id: ServiceID | None
    incident_id: IncidentID | None
    subject: Title
    description: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    category: Category
    priority: Priority
    status: Literal['open', 'in_progress', 'resolved', 'closed']
    opened_at: AwareDatetime
    resolved_at: AwareDatetime | None
    resolution_summary: Summary | None


TABLE_MODELS = {
    'employees': Employee, 'accounts': Account, 'devices': Device,
    'software_products': Software, 'software_entitlements': Entitlement,
    'services': Service, 'service_incidents': Incident, 'support_tickets': Ticket,
}
KEYS = {
    'employees': ('employee_id',), 'accounts': ('account_id',),
    'devices': ('device_id',), 'software_products': ('software_id',),
    'software_entitlements': ('employee_id', 'software_id'),
    'services': ('service_id',), 'service_incidents': ('incident_id',),
    'support_tickets': ('ticket_id',),
}
