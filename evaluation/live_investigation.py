"""Opt-in Phase 5B paired evaluation, using unchanged production entry points."""

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time

import httpx
from openai import OpenAI
from psycopg import sql

from app.investigation.graph import Dependencies, run_investigation
from app.investigation.kb_access import ReadOnlyKBStore
from app.investigation.policy import TOOLS, validate_lookup
from app.investigation.schemas import DECISION_ADAPTER, Limits
from app.kb.documents import load_chunks
from app.kb.schemas import Chunk
from app.operations.db import OperationalDB
from app.operations.records import TABLE_MODELS
from app.operations.seed import load_seed
from app.providers.embeddings import EmbeddingSpec
from app.providers.openai import DEFAULT_MODEL, OpenAIProvider
from app.providers.openai_embeddings import OpenAIEmbeddings
from app.providers.openai_planner import OpenAIPlanner
from app.providers.openai_recommendation import OpenAIRecommendation
from app.providers.openai_synthesis import OpenAISynthesis
from app.providers.recommendation import RecommendationError
from app.rag.recommendation import build_query, generate_recommendation
from evaluation.investigation_e2e import (
    MANIFEST, Case, digest, load_cases, planner_metrics, review_items, scoring_row,
    summarize, text_digest,
)
from evaluation.live_telemetry import API_BASE_URL, MeteredTransport, openai_transport, usage_totals
from evaluation.synthesis_diagnostics import ObservedSynthesis

PILOT_IDS = ('vpn-confirmed', 'vpn-future-condition', 'irrelevant-incident', 'unsupported-procedure')
MODEL_ENV = {'classification': 'OPENAI_MODEL', 'embedding': 'OPENAI_EMBEDDING_MODEL',
             'planner': 'OPENAI_PLANNER_MODEL', 'synthesis': 'OPENAI_SYNTHESIS_MODEL',
             'standalone': 'OPENAI_RECOMMENDATION_MODEL'}


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def select_cases(ids: list[str] | None = None) -> list[Case]:
    ids = list(PILOT_IDS) if ids is None else ids
    if not ids or len(set(ids)) != len(ids) or any(key not in PILOT_IDS for key in ids):
        raise ValueError('Choose distinct Phase 5B pilot scenarios.')
    cases = {c.id: c for c in load_cases()}
    selected = [cases[key] for key in ids]
    for case in selected:
        build_query(case.request.ticket)
        # These four labels apply to the whole KB; never relabel frozen fixtures.
        if case.answerable != case.kb_answerable:
            raise ValueError('Pilot requires corpus-level answerability labels.')
    return selected


def model_settings() -> dict[str, str]:
    models = {key: os.getenv(env, 'text-embedding-3-small' if key == 'embedding' else DEFAULT_MODEL).strip()
              for key, env in MODEL_ENV.items()}
    if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,159}', value) for value in models.values()):
        raise ValueError('Invalid model configuration.')
    return models


def database_audit(store: ReadOnlyKBStore, db: OperationalDB) -> dict:
    """Read-only fingerprints include every operational column and KB vector.

    Check the frozen corpus/seed too: unchanged but unrelated data cannot silently
    inherit Phase 5A labels. No administrative URL or provisioning is used.
    """
    output = {}
    seed = load_seed()
    with db.connection() as conn:
        for name, model in TABLE_MODELS.items():
            rows = conn.execute(sql.SQL('SELECT row_to_json(t) AS value FROM ops.{} t')
                                .format(sql.Identifier(name))).fetchall()
            values = sorted((canonical(model.model_validate(r['value']).model_dump(mode='json')) for r in rows))
            expected = sorted(canonical(r.model_dump(mode='json')) for r in seed[name])
            output['ops.' + name] = {'rows': len(rows), 'sha256': digest(canonical(values).encode()),
                                     'matches_frozen_inputs': values == expected}
    with store._connection() as conn, conn.transaction():
        rows = conn.execute('SELECT row_to_json(t) AS value FROM public.kb_chunks t ORDER BY chunk_id').fetchall()
    values = [r['value'] for r in rows]
    chunks = sorted(canonical(Chunk.model_validate({k: r[k] for k in Chunk.model_fields}).model_dump()) for r in values)
    expected = sorted(canonical(c.model_dump()) for c in load_chunks(Path('knowledge_base')))
    output['public.kb_chunks'] = {'rows': len(rows), 'sha256': digest(canonical(values).encode()),
                                 'matches_frozen_inputs': chunks == expected}
    return output


