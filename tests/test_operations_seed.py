from unittest.mock import Mock

import pytest

from app.operations import seed as module


def test_fixture_is_deterministic_and_uses_only_fictional_addresses():
    first = module.load_seed()
    assert first == module.load_seed()
    assert all(row.email.endswith('@northstar.example') for row in first['employees'])
    assert all(row.updated_at.isoformat() == '2026-10-16T08:00:00+00:00'
               for rows in first.values() for row in rows)


def test_bad_fixture_fails_before_database_connection(monkeypatch):
    monkeypatch.setattr(module, 'load_seed', Mock(side_effect=ValueError('bad fixture')))
    connect = Mock()
    monkeypatch.setattr(module.psycopg, 'connect', connect)
    with pytest.raises(module.OperationalDataError, match='validation'):
        module.seed('unused')
    connect.assert_not_called()
