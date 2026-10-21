"""Deterministic allowlist and scope gate. Text is never an identifier source."""

import json
from datetime import timezone

from pydantic import BaseModel

from app.operations import schemas as s, tools
from app.investigation.schemas import InvestigationRequest, LookupDecision

# One explicit registry: the existing six functions and their existing contracts.
TOOLS = {
    'get_employee_account_status': (s.EmployeeInput, s.EmployeeAccountResult, tools.get_employee_account_status),
    'get_employee_devices': (s.EmployeeInput, s.EmployeeDevicesResult, tools.get_employee_devices),
    'get_device_details': (s.DeviceInput, s.DeviceDetailsResult, tools.get_device_details),
    'check_software_entitlement': (s.EntitlementInput, s.SoftwareEntitlementResult, tools.check_software_entitlement),
    'get_recent_support_tickets': (s.RecentTicketsInput, s.RecentTicketsResult, tools.get_recent_support_tickets),
    'get_active_service_incidents': (s.ActiveIncidentsInput, s.ActiveIncidentsResult, tools.get_active_service_incidents),
}


class PolicyError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def validate_lookup(decision: LookupDecision, request: InvestigationRequest,
                    device_ids: set[str]) -> tuple[BaseModel, str]:
    if decision.tool not in TOOLS:
        raise PolicyError('tool_not_allowed')
    arguments = dict(decision.arguments)
    if decision.tool in ('get_recent_support_tickets', 'get_active_service_incidents'):
        arguments.setdefault('limit', 5)
    model = TOOLS[decision.tool][0].model_validate(arguments)
    if isinstance(model, s.RecentTicketsInput) and model.since is not None:
        model.since = model.since.astimezone(timezone.utc)
    values = model.model_dump(mode='json')
    if 'employee_id' in values and (not request.employee_id or values['employee_id'] != request.employee_id):
        raise PolicyError('employee_out_of_scope')
    if 'device_id' in values and values['device_id'] not in device_ids:
        raise PolicyError('device_not_verified_in_scope')
    if 'software_id' in values and values['software_id'] not in request.software_ids:
        raise PolicyError('software_out_of_scope')
    if 'service_id' in values and values['service_id'] not in request.service_ids:
        raise PolicyError('service_out_of_scope')
    if values.get('limit', 0) > 5:
        raise PolicyError('result_limit_exceeded')
    key = decision.tool + ':' + json.dumps(values, sort_keys=True, separators=(',', ':'))
    return model, key


def validate_result(tool: str, arguments: dict, raw: BaseModel | dict) -> BaseModel:
    result = TOOLS[tool][1].model_validate(raw.model_dump() if isinstance(raw, BaseModel) else raw)
    # A well-formed result for a DIFFERENT request is still rejected.
    for field, key in [('employee', 'employee_id'), ('software', 'software_id'), ('service', 'service_id'), ('device', 'device_id')]:
        value = getattr(result, field, None)
        if value is not None and getattr(value, key) != arguments.get(key):
            raise PolicyError('result_scope_mismatch')
    for missing in result.missing_entities:
        if arguments.get(missing.entity_type + '_id') != missing.entity_id:
            raise PolicyError('result_scope_mismatch')
    if tool == 'get_active_service_incidents' and result.status == 'ok' and result.service is None:
        raise PolicyError('result_scope_mismatch')
    if tool in ('get_recent_support_tickets', 'get_active_service_incidents'):
        rows = result.tickets if tool == 'get_recent_support_tickets' else result.incidents
        if len(rows) > arguments['limit']:
            raise PolicyError('result_limit_exceeded')
    return result