def preflight(cases: list[Case], models: dict, *, store=None, db=None) -> dict:
    report = {'mode': 'preflight', 'api_calls': 0, 'paid_opt_in_required': True,
              'scenario_ids': [c.id for c in cases], 'models': models,
              'limits': Limits().model_dump(), 'max_api_requests': 8 * len(cases),
              'request_timeout_seconds': 30, 'sdk_retries': 0,
              'database_checked': False, 'database_snapshot': None,
              'manifest': json.loads(MANIFEST.read_text(encoding='utf-8'))}
    if store is not None and db is not None:
        manifest = store.manifest()
        expected = EmbeddingSpec(provider='openai', model=models['embedding'], dimensions=1536).model_dump()
        if manifest['embedding'] != expected:
            raise ValueError('Index embedding configuration mismatch.')
        snapshot = database_audit(store, db)
        if not all(row['matches_frozen_inputs'] for row in snapshot.values()):
            raise ValueError('Database differs from the frozen evaluation inputs.')
        report.update(database_checked=True, database_snapshot=snapshot, index=manifest)
    return report


class RecordedPlanner:
    """Observe schema-valid proposals; the graph still owns policy validation."""

    def __init__(self, planner):
        self.planner = planner
        self.decisions: list[dict] = []

    def decide(self, view, index):
        started = time.monotonic()
        row = {'index': index, 'decision': None, 'error': None}
        try:
            decision = self.planner.decide(view, index)
            parsed = DECISION_ADAPTER.validate_python(decision)
            if parsed.kind == 'lookup':
                # Match graph diagnostics: never echo unvalidated arguments or tools.
                row['decision'] = {'kind': 'lookup', 'tool': parsed.tool if parsed.tool in TOOLS else None,
                                   'arguments': None}
                try:
                    arguments, _ = validate_lookup(parsed, view.request, set(view.available_device_ids))
                    row['decision']['arguments'] = arguments.model_dump(mode='json')
                except Exception:
                    row['error'] = 'proposal_not_permitted'
            else:
                row['decision'] = parsed.model_dump(mode='json')
            return decision
        except Exception:
            row['error'] = 'planner_response_failed'
            raise
        finally:
            row['latency_seconds'] = time.monotonic() - started
            self.decisions.append(row)


def project_report(raw: dict | None) -> dict | None:
    """Current actions only for Phase 2 metrics; never project conditional guidance."""
    if raw is None:
        return None
    return {'status': raw['status'], 'summary': raw['summary']['text'],
            'steps': [{'step_type': s['step_type'], 'action': s['action'],
                       'supporting_chunk_ids': [r['chunk_id'] for r in s['references'] if r['kind'] == 'kb_chunk']}
                      for s in raw['steps']], 'missing_information': raw['missing_information'],
            'escalation_required': raw['escalation_required'],
            'escalation_reason': raw['escalation_reason']['text'] if raw['escalation_reason'] else None}


