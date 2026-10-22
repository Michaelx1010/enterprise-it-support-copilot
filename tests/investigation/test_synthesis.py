"""Application grounding constraints and deterministic graph failure semantics."""

from dataclasses import replace
import json
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.investigation.graph import build_graph, run_investigation
from app.investigation.schemas import InvestigationSynthesis, InvestigationResult
from app.investigation.scripted import ScriptedPlanner
from app.investigation.synthesis import generate_synthesis, MAX_PAYLOAD_CHARACTERS
from app.providers.synthesis import SynthesisError


@pytest.fixture
def provider(synthesis_report):
    return Mock(generate=Mock(return_value=InvestigationSynthesis.model_validate(synthesis_report)))


def run(request, deps, provider, decisions=None, **overrides):
    return run_investigation(request, dependencies=replace(deps, synthesis=provider,
        planner=ScriptedPlanner(decisions or [{'kind': 'finish'}]), **overrides))


def test_optional_graph_nodes_preserve_scripted_graph():
    old = build_graph().get_graph()
    new = build_graph(synthesis=True).get_graph()
    assert 'synthesize' not in old.nodes and 'synthesize' in new.nodes
    edges = {(e.source, e.target) for e in new.edges}
    assert ('execute', 'plan') in edges and ('synthesize', 'assemble') in edges
    assert all((node, 'synthesize') in edges for node in ('classify', 'retrieve', 'plan', 'guard', 'execute'))


def test_cited_operational_finding_and_metadata_survive(inv_request, inv_dependencies, provider):
    report = provider.generate.return_value.model_dump()
    report['findings'] = [{'text': 'The recorded device list contains two assigned devices.',
                           'references': [{'kind': 'operational_observation', 'lookup_id': 'lookup-1'}]}]
    provider.generate.return_value = InvestigationSynthesis.model_validate(report)
    result = run(inv_request, inv_dependencies, provider, [
        {'kind': 'lookup', 'tool': 'get_employee_devices', 'arguments': {'employee_id': 'EMP-001'}}, {'kind': 'finish'}])
    assert result.phase == '4B.2' and result.status == 'completed'
    assert result.synthesis_status == 'completed' and result.synthesis_attempts == 1
    assert result.planner_decisions == 2 and result.lookup_attempts == 1
    assert [event.node for event in result.graph_trace][-2:] == ['synthesize', 'assemble']
    payload = json.loads(provider.generate.call_args.kwargs['payload'])
    source = payload['untrusted_evidence']['operational_observations'][0]['observation']['result']
    assert source['queried_at'] and source['devices'][0]['updated_at'] and not source['live_verified']
    assert payload['untrusted_evidence']['kb_procedures'][0]['result']['chunk']['source_path']
    assert result.human_review_required and not result.mutating_actions_executed


@pytest.mark.parametrize('location', ['summary', 'findings', 'steps', 'uncertainties', 'escalation_reason'])
@pytest.mark.parametrize('kind', ['kb_chunk', 'operational_observation'])
def test_every_citation_location_is_checked(inv_request, inv_dependencies, synthesis_report, location, kind):
    bad = {'kind': kind, 'chunk_id' if kind == 'kb_chunk' else 'lookup_id': 'invented'}
    if location == 'escalation_reason':
        synthesis_report['steps'][0]['step_type'] = 'escalation'
        synthesis_report['escalation_required'] = True
        synthesis_report[location] = {'text': 'A handoff is documented.',
                                      'references': synthesis_report['steps'][0]['references'] + [bad]}
    elif location == 'summary':
        synthesis_report[location]['references'].append(bad)
    elif location == 'findings':
        synthesis_report[location] = [{'text': 'An alleged observation.', 'references': [bad]}]
    else:
        synthesis_report[location][0]['references'].append(bad)
    provider = Mock(generate=Mock(return_value=InvestigationSynthesis.model_validate(synthesis_report)))
    result = run(inv_request, inv_dependencies, provider)
    assert result.status == 'partial' and result.synthesis_status == 'failed'
    assert result.recommendation is None and result.kb_evidence and result.classification
    assert result.errors[-1].code == 'synthesis_invalid_citation'
    assert result.synthesis_attempts == 1 and 'invented' not in result.model_dump_json()


