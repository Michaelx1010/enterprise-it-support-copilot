"""V4 derivation mechanics, not evidence of live semantic improvement."""

from copy import deepcopy
from dataclasses import replace
import json

import httpx
import pytest
from pydantic import ValidationError

from app.investigation.schemas import InvestigationSynthesis
from app.investigation.synthesis_draft import (
    InvestigationSynthesisDraftV1, InvestigationSynthesisDraftV2,
    InvestigationSynthesisDraftV3, InvestigationSynthesisDraftV4,
)
from app.providers.openai_synthesis import OpenAISynthesis
from app.providers.synthesis import SynthesisError
from evaluation.investigation_e2e import RagReplay, review_items
from evaluation.investigation_synthesis import SynthesisCase, evaluate, summarize
from evaluation.live_investigation import project_report, run_pair, select_cases
from evaluation.live_telemetry import MeteredTransport
from evaluation.recommendation import aggregate


@pytest.mark.parametrize('count', [0, 1, 2])
@pytest.mark.parametrize('future', [False, True])
def test_status_derives_only_from_current_steps_without_rewriting(synthesis_report, as_synthesis_draft, count, future):
    candidate = as_synthesis_draft(synthesis_report)
    candidate['steps'] *= count
    candidate['summary']['text'] = 'Authored uncertainty; these words do not determine status.'
    if future:
        candidate['conditional_guidance'] = [{
            'condition': 'If a gateway error persists after retrying.',
            'action': 'Provide the persistent error to Network Support.',
            'references': deepcopy(synthesis_report['steps'][0]['references']),
            'missing_evidence': 'Whether a gateway error persists after a retry.',
        }]
    before = deepcopy(candidate)
    report = InvestigationSynthesisDraftV4.model_validate(candidate).to_canonical()
    assert report.status == ('supported' if count else 'insufficient_evidence')
    assert report.escalation_required is False and report.trigger_basis is None
    assert report.model_dump(exclude={'status', 'escalation_required'}) == {
        k: v for k, v in before.items() if k != 'schema_version'}
    assert candidate == before
    assert not {'status', 'escalation_required'} & InvestigationSynthesisDraftV4.model_fields.keys()


@pytest.mark.parametrize('version,model', [
    (1, InvestigationSynthesisDraftV1), (2, InvestigationSynthesisDraftV2), (3, InvestigationSynthesisDraftV3),
])
@pytest.mark.parametrize('contradiction', ['supported_empty', 'insufficient_nonempty'])
def test_legacy_status_contradictions_still_reject(synthesis_report, as_synthesis_draft, version, model, contradiction):
    candidate = as_synthesis_draft(synthesis_report, version=version)
    if contradiction == 'supported_empty': candidate['steps'] = []
    else: candidate['status'] = 'insufficient_evidence'
    with pytest.raises(ValidationError) as caught:
        model.model_validate(candidate)
    assert caught.value.errors(include_input=False)[0]['type'] == 'status_steps_mismatch'


@pytest.mark.parametrize('version,model', [
    (1, InvestigationSynthesisDraftV1), (2, InvestigationSynthesisDraftV2), (3, InvestigationSynthesisDraftV3),
])
def test_historical_drafts_load_but_live_provider_never_falls_back(
        synthesis_report, as_synthesis_draft, planner_client, planner_response, version, model):
    candidate = as_synthesis_draft(synthesis_report, version=version)
    assert model.model_validate(candidate).to_canonical() == InvestigationSynthesis.model_validate(synthesis_report)
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(candidate)))
    with pytest.raises(SynthesisError, match='invalid_output'):
        OpenAISynthesis(planner_client(handler)).generate(instructions='', payload='')
    assert len(calls) == 1


@pytest.mark.parametrize('future', [False, True])
def test_answerable_zero_step_sdk_output_is_an_incorrect_abstention(
        synthesis_report, as_synthesis_draft, planner_client, planner_response, inv_request, inv_dependencies, future):
    candidate = as_synthesis_draft(synthesis_report)
    candidate['steps'] = []
    if future:
        candidate['conditional_guidance'] = [{
            'condition': 'If errors persist after a reconnect.', 'action': 'Contact Network Support if errors persist.',
            'references': deepcopy(synthesis_report['steps'][0]['references']),
            'missing_evidence': 'Whether an error persists after reconnecting.',
        }]
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(candidate)))
    provider = OpenAISynthesis(planner_client(handler))
    case = SynthesisCase(id='authored-answerable-abstention', ticket='VPN failed once; I have not retried.',
        kb={synthesis_report['steps'][0]['references'][0]['chunk_id']: 'Select Corporate and reconnect once.'}, observations={}, candidate=None,
        expected_status='supported', expected_escalation=False, expected_replay='accepted',
        manual_verdict='incorrect', review_notes='Answerable request incorrectly receives zero current actions.')
    original = case.model_dump_json()
    result = evaluate(case, provider)
    assert result['outcome'] == 'accepted' and result['report']['status'] == 'insufficient_evidence'
    metrics = summarize([case], [result])
    assert metrics['incorrect_abstentions'] == {'count': 1, 'accepted_answerable_cases': 1}
    assert metrics['unsupported_abstentions'] == {'count': 0, 'accepted_cases': 0}
    assert case.model_dump_json() == original
    assert calls[0]['text']['format']['name'] == 'InvestigationSynthesisDraftV4'
    assert len(calls) == 1

    # The production paired projection retains the frozen expected label too.
    paired_case = select_cases(['vpn-future-condition'])[0].model_copy(update={'request': inv_request})
    meter = MeteredTransport(httpx.MockTransport(lambda _: pytest.fail('No real network')))
    row = run_pair(paired_case, dependencies=replace(inv_dependencies, synthesis=provider),
        standalone=RagReplay(project_report(synthesis_report)), meter=meter)
    assert row['agent']['answerable'] and row['agent']['recommendation']['status'] == 'insufficient_evidence'
    assert aggregate([row['agent']])['incorrect_abstentions'] == {'count': 1, 'answerable_cases': 1, 'rate': 1.0}
    assert row['agent']['citation_metrics']['citation_coverage'] is None
    assert all(item['entailment'] is None for item in review_items(result['report'], agent=True))
    assert len(calls) == 2  # One independent authored call per evaluated path; no retry.
