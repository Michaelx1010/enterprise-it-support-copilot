"""Frozen development pilot controller. Default: no API or database access.

Reuse Phase 5B run_paid/run_pair unchanged, with one shared admission budget.
Reservations are deliberately conservative estimates, NOT provider billing limits.
Unknown usage stops further dispatch; raw requests are never written by this module.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
from importlib.metadata import version
from pathlib import Path
import platform
import subprocess

import httpx

from evaluation import live_investigation as live
from evaluation.live_telemetry import API_BASE_URL, MeteredTransport, openai_transport

PROTOCOL = Path('evaluation/phase5c5_protocol.json')
OUTPUT_ROOT = Path('reports/phase5c/live')
SCENARIOS = ('vpn-future-condition', 'vpn-confirmed', 'irrelevant-incident', 'unsupported-procedure')
STAGES = {'TicketClassification': ('classification', 500), 'PlannerResponseV2': ('planner', 700),
          'InvestigationSynthesisDraftV3': ('synthesis', 3000), 'SupportRecommendation': ('standalone', 2500)}


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temporary.replace(path)


class BudgetStop(httpx.TransportError):
    """A fixed safe message; production providers retain their normal error handling."""


class PilotBudget:
    def __init__(self, protocol: dict, checkpoint=None):
        self.protocol = protocol
        self.checkpoint = checkpoint or (lambda: None)
        self.entries: list[dict] = []
        self.stop_reason: str | None = None

    def snapshot(self) -> dict:
        return {'stop_reason': self.stop_reason, 'admitted_requests': len(self.entries),
                'accounted_tokens': sum(e['accounted_tokens'] for e in self.entries),
                'accounted_usd': str(sum((Decimal(e['accounted_usd']) for e in self.entries), Decimal(0))),
                'entries': self.entries}

    def stop(self, reason: str) -> None:
        self.stop_reason = self.stop_reason or reason
        self.checkpoint()
        raise BudgetStop('Evaluation admission stopped; consult the sanitized budget ledger.')

    def cost(self, model: str, inputs: int, outputs: int) -> Decimal:
        price = self.protocol['pricing_usd_per_million'][model]
        return (Decimal(price['input']) * inputs + Decimal(price['output']) * outputs) / 1_000_000

    def reserve(self, request: httpx.Request, attempt_id: str, arm: str) -> dict:
        if self.stop_reason:
            self.stop(self.stop_reason)
        # Never send unknown models, endpoints, tools or changed generation settings.
        if request.method != 'POST' or str(request.url) not in (API_BASE_URL + '/responses', API_BASE_URL + '/embeddings'):
            self.stop('request_configuration_changed')
        try:
            body = json.loads(request.content)
            if request.url.path == '/v1/embeddings':
                stage, output = 'embedding', 0
                valid = body.get('dimensions') == 1536 and body.get('encoding_format') == 'float'
            else:
                stage, output = STAGES[body['text']['format']['name']]
                valid = body.get('max_output_tokens') == output and body.get('store') is False
                valid = valid and (('temperature' not in body) if stage == 'classification' else body.get('temperature') == 0)
            model = self.protocol['models'][stage]
            valid = valid and body.get('model') == model and not any(
                key in body for key in ('tools', 'previous_response_id', 'conversation', 'background', 'stream', 'service_tier'))
        except (KeyError, ValueError, TypeError, AttributeError):
            self.stop('request_configuration_changed')
        if not valid:
            self.stop('request_configuration_changed')
        # All serialized bytes (including schema) plus protocol overhead reserve.
        # This is an admission estimate, not an exact tokenizer or billing oracle.
        inputs = len(request.content) + self.protocol['budget']['input_overhead_reserve']
        cost = self.cost(model, inputs, output)
        current, limit = self.snapshot(), self.protocol['budget']
        if current['admitted_requests'] >= limit['max_requests']:
            self.stop('request_limit')
        if current['accounted_tokens'] + inputs + output > limit['max_tokens']:
            self.stop('token_limit')
        if Decimal(current['accounted_usd']) + cost > Decimal(limit['max_usd']):
            self.stop('cost_limit')
        entry = {'attempt_id': attempt_id, 'arm': arm, 'stage': stage, 'model': model,
                 'status': 'reserved_dispatch_unknown', 'reserved_input_tokens': inputs,
                 'reserved_output_tokens': output, 'accounted_tokens': inputs + output,
                 'accounted_usd': str(cost), 'estimated_usage_cost_usd': None}
        self.entries.append(entry)
        self.checkpoint()  # Durable reservation before dispatch, no headers/body.
        return entry

    def settle(self, entry: dict, call: dict) -> None:
        usage = call.get('usage') or {}
        embedding = entry['stage'] == 'embedding'
        inputs = usage.get('prompt_tokens' if embedding else 'input_tokens')
        outputs = 0 if embedding else usage.get('output_tokens')
        total = usage.get('total_tokens')
        known = all(type(v) is int and v >= 0 for v in (inputs, outputs, total))
        if not known or total != inputs + outputs:
            entry['status'] = 'usage_unknown_reservation_retained'
            self.stop_reason = self.stop_reason or 'usage_unavailable'
        elif inputs > entry['reserved_input_tokens'] or outputs > entry['reserved_output_tokens']:
            entry['status'] = 'usage_exceeded_reservation'
            entry['accounted_tokens'] = max(entry['accounted_tokens'], total)
            entry['accounted_usd'] = str(max(Decimal(entry['accounted_usd']), self.cost(entry['model'], inputs, outputs)))
            self.stop_reason = self.stop_reason or 'usage_exceeded_reservation'
        else:
            entry['status'] = 'usage_recorded'
            entry['accounted_tokens'] = total
            entry['accounted_usd'] = str(self.cost(entry['model'], inputs, outputs))
        if known:
            # Ignore cache discounts conservatively. This is never labelled billed cost.
            entry['estimated_usage_cost_usd'] = str(self.cost(entry['model'], inputs, outputs))
        self.checkpoint()


class BudgetedTransport(MeteredTransport):
    def __init__(self, transport: httpx.BaseTransport, budget: PilotBudget, attempt_id: str):
        super().__init__(transport)
        self.budget, self.attempt_id = budget, attempt_id

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        entry = self.budget.reserve(request, self.attempt_id, self.arm)
        try:
            return super().handle_request(request)
        finally:
            # MeteredTransport records even transport failures/interruptions. Blocked
            # requests never reach it, and therefore are NOT counted as API calls.
            self.budget.settle(entry, self.calls[-1])


def load_protocol() -> dict:
    protocol = json.loads(PROTOCOL.read_text(encoding='utf-8'))
    if protocol['protocol_version'] != 'phase5c5-pilot-v1':
        raise ValueError('Unsupported pilot protocol.')
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
    actual = live.source_metadata()
    if head != protocol['candidate_git_commit'] or any(
            actual[key] != protocol[key] for key in ('application_sha256', 'lockfile_sha256', 'prompt_versions')):
        raise ValueError('Frozen application configuration changed.')
    unchanged = subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', 'app', 'knowledge_base',
                                'uv.lock', 'pyproject.toml'], capture_output=True)
    if unchanged.returncode != 0:
        raise ValueError('Candidate application files changed.')
    if live.model_settings() != protocol['models']:
        raise ValueError('Frozen model configuration changed.')
    environment = {'python': platform.python_version(),
                   'packages': {name: version(name) for name in protocol['environment']['packages']}}
    if environment != protocol['environment']:
        raise ValueError('Frozen dependency environment changed.')
    for path, expected in (protocol['input_file_sha256'] | protocol['preparation_source_sha256']).items():
        if live.text_digest(Path(path)) != expected:
            raise ValueError('Frozen input or evaluation source changed.')
    expected = [{'attempt_id': f'{i + 1:02d}-{scenario}', 'scenario': scenario}
                for i, scenario in enumerate(SCENARIOS * 2)]
    if protocol['attempts'] != expected or protocol['budget'] != {
            'max_requests': 64, 'max_tokens': 400000, 'max_usd': '0.50', 'input_overhead_reserve': 4096}:
        raise ValueError('Pilot matrix or approved budget changed.')
    return protocol


def safe_directory(path: Path) -> Path:
    root = OUTPUT_ROOT.resolve()
    # Reject a redirected reports subtree as well as output traversal/symlinks.
    if root != Path.cwd().resolve() / 'reports' / 'phase5c' / 'live':
        raise ValueError('Output root must not redirect outside the workspace.')
    directory = path.resolve()
    if not directory.is_relative_to(root) or directory == root or directory.exists():
        raise ValueError('Use a new directory strictly inside reports/phase5c/live/.')
    return directory


def execute(protocol: dict, checked: dict, *, store, db, directory: Path, allow_paid: bool = False) -> int:
    if not allow_paid or not checked['database_checked']:
        raise ValueError('Paid opt-in and database preflight required.')
    rows = [{'attempt_id': a['attempt_id'], 'scenario': a['scenario'], 'state': 'not_started'}
            for a in protocol['attempts']]
    report = {'protocol': protocol, 'protocol_sha256': live.text_digest(PROTOCOL),
              'preparation_sha256': live.text_digest(Path(__file__)), **live.source_metadata(),
              'mode': 'phase5c_development_live_pilot', 'status': 'running', 'attempts': rows,
              'manual_review': 'pending', 'started_at': datetime.now(timezone.utc).isoformat(), 'errors': []}
    scored = []
    budget = PilotBudget(protocol)
    def checkpoint():
        report['budget'] = budget.snapshot()
        report['planned_pairs'] = len(rows)
        report['recorded_pairs'] = len(scored)
        report['unrecorded_attempt_ids'] = [r['attempt_id'] for r in rows if r['state'] != 'recorded']
        report['mechanical_metrics_recorded_pairs_only'] = live.summarize(scored)
        write_json(directory / 'pilot.json', report)
    budget.checkpoint = checkpoint
    checkpoint()
    cases = {c.id: c for c in live.select_cases(list(SCENARIOS))}
    try:
        for row in rows:
            if budget.stop_reason:
                break
            row['state'] = 'started'
            checkpoint()
            target = directory / row['attempt_id']
            target.mkdir(exist_ok=False)
            # Reuse fixed endpoint, environment proxy selection, zero retries,
            # SDK providers, graph, paired evidence sharing, diagnostics and V2 worksheet.
            meter = BudgetedTransport(openai_transport().transport, budget, row['attempt_id'])
            code = live.run_paid([cases[row['scenario']]], protocol['models'], store=store, db=db,
                                 directory=target, checked=checked | {'scenario_ids': [row['scenario']]},
                                 allow_paid=True, meter=meter)
            saved = json.loads((target / 'paired.json').read_text(encoding='utf-8'))
            for pair in saved['cases']:
                # Distinct attempt IDs in derived metrics only; preserve source files
                # and the original scenario ID and ticket passed to both systems.
                derived = deepcopy(pair)
                derived['id'] = row['attempt_id']
                for arm in ('agent', 'standalone'):
                    derived[arm]['id'] = row['attempt_id']
                scored.append(derived)
            row.update(state='recorded' if len(saved['cases']) == 1 else 'incomplete',
                       exit_code=code, api_requests=len(saved['api_calls']),
                       paired_sha256=live.text_digest(target / 'paired.json'),
                       worksheet_sha256=live.text_digest(target / 'manual-review.json'))
            checkpoint()
            # Model rejections remain scored attempts; never retry them. Environment,
            # integrity and interruption failures stop the batch, retaining all slots.
            if saved['errors'] or row['state'] == 'incomplete':
                report['errors'].append('attempt_environment_or_integrity_failure')
                break
    except KeyboardInterrupt:
        report['errors'].append('interrupted')
    except Exception:
        report['errors'].append('pilot_failed')
    report['status'] = ('completed' if not report['errors'] and not budget.stop_reason and
                        all(r['state'] == 'recorded' for r in rows) else 'partial')
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    checkpoint()
    return 0 if report['status'] == 'completed' else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--allow-paid', action='store_true')
    parser.add_argument('--check-db', action='store_true')
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args(argv)
    try:
        protocol = load_protocol()
        directory = safe_directory(args.output_dir) if args.output_dir is not None else None
        if args.allow_paid and directory is None:
            raise ValueError('Paid mode requires a fresh output directory.')
        store = live.ReadOnlyKBStore.from_environment() if args.check_db or args.allow_paid else None
        db = live.OperationalDB.from_environment() if args.check_db or args.allow_paid else None
        checked = live.preflight(live.select_cases(list(SCENARIOS)), protocol['models'], store=store, db=db)
        if checked['limits'] != protocol['graph_limits'] or checked['max_api_requests'] * 2 != 64:
            raise ValueError('Request or tool limits changed.')
        if checked['database_checked'] and checked['database_snapshot'] != protocol['database_snapshot']:
            raise ValueError('Database differs from archived verified snapshot.')
        if checked['database_checked'] and checked['index'] != protocol['retrieval']['index']:
            raise ValueError('KB index configuration changed.')
        if not args.allow_paid:
            print(json.dumps({'mode': 'dry_run', 'api_calls': 0, 'database_checked': checked['database_checked'],
                              'candidate_git_commit': protocol['candidate_git_commit'], 'attempts': protocol['attempts'],
                              'max_api_requests': 64, 'budget': protocol['budget'],
                              'protocol_sha256': live.text_digest(PROTOCOL)}, indent=2))
            return 0
        directory.mkdir(parents=True, exist_ok=False)
        return execute(protocol, checked, store=store, db=db, directory=directory, allow_paid=True)
    except Exception:
        print(json.dumps({'error': 'pilot_configuration_or_execution_failed', 'raw_details_withheld': True}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
