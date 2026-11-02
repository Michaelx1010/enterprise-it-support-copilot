"""Authored pilot-error contrasts; mocks do not measure model judgment."""

from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from app.investigation import planner, synthesis
from app.investigation.graph import run_investigation
from app.investigation.schemas import InvestigationRequest
from app.investigation.scripted import ReplayStore, ScriptedClassifier, ScriptedEmbedder
from app.kb.documents import load_chunks
from app.kb.schemas import SearchResult
from app.providers.openai_planner import OpenAIPlanner
from app.providers.openai_synthesis import OpenAISynthesis
from app.rag.recommendation import build_query
from app.schemas import TicketClassification
from evaluation.investigation_e2e import review_items
from evaluation.investigation_synthesis import SynthesisCase, evaluate, summarize


@pytest.fixture
def corpus():
    return {chunk.section_id: chunk for chunk in load_chunks(Path('knowledge_base'))}


@pytest.mark.parametrize('scenario', ['documentation_gap', 'missing_employee', 'missing_software', 'irrelevant_clarification'])
def test_authored_terminal_contrasts_keep_valid_clarification_and_safe_abstention(
        scenario, corpus, inv_dependencies, planner_client, planner_response):
    unsupported = scenario in ('documentation_gap', 'irrelevant_clarification')
    ticket = ('How can IT restore deleted cafeteria payment transactions?' if unsupported else
              'Check whether my company account is recorded locked.' if scenario == 'missing_employee' else
              'Check whether I have a license for my requested software.')
    sections = (['password-reset#identity-verification-boundary', 'mfa-recovery#lost-phone-or-replaced-authenticator',
                 'mfa-recovery#codes-rejected-on-the-same-phone'] if unsupported else
                ['account-lockouts#several-applications-reject-login'] if scenario == 'missing_employee' else
                ['software-licensing#license-allocation'])
    request = InvestigationRequest(ticket={'subject': 'Fictional IT request', 'description': ticket},
        employee_id='EMP-001' if scenario == 'missing_software' else None)
    decision = ({'kind': 'insufficient_evidence', 'gap_kind': 'documentation'} if scenario == 'documentation_gap' else
                {'kind': 'clarify', 'missing_fields': ['software_ids' if scenario == 'missing_software' else 'employee_id']})
    expected_terminal = 'insufficient_evidence' if unsupported else 'clarify'
    rows = [SearchResult(chunk=corpus[s], distance=i / 10) for i, s in enumerate(sections)]
    calls = []
    def handler(api_request):
        body = json.loads(api_request.content)
        calls.append(body)
        assert body['input'][0]['content'] == planner.INSTRUCTIONS
        assert body['text']['format']['name'] == 'PlannerResponseV2'
        payload = json.loads(body['input'][1]['content'])
        assert payload['prompt_version'] == 'investigation-planner-v5'
        assert payload['untrusted_evidence']['ticket'] == request.ticket.model_dump()
        assert [e['result'] for e in payload['untrusted_evidence']['kb_procedures']] == [r.model_dump(mode='json') for r in rows]
        assert payload['control']['employee_id'] == request.employee_id
        assert payload['control']['software_ids'] == []
        assert not {'expected_terminal', 'manual_verdict', 'review_notes'} & payload.keys()
        return httpx.Response(200, json=planner_response(decision))
    forbidden_synthesis = Mock(generate=Mock(side_effect=AssertionError('Terminal decisions must not call synthesis.')))
    spec = inv_dependencies.embedder.spec
    result = run_investigation(request, dependencies=replace(inv_dependencies,
        classifier=ScriptedClassifier(TicketClassification(category='Account', priority='Medium', summary=ticket)),
        embedder=ScriptedEmbedder(build_query(request.ticket), spec, [1., 0., 0.]), store=ReplayStore(spec, rows),
        planner=OpenAIPlanner(planner_client(handler)), synthesis=forbidden_synthesis))
    assert result.status == 'completed' and result.planner_decisions == len(calls) == 1
    assert result.lookup_attempts == result.synthesis_attempts == 0
    forbidden_synthesis.generate.assert_not_called()
    assert not result.recommendation.steps and not result.recommendation.escalation_required
    assert result.human_review_required and not result.mutating_actions_executed
    assert (result.stop_reason == expected_terminal) is (scenario != 'irrelevant_clarification')
    assert result.missing_fields == decision.get('missing_fields', [])
    if scenario == 'documentation_gap':
        assert 'supplied KB evidence' in result.recommendation.summary.text
        assert all('employee_id' not in text for text in result.recommendation.missing_information)
    # The wrong clarification still passes structural validation. It is an authored
    # semantic failure, never evidence that the revised prompt chose correctly.


@pytest.mark.parametrize('scenario', ['confirmed', 'first_failure', 'email_checks',
                                      'prematurely_deferred', 'invented_future_handoff'])
