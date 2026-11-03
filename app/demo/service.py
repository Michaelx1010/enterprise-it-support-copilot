"""UI adapters: explicit scripted replay or an explicitly authorized live run."""

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
from typing import Literal

from app.investigation.graph import Dependencies, run_investigation
from app.investigation.schemas import InvestigationRequest, InvestigationResult
from app.investigation.scripted import InvestigationScript, script_dependencies
from app.investigation.synthesis_draft import InvestigationSynthesisDraftV4
from app.kb.documents import load_chunks
from app.kb.schemas import SearchResult
from app.rag.recommendation import build_query

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / 'examples' / 'demo-scenarios.json'


class DemoError(Exception):
    """Only application-owned codes cross the UI boundary, never exception text."""


@dataclass(frozen=True)
class DemoRun:
    request: InvestigationRequest
    result: InvestigationResult
    mode: Literal['example', 'live']
    label: str


def examples() -> list[dict]:
    return json.loads(EXAMPLES.read_text(encoding='utf-8'))['scenarios']


class ExampleSynthesis:
    def __init__(self, draft: dict | None):
        self.draft = draft

    def generate(self, *, instructions: str, payload: str):
        # An authored response, never a model call or a fallback for a live failure.
        return InvestigationSynthesisDraftV4.model_validate(self.draft).to_canonical()


def run_example(example_id: str) -> DemoRun:
    data = json.loads(EXAMPLES.read_text(encoding='utf-8'))
    case = next((row for row in data['scenarios'] if row['id'] == example_id), None)
    if case is None:
        raise DemoError('unknown_example')
    chunks = {c.section_id: c for c in load_chunks(ROOT / 'knowledge_base')}
    script = InvestigationScript(
        request=case['request'], classification=case['classification'], decisions=case['decisions'],
        embedding_spec={'provider': 'fixture', 'model': 'demo-replay', 'dimensions': 3},
        query_vector=[1., 0., 0.],
        kb_results=[SearchResult(chunk=chunks[key], distance=0.0) for key in case['sections']],
        lookup_results=data['lookup_results'] if case['use_snapshots'] else [],
    )
    dependencies = replace(script_dependencies(script), synthesis=ExampleSynthesis(case['draft']))
    result = run_investigation(script.request, dependencies=dependencies)
    return DemoRun(script.request, result, 'example', case['title'])


def live_enabled() -> bool:
    return os.getenv('IT_SUPPORT_DEMO_LIVE', '') == '1'


def run_live(request: InvestigationRequest, *, allow_paid: bool = False) -> DemoRun:
    if not live_enabled() or allow_paid is not True:
        raise DemoError('live_not_authorized')
    try:
        request = InvestigationRequest.model_validate(request.model_dump())
        build_query(request.ticket)
    except Exception:
        raise DemoError('invalid_request') from None
    # No env values are returned, logged or interpolated into errors.
    if not all(os.getenv(key, '').strip() for key in
               ('OPENAI_API_KEY', 'OPS_DATABASE_URL', 'KB_READER_DATABASE_URL')):
        raise DemoError('missing_configuration')
    try:
        from app.investigation.kb_access import ReadOnlyKBStore
        from app.operations.db import OperationalDB
        from app.providers.openai import DEFAULT_MODEL, OpenAIProvider
        from app.providers.openai_embeddings import OpenAIEmbeddings
        from app.providers.openai_planner import OpenAIPlanner
        from app.providers.openai_synthesis import OpenAISynthesis

        # Same composition as investigate live --synthesize. The graph owns all
        # retrieval, dispatch, scope checks, limits, validation and failure semantics.
        store, db = ReadOnlyKBStore.from_environment(), OperationalDB.from_environment()
        planner = OpenAIPlanner.from_environment()
        with planner.client as client:
            dependencies = Dependencies(
                classifier=OpenAIProvider(client, model=os.getenv('OPENAI_MODEL', DEFAULT_MODEL)),
                embedder=OpenAIEmbeddings(client, model=os.getenv('OPENAI_EMBEDDING_MODEL', 'text-embedding-3-small')),
                store=store, db=db, planner=planner, phase='4B.1',
                synthesis=OpenAISynthesis.from_environment(client),
            )
            result = run_investigation(request, dependencies=dependencies)
        return DemoRun(request, result, 'live', 'Live investigation')
    except Exception:
        raise DemoError('investigation_setup_failed') from None
