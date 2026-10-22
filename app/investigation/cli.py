"""Scripted replay and explicit live planning with opt-in advisory synthesis."""

import argparse
import json
import os
from pathlib import Path
import sys


def add_commands(commands: argparse._SubParsersAction):
    parser = commands.add_parser('investigate', help='Bounded read-only investigation; scripted or live planning.')
    sub = parser.add_subparsers(dest='investigation_command', required=True)
    run = sub.add_parser('scripted', help='Replay decisions; no live planner, embedding or synthesis model.')
    run.add_argument('--script', type=Path, required=True)
    run.add_argument('--backend', choices=['fixture', 'postgres'], default='fixture')
    live = sub.add_parser('live', help='Paid OpenAI planning, classification and embeddings with restricted PostgreSQL readers.')
    live.add_argument('--request', type=Path, required=True, help='JSON InvestigationRequest with explicit identifier scope.')
    live.add_argument('--synthesize', action='store_true', help='Phase 4B.2: add at most one paid grounded synthesis request.')
    setup = sub.add_parser('provision-kb-reader', help='Admin bootstrap only: create KB-only read credentials.')
    setup.add_argument('--env-file', type=Path, default=Path('.env.kb'))


def _run_live(args: argparse.Namespace) -> int:
    from app.investigation.graph import Dependencies, run_investigation
    from app.investigation.kb_access import ReadOnlyKBStore
    from app.investigation.schemas import InvestigationRequest
    from app.operations.db import OperationalDB
    from app.rag.recommendation import build_query

    if args.request.stat().st_size > 250000:
        raise ValueError('Request too large.')
    request = InvestigationRequest.model_validate_json(args.request.read_text(encoding='utf-8'))
    build_query(request.ticket)  # Validate before credentials or any provider construction.
    store, db = ReadOnlyKBStore.from_environment(), OperationalDB.from_environment()
    from app.providers.openai import DEFAULT_MODEL as CLASSIFICATION_MODEL, OpenAIProvider
    from app.providers.openai_embeddings import OpenAIEmbeddings
    from app.providers.openai_planner import OpenAIPlanner

    planner = OpenAIPlanner.from_environment()
    # Reuse existing provider implementations with a shared, zero-retry client.
    with planner.client as client:
        synthesis = None
        if args.synthesize:
            from app.providers.openai_synthesis import OpenAISynthesis

            synthesis = OpenAISynthesis.from_environment(client)
        dependencies = Dependencies(
            classifier=OpenAIProvider(client, model=os.getenv('OPENAI_MODEL', CLASSIFICATION_MODEL)),
            embedder=OpenAIEmbeddings(client, model=os.getenv('OPENAI_EMBEDDING_MODEL', 'text-embedding-3-small')),
            store=store, db=db, planner=planner, phase='4B.1', synthesis=synthesis,
        )
        result = run_investigation(request, dependencies=dependencies)
    print(json.dumps({'backend': 'postgres', 'planner': 'openai', 'planner_model': planner.model,
                      'classification': 'openai', 'query_embedding': 'openai',
                      'synthesis': 'openai' if synthesis else None,
                      'synthesis_model': synthesis.model if synthesis else None,
                      'result': result.model_dump(mode='json')}, indent=2))
    return 0 if result.status == 'completed' else (2 if result.status == 'partial' else 1)


def run(args: argparse.Namespace) -> int:
    try:
        if args.investigation_command == 'provision-kb-reader':
            from app.investigation.kb_access import provision_kb_reader
            from app.operations.db import admin_url

            provision_kb_reader(admin_url(), args.env_file)
            print(json.dumps({'status': 'ok', 'operation': 'kb_reader_provisioned'}))
            return 0
        if args.investigation_command == 'live':
            return _run_live(args)
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
                                   'message': 'Check the input file and explicitly configured credentials; no secrets are shown.'}}), file=sys.stderr)
        return 1
