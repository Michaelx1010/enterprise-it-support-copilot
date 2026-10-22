"""Context consistency regressions for the user-reported VPN smoke test."""

from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from app.investigation.graph import run_investigation
from app.investigation.planner import PlannerResponse
from app.investigation.schemas import InvestigationRequest
from app.investigation.scripted import ReplayStore, ScriptedEmbedder, ScriptedPlanner
from app.kb.documents import load_chunks
from app.kb.schemas import SearchResult
from app.rag.recommendation import build_query
from app.schemas import TicketInput


def lookup(tool, **arguments):
    return {'kind': 'lookup', 'tool': tool, 'arguments': arguments}


def clarify(*fields):
    return {'kind': 'clarify', 'missing_fields': list(fields)}


@pytest.fixture
def smoke_case(inv_dependencies):
    # The checked-in request is the exact input named in the user's smoke command.
    request = InvestigationRequest.model_validate_json(
        Path('examples/investigation-request.json').read_text(encoding='utf-8'))
    spec = inv_dependencies.embedder.spec
    chunks = [c for c in load_chunks(Path('knowledge_base')) if c.document_id == 'vpn-access']
    rows = [SearchResult(chunk=c, distance=d) for c, d in zip(chunks, [0.4671, 0.4792, 0.5116])]
    assert len(rows) == 3
    deps = replace(inv_dependencies,
                   embedder=ScriptedEmbedder(build_query(request.ticket), spec, [1., 0., 0.]),
                   store=ReplayStore(spec, rows), phase='4B.1')
    return request, deps


def mocked_planner(decisions, planner_client, planner_response, payloads):
    from app.providers.openai_planner import OpenAIPlanner

    def handler(request):
        payloads.append(json.loads(json.loads(request.content)['input'][1]['content']))
        return httpx.Response(200, json=planner_response(decisions[len(payloads) - 1]))
    return OpenAIPlanner(planner_client(handler))


def test_smoke_clarification_is_schema_valid_but_rejected_in_context(
        smoke_case, planner_client, planner_response):
    request, deps = smoke_case
    bad = clarify('employee_id', 'service_ids', 'software_ids', 'ticket_details')
    # Schema validity is explicitly NOT the assertion under test.
    assert PlannerResponse.model_validate({'decision': bad}).graph_decision() == bad
    payloads = []
    planner = mocked_planner([
        lookup('get_employee_account_status', employee_id='EMP-001'),
        lookup('get_active_service_incidents', service_id='SVC-001', limit=5),
        bad,
    ], planner_client, planner_response, payloads)
    result = run_investigation(request, dependencies=replace(deps, planner=planner))
    third = payloads[2]
    assert third['control']['employee_id'] == 'EMP-001'
    assert third['control']['service_ids'] == ['SVC-001']
    assert third['control']['software_ids'] == []
    assert third['untrusted_evidence']['ticket'] == request.ticket.model_dump()
    assert len(third['untrusted_evidence']['operational_observations']) == 2
    assert len(third['untrusted_evidence']['kb_procedures']) == 3
    assert third['control']['remaining_decisions'] == third['control']['remaining_lookups'] == 2
    assert result.status == 'partial' and result.stop_reason == 'planner_failed'
    assert result.errors[-1].stage == 'planner'
    assert result.planner_decisions == len(payloads) == 3  # No retry or automatic substitute.
    assert result.lookup_attempts == 2 and len(result.operational_evidence) == 2
    assert result.classification is not None and len(result.kb_evidence) == 3
    assert result.missing_fields == []
    assert all(outcome.executed and outcome.status == 'ok' for outcome in result.lookup_trace)
    assert result.human_review_required and not result.mutating_actions_executed


@pytest.mark.parametrize('fields', [
    ['employee_id'], ['service_ids'], ['software_ids'],
    ['employee_id', 'ticket_details'], ['ticket_details', 'ticket_details'],
])
def test_mocked_clarification_checks_context_not_only_enum(
        inv_request, inv_dependencies, planner_client, planner_response, fields):
    payloads = []
    decision = clarify(*fields)
    assert PlannerResponse.model_validate({'decision': decision}).graph_decision() == decision
    planner = mocked_planner([decision], planner_client, planner_response, payloads)
    executor = Mock()
    result = run_investigation(inv_request, dependencies=replace(
        inv_dependencies, planner=planner, fixture_lookup=executor))
    assert result.stop_reason == 'planner_failed' and result.status == 'partial'
    assert result.missing_fields == [] and len(payloads) == 1
    executor.assert_not_called()


