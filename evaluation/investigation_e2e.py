"""Controlled full-pipeline replay and paired scoring. No live-model entry point."""

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from app.investigation.graph import run_investigation
from app.investigation.schemas import InvestigationRequest, LookupDecision
from app.investigation.scripted import InvestigationScript, ScriptedLookup, script_dependencies
from app.kb.documents import load_chunks
from app.kb.schemas import SearchResult
from app.operations.records import Model
from app.providers.recommendation import RecommendationError
from app.rag.recommendation import recommend
from app.rag.schemas import SupportRecommendation
from app.schemas import TicketClassification
from evaluation.investigation_synthesis import ReplayProvider
from evaluation.planner_efficiency import decision_key, evidence_coverage
from evaluation.recommendation import aggregate, citation_metrics

DATASET = Path('evaluation/investigation_e2e.jsonl')
MANIFEST = Path('evaluation/investigation_e2e_manifest.json')


class RedundantPair(Model):
    previous: LookupDecision
    following: LookupDecision


class Case(Model):
    id: str
    request: InvestigationRequest
    classification: TicketClassification
    kb_chunk_ids: list[str] = Field(max_length=3)
    decisions: list[dict] = Field(min_length=1, max_length=4)
    lookups: list[ScriptedLookup]
    required_evidence: list[LookupDecision]
    redundant_after: list[RedundantPair]
    unnecessary: list[LookupDecision]
    answerable: bool  # Given the controlled KB evidence; both arms share this label.
    kb_answerable: bool  # Whole-corpus label, distinguishes deliberate retrieval misses.
    expected_escalation: bool
    trigger_status: Literal['confirmed', 'unconfirmed', 'not_applicable']
    review_notes: str
    agent_response: dict | None
    rag_response: dict | None

    @model_validator(mode='after')
    def valid_labels(self):
        if self.expected_escalation and (not self.answerable or self.trigger_status != 'confirmed'):
            raise ValueError('Positive escalation requires an answerable, established trigger.')
        if self.answerable and not self.kb_answerable:
            raise ValueError('Controlled evidence cannot exceed corpus answerability.')
        for decision in self.required_evidence + self.unnecessary:
            decision_key(decision.model_dump())
        if len({decision_key(d.model_dump()) for d in self.required_evidence}) != len(self.required_evidence):
            raise ValueError('Required evidence must be unique.')
        return self


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def text_digest(path: Path) -> str:
    # Git checkout line endings must not invalidate an otherwise identical corpus.
    return digest(path.read_text(encoding='utf-8').encode())


def fingerprints() -> dict:
    chunks = load_chunks(Path('knowledge_base'))
    return {'kb_sha256': digest(json.dumps([c.model_dump() for c in chunks], sort_keys=True).encode()),
            'ops_seed_sha256': text_digest(Path('app/operations/seed_data.json'))}