@pytest.mark.parametrize('mutation', [
    'no_citation', 'ops_only_step', 'duplicate', 'unsupported_steps', 'supported_empty',
    'flag_without_step', 'step_without_flag', 'reason_without_flag', 'reason_without_kb',
    'extra_action', 'string_bool',
])
def test_report_structural_contracts(synthesis_report, mutation):
    if mutation == 'no_citation': synthesis_report['summary']['references'] = []
    elif mutation == 'ops_only_step': synthesis_report['steps'][0]['references'] = [{'kind': 'operational_observation', 'lookup_id': 'lookup-1'}]
    elif mutation == 'duplicate': synthesis_report['summary']['references'] *= 2
    elif mutation == 'unsupported_steps': synthesis_report['status'] = 'insufficient_evidence'
    elif mutation == 'supported_empty': synthesis_report['steps'] = []
    elif mutation == 'flag_without_step': synthesis_report['escalation_required'] = True
    elif mutation == 'step_without_flag': synthesis_report['steps'][0]['step_type'] = 'escalation'
    elif mutation == 'reason_without_flag': synthesis_report['escalation_reason'] = synthesis_report['summary']
    elif mutation == 'reason_without_kb':
        synthesis_report['escalation_required'] = True
        synthesis_report['steps'][0]['step_type'] = 'escalation'
        synthesis_report['escalation_reason'] = synthesis_report['summary']
    elif mutation == 'extra_action': synthesis_report['mutating_actions_executed'] = True
    else: synthesis_report['escalation_required'] = 'false'
    with pytest.raises(ValidationError):
        InvestigationSynthesis.model_validate(synthesis_report)


@pytest.mark.parametrize('mode', ['clarify', 'no_kb', 'retrieval_failed', 'no_evidence'])
def test_deterministic_abstention_makes_no_model_call(inv_request, inv_dependencies, provider, mode):
    overrides = {}
    decisions = [{'kind': 'finish'}]
    if mode == 'clarify': decisions = [{'kind': 'clarify', 'missing_fields': ['ticket_details']}]
    elif mode == 'no_kb': overrides['store'] = Mock(manifest=inv_dependencies.store.manifest, search=Mock(return_value=[]))
    else:
        overrides['store'] = Mock(manifest=Mock(side_effect=RuntimeError('private')))
        if mode == 'no_evidence': overrides['classifier'] = Mock(generate=Mock(side_effect=RuntimeError('private')))
    result = run(inv_request, inv_dependencies, provider, decisions, **overrides)
    provider.generate.assert_not_called()
    assert result.synthesis_attempts == 0 and result.synthesis_status == 'completed'
    assert result.recommendation.status == 'insufficient_evidence' and not result.recommendation.steps
    assert 'Escalation need is undetermined.' in result.recommendation.summary.text
    expected = 'failed' if mode == 'no_evidence' else ('partial' if mode == 'retrieval_failed' else 'completed')
    assert result.status == expected
    if mode == 'clarify': assert result.missing_fields == ['ticket_details']


@pytest.mark.parametrize('error', [RuntimeError('CANARY-SECRET'), SynthesisError('invalid_output'), SynthesisError('CANARY-SECRET')])
def test_synthesis_failure_preserves_investigation(inv_request, inv_dependencies, provider, error):
    provider.generate.side_effect = error
    result = run(inv_request, inv_dependencies, provider, [
        {'kind': 'lookup', 'tool': 'get_employee_devices', 'arguments': {'employee_id': 'EMP-001'}}, {'kind': 'finish'}])
    assert result.status == 'partial' and result.stop_reason == 'finish'
    assert result.synthesis_status == 'failed' and result.recommendation is None
    assert result.lookup_attempts == 1 and len(result.operational_evidence) == 1
    assert result.synthesis_attempts == provider.generate.call_count == 1
    assert 'CANARY' not in result.model_dump_json()


