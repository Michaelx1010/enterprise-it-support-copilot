"""Explicit replay fixtures for graph testing, never presented as live AI output."""

from copy import deepcopy

from pydantic import Field

from app.investigation.graph import Dependencies, PlannerView
from app.investigation.policy import validate_result
from app.investigation.schemas import InvestigationRequest, Limits
from app.kb.schemas import SearchResult
from app.operations.records import Model
from app.providers.embeddings import EmbeddingSpec, validate_vectors
from app.rag.recommendation import build_query
from app.schemas import TicketClassification


class ScriptedLookup(Model):
    tool: str
    arguments: dict
    result: dict


class InvestigationScript(Model):
    request: InvestigationRequest
    classification: TicketClassification
    decisions: list[dict] = Field(min_length=1, max_length=4)
    embedding_spec: EmbeddingSpec
    query_vector: list[float] = Field(min_length=1, max_length=1536)
    kb_results: list[SearchResult] = Field(default_factory=list, max_length=3)
    lookup_results: list[ScriptedLookup] = Field(default_factory=list, max_length=4)
    limits: Limits = Field(default_factory=Limits)


class ScriptedPlanner:
    def __init__(self, decisions: list[dict]):
        self.decisions = deepcopy(decisions)

    def decide(self, view: PlannerView, index: int) -> dict:
        # Exhaustion is a planner error; an explicit finish/clarify is required.
        return deepcopy(self.decisions[index])


class ScriptedClassifier:
    def __init__(self, result: TicketClassification):
        self.result = result.model_copy(deep=True)

    def generate(self, *, instructions: str, ticket_text: str) -> TicketClassification:
        return self.result.model_copy(deep=True)


class ScriptedEmbedder:
    def __init__(self, query: str, spec: EmbeddingSpec, vector: list[float]):
        validate_vectors([vector], 1, spec.dimensions)
        self.query, self.spec, self.vector = query, spec, list(vector)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if texts != [self.query]:
            raise ValueError('Scripted vector is only for the supplied ticket query.')
        return [list(self.vector)]


class ReplayStore:
    """Replay supplied rankings through the retrieval entry point; no semantic search."""

    def __init__(self, spec: EmbeddingSpec, results: list[SearchResult]):
        self.spec, self.results = spec, deepcopy(results)

    def manifest(self) -> dict:
        return {'embedding': self.spec.model_dump()}

    def search(self, vector: list[float], spec: EmbeddingSpec, top_k: int) -> list[SearchResult]:
        return deepcopy(self.results[:top_k])


class ReplayLookups:
    def __init__(self, results: list[ScriptedLookup]):
        self.results = deepcopy(results)

    def __call__(self, tool, request):
        for row in self.results:
            if row.tool == tool and row.arguments == request.model_dump(mode='json'):
                return validate_result(tool, row.arguments, deepcopy(row.result))
        raise ValueError('No exact lookup fixture for request.')


def script_dependencies(script: InvestigationScript, *, postgres: bool = False) -> Dependencies:
    embedder = ScriptedEmbedder(build_query(script.request.ticket), script.embedding_spec, script.query_vector)
    if postgres:
        # No model clients, administrative fallback, writes or schema initialization.
        from app.investigation.kb_access import ReadOnlyKBStore
        from app.operations.db import OperationalDB

        if script.kb_results or script.lookup_results:
            raise ValueError('Postgres scripts must not contain replay results.')
        store, db, fixture = ReadOnlyKBStore.from_environment(), OperationalDB.from_environment(), None
    else:
        store, db, fixture = ReplayStore(script.embedding_spec, script.kb_results), None, ReplayLookups(script.lookup_results)
    return Dependencies(classifier=ScriptedClassifier(script.classification), embedder=embedder,
                        store=store, planner=ScriptedPlanner(script.decisions), db=db,
                        fixture_lookup=fixture, limits=script.limits)
