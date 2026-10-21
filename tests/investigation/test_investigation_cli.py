from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.cli import main
from app.investigation.kb_access import KBAccessError, ReadOnlyKBStore, provision_kb_reader
from app.investigation.scripted import InvestigationScript, script_dependencies

EXAMPLE = Path('examples/investigation-scripted.json')


def test_example_cli_is_offline_and_reports_actual_execution(monkeypatch, capsys):
    monkeypatch.setenv('LANGSMITH_TRACING', 'true')
    import app.providers.openai as classification
    import app.providers.openai_embeddings as embeddings
    import app.providers.openai_recommendation as recommendation
    for module, cls in [(classification, 'OpenAIProvider'), (embeddings, 'OpenAIEmbeddings'), (recommendation, 'OpenAIRecommendation')]:
        monkeypatch.setattr(getattr(module, cls), 'from_environment', Mock(side_effect=AssertionError('No live model permitted.')))
    assert main(['investigate', 'scripted', '--script', str(EXAMPLE)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['backend'] == 'fixture' and output['query_embedding'] == 'supplied_vector'
    result = output['result']
    assert result['status'] == 'completed' and len(result['kb_evidence']) == 3
    assert result['lookup_attempts'] == 2 and result['synthesis_status'] == 'not_run'
    assert result['mutating_actions_executed'] is False


@pytest.mark.parametrize('change,expected', [
    ('blocked', 2), ('exhausted', 2), ('bad_vector', 1), ('unknown_field', 1), ('malformed_json', 1), ('too_large', 1),
])
def test_cli_failures_and_partial_exit_codes(tmp_path, capsys, change, expected):
    data = json.loads(EXAMPLE.read_text())
    if change == 'blocked':
        data['decisions'] = [{'kind': 'lookup', 'tool': 'write_account', 'arguments': {'credential': 'CANARY-SECRET'}}]
    elif change == 'exhausted':
        data['decisions'] = data['decisions'][:1]
    elif change == 'bad_vector':
        data['query_vector'] = [0, 0, 0]
    elif change == 'unknown_field':
        data['secret'] = 'CANARY-SECRET'
    path = tmp_path / 'script.json'
    path.write_text('CANARY-SECRET' if change == 'malformed_json' else ('x' * 250001 if change == 'too_large' else json.dumps(data)))
    assert main(['investigate', 'scripted', '--script', str(path)]) == expected
    output = capsys.readouterr()
    assert 'CANARY-SECRET' not in output.out + output.err
    assert 'Traceback' not in output.out + output.err


def test_postgres_mode_never_falls_back_to_fixture_or_admin(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv('KB_READER_DATABASE_URL', raising=False)
    monkeypatch.delenv('OPS_DATABASE_URL', raising=False)
    monkeypatch.setenv('DATABASE_URL', 'CANARY-ADMIN-NOT-A-FALLBACK')
    data = json.loads(EXAMPLE.read_text())
    data['kb_results'] = data['lookup_results'] = []
    path = tmp_path / 'postgres.json'
    path.write_text(json.dumps(data))
    assert main(['investigate', 'scripted', '--script', str(path), '--backend', 'postgres']) == 1
    assert 'CANARY' not in capsys.readouterr().err
    with pytest.raises(KBAccessError):
        ReadOnlyKBStore.from_environment()


def test_postgres_mode_refuses_replay_results():
    script = InvestigationScript.model_validate_json(EXAMPLE.read_text())
    with pytest.raises(ValueError, match='replay'):
        script_dependencies(script, postgres=True)


def test_supplied_embedding_is_bound_to_exact_ticket_query():
    script = InvestigationScript.model_validate_json(EXAMPLE.read_text())
    dependencies = script_dependencies(script)
    with pytest.raises(ValueError):
        dependencies.embedder.embed(['a different ticket'])


@pytest.mark.parametrize('path', ['credentials.json', '.env.example', 'ordinary.txt'])
def test_kb_provisioning_requires_ignored_env_filename(tmp_path, path):
    with pytest.raises(KBAccessError):
        provision_kb_reader('unused', tmp_path / path)


def test_graph_disables_external_tracing(inv_request, inv_dependencies, monkeypatch):
    from langsmith.run_helpers import get_tracing_context
    from app.investigation.graph import run_investigation

    class Planner:
        def decide(self, view, index):
            assert get_tracing_context()['enabled'] is False
            return {'kind': 'finish'}
    monkeypatch.setenv('LANGSMITH_TRACING', 'true')
    result = run_investigation(inv_request, dependencies=replace(inv_dependencies, planner=Planner()))
    assert result.status == 'completed'