def run_pair(case: Case, *, dependencies: Dependencies, standalone, meter: MeteredTransport) -> dict:
    meter.case_id, meter.arm = case.id, 'agent'
    first_call = len(meter.calls)
    started = time.monotonic()
    planner = RecordedPlanner(dependencies.planner)
    synthesis = ObservedSynthesis(dependencies.synthesis) if dependencies.synthesis is not None else None
    result = run_investigation(case.request, dependencies=replace(dependencies, planner=planner, synthesis=synthesis))
    agent_seconds = time.monotonic() - started
    # Exactly the graph's validated retrieval result, including rank, text and distance.
    evidence = [e.result.model_copy(deep=True) for e in result.kb_evidence]
    raw = result.recommendation.model_dump(mode='json') if result.recommendation else None
    agent_error = None if raw else {'stage': 'generation', 'code': next(
        (e.code.removeprefix('synthesis_') for e in reversed(result.errors) if e.stage == 'synthesis'), 'missing_output')}
    retrieval_ok = any(e.node == 'retrieve' and e.outcome in ('ok', 'empty') for e in result.graph_trace)
    if not retrieval_ok:
        agent_error = {'stage': 'retrieval', 'code': 'shared_retrieval_failed'}
    rag, rag_error = None, None
    meter.arm = 'standalone'
    rag_started = time.monotonic()
    if not retrieval_ok:
        # A failed/skipped retrieval is not a successful empty-result abstention.
        rag_error = {'stage': 'retrieval', 'code': 'shared_retrieval_failed'}
    else:
        try:
            rag = generate_recommendation(case.request.ticket, evidence, provider=standalone).recommendation.model_dump()
        except RecommendationError as exc:
            codes = {'invalid_output', 'invalid_citation', 'provider_failure', 'incomplete', 'refusal', 'missing_output'}
            rag_error = {'stage': 'generation', 'code': exc.code if exc.code in codes else 'provider_failure'}
        except Exception:
            rag_error = {'stage': 'generation', 'code': 'provider_failure'}
    calls = meter.calls[first_call:]
    shared_kb = [e.model_dump(mode='json') for e in evidence]
    return {'id': case.id, 'request': case.request.model_dump(mode='json'), 'shared_kb': shared_kb,
            'shared_kb_sha256': digest(canonical(shared_kb).encode()), 'shared_retrieval_succeeded': retrieval_ok,
            'trigger_status': case.trigger_status, 'corpus_answerable': case.kb_answerable,
            'expected_escalation': case.expected_escalation,
            'phase5a_reference_chunk_ids': case.kb_chunk_ids,
            'retrieved_reference_overlap': sorted(set(case.kb_chunk_ids) & {e.chunk.chunk_id for e in evidence}),
            'frozen_review_notes': case.review_notes,
            'agent_result': result.model_dump(mode='json'), 'planner_decisions': planner.decisions,
            'synthesis_diagnostics': synthesis.finish(result) if synthesis else [],
            'agent': scoring_row(case, project_report(raw) if retrieval_ok else None, evidence, agent_error),
            'standalone': scoring_row(case, rag, evidence, rag_error),
            'planner': planner_metrics(case, result),
            'latency_seconds': {'agent_including_shared_retrieval': agent_seconds,
                                'standalone_generation_only': time.monotonic() - rag_started,
                                'pair': time.monotonic() - started},
            'api_calls': calls, 'usage': usage_totals(calls),
            'manual_review': {'status': 'pending', 'agent_claims': review_items(raw, agent=True),
                              'standalone_claims': review_items(rag, agent=False),
                              'retrieved_evidence_sufficient': None, 'missing_information_sufficient': None,
                              'hidden_conditional_handoff': None, 'current_escalation_trigger_supported': None,
                              'paired_usefulness': None, 'reviewer': None}}


def source_metadata() -> dict:
    from app.investigation.planner import PROMPT_VERSION as planner_version
    from app.investigation.synthesis import PROMPT_VERSION as synthesis_version
    from app.rag.prompts import PROMPT_VERSION as rag_version

    return {'prompt_versions': {'planner': planner_version, 'synthesis': synthesis_version, 'standalone': rag_version},
            'application_sha256': digest(b''.join(p.as_posix().encode() + p.read_text(encoding='utf-8').encode()
                                               for p in sorted(Path('app').rglob('*.py')))),
            'evaluator_sha256': {p: text_digest(Path(p)) for p in (
                'evaluation/live_investigation.py', 'evaluation/live_telemetry.py',
                'evaluation/synthesis_diagnostics.py',
                'evaluation/investigation_e2e.py', 'evaluation/recommendation.py')},
            'lockfile_sha256': text_digest(Path('uv.lock'))}


def write_artifacts(directory: Path, report: dict) -> None:
    report['usage'] = usage_totals(report['api_calls'])
    report['live_model_requests_attempted'] = len(report['api_calls'])
    report['recorded_pair_count'] = len(report['cases'])
    report['unrecorded_scenario_ids'] = [key for key in report['preflight']['scenario_ids']
                                        if key not in {r['id'] for r in report['cases']}]
    report['mechanical_metrics'] = summarize(report['cases'])
    worksheet = {'run_mode': report['mode'], 'paired_outputs': 'paired.json', 'status': 'pending',
                 'cases': [{'id': row['id'], **row['manual_review']} for row in report['cases']]}
    for name, value in [('paired.json', report), ('manual-review.json', worksheet)]:
        temporary = directory / (name + '.tmp')
        temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        temporary.replace(directory / name)


