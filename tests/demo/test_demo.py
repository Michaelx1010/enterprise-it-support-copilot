"""Local UI and adapter checks. All paid/network/database boundaries are blocked."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import httpx
import psycopg
import pytest

pytest.importorskip('streamlit', reason='Install the optional demo extra for UI tests.')
from streamlit.testing.v1 import AppTest

from app.demo import service
from app.demo.presentation import escalation_label, fact_rows, outcome, reference_labels, visible_report
from app.investigation.schemas import InvestigationResult


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('No real HTTP or database connection is allowed in demo tests.')
    monkeypatch.setattr(httpx.Client, 'send', forbidden)
    monkeypatch.setattr(psycopg, 'connect', forbidden)
    monkeypatch.delenv('IT_SUPPORT_DEMO_LIVE', raising=False)
    for name in ('OPENAI_API_KEY', 'OPS_DATABASE_URL', 'KB_READER_DATABASE_URL'):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize('key,escalation,stop,lookups', [
    ('vpn-first-failure', False, 'finish', 3),
    ('vpn-escalation', True, 'finish', 3),
    ('documentation-gap', False, 'insufficient_evidence', 0),
])
def test_examples_use_real_graph_with_validated_authored_evidence(key, escalation, stop, lookups):
    run = service.run_example(key)
    result = InvestigationResult.model_validate(run.result.model_dump())
    assert result.status == 'completed' and not result.errors
    assert result.stop_reason == stop and result.lookup_attempts == lookups
    assert result.recommendation.escalation_required is escalation
    assert result.human_review_required and not result.mutating_actions_executed
    assert len(reference_labels(result)) == 2 + len(result.kb_evidence) + lookups
    if key == 'vpn-first-failure':
        assert result.recommendation.conditional_guidance and not result.recommendation.trigger_basis
    if key == 'vpn-escalation':
        assert result.recommendation.trigger_basis and not result.recommendation.conditional_guidance
    if key == 'documentation-gap':
        assert not result.recommendation.steps and result.synthesis_attempts == 0
        assert escalation_label(result.recommendation) == 'Undetermined'
    if lookups:
        records = fact_rows(result.operational_evidence[0].observation.result.model_dump(mode='json'))
        assert any(row['Recorded field'] == 'queried at' for row in records)
        assert any('observed at' in row['Recorded field'] for row in records)


@pytest.mark.parametrize('enabled,consent', [('0', True), ('1', False), ('true', True)])
def test_live_requires_two_explicit_opt_ins(monkeypatch, enabled, consent):
    monkeypatch.setenv('IT_SUPPORT_DEMO_LIVE', enabled)
    graph = Mock()
    monkeypatch.setattr(service, 'run_investigation', graph)
    with pytest.raises(service.DemoError, match='live_not_authorized'):
        service.run_live(None, allow_paid=consent)
    graph.assert_not_called()


def test_live_reuses_providers_readers_and_graph_and_closes_client(monkeypatch, capsys, caplog):
    from app.investigation.kb_access import ReadOnlyKBStore
    from app.operations.db import OperationalDB
    from app.providers.openai_planner import OpenAIPlanner
    from app.providers.openai import OpenAIProvider
    from app.providers.openai_embeddings import OpenAIEmbeddings
    from app.providers.openai_synthesis import OpenAISynthesis
    example = service.run_example('vpn-first-failure')
    monkeypatch.setenv('IT_SUPPORT_DEMO_LIVE', '1')
    for key in ('OPENAI_API_KEY', 'OPS_DATABASE_URL', 'KB_READER_DATABASE_URL'):
        monkeypatch.setenv(key, 'TEST-ONLY-NOT-A-CREDENTIAL')
    client = MagicMock()
    client.__enter__.return_value = client
    client.with_options.return_value = client
    planner = SimpleNamespace(client=client)
    store, db = object(), object()
    monkeypatch.setattr(OpenAIPlanner, 'from_environment', Mock(return_value=planner))
    monkeypatch.setattr(ReadOnlyKBStore, 'from_environment', Mock(return_value=store))
    monkeypatch.setattr(OperationalDB, 'from_environment', Mock(return_value=db))
    graph = Mock(return_value=example.result)
    monkeypatch.setattr(service, 'run_investigation', graph)
    result = service.run_live(example.request, allow_paid=True)
    deps = graph.call_args.kwargs['dependencies']
    assert graph.call_args.args == (example.request,)
    assert deps.store is store and deps.db is db and deps.planner is planner
    assert isinstance(deps.classifier, OpenAIProvider) and isinstance(deps.embedder, OpenAIEmbeddings)
    assert isinstance(deps.synthesis, OpenAISynthesis) and deps.fixture_lookup is None
    assert deps.limits.planner_decisions == deps.limits.lookup_attempts == 4
    assert result.result is example.result and result.mode == 'live'
    client.__exit__.assert_called_once()
    graph.side_effect = RuntimeError('CANARY-secret-connection-url')
    with pytest.raises(service.DemoError) as error:
        service.run_live(example.request, allow_paid=True)
    assert str(error.value) == 'investigation_setup_failed' and error.value.__suppress_context__
    assert client.__exit__.call_count == 2
    captured = capsys.readouterr()
    assert 'CANARY-secret-connection-url' not in captured.out + captured.err + caplog.text


def test_missing_config_never_falls_back_to_admin(monkeypatch):
    from app.providers.openai_planner import OpenAIPlanner
    factory = Mock()
    monkeypatch.setattr(OpenAIPlanner, 'from_environment', factory)
    monkeypatch.setenv('IT_SUPPORT_DEMO_LIVE', '1')
    monkeypatch.setenv('DATABASE_URL', 'CANARY-admin-credentials')
    with pytest.raises(service.DemoError, match='missing_configuration'):
        service.run_live(service.run_example('documentation-gap').request, allow_paid=True)
    factory.assert_not_called()


def failed_run():
    example = service.run_example('vpn-first-failure')
    data = example.result.model_dump()
    data.update(status='partial', recommendation=None, synthesis_status='failed', synthesis_attempts=1,
                errors=[{'stage': 'synthesis', 'code': 'synthesis_invalid_output'}])
    return replace(example, result=InvestigationResult.model_validate(data), mode='live')


def test_retrieval_fallback_not_presented_as_successful_documentation_abstention():
    example = service.run_example('documentation-gap')
    data = example.result.model_dump()
    data.update(status='partial', kb_evidence=[], errors=[{'stage':'retrieval','code':'retrieval_failed'}])
    data['graph_trace'].append({'node':'synthesize','outcome':'no_kb_abstention','lookup_id':None})
    result = InvestigationResult.model_validate(data)
    assert visible_report(result) is None
    assert outcome(result)[0] == 'warning' and escalation_label(None) == 'Undetermined'
    assert result.recommendation is not None  # Original diagnostic evidence is not rewritten.


@pytest.mark.parametrize('key', ['vpn-first-failure', 'vpn-escalation', 'documentation-gap'])
def test_ui_examples_render_and_rerenders_do_not_repeat_work(monkeypatch, key):
    original = service.run_example
    example = Mock(side_effect=original)
    live = Mock(side_effect=AssertionError('Must not dispatch live work'))
    monkeypatch.setattr(service, 'run_example', example)
    monkeypatch.setattr(service, 'run_live', live)
    app = AppTest.from_file(str(service.ROOT / 'streamlit_app.py'), default_timeout=20).run()
    assert not app.exception and not app.error
    assert not app.text_input and not app.text_area  # Fixed examples remain readable, non-editable text.
    example.assert_not_called()
    app.selectbox(key='scenario').select(key).run()
    app.button[0].click().run()
    assert not app.exception and not app.error
    assert [tab.label for tab in app.tabs] == ['Recommendation', 'Evidence', 'Activity & limitations']
    assert len(app.metric) == 4 and len(app.session_state['run'].result.graph_trace) > 0
    example.assert_called_once_with(key)
    app.run()
    example.assert_called_once()
    live.assert_not_called()
    app.radio(key='mode').set_value('Live investigation').run()
    assert 'run' not in app.session_state and app.button[0].disabled
    live.assert_not_called()


def test_live_form_requires_submit_and_consent_and_preserves_failed_evidence(monkeypatch, capsys, caplog):
    result = failed_run()
    def submit(request, *, allow_paid):
        if not allow_paid:
            raise service.DemoError('live_not_authorized')
        return result
    live = Mock(side_effect=submit)
    monkeypatch.setattr(service, 'run_live', live)
    monkeypatch.setenv('IT_SUPPORT_DEMO_LIVE', '1')
    app = AppTest.from_file(str(service.ROOT / 'streamlit_app.py'), default_timeout=20).run()
    app.radio(key='mode').set_value('Live investigation').run()
    app.text_input(key='subject').set_value('VPN failed')
    app.text_area(key='description').set_value('Public sites work, but VPN failed once.').run()
    live.assert_not_called()
    # Streamlit batches form changes at submission, not at unrelated rerenders.
    app.text_input(key='subject').set_value('VPN failed')
    app.text_area(key='description').set_value('Public sites work, but VPN failed once.')
    app.button[0].click().run()
    assert 'paid-use confirmation' in app.error[0].value
    app.checkbox(key='paid_consent').check().run()
    assert live.call_count == 1
    app.checkbox(key='paid_consent').check()
    app.button[0].click().run()
    assert live.call_count == 2 and not app.exception
    assert app.session_state['run'].result.kb_evidence == result.result.kb_evidence
    assert any('No accepted recommendation' in message.value for message in app.warning)
    assert any('Partial investigation' in message.value for message in app.warning)
    app.run()
    assert live.call_count == 2
    live.side_effect = service.DemoError('CANARY-secret')
    app.button[0].click().run()
    assert 'run' not in app.session_state
    assert all('CANARY' not in message.value for message in app.error)
    captured = capsys.readouterr()
    assert 'CANARY-secret' not in captured.out + captured.err + caplog.text


@pytest.mark.parametrize('state', ['clarify', 'failed', 'long_content'])
def test_additional_display_states_preserve_plain_text_and_empty_lists(monkeypatch, state):
    from app.investigation.synthesis import abstention
    run = service.run_example('documentation-gap')
    data = run.result.model_dump()
    if state == 'clarify':
        data.update(stop_reason='clarify', missing_fields=['employee_id'],
                    recommendation=abstention('More information is needed.', ['Employee ID for the requested account lookup.']).model_dump())
    elif state == 'failed':
        data.update(status='failed', classification=None, kb_evidence=[], stop_reason='planner_failed',
                    recommendation=None, synthesis_status='skipped',
                    errors=[{'stage':'planner','code':'planner_failed'}])
    else:
        # Rendering must preserve long supplied text literally, including markup.
        run.request.ticket.description = '<script>CANARY-NOT-HTML</script> ' + 'Fictional detail. ' * 180
        data['recommendation']['summary']['text'] = 'Long example summary. ' * 27
    run = replace(run, result=InvestigationResult.model_validate(data))
    monkeypatch.setattr(service, 'run_example', Mock(return_value=run))
    app = AppTest.from_file(str(service.ROOT / 'streamlit_app.py'), default_timeout=20).run()
    app.button[0].click().run()
    assert not app.exception
    assert any('Undetermined' == item.value for item in app.text)
    assert not app.session_state['run'].result.recommendation or not app.session_state['run'].result.recommendation.steps
    if state == 'clarify':
        assert any('More information needed' in item.value for item in app.info)
        assert any(item.value == 'Employee ID' for item in app.text)
    elif state == 'failed':
        assert any('Investigation failed' in item.value for item in app.error)
        assert any('No accepted recommendation' in item.value for item in app.warning)
    else:
        assert any(item.value == run.request.ticket.description.strip() for item in app.text)
        assert all('CANARY-NOT-HTML' not in item.value for item in app.markdown)


def test_clarification_and_failure_are_distinct_display_states():
    run = service.run_example('documentation-gap')
    data = run.result.model_dump()
    data.update(stop_reason='clarify', missing_fields=['employee_id'])
    assert outcome(InvestigationResult.model_validate(data))[0] == 'info'
    data.update(status='failed', errors=[{'stage':'planner','code':'planner_failed'}])
    assert outcome(InvestigationResult.model_validate(data))[0] == 'error'