def load_cases() -> list[Case]:
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if manifest['inputs'] != fingerprints() or manifest['dataset_sha256'] != text_digest(DATASET):
        raise ValueError('Evaluation inputs changed; review labels and deliberately update the manifest.')
    cases = [Case.model_validate_json(line) for line in DATASET.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not cases or len({c.id for c in cases}) != len(cases):
        raise ValueError('Cases require distinct IDs.')
    return cases


class RagReplay:
    def __init__(self, candidate: dict | None):
        self.candidate = candidate

    def generate(self, *, instructions: str, payload: str) -> SupportRecommendation:
        if self.candidate is None:
            raise RecommendationError('Fixture provider failure.', code='provider_failure')
        return SupportRecommendation.model_validate(self.candidate)


def planner_metrics(case: Case, result) -> dict:
    coverage = evidence_coverage(case, result) if case.required_evidence else {'covered': 0, 'expected': 0, 'ratio': None}
    seen, redundant, unnecessary = set(), [], []
    for lookup in result.lookup_trace:
        if not lookup.executed or lookup.evidence is None:
            continue
        key = decision_key({'kind': 'lookup', 'tool': lookup.tool, 'arguments': lookup.arguments})
        if any(key == decision_key(p.following.model_dump()) and decision_key(p.previous.model_dump()) in seen
               for p in case.redundant_after):
            redundant.append(lookup.lookup_id)
        if any(key == decision_key(d.model_dump()) for d in case.unnecessary):
            unnecessary.append(lookup.lookup_id)
        seen.add(key)
    return {'coverage': coverage, 'redundant_lookup_ids': redundant, 'unnecessary_lookup_ids': unnecessary,
            'duplicate_proposals': sum(t.status == 'duplicate' for t in result.lookup_trace),
            'decisions': result.planner_decisions, 'attempts': result.lookup_attempts,
            'blocked_or_failed': sum(t.status in ('blocked', 'error', 'rejected') for t in result.lookup_trace)}


def review_items(report: dict | None, *, agent: bool) -> list[dict]:
    if report is None:
        return []
    # Reviewer splits compound sentences into atomic claims; no NLP truth heuristic.
    names = ('summary', 'findings', 'uncertainties', 'steps', 'escalation_reason', 'conditional_guidance') if agent else ('summary', 'steps', 'escalation_reason')
    items = []
    for name in names:
        values = report.get(name)
        for index, value in enumerate(values if isinstance(values, list) else [values]):
            if value is not None:
                items.append({'location': f'{name}.{index}', 'value': value,
                              'atomic_claims': [], 'entailment': None, 'snapshot_freshness': None,
                              'applicability': None, 'trigger_established': None, 'notes': None})
    return items


def scoring_row(case: Case, report: dict | None, evidence: list[SearchResult], error: dict | None) -> dict:
    return {'id': case.id, 'group': 'supported' if case.answerable else 'unsupported',
            'answerable': case.answerable, 'expected_escalation': case.expected_escalation,
            'outcome': 'accepted' if report else ('rejected' if error and error['code'] in ('invalid_output', 'invalid_citation') else 'failed'),
            'recommendation': report, 'error': error,
            'citation_metrics': citation_metrics(SupportRecommendation.model_validate(report), evidence) if report else None}


def run_case(case: Case) -> dict:
    chunks = {c.chunk_id: c for c in load_chunks(Path('knowledge_base'))}
    evidence = [SearchResult(chunk=chunks[key], distance=0.0) for key in case.kb_chunk_ids]
    script = InvestigationScript(request=case.request, classification=case.classification,
        embedding_spec={'provider': 'fixture', 'model': 'controlled-e2e', 'dimensions': 3},
        query_vector=[1., 0., 0.], decisions=case.decisions, kb_results=evidence, lookup_results=case.lookups)
    from dataclasses import replace

    deps = replace(script_dependencies(script), synthesis=ReplayProvider(case.agent_response))
    result = run_investigation(case.request, dependencies=deps)
    raw = result.recommendation.model_dump(mode='json') if result.recommendation else None
    projection = None if raw is None else {
        'status': raw['status'], 'summary': raw['summary']['text'],
        'steps': [{'step_type': step['step_type'], 'action': step['action'],
                   'supporting_chunk_ids': [r['chunk_id'] for r in step['references'] if r['kind'] == 'kb_chunk']}
                  for step in raw['steps']], 'missing_information': raw['missing_information'],
        'escalation_required': raw['escalation_required'],
        'escalation_reason': raw['escalation_reason']['text'] if raw['escalation_reason'] else None}
    agent_error = None if raw else {'stage': 'generation', 'code': result.errors[-1].code.removeprefix('synthesis_') if result.errors else 'missing_output'}
    rag, rag_error = None, None
    try:
        rag = recommend(case.request.ticket, embedder=deps.embedder, store=deps.store,
                        provider=RagReplay(case.rag_response)).recommendation.model_dump()
    except RecommendationError as exc:
        rag_error = {'stage': 'generation', 'code': exc.code}
    return {'id': case.id, 'request': case.request.model_dump(mode='json'),
            'controlled_kb': [e.model_dump() for e in evidence],
            'kb_answerable': case.kb_answerable, 'answerable_with_controlled_evidence': case.answerable,
            'trigger_status': case.trigger_status, 'review_notes': case.review_notes,
            'agent_result': result.model_dump(mode='json'),
            'agent': scoring_row(case, projection, evidence, agent_error),
            'standalone': scoring_row(case, rag, evidence, rag_error),
            'planner': planner_metrics(case, result),
            'manual_review': {'status': 'pending', 'agent_claims': review_items(raw, agent=True),
                              'standalone_claims': review_items(rag, agent=False),
                              'missing_information_sufficient': None, 'hidden_conditional_handoff': None,
                              'paired_usefulness': None, 'reviewer': None}}


def summarize(rows: list[dict]) -> dict:
    output = {arm: aggregate([r[arm] for r in rows]) for arm in ('agent', 'standalone')}
    for arm in output:
        output[arm]['premature_escalation_ids'] = [r['id'] for r in rows if r['trigger_status'] == 'unconfirmed'
            and r[arm]['outcome'] == 'accepted' and r[arm]['recommendation']['escalation_required']]
    output['planner'] = {
        'covered': sum(r['planner']['coverage']['covered'] for r in rows),
        'expected': sum(r['planner']['coverage']['expected'] for r in rows),
        'redundant': sum(len(r['planner']['redundant_lookup_ids']) for r in rows),
        'unnecessary': sum(len(r['planner']['unnecessary_lookup_ids']) for r in rows)}
    output['unreviewed_cases'] = sum(r['manual_review']['status'] == 'pending' for r in rows)
    output['agent_workflow_status'] = dict(Counter(r['agent_result']['status'] for r in rows))
    output['agent_stop_reasons'] = dict(Counter(r['agent_result']['stop_reason'] for r in rows))
    return output


def run() -> dict:
    from app.investigation.planner import PROMPT_VERSION as planner_version
    from app.investigation.synthesis import PROMPT_VERSION as synthesis_version
    from app.rag.prompts import PROMPT_VERSION as rag_version

    cases = load_cases()
    rows = [run_case(case) for case in cases]
    load_cases()  # Reject changed inputs during the run as well as before it.
    return {'mode': 'deterministic_fixture_replay', 'live_model_quality_measured': False,
            'prompt_versions': {'planner': planner_version, 'synthesis': synthesis_version, 'standalone': rag_version},
            'models_called': [],
            'manifest': json.loads(MANIFEST.read_text(encoding='utf-8')),
            'application_sha256': digest(b''.join(p.as_posix().encode() + p.read_text(encoding='utf-8').encode() for p in sorted(Path('app').rglob('*.py')))),
            'evaluator_sha256': text_digest(Path(__file__)),
            'metrics': summarize(rows), 'cases': rows}


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