def run_paid(cases: list[Case], models: dict, *, store, db, directory: Path, checked: dict,
             allow_paid: bool = False) -> int:
    if not allow_paid or not checked['database_checked']:
        raise ValueError('Explicit paid opt-in and database preflight required.')
    report = {'mode': 'live_paired_evaluation',
              'semantic_quality_review': 'pending', 'status': 'running',
              'started_at': datetime.now(timezone.utc).isoformat(), 'preflight': checked,
              'cases': [], 'api_calls': [], 'errors': [], 'database_unchanged': None,
              **source_metadata()}
    write_artifacts(directory, report)  # Verify writable artifacts before any API request.
    meter = openai_transport()
    report['api_calls'] = meter.calls
    try:
        # Credentials are read by the SDK, never inspected or included in artifacts.
        with OpenAI(base_url=API_BASE_URL, timeout=30.0, max_retries=0,
                    http_client=httpx.Client(transport=meter, timeout=30.0)) as client:
            dependencies = Dependencies(
                classifier=OpenAIProvider(client, model=models['classification']),
                embedder=OpenAIEmbeddings(client, model=models['embedding']), store=store, db=db,
                planner=OpenAIPlanner(client, model=models['planner']), phase='4B.1',
                synthesis=OpenAISynthesis(client, model=models['synthesis']))
            standalone = OpenAIRecommendation(client, model=models['standalone'])
            for case in cases:
                row = run_pair(case, dependencies=dependencies, standalone=standalone, meter=meter)
                report['cases'].append(row)
                write_artifacts(directory, report)
    except KeyboardInterrupt:
        report['errors'].append('interrupted')
    except Exception:
        report['errors'].append('evaluation_failed')
    finally:
        meter.close()
        try:
            load_cases()
            report['database_after'] = database_audit(store, db)
            report['database_unchanged'] = report['database_after'] == checked['database_snapshot']
            if not report['database_unchanged']:
                report['errors'].append('database_changed')
        except Exception:
            report['errors'].append('final_verification_failed')
        failed = any(r['agent_result']['status'] != 'completed' or not r['shared_retrieval_succeeded']
                     or any(r[a]['outcome'] != 'accepted' for a in ('agent', 'standalone')) for r in report['cases'])
        report['status'] = 'partial' if report['errors'] or failed or len(report['cases']) != len(cases) else 'completed'
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        write_artifacts(directory, report)
    return 0 if report['status'] == 'completed' else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='Default: no model clients or API calls.')
    mode.add_argument('--allow-paid', action='store_true', help='Explicitly opt in to bounded OpenAI requests.')
    parser.add_argument('--check-db', action='store_true', help='Preflight restricted readers and frozen data without API calls.')
    parser.add_argument('--scenario', action='append', choices=PILOT_IDS)
    parser.add_argument('--output-dir', type=Path, help='New directory strictly inside ignored reports/. Required for paid mode.')
    args = parser.parse_args(argv)
    stage = 'input_validation'
    try:
        cases, models = select_cases(args.scenario), model_settings()
        directory = args.output_dir.resolve() if args.output_dir else None
        if directory is not None:
            directory.relative_to(Path('reports').resolve())
            if directory == Path('reports').resolve() or directory.exists():
                raise ValueError('Use a new directory inside reports/.')
        if args.allow_paid and directory is None:
            raise ValueError('Paid runs require an output directory.')
        stage = 'database_preflight'
        store = ReadOnlyKBStore.from_environment() if args.check_db or args.allow_paid else None
        db = OperationalDB.from_environment() if args.check_db or args.allow_paid else None
        checked = preflight(cases, models, store=store, db=db)
        if not args.allow_paid:
            print(json.dumps(checked, indent=2))
            return 0
        stage = 'output_setup'
        directory.mkdir(parents=True, exist_ok=False)
        stage = 'evaluation'
        code = run_paid(cases, models, store=store, db=db, directory=directory, checked=checked, allow_paid=True)
        print(json.dumps({'output_dir': str(directory), 'exit_code': code}))
        return code
    except Exception:
        print(json.dumps({'error': stage + '_failed', 'details': 'Check local inputs/configuration; raw exceptions are withheld.'}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
