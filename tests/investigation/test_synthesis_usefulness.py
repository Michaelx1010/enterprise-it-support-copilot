"""Authored semantic contrasts and prompt wiring; no automatic semantic judge."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.investigation.graph import run_investigation
from app.investigation.schemas import InvestigationRequest
from app.investigation.scripted import ReplayStore, ScriptedEmbedder, ScriptedPlanner
from app.investigation.synthesis import INSTRUCTIONS, PROMPT_VERSION
from app.investigation.synthesis_draft import InvestigationSynthesisDraftV3
from app.kb.documents import load_chunks
from app.kb.schemas import SearchResult
from app.operations.schemas import ActiveIncidentsResult
from app.providers.openai_synthesis import OpenAISynthesis, DEFAULT_MODEL, MAX_OUTPUT_TOKENS
from app.rag.recommendation import build_query
from evaluation.investigation_e2e import REVIEW_CRITERIA, REVIEW_WORKSHEET_VERSION, review_items
from evaluation.investigation_synthesis import ReplayProvider, evaluate, load_cases, summarize
from evaluation.live_investigation import project_report, source_metadata

CASES = load_cases(Path('evaluation/investigation_synthesis_usefulness.jsonl'))


@pytest.mark.parametrize('case', CASES, ids=lambda c: c.id)
def test_real_sdk_and_replay_preserve_authored_semantics_without_repair(case, planner_client, planner_response):
    calls = []
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body['input'][0]['content'] == INSTRUCTIONS
        assert body['text']['format']['name'] == 'InvestigationSynthesisDraftV3'
        assert body['model'] == DEFAULT_MODEL and body['max_output_tokens'] == MAX_OUTPUT_TOKENS == 3000
        assert body['temperature'] == 0 and body['store'] is False and 'tools' not in body
        payload = json.loads(body['input'][1]['content'])
        assert payload['untrusted_evidence']['ticket'] == case.ticket
        assert payload['untrusted_evidence']['kb_procedures'] == case.kb
        assert payload['untrusted_evidence']['operational_observations'] == case.observations
        assert case.review_notes not in json.dumps(payload)
        assert not {'manual_verdict', 'expected_status', 'expected_escalation'} & payload.keys()
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(case.candidate)))
    before = deepcopy(case.candidate)
    actual = evaluate(case, OpenAISynthesis(planner_client(handler)))
    replay = evaluate(case, ReplayProvider(case.candidate, draft_v3=True))
    assert actual == replay and actual['outcome'] == case.expected_replay == 'accepted'
    assert len(calls) == 1 and case.candidate == before
    canonical = InvestigationSynthesisDraftV3.model_validate(before).to_canonical()
    assert actual['report'] == canonical.model_dump(mode='json')
    assert actual['report']['summary']['text'] == before['summary']['text']  # No prose repair/truncation.
    assert canonical.escalation_required == any(s['step_type'] == 'escalation' for s in before['steps'])
    assert len(project_report(actual['report'])['steps']) == len(before['steps'])
    # Incorrect candidates deliberately pass structural checks. This assertion
    # tests the boundary, not recommendation quality or prompt effectiveness.
    assert case.manual_verdict in ('acceptable', 'incorrect')


def test_control_labels_and_counts_are_not_measured_model_quality():
    assert len(CASES) == 26
    assert sum(c.manual_verdict == 'acceptable' for c in CASES) == 13
    assert sum(c.manual_verdict == 'incorrect' for c in CASES) == 13
    rows = [evaluate(c, ReplayProvider(c.candidate, draft_v3=True)) for c in CASES]
    metrics = summarize(CASES, rows)
    assert metrics['accepted'] == 26 and metrics['rejected_or_failed'] == 0
    assert metrics['accepted_citation_validity']['valid'] == metrics['accepted_citation_validity']['total']
    assert metrics['incorrect_abstentions']['count'] == 0
    assert metrics['escalation_label_matches']['count'] == 25  # Deliberately premature first-failure handoff.
    assert next(c for c in CASES if c.id == 'first-reconnect-negative').expected_escalation is False
    assert all(c.manual_verdict == 'incorrect' for c in CASES if c.id.endswith('-negative'))


def test_sources_are_existing_kb_text_and_counterfactual_live_state_is_explicit(inv_results):
    chunks = {c.chunk_id: c.content for c in load_chunks(Path('knowledge_base'))}
    for case in CASES:
        assert all(chunks[key] == text for key, text in case.kb.items())
    current = next(c for c in CASES if c.id == 'incident-confirmation-positive')
    assert current.candidate['findings'][0]['references'] == [{'kind': 'ticket'}]
    # No live-verification capability is smuggled into a synthetic observation.
    invalid = deepcopy(inv_results['get_active_service_incidents'])
    invalid['live_verified'] = True
    with pytest.raises(ValidationError):
        ActiveIncidentsResult.model_validate(invalid)


@pytest.mark.parametrize('mutation,expected', [
    ('unknown_kb', 'invalid_citation'), ('unknown_observation', 'invalid_citation'),
    ('no_step_kb', 'invalid_output'), ('reason_without_current', 'invalid_output'),
    ('missing_current_basis', 'invalid_output'), ('summary_over_limit', 'invalid_output'),
])
def test_semantic_prompt_changes_leave_rejections_and_no_retry_intact(
        mutation, expected, planner_client, planner_response):
    case_id = 'completed-reconnect-positive' if mutation == 'missing_current_basis' else 'version-inventory-positive'
    case = next(c for c in CASES if c.id == case_id).model_copy(deep=True)
    candidate = case.candidate
    if mutation == 'unknown_kb': candidate['steps'][0]['references'][0]['chunk_id'] = 'PRIVATE'
    elif mutation == 'unknown_observation': candidate['findings'][0]['references'][0]['lookup_id'] = 'PRIVATE'
    elif mutation == 'no_step_kb': candidate['steps'][0]['references'] = [{'kind': 'ticket'}]
    elif mutation == 'reason_without_current': candidate['escalation_reason'] = deepcopy(candidate['summary'])
    elif mutation == 'missing_current_basis': candidate['trigger_basis'] = None
    else: candidate['summary']['text'] = 'X' * 601
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(candidate)))
    result = evaluate(case, OpenAISynthesis(planner_client(handler, max_retries=5)))
    assert result['outcome'] == expected and result['report'] is None and len(calls) == 1
    assert 'PRIVATE' not in json.dumps(result)


@pytest.mark.parametrize('case_id', ['completed-reconnect-positive', 'first-reconnect-positive', 'password-unconfirmed-positive'])
@pytest.mark.parametrize('failure', [False, True])
def test_full_graph_uses_v6_once_and_preserves_context_on_failure(
        case_id, failure, inv_dependencies, planner_client, planner_response):
    case = next(c for c in CASES if c.id == case_id)
    chunks = {c.chunk_id: c for c in load_chunks(Path('knowledge_base'))}
    rows = [SearchResult(chunk=chunks[key], distance=i / 10) for i, key in enumerate(case.kb)]
    request = InvestigationRequest(ticket={'subject': 'Fictional support investigation', 'description': case.ticket}, employee_id='EMP-001')
    spec = inv_dependencies.embedder.spec
    candidate = deepcopy(case.candidate)
    candidate['uncertainties'].append({'text': 'Operational evidence consists of recorded snapshots, not verified live state.',
                                        'references': [{'kind': 'investigation_context'}]})
    calls = []
    def handler(api_request):
        body = json.loads(api_request.content)
        calls.append(body)
        payload = json.loads(body['input'][1]['content'])
        assert payload['prompt_version'] == PROMPT_VERSION == 'investigation-synthesis-v6'
        assert payload['untrusted_evidence']['ticket'] == request.ticket.model_dump()
        assert len(payload['untrusted_evidence']['operational_observations']) == 1
        assert payload['investigation_context']['live_verified'] is False
        if failure: return httpx.Response(500, json={'error': {'message': 'PRIVATE', 'type': 'api_error'}})
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(candidate)))
    deps = replace(inv_dependencies, planner=ScriptedPlanner([
        {'kind': 'lookup', 'tool': 'get_employee_account_status', 'arguments': {'employee_id': 'EMP-001'}},
        {'kind': 'finish'}]), store=ReplayStore(spec, rows),
        embedder=ScriptedEmbedder(build_query(request.ticket), spec, [1., 0., 0.]),
        synthesis=OpenAISynthesis(planner_client(handler)))
    result = run_investigation(request, dependencies=deps)
    assert result.status == ('partial' if failure else 'completed') and result.stop_reason == 'finish'
    assert result.synthesis_attempts == len(calls) == 1 and result.planner_decisions == 2
    assert result.lookup_attempts == 1 and len(result.operational_evidence) == 1
    assert result.lookup_trace[0].executed and result.classification
    assert [e.result for e in result.kb_evidence] == rows
    assert result.human_review_required and not result.mutating_actions_executed
    if failure:
        assert result.recommendation is None and result.errors[-1].code == 'synthesis_provider_failure'
        assert 'PRIVATE' not in result.model_dump_json()
    else:
        assert result.recommendation.status == case.expected_status
        assert result.recommendation.escalation_required == case.expected_escalation


@pytest.mark.parametrize('agent', [False, True])
def test_manual_worksheet_additions_are_pending_and_do_not_mutate_reports(agent):
    case = next(c for c in CASES if c.id == 'first-reconnect-positive')
    raw = InvestigationSynthesisDraftV3.model_validate(case.candidate).to_canonical().model_dump(mode='json')
    report = raw if agent else project_report(raw)
    before = deepcopy(report)
    rows = review_items(report, agent=agent)
    assert report == before and REVIEW_WORKSHEET_VERSION == 'investigation-manual-review-v2'
    assert set(REVIEW_CRITERIA) == {'entailment', 'attribution', 'snapshot_freshness', 'applicability',
                                  'completed_vs_proposed', 'trigger_established', 'practical_usefulness', 'summary_completeness'}
    assert all(all(row[key] is None for key in REVIEW_CRITERIA) for row in rows)
    assert any(row['location'] == 'summary.0' for row in rows)
    assert any(row['location'].startswith('conditional_guidance.') for row in rows) == agent
    assert all(row['atomic_claims'] == [] for row in rows)
    assert review_items(None, agent=agent) == []


def test_live_metadata_versions_only_current_prompt_and_keeps_schema_identity():
    metadata = source_metadata()
    assert 'investigation-synthesis-v6' in json.dumps(metadata)
    assert 'investigation-planner-v4' in json.dumps(metadata)
    assert InvestigationSynthesisDraftV3.model_fields['schema_version'].annotation.__args__ == ('investigation-synthesis-draft-v3',)
