import pytest
from pydantic import ValidationError

from app.operations import schemas as s


@pytest.mark.parametrize('model,payload', [
    (s.EmployeeInput, {'employee_id': 'EMP-001 OR 1=1'}),
    (s.EmployeeInput, {'employee_id': ''}),
    (s.EmployeeInput, {'employee_id': 'emp-001'}),
    (s.EmployeeInput, {'employee_id': 'EMP-001', 'authorized': True}),
    (s.DeviceInput, {'device_id': 'EMP-001'}),
    (s.EntitlementInput, {'employee_id': 'EMP-001', 'software_id': 'SW-1'}),
    (s.RecentTicketsInput, {'employee_id': 'EMP-001', 'limit': True}),
    (s.RecentTicketsInput, {'employee_id': 'EMP-001', 'limit': '5'}),
    (s.RecentTicketsInput, {'employee_id': 'EMP-001', 'limit': 0}),
    (s.RecentTicketsInput, {'employee_id': 'EMP-001', 'since': '2026-10-16T08:00:00'}),
    (s.ActiveIncidentsInput, {'service_id': 'anything'}),
    (s.ActiveIncidentsInput, {'limit': 51}),
])
def test_inputs_reject_invalid_identifiers_limits_and_unknown_fields(model, payload):
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_timezone_input_and_whitespace_are_normalized():
    request = s.RecentTicketsInput(employee_id=' EMP-001 ', since='2026-10-16T08:00:00Z')
    assert request.employee_id == 'EMP-001'
    assert request.since.utcoffset().total_seconds() == 0


@pytest.mark.parametrize('change', [
    {'status': 'ok'}, {'live_verified': True}, {'data_kind': 'live'},
    {'queried_at': '2026-10-16T08:00:00'},
])
def test_result_metadata_rejects_inconsistent_or_live_claims(change):
    data = dict(status='not_found', missing_entities=[{'entity_type': 'employee', 'entity_id': 'EMP-999'}],
                queried_at='2026-10-19T08:00:00Z', employee=None, account=None)
    with pytest.raises(ValidationError):
        s.EmployeeAccountResult.model_validate(data | change)
