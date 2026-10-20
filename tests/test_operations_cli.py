import json
from unittest.mock import Mock

import pytest

from app.cli import main
from app.operations import cli
from app.operations.db import OperationalDataError
from app.operations.schemas import EmployeeAccountResult


def test_cli_prints_typed_missing_result(monkeypatch, capsys):
    monkeypatch.setattr(cli.OperationalDB, 'from_environment', Mock(return_value=object()))
    function = Mock(return_value=EmployeeAccountResult(status='not_found', missing_entities=[
        {'entity_type': 'employee', 'entity_id': 'EMP-999'}], queried_at='2026-10-19T08:00:00Z', employee=None, account=None))
    monkeypatch.setattr(cli.tools, 'get_employee_account_status', function)
    assert main(['ops', 'account', 'EMP-999']) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)['status'] == 'not_found'
    assert output.err == ''


@pytest.mark.parametrize('args', [
    ['account', 'invalid-secret'], ['device', 'EMP-001'],
    ['tickets', 'EMP-001', '--limit', '0'], ['incidents', '--limit', '100'],
    ['tickets', 'EMP-001', '--since', 'not-a-date'],
])
def test_bad_input_is_rejected_before_db_and_not_echoed(args, monkeypatch, capsys):
    factory = Mock()
    monkeypatch.setattr(cli.OperationalDB, 'from_environment', factory)
    assert main(['ops', *args]) == 2
    factory.assert_not_called()
    output = capsys.readouterr()
    assert output.out == '' and json.loads(output.err)['error']['code'] == 'invalid_input'
    assert 'invalid-secret' not in output.err


def test_configuration_failure_has_json_error(monkeypatch, capsys):
    monkeypatch.delenv('OPS_DATABASE_URL', raising=False)
    assert main(['ops', 'account', 'EMP-001']) == 1
    output = capsys.readouterr()
    assert not output.out and json.loads(output.err)['error']['code'] == 'configuration_error'
