"""Local developer scripts. Neither runtime mode constructs a live model client."""

import argparse
import json
from pathlib import Path
import sys


def add_commands(commands: argparse._SubParsersAction):
    parser = commands.add_parser('investigate', help='Phase 4A scripted read-only investigation.')
    sub = parser.add_subparsers(dest='investigation_command', required=True)
    run = sub.add_parser('scripted', help='Replay decisions; no live planner, embedding or synthesis model.')
    run.add_argument('--script', type=Path, required=True)
    run.add_argument('--backend', choices=['fixture', 'postgres'], default='fixture')
    setup = sub.add_parser('provision-kb-reader', help='Admin bootstrap only: create KB-only read credentials.')
    setup.add_argument('--env-file', type=Path, default=Path('.env.kb'))


def run(args: argparse.Namespace) -> int:
    try:
        if args.investigation_command == 'provision-kb-reader':
            from app.investigation.kb_access import provision_kb_reader
            from app.operations.db import admin_url

            provision_kb_reader(admin_url(), args.env_file)
            print(json.dumps({'status': 'ok', 'operation': 'kb_reader_provisioned'}))
            return 0
        # Developer fixture files are bounded, and their validation errors never echo input.
        if args.script.stat().st_size > 250000:
            raise ValueError('Script too large.')
        from app.investigation.graph import run_investigation
        from app.investigation.scripted import InvestigationScript, script_dependencies

        script = InvestigationScript.model_validate_json(args.script.read_text(encoding='utf-8'))
        result = run_investigation(script.request, dependencies=script_dependencies(script, postgres=args.backend == 'postgres'))
        print(json.dumps({'backend': args.backend, 'planner': 'scripted', 'classification': 'scripted',
                          'query_embedding': 'supplied_vector', 'result': result.model_dump(mode='json')}, indent=2))
        return 0 if result.status == 'completed' else (2 if result.status == 'partial' else 1)
    except Exception:
        print(json.dumps({'error': {'code': 'investigation_setup_failed',
                                   'message': 'Check the script and explicitly configured reader credentials; no secrets are shown.'}}), file=sys.stderr)
        return 1
