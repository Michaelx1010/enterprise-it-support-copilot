"""Versioned terminal choices, contextual semantics and deterministic abstention."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
from openai.lib._pydantic import to_strict_json_schema
import pytest

from app.investigation.graph import run_investigation
from app.investigation.planner import PlannerError, PlannerResponse, PlannerResponseV2, PlannerView
from app.investigation.schemas import DECISION_ADAPTER, InvestigationResult, InvestigationSynthesis, Limits
from app.investigation.scripted import ScriptedPlanner, script_dependencies
from app.investigation.synthesis_draft import InvestigationSynthesisDraftV1, InvestigationSynthesisDraftV2, InvestigationSynthesisDraftV3
from app.providers.openai_planner import OpenAIPlanner
from app.rag.schemas import SupportRecommendation
from evaluation.live_investigation import RecordedPlanner, project_report
from evaluation.live_telemetry import MeteredTransport, usage_totals
from evaluation.planner_terminals import case_script, evaluate, load_cases

VERSION = 'investigation-planner-response-v2'
GAP = {'kind': 'insufficient_evidence', 'gap_kind': 'documentation'}
CASES = load_cases()

# Captured before Phase 5C.3 from c71f00d; no historical artifact is rewritten.
SCHEMA_HASHES = [
    (PlannerResponse, 'acad5eaeab7a38b1e29af8b0e78c376f577a948affe66a8c2f183049557e20af', 'acad5eaeab7a38b1e29af8b0e78c376f577a948affe66a8c2f183049557e20af'),
    (InvestigationResult, '86d85b460f2a8be48638be49b8e298cc6bace5b66c223c3fc9da2c7ee2723c7c', 'd48688c6e8c244bf91a4569a4c36f915b60bed6f7995f40c01357af395e8e39a'),
    (InvestigationSynthesis, '2fb39d8df951ca5c786ca5b241b0adaa0b21994efb7f5029df8fb6b08db061a1', '2ba827873431b5a02aa189d7428bdab80d62b94a161bbfa408fcf42a239a33e5'),
    (InvestigationSynthesisDraftV1, '7805c036770c6b0a73060e67239ac8804596a54b5a761bf9f668b8a236d8f02e', '21ea04537730fe93991770ce07179a8614369b163ba6cc1713e1664fdd37fd03'),
    (InvestigationSynthesisDraftV2, '3aa89c23fd9b1ef54aa4f39db20a00a02d8bf067f752892a04d0a16e822e8f17', '245fc0da69aa83562f7a454d6d8be43b80616678eacaf72fa5af4cbfbc305794'),
    (InvestigationSynthesisDraftV3, '6eb9a1f208f2423bed3d79cafde1c771df03342bb732c3bd525a56bd740a33bd', '0efe75163b88125116e34c444bad9b47c5dd93bbb91ac949f135a637ba481749'),
    (SupportRecommendation, 'a73ef1e090b3ca069ad58580f81caec4fed551e8a9b914d532e14719aa3a4f87', 'a73ef1e090b3ca069ad58580f81caec4fed551e8a9b914d532e14719aa3a4f87'),
]


@pytest.mark.parametrize('mode', ['validation', 'serialization', 'sdk'])
@pytest.mark.parametrize('model,canonical_hash,sdk_hash', SCHEMA_HASHES, ids=[row[0].__name__ for row in SCHEMA_HASHES])
def test_historical_planner_and_all_report_schema_hashes_unchanged(mode, model, canonical_hash, sdk_hash):
    schema = to_strict_json_schema(model) if mode == 'sdk' else model.model_json_schema(mode=mode)
    assert hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest() == (sdk_hash if mode == 'sdk' else canonical_hash)


@pytest.mark.parametrize('case', CASES, ids=lambda c: c.id)
def test_authored_terminal_replay_distinguishes_semantics_from_acceptance(case):
    row = evaluate(case)
    assert row['mechanically_completed']
    assert row['matches_authored_expectation'] == (case.manual_verdict == 'correct')
    assert row['planner_decisions'] == 1 and row['lookup_attempts'] == 0
    # The negative controls are semantically INCORRECT despite valid typed outputs.
    assert row['manual_verdict'] == case.manual_verdict


@pytest.mark.parametrize('case', CASES, ids=lambda c: c.id)
def test_mock_sdk_preserves_terminal_context_and_manual_labels(case, planner_client, planner_response):
    script = case_script(case)
    payloads = []
    def handler(request):
        payloads.append(json.loads(json.loads(request.content)['input'][1]['content']))
        return httpx.Response(200, json=planner_response(case.decision.model_dump(mode='json')))
    result = run_investigation(script.request, dependencies=replace(
        script_dependencies(script), planner=OpenAIPlanner(planner_client(handler)), phase='4B.1'))
    assert result.status == 'completed' and result.stop_reason == case.decision.kind
    assert result.missing_fields == getattr(case.decision, 'missing_fields', [])
    assert result.synthesis_status == 'not_run' and result.recommendation is None
    assert result.planner_decisions == len(payloads) == 1 and result.lookup_attempts == 0
    payload = payloads[0]
    assert payload['untrusted_evidence']['ticket'] == script.request.ticket.model_dump()
    assert [e['reference']['chunk_id'] for e in payload['untrusted_evidence']['kb_procedures']] == case.kb_chunk_ids
    assert not {'manual_verdict', 'review_notes', 'expected_terminal', 'expected_missing_fields'} & payload.keys()
    assert case.review_notes not in json.dumps(payload)


@pytest.mark.parametrize('candidate', [
    {'decision': GAP},  # Historical envelope is not a live fallback.
    {'schema_version': 'investigation-planner-response-v1', 'decision': GAP},
    {'schema_version': None, 'decision': GAP},
    {'schema_version': VERSION, 'decision': {'kind': 'insufficient_evidence'}},
    {'schema_version': VERSION, 'decision': GAP | {'gap_kind': 'operational'}},
    {'schema_version': VERSION, 'decision': GAP | {'missing_fields': ['employee_id']}},
    {'schema_version': VERSION, 'decision': GAP | {'reason': 'PRIVATE-MODEL-OUTPUT'}},
    {'schema_version': VERSION, 'decision': GAP, 'PRIVATE-KEY': 'PRIVATE-SECRET'},
])
def test_invalid_wire_rejects_once_without_exposing_output(candidate, inv_request, planner_client, planner_response):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(candidate)))
    planner = OpenAIPlanner(planner_client(handler, max_retries=5))
    view = PlannerView(request=inv_request, classification=None, kb_evidence=[],
                       operational_evidence=[], available_device_ids=[])
    with pytest.raises(PlannerError) as caught:
        planner.decide(view, 0)
    assert caught.value.code == 'invalid_output' and len(calls) == 1
    assert 'PRIVATE' not in str(caught.value) and caught.value.__suppress_context__


@pytest.mark.parametrize('mutation', ['legacy', 'version', 'decision'])
def test_provider_revalidates_parsed_type_and_fields(mutation, inv_request, recwarn):
    parsed = PlannerResponseV2(schema_version=VERSION, decision=GAP)
    if mutation == 'legacy': parsed = PlannerResponse(decision={'kind': 'finish'})
    elif mutation == 'version': parsed.schema_version = 'private-version'
    else: parsed.decision.gap_kind = 'private-gap'
    response = SimpleNamespace(status='completed', output_parsed=parsed,
        output=[SimpleNamespace(type='message', content=[SimpleNamespace(type='output_text')])])
    client = Mock()
    client.with_options.return_value = client
    client.responses.parse.return_value = response
    view = PlannerView(request=inv_request, classification=None, kb_evidence=[],
                       operational_evidence=[], available_device_ids=[])
    with pytest.raises(PlannerError, match='invalid_output'):
        OpenAIPlanner(client).decide(view, 0)
    assert client.responses.parse.call_count == 1
    assert not recwarn


@pytest.mark.parametrize('case_id', ['cafeteria-documentation-gap', 'irrelevant-kb-documentation-gap'])
def test_documentation_abstention_is_fixed_no_action_and_no_synthesis_call(case_id):
    script = case_script(next(c for c in CASES if c.id == case_id))
    synthesis = Mock(generate=Mock(side_effect=AssertionError('Must not generate')))
    result = run_investigation(script.request, dependencies=replace(script_dependencies(script), synthesis=synthesis))
    synthesis.generate.assert_not_called()
    report = result.recommendation
    assert result.status == 'completed' and result.stop_reason == 'insufficient_evidence'
    assert result.synthesis_status == 'completed' and result.synthesis_attempts == 0
    assert result.missing_fields == [] and report.status == 'insufficient_evidence'
    assert report.summary.text == ('The supplied KB evidence does not establish an applicable documented procedure '
                                   'for this request. Escalation need is undetermined.')
    assert report.missing_information == ['Applicable procedure documentation is needed for human review.']
    assert report.steps == report.conditional_guidance == []
    assert not report.escalation_required and report.escalation_reason is report.trigger_basis is None
    assert report.summary.references[0].kind == 'investigation_context'
    assert result.graph_trace[-2].outcome == 'documentation_abstention'
    assert result.kb_evidence and result.classification
    assert result.human_review_required and not result.mutating_actions_executed
    assert project_report(report.model_dump())['steps'] == []
    assert InvestigationResult.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize('error_mode', ['none', 'classification', 'retrieval', 'both'])
def test_gap_retains_observations_and_errors_without_promoting_partial_runs(
        error_mode, inv_request, inv_dependencies):
    provider = Mock()
    deps = replace(inv_dependencies, synthesis=provider, planner=ScriptedPlanner([
        {'kind': 'lookup', 'tool': 'get_employee_account_status', 'arguments': {'employee_id': 'EMP-001'}}, GAP]))
    if error_mode in ('classification', 'both'):
        deps = replace(deps, classifier=Mock(generate=Mock(side_effect=RuntimeError('PRIVATE'))))
    if error_mode in ('retrieval', 'both'):
        deps = replace(deps, store=Mock(manifest=Mock(side_effect=RuntimeError('PRIVATE'))))
    result = run_investigation(inv_request, dependencies=deps)
    assert result.status == ('completed' if error_mode == 'none' else 'partial')
    assert result.stop_reason == 'insufficient_evidence' and result.planner_decisions == 2
    assert result.lookup_attempts == len(result.lookup_trace) == len(result.operational_evidence) == 1
    assert result.lookup_trace[0].executed and result.lookup_trace[0].status == 'ok'
    assert not result.operational_evidence[0].observation.result.live_verified
    assert result.operational_evidence[0].observation.result.queried_at
    assert bool(result.errors) == (error_mode != 'none')
    assert 'PRIVATE' not in result.model_dump_json() and result.synthesis_attempts == 0
    provider.generate.assert_not_called()


def test_gap_without_any_successful_evidence_stays_failed(inv_request, inv_dependencies):
    result = run_investigation(inv_request, dependencies=replace(inv_dependencies,
        planner=ScriptedPlanner([GAP]), synthesis=Mock(),
        classifier=Mock(generate=Mock(side_effect=RuntimeError('PRIVATE'))),
        store=Mock(manifest=Mock(side_effect=RuntimeError('PRIVATE')))))
    assert result.status == 'failed' and len(result.errors) == 2
    assert not result.kb_evidence and not result.operational_evidence and result.classification is None
    assert result.recommendation.steps == [] and result.synthesis_attempts == 0


@pytest.mark.parametrize('stop', ['budget', 'blocked', 'lookup_error', 'planner_error'])
def test_documentation_terminal_cannot_bypass_stops(stop, inv_request, inv_dependencies):
    lookup = {'kind': 'lookup', 'tool': 'get_employee_devices', 'arguments': {'employee_id': 'EMP-001'}}
    deps = inv_dependencies
    sequence = [lookup, GAP]
    expected = {'budget': 'decision_budget', 'blocked': 'employee_out_of_scope',
                'lookup_error': 'lookup_failed', 'planner_error': 'planner_failed'}[stop]
    if stop == 'budget': deps = replace(deps, limits=Limits(planner_decisions=1))
    if stop == 'blocked': sequence[0] = lookup | {'arguments': {'employee_id': 'EMP-002'}}
    if stop == 'lookup_error': deps = replace(deps, fixture_lookup=Mock(side_effect=RuntimeError('PRIVATE')))
    if stop == 'planner_error': sequence[1] = GAP | {'missing_fields': ['employee_id']}
    result = run_investigation(inv_request, dependencies=replace(deps, planner=ScriptedPlanner(sequence)))
    assert result.status == 'partial' and result.stop_reason == expected and result.errors
    assert result.kb_evidence and result.classification
    assert result.synthesis_status == 'not_run' and result.recommendation is None
    assert result.operational_evidence or stop in ('blocked', 'lookup_error')
    assert 'PRIVATE' not in result.model_dump_json()


def test_last_allowed_terminal_and_deadline_are_preserved(inv_request, inv_dependencies):
    result = run_investigation(inv_request, dependencies=replace(inv_dependencies,
        limits=Limits(planner_decisions=1), planner=ScriptedPlanner([GAP]), synthesis=Mock()))
    assert result.status == 'completed' and result.planner_decisions == 1
    time = [0.]
    class LatePlanner:
        def decide(self, view, index):
            time[0] = 121.
            return deepcopy(GAP)
    provider = Mock()
    result = run_investigation(inv_request, dependencies=replace(inv_dependencies,
        planner=LatePlanner(), synthesis=provider, clock=lambda: time[0]))
    assert result.status == 'partial' and result.recommendation is None
    assert result.synthesis_status == 'skipped' and result.errors[-1].code == 'synthesis_deadline'
    provider.generate.assert_not_called()


def test_supported_action_with_no_optional_scope_reaches_unchanged_synthesis(synthesis_report):
    script = case_script(next(c for c in CASES if c.id == 'supported-without-optional-scope'))
    synthesis_report['steps'][0]['references'] = [{'kind': 'kb_chunk', 'chunk_id': script.kb_results[0].chunk.chunk_id}]
    provider = Mock(generate=Mock(return_value=InvestigationSynthesis.model_validate(synthesis_report)))
    result = run_investigation(script.request, dependencies=replace(script_dependencies(script), synthesis=provider))
    assert result.status == 'completed' and result.stop_reason == 'finish'
    assert result.synthesis_attempts == provider.generate.call_count == 1
    assert result.missing_fields == [] and result.recommendation.status == 'supported'


@pytest.mark.parametrize('schema', ['PlannerResponse', 'PlannerResponseV2'])
def test_telemetry_preserves_old_and_new_schema_identity(schema):
    meter = MeteredTransport(httpx.MockTransport(lambda request: httpx.Response(200, json={})))
    with httpx.Client(transport=meter) as client:
        client.post('https://api.openai.com/v1/responses', json={
            'model': 'test', 'text': {'format': {'name': schema}}, 'input': 'PRIVATE'})
    assert meter.calls[0]['stage'] == 'planner' and meter.calls[0]['usage'] is None
    assert usage_totals(meter.calls)['requests_without_total_tokens'] == 1
    assert 'PRIVATE' not in json.dumps(meter.calls)


def test_evaluation_recorder_retains_typed_gap_without_invented_identifiers(inv_request):
    planner = RecordedPlanner(ScriptedPlanner([GAP]))
    view = PlannerView(request=inv_request, classification=None, kb_evidence=[],
                       operational_evidence=[], available_device_ids=[])
    assert planner.decide(view, 0) == GAP
    assert planner.decisions[0]['decision'] == GAP and planner.decisions[0]['error'] is None
    assert DECISION_ADAPTER.validate_python(GAP).model_dump() == GAP