def test_authored_synthesis_contrasts_separate_policy_trigger_and_missing_details(
        scenario, corpus, planner_client, planner_response):
    email = scenario in ('email_checks', 'invented_future_handoff')
    confirmed = scenario in ('confirmed', 'prematurely_deferred')
    incorrect = scenario in ('prematurely_deferred', 'invented_future_handoff')
    ticket = ('New mail arrives in browser email but desktop mail does not sync.' if email else
              'Public sites load. Corporate gateway error G42 keeps recurring after reconnecting once.' if confirmed else
              'Public sites load without VPN. Corporate VPN failed once; I have not retried.')
    chunk = corpus['email-troubleshooting#browser-works-but-desktop-does-not-sync' if email else 'vpn-access#connection-failures']
    kb_ref, ticket_ref = {'kind': 'kb_chunk', 'chunk_id': chunk.chunk_id}, {'kind': 'ticket'}
    current_handoff = scenario == 'confirmed'
    action = ('Send the reported persistent G42 gateway error and client version to Network Support.' if current_handoff else
              'Confirm the client is not in Work Offline mode and restart it once.' if email else
              'Confirm that a public website loads without VPN.' if confirmed else
              'Select the Corporate gateway and reconnect once.')
    report = {
        'schema_version': 'investigation-synthesis-draft-v4',
        'summary': {'text': 'The user reports: ' + ticket, 'references': [ticket_ref]},
        'findings': [], 'steps': [{'step_type': 'escalation' if current_handoff else 'troubleshooting',
                                  'action': action, 'references': [kb_ref, ticket_ref]}],
        'missing_information': ['Provide the error time and client version for the handoff.'] if confirmed else [],
        'uncertainties': [], 'escalation_reason': None, 'conditional_guidance': [], 'trigger_basis': None,
    }
    if current_handoff:
        report['escalation_reason'] = {'text': 'The ticket reports persistent gateway errors after a retry, matching the KB handoff rule.',
                                       'references': [kb_ref, ticket_ref]}
        report['trigger_basis'] = {'policy_references': [kb_ref], 'factual_references': [ticket_ref],
                                  'explanation': 'Persistence after a retry is ticket-reported; the error timestamp is still needed for submission.'}
    if scenario in ('first_failure', 'prematurely_deferred', 'invented_future_handoff'):
        report['conditional_guidance'] = [{
            'condition': 'Desktop sync still fails after the client checks.' if email else 'Gateway errors persist after reconnecting once.',
            'action': 'Escalate to Messaging Support.' if email else 'Send the error code and client version to Network Support.',
            'references': [kb_ref], 'missing_evidence': 'Whether the issue persists after the documented checks.',
        }]
    observations = {}
    if email:
        observations = {'lookup-1': 'Recorded service owner: Messaging Support. updated_at=2026-10-16T08:00:00Z; live_verified=false. Not policy.'}
        report['uncertainties'] = [{'text': 'The October 16 service-owner snapshot does not verify live state or authorize a handoff.',
                                   'references': [{'kind': 'operational_observation', 'lookup_id': 'lookup-1'}]}]
    case = SynthesisCase(id=scenario, ticket=ticket, kb={chunk.chunk_id: chunk.content}, observations=observations,
        candidate=report, expected_status='supported', expected_escalation=confirmed, expected_replay='accepted',
        manual_verdict='incorrect' if incorrect else 'acceptable',
        review_notes='Authored control: compare documented policy, reported trigger and remaining submission details.')
    before = case.model_dump_json()
    calls = []
    def handler(api_request):
        body = json.loads(api_request.content)
        calls.append(body)
        assert body['input'][0]['content'] == synthesis.INSTRUCTIONS
        assert body['text']['format']['name'] == 'InvestigationSynthesisDraftV4'
        payload = json.loads(body['input'][1]['content'])
        assert payload['untrusted_evidence'] == {'ticket': ticket, 'kb_procedures': case.kb, 'operational_observations': observations}
        assert case.review_notes not in json.dumps(payload)
        assert not {'manual_verdict', 'expected_escalation', 'expected_status'} & payload.keys()
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(report)))
    result = evaluate(case, OpenAISynthesis(planner_client(handler)))
    assert result['outcome'] == 'accepted' and len(calls) == 1
    assert result['report'] == report_without_version(report) | {'status': 'supported', 'escalation_required': current_handoff}
    assert case.model_dump_json() == before
    metrics = summarize([case], [result])
    assert metrics['escalation_label_matches']['count'] == (0 if scenario == 'prematurely_deferred' else 1)
    assert all(row['entailment'] is None for row in review_items(result['report'], agent=True))
    if incorrect:
        assert case.manual_verdict == 'incorrect'  # Valid citations do not prove correct applicability/policy.
    if scenario == 'invented_future_handoff':
        assert 'Messaging Support' not in chunk.content  # Owner metadata cannot authorize this invented policy.


def report_without_version(report):
    return {key: value for key, value in report.items() if key != 'schema_version'}
