"""Verify and consolidate immutable saved pilots. No SDK calls or database access.

Run from the repository root. The checksum-only manifest is version controlled;
original reports and derived evidence stay local under ignored reports/.
"""

import argparse
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re

from app.investigation.schemas import InvestigationResult
from app.kb.schemas import SearchResult
from app.rag.schemas import SupportRecommendation
from evaluation.investigation_e2e import load_cases, planner_metrics, summarize, text_digest
from evaluation.live_investigation import canonical, project_report, source_metadata
from evaluation.live_telemetry import usage_totals
from evaluation.recommendation import citation_metrics

MANIFEST = Path('evaluation/phase5b_baseline_manifest.json')
REPORTS = Path('reports/phase5b')
OUTPUT_ROOT = Path('reports/phase5c')


def require(condition: bool) -> None:
    if not condition:
        raise ValueError('Baseline verification failed; original inputs must not be rewritten.')


def consolidate(*, manifest_path: Path = MANIFEST, reports_root: Path = REPORTS) -> dict:
    """Verify saved outcomes, never rerun models or replace old diagnostics.

    A fresh copy receives run/scenario attempt IDs. Repeated scenarios and failures
    remain in denominators. Current source fingerprints are provenance, not a
    requirement that application code still equals the historical revision.
    """
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    require(manifest['format_version'] == 1 and bool(manifest['runs']))
    require(len({r['id'] for r in manifest['runs']}) == len(manifest['runs']))
    require(manifest['frozen_manifest_sha256'] == text_digest(Path('evaluation/investigation_e2e_manifest.json')))
    cases = {case.id: case for case in load_cases()}
    frozen_manifest = json.loads(Path('evaluation/investigation_e2e_manifest.json').read_text(encoding='utf-8'))
    rows, metadata, calls, input_hashes = [], {}, [], {}
    preserved = {}
    for name, expected_hash in manifest.get('preserved_derived_artifacts', {}).items():
        path = Path(name).resolve()
        require(path.is_relative_to(OUTPUT_ROOT.resolve()))
        if path.exists():
            require(sha256(path.read_bytes()).hexdigest() == expected_hash)
            preserved[name] = {'sha256': expected_hash, 'verification': 'matched'}
        else:
            preserved[name] = {'sha256': expected_hash, 'verification': 'not_available_locally'}
    root = reports_root.resolve()
    for entry in manifest['runs']:
        run = entry['id']
        require(bool(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', run)))
        require(entry['cohort'] in ('post_connectivity', 'transport_failure_history'))
        require(set(entry['files']) == {'paired.json', 'manual-review.json'})
        saved = {}
        for name, expected_hash in entry['files'].items():
            path = (root / run / name).resolve()
            require(path.is_relative_to(root))
            content = path.read_bytes()
            require(sha256(content).hexdigest() == expected_hash)
            input_hashes[path] = expected_hash
            saved[name] = json.loads(content)
        report, worksheet = saved['paired.json'], saved['manual-review.json']
        for key in ('application_sha256', 'lockfile_sha256', 'prompt_versions'):
            require(report[key] == manifest[key])
        require(report['preflight']['models'] == manifest['models'])
        require(report['preflight']['manifest'] == frozen_manifest)
        require(report['database_unchanged'] is True)
        require(report['database_after'] == report['preflight']['database_snapshot'])
        require(report['mechanical_metrics'] == summarize(report['cases']))
        require(report['usage'] == usage_totals(report['api_calls']))
        require(worksheet['status'] == 'pending')
        require(worksheet['cases'] == [{'id': c['id'], **c['manual_review']} for c in report['cases']])
        require(not report['unrecorded_scenario_ids'])
        require(report['recorded_pair_count'] == len(report['cases']))
        require(report['api_calls'] == [call for c in report['cases'] for call in c['api_calls']])
        metadata[run] = {key: report[key] for key in (
            'started_at', 'finished_at', 'status', 'database_unchanged', 'application_sha256',
            'evaluator_sha256', 'lockfile_sha256', 'prompt_versions', 'usage')}
        metadata[run]['models'] = report['preflight']['models']
        require([c['id'] for c in report['cases']] == report['preflight']['scenario_ids'])
        for original in report['cases']:
            row = deepcopy(original)
            case = cases[row['id']]
            require(row['request'] == case.request.model_dump(mode='json'))
            require((row['trigger_status'], row['corpus_answerable'], row['expected_escalation']) ==
                    (case.trigger_status, case.kb_answerable, case.expected_escalation))
            require(row['shared_kb_sha256'] == sha256(canonical(row['shared_kb']).encode()).hexdigest())
            result = InvestigationResult.model_validate(row['agent_result'])
            require(row['shared_kb'] == [e.result.model_dump(mode='json') for e in result.kb_evidence])
            require(row['planner'] == planner_metrics(case, result))
            evidence = [SearchResult.model_validate(e) for e in row['shared_kb']]
            for arm in ('agent', 'standalone'):
                require(row[arm]['id'] == case.id)
                require((row[arm]['answerable'], row[arm]['expected_escalation']) ==
                        (case.answerable, case.expected_escalation))
                require(row[arm]['group'] == ('supported' if case.answerable else 'unsupported'))
                if row[arm]['outcome'] == 'accepted':
                    candidate = SupportRecommendation.model_validate(row[arm]['recommendation'])
                    require(row[arm]['citation_metrics'] == citation_metrics(candidate, evidence))
                else:
                    require(row[arm]['outcome'] in ('rejected', 'failed'))
                    require(row[arm]['recommendation'] is None and row[arm]['citation_metrics'] is None)
            if result.recommendation:
                require(project_report(result.recommendation.model_dump(mode='json')) == row['agent']['recommendation'])
            require(row['usage'] == usage_totals(row['api_calls']))
            row.update(scenario_id=row['id'], run_id=run, cohort=entry['cohort'])
            row['id'] = f"{run}/{row['scenario_id']}"
            for arm in ('agent', 'standalone'):
                row[arm]['id'] = row['id']
            row['agent_output_origin'] = ('model_synthesis' if result.synthesis_attempts else
                'deterministic_abstention' if result.recommendation else 'no_output')
            rows.append(row)
        calls.extend(report['api_calls'])
    require(len({row['id'] for row in rows}) == len(rows))
    require(all(sha256(path.read_bytes()).hexdigest() == expected for path, expected in input_hashes.items()))
    require(manifest_path.read_bytes() == manifest_bytes)
    require(all(sha256(Path(name).read_bytes()).hexdigest() == item['sha256']
                for name, item in preserved.items() if item['verification'] == 'matched'))
    post = [r for r in rows if r['cohort'] == 'post_connectivity']
    supported = [r for r in post if r['corpus_answerable']]
    future = [r for r in post if r['trigger_status'] == 'unconfirmed']
    future_assessment = {}
    for arm in ('agent', 'standalone'):
        accepted = [r for r in future if r[arm]['outcome'] == 'accepted']
        premature = sum(r[arm]['recommendation']['escalation_required'] for r in accepted)
        future_assessment[arm] = {'all_attempts': len(future), 'assessable_outputs': len(accepted),
            'unscored_rejections_or_failures': len(future) - len(accepted), 'premature_count': premature,
            'premature_rate_on_assessable': premature / len(accepted) if accepted else None,
            'accepted_correct_no_escalation_over_all_attempts':
                (len(accepted) - premature) / len(future) if future else None}
    return {'kind': 'retrospective_saved_live_baseline', 'new_live_requests': 0,
        'original_manual_reviews': 'pending; separate source review in docs/phase5c.md, human sign-off pending',
        'run_metadata': metadata, 'post_connectivity_metrics': summarize(post),
        'all_collected_attempts_metrics': summarize(rows), 'supported_post_connectivity_metrics': summarize(supported),
        'future_condition_assessment': future_assessment, 'usage_all_collected': usage_totals(calls),
        'usage_post_connectivity': usage_totals([call for row in post for call in row['api_calls']]),
        'http_status_counts_all': dict(Counter(str(c['http_status']) for c in calls)), 'attempts': rows,
        'originals_unchanged': True, 'preserved_derived_artifacts': preserved, 'source_file_sha256': {
            path.relative_to(root).as_posix(): value for path, value in input_hashes.items()},
        'manifest_sha256': sha256(manifest_bytes).hexdigest(),
        'consolidator_sha256': text_digest(Path(__file__)), 'consolidation_source': source_metadata()}


def write_baseline(directory: Path, report: dict) -> Path:
    directory, root = directory.resolve(), OUTPUT_ROOT.resolve()
    require(directory != root and directory.is_relative_to(root))
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / 'baseline.json'
    with path.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, help='New directory inside reports/phase5c; omitted means verify only.')
    args = parser.parse_args(argv)
    try:
        report = consolidate()
        if args.output_dir is not None:
            write_baseline(args.output_dir, report)
    except (ValueError, OSError, KeyError, TypeError):
        print('Baseline verification/output failed. Check source availability, checksums and a new output directory.')
        return 1
    print(f"Verified {len(report['attempts'])} saved pairs; zero API/database calls; originals unchanged.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