def test_partial_investigation_cannot_be_promoted_to_completed(inv_request, inv_dependencies, provider):
    result = run(inv_request, inv_dependencies, provider, [
        {'kind': 'lookup', 'tool': 'get_employee_devices', 'arguments': {'employee_id': 'EMP-002'}}])
    assert result.status == 'partial' and result.stop_reason == 'employee_out_of_scope'
    assert result.synthesis_status == 'completed' and result.lookup_attempts == 0
    payload = json.loads(provider.generate.call_args.kwargs['payload'])
    assert payload['investigation_context']['incomplete']
    assert payload['untrusted_evidence']['operational_observations'] == []


def test_partial_report_requires_context_limitation(inv_request, inv_dependencies, provider):
    provider.generate.return_value.uncertainties = []
    result = run(inv_request, inv_dependencies, provider, classifier=Mock(generate=Mock(side_effect=RuntimeError())))
    assert result.recommendation is None and result.errors[-1].code == 'synthesis_missing_limitations'


@pytest.mark.parametrize('mode', ['before', 'during', 'context'])
def test_deadline_and_context_limits_prevent_or_discard_synthesis(inv_request, inv_dependencies, provider, mode):
    time = [0.0]
    def generate(**kwargs):
        time[0] = 121
        return provider.generate.return_value
    if mode == 'during': provider.generate.side_effect = generate
    def classifier(**kwargs):
        if mode == 'before': time[0] = 121
        return inv_dependencies.classifier.generate(**kwargs)
    overrides = {'clock': lambda: time[0], 'classifier': Mock(generate=classifier)}
    decisions = [{'kind': 'finish'}]
    if mode == 'context':
        from app.investigation.schemas import Limits
        overrides['limits'] = Limits(operational_characters=1)
        decisions = [{'kind': 'lookup', 'tool': 'get_employee_devices', 'arguments': {'employee_id': 'EMP-001'}}]
    result = run(inv_request, inv_dependencies, provider, decisions, **overrides)
    assert result.recommendation is None and result.status == 'partial'
    assert result.synthesis_status == ('failed' if mode == 'during' else 'skipped')
    assert provider.generate.call_count == (1 if mode == 'during' else 0)


def test_payload_cap_does_not_call_provider(provider):
    with pytest.raises(SynthesisError, match='context_limit'):
        generate_synthesis('x' * (MAX_PAYLOAD_CHARACTERS + 1), kb_ids=set(), lookup_ids=set(), provider=provider)
    provider.generate.assert_not_called()


def test_mutated_provider_model_is_revalidated(inv_request, inv_dependencies, provider):
    provider.generate.return_value.summary.references = []
    result = run(inv_request, inv_dependencies, provider)
    assert result.recommendation is None and result.errors[-1].code == 'synthesis_invalid_output'


def test_output_envelope_revalidates_references(inv_request, inv_dependencies, provider):
    result = run(inv_request, inv_dependencies, provider)
    data = result.model_dump()
    data['recommendation']['steps'][0]['references'][0]['chunk_id'] = 'fabricated'
    with pytest.raises(ValidationError): InvestigationResult.model_validate(data)


def test_valid_ids_do_not_prove_groundedness(inv_request, inv_dependencies, provider):
    provider.generate.return_value.steps[0].action = 'Disable all endpoint protection and promise the repair succeeded.'
    result = run(inv_request, inv_dependencies, provider)
    assert result.synthesis_status == 'completed'  # Deliberate semantic negative control.
    # This requires manual groundedness review; never claim ID validation proves correctness.
