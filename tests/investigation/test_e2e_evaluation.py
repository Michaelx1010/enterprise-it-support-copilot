"""The replay/scoring harness is tested, not the quality of a live model."""

import json

import pytest

from app.operations.seed import load_seed
from evaluation.investigation_e2e import load_cases, run_case, summarize

CASES = load_cases()


@pytest.fixture(scope='module')
def rows():
    return [run_case(case) for case in CASES]


@pytest.mark.parametrize('case', CASES, ids=lambda case: case.id)
def test_paired_pipeline_replay(case, rows):
    result = next(r for r in rows if r['id'] == case.id)
    assert result['agent']['outcome'] == result['standalone']['outcome'] == 'accepted'
    agent = result['agent_result']
    assert agent['status'] == 'completed' and not agent['errors']
    assert agent['human_review_required'] and not agent['mutating_actions_executed']
    assert agent['planner_decisions'] <= 4 and agent['lookup_attempts'] <= 4 and agent['synthesis_attempts'] <= 1
    assert [e['result'] for e in agent['kb_evidence']] == result['controlled_kb']
    assert result['manual_review']['status'] == 'pending'
    for claim in result['manual_review']['agent_claims']:
        assert claim['entailment'] is None and claim['trigger_established'] is None


def test_negative_controls_and_denominators(rows):
    metrics = summarize(rows)
    assert metrics['planner'] == {'covered': 16, 'expected': 17, 'redundant': 1, 'unnecessary': 1}
    assert metrics['agent']['escalation']['precision'] == .8
    assert metrics['agent']['escalation']['recall'] == 1
    assert metrics['agent']['premature_escalation_ids'] == ['vpn-future-condition']
    assert metrics['standalone']['premature_escalation_ids'] == []
    assert metrics['agent']['unsupported_abstention']['abstained'] == 4
    assert metrics['agent_workflow_status'] == {'completed': 12}
    assert metrics['unreviewed_cases'] == 12  # Valid references are not manual grades.
    stale = next(r for r in rows if r['id'] == 'stale-vpn-snapshot')
    assert stale['agent']['outcome'] == 'accepted'
    assert stale['agent_result']['recommendation']['findings']  # Authored false live-state claim survives IDs.
    assert stale['manual_review']['agent_claims'][1]['entailment'] is None


@pytest.mark.parametrize('arm', ['agent', 'rag'])
@pytest.mark.parametrize('failure', ['provider', 'citation', 'schema'])
def test_failures_are_not_successful_abstentions_or_hidden_in_recall(arm, failure):
    case = CASES[0].model_copy(deep=True)
    name = arm + '_response'
    candidate = getattr(case, name)
    if failure == 'provider': setattr(case, name, None)
    elif failure == 'schema': candidate['steps'] = []
    elif arm == 'agent': candidate['steps'][0]['references'][0]['chunk_id'] = 'invented'
    else: candidate['steps'][0]['supporting_chunk_ids'] = ['invented']
    row = run_case(case)
    key = 'agent' if arm == 'agent' else 'standalone'
    assert row[key]['outcome'] == ('failed' if failure == 'provider' else 'rejected')
    assert row[key]['recommendation'] is None
    score = summarize([row])[key]
    assert score['accepted'] == 0 and score['unsupported_abstention']['abstained'] == 0
    assert score['escalation']['recall'] is None
    assert score['escalation']['recall_over_all_positive_attempts'] == 0
    if arm == 'agent':
        assert row['agent_result']['status'] == 'partial'
        assert len(row['agent_result']['operational_evidence']) == 3


def test_fixture_rows_are_projections_of_existing_seed_not_invented_operational_state():
    seed = load_seed()
    candidates = [record.model_dump(mode='json') for records in seed.values() for record in records]
    for case in CASES:
        for lookup in case.lookups:
            assert lookup.result['queried_at'] == '2026-10-23T08:00:00Z'
            assert lookup.result['live_verified'] is False
            for key in ('employee', 'account', 'device', 'owner', 'service', 'devices', 'incidents'):
                value = lookup.result.get(key)
                for fact in value if isinstance(value, list) else [value]:
                    if fact is not None:
                        assert any(all(record.get(k) == v for k, v in fact.items()) for record in candidates)


def test_missing_record_and_retrieval_miss_have_different_meanings(rows):
    for row in rows:
        if row['id'] in ('clarify-unknown-system', 'disabled-but-ambiguous'):
            assert not row['kb_answerable'] and not row['answerable_with_controlled_evidence']
    missing = next(r for r in rows if r['id'] == 'missing-account-record')
    observation = missing['agent_result']['operational_evidence'][0]['observation']['result']
    assert observation['employee'] is not None and observation['account'] is None
    assert missing['agent']['recommendation']['status'] == 'supported'
    empty = next(r for r in rows if r['id'] == 'empty-retrieval')
    assert empty['kb_answerable'] and not empty['answerable_with_controlled_evidence']
    assert empty['agent_result']['synthesis_attempts'] == 0
    assert empty['agent']['recommendation']['status'] == 'insufficient_evidence'
    assert empty['standalone']['recommendation']['status'] == 'insufficient_evidence'


def test_replay_does_not_mutate_cases_or_seed_and_scores_are_reproducible(rows):
    before = [case.model_dump_json() for case in CASES]
    seed = json.dumps({k: [r.model_dump(mode='json') for r in v] for k, v in load_seed().items()}, sort_keys=True)
    again = [run_case(case) for case in CASES]
    assert summarize(again) == summarize(rows)
    assert before == [case.model_dump_json() for case in CASES]
    assert seed == json.dumps({k: [r.model_dump(mode='json') for r in v] for k, v in load_seed().items()}, sort_keys=True)


def test_guard_failure_keeps_partial_workflow_distinct_from_valid_report():
    case = CASES[0].model_copy(deep=True)
    case.decisions[0]['arguments']['employee_id'] = 'EMP-002'
    row = run_case(case)
    assert row['agent_result']['status'] == 'partial' and row['agent_result']['lookup_attempts'] == 0
    assert row['planner']['coverage']['covered'] == 0
    assert summarize([row])['agent_workflow_status'] == {'partial': 1}


def test_manifest_accepts_checkout_line_endings_but_rejects_content_changes(tmp_path, monkeypatch):
    from evaluation import investigation_e2e as evaluation

    source = evaluation.DATASET.read_text(encoding='utf-8')
    path = tmp_path / 'cases.jsonl'
    path.write_bytes(source.replace('\n', '\r\n').encode())
    monkeypatch.setattr(evaluation, 'DATASET', path)
    assert len(evaluation.load_cases()) == 12
    path.write_text(source + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='inputs changed'):
        evaluation.load_cases()
