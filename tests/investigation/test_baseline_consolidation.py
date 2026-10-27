"""Reusable consolidation works without local pilots, keys, network or a database."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from evaluation import phase5b_baseline as baseline
from evaluation.investigation_e2e import load_cases, run_case, summarize, text_digest
from evaluation.live_investigation import canonical, source_metadata
from evaluation.live_telemetry import usage_totals


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / 'inputs'
    root.mkdir()
    current = source_metadata()
    manifest = {key: current[key] for key in ('application_sha256', 'lockfile_sha256', 'prompt_versions')}
    manifest.update(format_version=1, models={'synthesis': 'mock-model'}, runs=[],
        frozen_manifest_sha256=text_digest(Path('evaluation/investigation_e2e_manifest.json')))
    for name, rejected in (('repeat-001', False), ('repeat-002', True)):
        case = deepcopy(next(c for c in load_cases() if c.id == 'vpn-future-condition'))
        if rejected:
            case.agent_response['steps'] = []
        row = run_case(case)
        row['shared_kb'] = row.pop('controlled_kb')
        row.update(corpus_answerable=case.kb_answerable, expected_escalation=case.expected_escalation,
            shared_kb_sha256=sha256(canonical(row['shared_kb']).encode()).hexdigest(), api_calls=[], usage=usage_totals([]))
        report = {**current, 'status': 'partial' if rejected else 'completed', 'started_at': 'offline', 'finished_at': 'offline',
            'preflight': {'models': manifest['models'], 'manifest': json.loads(Path('evaluation/investigation_e2e_manifest.json').read_text()),
                          'database_snapshot': {}, 'scenario_ids': [case.id]},
            'database_unchanged': True, 'database_after': {}, 'cases': [row], 'api_calls': [], 'usage': usage_totals([]),
            'mechanical_metrics': summarize([row]), 'recorded_pair_count': 1, 'unrecorded_scenario_ids': []}
        directory = root / name
        directory.mkdir()
        write_json(directory / 'paired.json', report)
        write_json(directory / 'manual-review.json', {'status': 'pending', 'cases': [{'id': case.id, **row['manual_review']}]})
        manifest['runs'].append({'id': name, 'cohort': 'post_connectivity',
            'files': {p.name: sha256(p.read_bytes()).hexdigest() for p in directory.iterdir()}})
    path = tmp_path / 'manifest.json'
    write_json(path, manifest)
    return root, path


def test_repeated_attempts_failures_and_original_bytes_are_preserved(archive, monkeypatch):
    root, manifest = archive
    before = {p: p.read_bytes() for p in root.rglob('*.json')}
    # New application revisions must not masquerade as the historical source.
    metadata = source_metadata()
    monkeypatch.setattr(baseline, 'source_metadata', lambda: {**metadata, 'application_sha256': 'new-revision'})
    result = baseline.consolidate(manifest_path=manifest, reports_root=root)
    assert len(result['attempts']) == 2
    assert len({r['id'] for r in result['attempts']}) == 2
    assert {r['scenario_id'] for r in result['attempts']} == {'vpn-future-condition'}
    metrics = result['post_connectivity_metrics']['agent']
    assert (metrics['attempted'], metrics['accepted'], metrics['rejected']) == (2, 1, 1)
    assert result['future_condition_assessment']['agent']['unscored_rejections_or_failures'] == 1
    assert result['consolidation_source']['application_sha256'] == 'new-revision'
    assert all(p.read_bytes() == content for p, content in before.items())
    assert result['new_live_requests'] == 0 and result['originals_unchanged']
    assert baseline.consolidate(manifest_path=manifest, reports_root=root) == result


def test_any_original_byte_change_rejects_without_overwriting(archive):
    root, manifest = archive
    path = root / 'repeat-001' / 'paired.json'
    path.write_bytes(path.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='Baseline verification failed'):
        baseline.consolidate(manifest_path=manifest, reports_root=root)


@pytest.mark.parametrize('change', ['metrics', 'ticket', 'evidence', 'worksheet', 'database', 'duplicate', 'traversal'])
def test_semantic_integrity_rejects_even_if_file_checksum_is_updated(archive, change):
    root, path = archive
    manifest = json.loads(path.read_text())
    entry = manifest['runs'][0]
    report_path = root / entry['id'] / 'paired.json'
    report = json.loads(report_path.read_text())
    if change == 'metrics': report['mechanical_metrics']['agent']['accepted'] = 99
    if change == 'ticket': report['cases'][0]['request']['ticket']['subject'] = 'Unrelated ticket'
    if change == 'evidence': report['cases'][0]['shared_kb'][0]['chunk']['content'] = 'Unrelated evidence'
    if change == 'database': report['database_after'] = {'changed': True}
    if change == 'duplicate': manifest['runs'].append(deepcopy(entry))
    if change == 'traversal': entry['id'] = '../outside'
    if change == 'worksheet':
        worksheet_path = report_path.with_name('manual-review.json')
        write_json(worksheet_path, {'status': 'pending', 'cases': []})
        entry['files']['manual-review.json'] = sha256(worksheet_path.read_bytes()).hexdigest()
    write_json(report_path, report)
    entry['files']['paired.json'] = sha256(report_path.read_bytes()).hexdigest()
    write_json(path, manifest)
    with pytest.raises(ValueError):
        baseline.consolidate(manifest_path=path, reports_root=root)


def test_output_is_exclusive_and_confined_to_new_report_directory(tmp_path, monkeypatch):
    root = tmp_path / 'reports'
    monkeypatch.setattr(baseline, 'OUTPUT_ROOT', root)
    directory = root / 'new-run'
    path = baseline.write_baseline(directory, {'example': 'derived'})
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        baseline.write_baseline(directory, {'example': 'replacement'})
    assert path.read_bytes() == before
    for target in (root, root.parent / 'outside', root / '..' / 'outside'):
        with pytest.raises(ValueError):
            baseline.write_baseline(target, {})


def test_cli_is_verify_only_by_default_and_never_prints_exception_content(monkeypatch, capsys):
    monkeypatch.setattr(baseline, 'consolidate', lambda: {'attempts': [1, 2]})
    monkeypatch.setattr(baseline, 'write_baseline', lambda *args: pytest.fail('No output requested'))
    assert baseline.main([]) == 0
    def failed():
        raise ValueError('PRIVATE prompt credential evidence')
    monkeypatch.setattr(baseline, 'consolidate', failed)
    assert baseline.main([]) == 1
    assert 'PRIVATE' not in capsys.readouterr().out


def test_preserved_derived_artifact_checksum_is_enforced(archive, tmp_path, monkeypatch):
    root, path = archive
    derived = tmp_path / 'derived'
    derived.mkdir()
    monkeypatch.setattr(baseline, 'OUTPUT_ROOT', derived)
    report = derived / 'old.json'
    report.write_bytes(b'original')
    manifest = json.loads(path.read_text())
    manifest['preserved_derived_artifacts'] = {report.as_posix(): sha256(report.read_bytes()).hexdigest()}
    write_json(path, manifest)
    result = baseline.consolidate(manifest_path=path, reports_root=root)
    assert result['preserved_derived_artifacts'][report.as_posix()]['verification'] == 'matched'
    report.write_bytes(b'changed')
    with pytest.raises(ValueError):
        baseline.consolidate(manifest_path=path, reports_root=root)