@pytest.mark.parametrize('field,absent,description', [
    ('employee_id', None, 'Check the devices assigned to the affected employee; their ID is not supplied.'),
    ('service_ids', [], 'Check recorded incidents for the affected service; its scoped ID is not supplied.'),
    ('software_ids', [], 'Check my software entitlement; the scoped software ID is not supplied.'),
])
def test_genuinely_absent_scope_can_still_be_clarified(
        inv_request, inv_dependencies, planner_client, planner_response, field, absent, description):
    request = inv_request.model_copy(update={
        field: absent, 'ticket': TicketInput(subject='Investigate recorded information', description=description)})
    payloads = []
    planner = mocked_planner([clarify(field)], planner_client, planner_response, payloads)
    deps = replace(inv_dependencies, planner=planner,
                   embedder=ScriptedEmbedder(build_query(request.ticket), inv_dependencies.embedder.spec, [1., 0., 0.]))
    result = run_investigation(request, dependencies=deps)
    assert result.status == 'completed' and result.stop_reason == 'clarify'
    assert result.missing_fields == [field] and result.lookup_attempts == 0


def test_empty_optional_scope_is_not_automatically_reported_missing(
        inv_request, inv_dependencies, planner_client, planner_response):
    request = inv_request.model_copy(update={'employee_id': None, 'service_ids': [], 'software_ids': []})
    payloads = []
    planner = mocked_planner([{'kind': 'finish'}], planner_client, planner_response, payloads)
    result = run_investigation(request, dependencies=replace(inv_dependencies, planner=planner))
    assert result.status == 'completed' and result.missing_fields == []
    assert result.lookup_attempts == 0 and len(payloads) == 1


def test_present_ticket_can_still_need_additional_symptom_detail(
        inv_request, inv_dependencies, planner_client, planner_response):
    # The subject/description do not provide an error code. Presence alone cannot
    # prove that every possible clarification is unnecessary.
    payloads = []
    planner = mocked_planner([clarify('ticket_details')], planner_client, planner_response, payloads)
    result = run_investigation(inv_request, dependencies=replace(inv_dependencies, planner=planner))
    assert result.status == 'completed' and result.missing_fields == ['ticket_details']
    assert result.stop_reason == 'clarify' and result.planner_decisions == 1


def test_devices_then_finish_is_possible_without_optional_software_scope(
        smoke_case, planner_client, planner_response):
    request, deps = smoke_case
    payloads = []
    planner = mocked_planner([
        lookup('get_employee_account_status', employee_id='EMP-001'),
        lookup('get_active_service_incidents', service_id='SVC-001', limit=5),
        lookup('get_employee_devices', employee_id='EMP-001'),
        {'kind': 'finish'},
    ], planner_client, planner_response, payloads)
    result = run_investigation(request, dependencies=replace(deps, planner=planner))
    assert result.status == 'completed' and result.stop_reason == 'finish'
    assert result.planner_decisions == len(payloads) == 4 and result.lookup_attempts == 3
    assert result.missing_fields == [] and result.errors == []
    assert payloads[2]['control']['available_device_ids'] == []  # Not needed to list devices.
    assert payloads[3]['control']['available_device_ids'] == ['DEV-001', 'DEV-010']
    assert all(p['control']['software_ids'] == [] for p in payloads)
    assert [e.observation.tool for e in result.operational_evidence] == [
        'get_employee_account_status', 'get_active_service_incidents', 'get_employee_devices']


def test_invalid_clarification_without_evidence_retains_failed_semantics(inv_request, inv_dependencies):
    deps = replace(inv_dependencies, planner=ScriptedPlanner([clarify('employee_id')]),
                   classifier=Mock(generate=Mock(side_effect=RuntimeError('private'))),
                   store=Mock(manifest=Mock(side_effect=RuntimeError('private'))))
    result = run_investigation(inv_request, dependencies=deps)
    assert result.status == 'failed' and result.stop_reason == 'planner_failed'
    assert result.classification is None and not result.kb_evidence and not result.operational_evidence
    assert result.missing_fields == [] and result.planner_decisions == 1


def test_clarification_validation_uses_original_scope_not_mutated_view(inv_request, inv_dependencies):
    class MutatingPlanner:
        def decide(self, view, index):
            view.request.employee_id = None
            return clarify('employee_id')
    result = run_investigation(inv_request, dependencies=replace(inv_dependencies, planner=MutatingPlanner()))
    assert result.stop_reason == 'planner_failed' and result.missing_fields == []
    assert inv_request.employee_id == 'EMP-001'
