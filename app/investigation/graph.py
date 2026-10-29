"""Fixed bounded investigation, optionally followed by one advisory synthesis."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import time
from typing import Callable, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langsmith import tracing_context
from pydantic import BaseModel, ValidationError

from app.classification import classify_ticket
from app.investigation.planner import Planner, PlannerView, validate_clarification
from app.investigation.policy import TOOLS, PolicyError, validate_lookup, validate_result
from app.investigation.schemas import (
    DECISION_ADAPTER, InvestigationRequest, InvestigationResult, KBEvidence,
    KBReference, Limits, LookupDecision, LookupOutcome, ObservationReference,
    OperationalEvidence, RunError, TraceEvent,
    InvestigationSynthesis,
)
from app.investigation.synthesis import abstention, build_payload, generate_synthesis, MAX_PAYLOAD_CHARACTERS
from app.kb.schemas import SearchResult
from app.kb.store import PgvectorStore
from app.operations.db import OperationalDB
from app.providers.base import ClassificationProvider
from app.providers.embeddings import EmbeddingProvider
from app.providers.synthesis import SynthesisProvider, SynthesisError
from app.rag.recommendation import build_query, retrieve_ticket
from app.schemas import TicketClassification


@dataclass(frozen=True, repr=False)
class Dependencies:
    classifier: ClassificationProvider
    embedder: EmbeddingProvider
    store: PgvectorStore
    planner: Planner
    db: OperationalDB | None = None
    # Fixture substitute only. Production dispatch is the fixed registry above.
    fixture_lookup: Callable[[str, BaseModel], BaseModel | dict] | None = None
    limits: Limits = field(default_factory=Limits)
    clock: Callable[[], float] = time.monotonic
    phase: Literal['4A', '4B.1'] = '4A'
    synthesis: SynthesisProvider | None = None


class InvestigationState(TypedDict):
    phase: Literal['4A', '4B.1', '4B.2']
    request: InvestigationRequest
    started_at: datetime
    deadline: float
    classification: TicketClassification | None
    kb_evidence: list[KBEvidence]
    operational_evidence: list[OperationalEvidence]
    lookup_trace: list[LookupOutcome]
    graph_trace: list[TraceEvent]
    errors: list[RunError]
    missing_fields: list[str]
    device_ids: set[str]
    seen: set[str]
    planner_decisions: int
    lookup_attempts: int
    operational_characters: int
    decision: LookupDecision | None
    arguments: dict | None
    stop_reason: str | None
    result: InvestigationResult | None
    synthesis_status: Literal['not_run', 'completed', 'failed', 'skipped']
    synthesis_attempts: int
    recommendation: InvestigationSynthesis | None


def _event(state, node, outcome, lookup_id=None):
    return state['graph_trace'] + [TraceEvent(node=node, outcome=outcome, lookup_id=lookup_id)]


def _error(state, stage, code):
    return state['errors'] + [RunError(stage=stage, code=code)]


def _expired(state, runtime, node):
    if runtime.context.clock() >= state['deadline']:
        return {'stop_reason': 'deadline', 'errors': _error(state, 'budget', 'deadline'),
                'graph_trace': _event(state, node, 'deadline')}
    return None


def validate_node(state: InvestigationState, runtime: Runtime[Dependencies]):
    # Revalidated before entering the graph; this node makes that boundary visible.
    return {'graph_trace': _event(state, 'validate', 'accepted')}


def classify_node(state: InvestigationState, runtime: Runtime[Dependencies]):
    if update := _expired(state, runtime, 'classify'):
        return update
    ticket = state['request'].ticket
    try:
        result = classify_ticket(ticket.subject, ticket.description, provider=runtime.context.classifier)
        return {'classification': result, 'graph_trace': _event(state, 'classify', 'ok')}
    except Exception:
        # Provider/DB exception strings and validation inputs may contain secrets.
        return {'errors': _error(state, 'classification', 'classification_failed'),
                'graph_trace': _event(state, 'classify', 'error')}


def retrieve_node(state: InvestigationState, runtime: Runtime[Dependencies]):
    if update := _expired(state, runtime, 'retrieve'):
        return update
    try:
        rows = retrieve_ticket(state['request'].ticket, embedder=runtime.context.embedder,
                               store=runtime.context.store, top_k=3)
        rows = [SearchResult.model_validate(row.model_dump()) for row in rows]
        if len(rows) > 3 or len({r.chunk.chunk_id for r in rows}) != len(rows):
            raise ValueError('Invalid retrieval results.')
        evidence = [KBEvidence(reference=KBReference(chunk_id=r.chunk.chunk_id), result=r) for r in rows]
        return {'kb_evidence': evidence, 'graph_trace': _event(state, 'retrieve', 'ok' if rows else 'empty')}
    except Exception:
        return {'errors': _error(state, 'retrieval', 'retrieval_failed'),
                'graph_trace': _event(state, 'retrieve', 'error')}


def plan_node(state: InvestigationState, runtime: Runtime[Dependencies]):
    if update := _expired(state, runtime, 'plan'):
        return update
    index = state['planner_decisions']
    if index >= runtime.context.limits.planner_decisions:
        return {'stop_reason': 'decision_budget', 'errors': _error(state, 'budget', 'decision_budget'),
                'graph_trace': _event(state, 'plan', 'decision_budget')}
    update = {'planner_decisions': index + 1, 'decision': None, 'arguments': None}
    view = PlannerView(request=state['request'], classification=state['classification'],
                       kb_evidence=state['kb_evidence'], operational_evidence=state['operational_evidence'],
                       available_device_ids=sorted(state['device_ids']),
                       lookup_trace=state['lookup_trace'], errors=state['errors'],
                       remaining_decisions=runtime.context.limits.planner_decisions - index,
                       remaining_lookups=runtime.context.limits.lookup_attempts - state['lookup_attempts']).model_copy(deep=True)
    try:
        decision = DECISION_ADAPTER.validate_python(runtime.context.planner.decide(view, index))
        if decision.kind == 'clarify':
            validate_clarification(decision, state['request'])
    except Exception:
        return update | {'stop_reason': 'planner_failed', 'errors': _error(state, 'planner', 'planner_failed'),
                         'graph_trace': _event(state, 'plan', 'error')}
    if decision.kind == 'lookup':
        return update | {'decision': decision, 'graph_trace': _event(state, 'plan', 'lookup')}
    return update | {'stop_reason': decision.kind,
                     'missing_fields': decision.missing_fields if decision.kind == 'clarify' else [],
                     'graph_trace': _event(state, 'plan', decision.kind)}


def guard_node(state: InvestigationState, runtime: Runtime[Dependencies]):
    if update := _expired(state, runtime, 'guard'):
        return update
    decision = state['decision']
    lookup_id = f'lookup-{len(state["lookup_trace"]) + 1}'
    tool = decision.tool if decision.tool in TOOLS else None
    arguments = None
    try:
        if state['lookup_attempts'] >= runtime.context.limits.lookup_attempts:
            raise PolicyError('lookup_budget')
        model, key = validate_lookup(decision, state['request'], state['device_ids'])
        arguments = model.model_dump(mode='json')
        if key in state['seen']:
            raise PolicyError('duplicate_lookup')
    except (PolicyError, ValidationError) as exc:
        code = exc.code if isinstance(exc, PolicyError) else 'invalid_arguments'
        outcome = LookupOutcome(lookup_id=lookup_id, tool=tool, arguments=arguments, executed=False,
                                status='duplicate' if code == 'duplicate_lookup' else 'blocked', code=code)
        return {'stop_reason': code, 'lookup_trace': state['lookup_trace'] + [outcome],
                'errors': _error(state, 'guard', code), 'graph_trace': _event(state, 'guard', code, lookup_id)}
    return {'arguments': arguments, 'seen': state['seen'] | {key},
            'graph_trace': _event(state, 'guard', 'allowed', lookup_id)}


def execute_node(state: InvestigationState, runtime: Runtime[Dependencies]):
    if update := _expired(state, runtime, 'execute'):
        return update
    tool = state['decision'].tool
    arguments = state['arguments']
    lookup_id = f'lookup-{len(state["lookup_trace"]) + 1}'
    update = {'lookup_attempts': state['lookup_attempts'] + 1}
    try:
        request = TOOLS[tool][0].model_validate(arguments)
        if runtime.context.fixture_lookup is not None:
            raw = runtime.context.fixture_lookup(tool, request)
        else:
            if runtime.context.db is None:
                raise RuntimeError('Missing restricted operational connection.')
            raw = TOOLS[tool][2](request, db=runtime.context.db)
        result = validate_result(tool, arguments, raw)
        if tool == 'get_device_details' and result.device and result.device.assigned_employee_id != state['request'].employee_id:
            raise PolicyError('device_ownership_conflict')
    except Exception as exc:
        rejected = isinstance(exc, (PolicyError, ValidationError))
        code = exc.code if isinstance(exc, PolicyError) else ('invalid_tool_result' if rejected else 'lookup_failed')
        outcome = LookupOutcome(lookup_id=lookup_id, tool=tool, arguments=arguments, executed=True,
                                status='rejected' if rejected else 'error', code=code)
        return update | {'stop_reason': code, 'lookup_trace': state['lookup_trace'] + [outcome],
                         'errors': _error(state, 'lookup', code), 'graph_trace': _event(state, 'execute', code, lookup_id)}
    reference = ObservationReference(lookup_id=lookup_id)
    evidence = OperationalEvidence(reference=reference, observation={'tool': tool, 'result': result.model_dump()})
    outcome = LookupOutcome(lookup_id=lookup_id, tool=tool, arguments=arguments, executed=True,
                            status=result.status, evidence=reference)
    count = state['operational_characters'] + len(evidence.model_dump_json())
    update |= {'lookup_trace': state['lookup_trace'] + [outcome],
               'operational_evidence': state['operational_evidence'] + [evidence],
               'operational_characters': count, 'graph_trace': _event(state, 'execute', result.status, lookup_id)}
    if count > runtime.context.limits.operational_characters:
        # Retain the validated observation for review, but never give oversized context to a planner.
        return update | {'stop_reason': 'context_budget', 'errors': _error(state, 'budget', 'context_budget')}
    if tool == 'get_employee_devices' and result.status == 'ok':
        update['device_ids'] = state['device_ids'] | {d.device_id for d in result.devices}
    return update


def synthesize_node(state: InvestigationState, runtime: Runtime[Dependencies]):
    def failure(code, *, attempts=0, skipped=False):
        return {'synthesis_status': 'skipped' if skipped else 'failed',
                'synthesis_attempts': attempts, 'recommendation': None,
                'errors': _error(state, 'synthesis', 'synthesis_' + code),
                'graph_trace': _event(state, 'synthesize', code)}

    if runtime.context.clock() >= state['deadline']:
        return failure('deadline', skipped=True)
    if state['stop_reason'] == 'context_budget':
        return failure('context_limit', skipped=True)
    if state['stop_reason'] == 'clarify':
        report = abstention('The investigation requires clarification before recommending actions.',
                            ['Clarification needed: ' + field for field in state['missing_fields']])
        return {'synthesis_status': 'completed', 'recommendation': report,
                'graph_trace': _event(state, 'synthesize', 'clarification_abstention')}
    if not state['kb_evidence']:
        report = abstention('No KB procedures are available to support recommendations.',
                            ['Applicable documentation is needed.'])
        return {'synthesis_status': 'completed', 'recommendation': report,
                'graph_trace': _event(state, 'synthesize', 'no_kb_abstention')}
    # Serialize a fresh evidence snapshot; the provider cannot mutate graph state.
    payload = build_payload(state['request'], state['kb_evidence'], state['operational_evidence'],
                            stop_reason=state['stop_reason'], errors=state['errors'],
                            missing_fields=state['missing_fields'])
    if len(payload) > MAX_PAYLOAD_CHARACTERS:
        return failure('context_limit', skipped=True)
    try:
        report = generate_synthesis(payload,
            kb_ids={e.reference.chunk_id for e in state['kb_evidence']},
            lookup_ids={e.reference.lookup_id for e in state['operational_evidence']},
            trigger_lookup_ids={e.reference.lookup_id for e in state['operational_evidence']
                                if e.observation.result.status == 'ok'},
            provider=runtime.context.synthesis)
    except Exception as exc:
        # Fixed allowlisted codes only, even for substitute providers.
        codes = {'provider_failure', 'invalid_output', 'invalid_citation', 'incomplete',
                 'refusal', 'missing_output', 'missing_limitations', 'context_limit'}
        code = exc.code if isinstance(exc, SynthesisError) and exc.code in codes else 'provider_failure'
        return failure(code, attempts=1)
    if runtime.context.clock() >= state['deadline']:
        return failure('deadline', attempts=1)
    return {'synthesis_status': 'completed', 'synthesis_attempts': 1, 'recommendation': report,
            'graph_trace': _event(state, 'synthesize', 'accepted')}


def assemble_node(state: InvestigationState, runtime: Runtime[Dependencies]):
    if runtime is not None and not state['errors'] and runtime.context.clock() >= state['deadline']:
        state = state | {'stop_reason': 'deadline', 'errors': _error(state, 'budget', 'deadline')}
    usable = state['classification'] is not None or bool(state['kb_evidence'] or state['operational_evidence'])
    clean = not state['errors'] and state['stop_reason'] in ('finish', 'clarify')
    status = 'completed' if clean else ('partial' if usable else 'failed')
    trace = _event(state, 'assemble', status)
    result = InvestigationResult(
        phase=state['phase'],
        status=status, stop_reason=state['stop_reason'] or 'graph_failed', started_at=state['started_at'],
        finished_at=datetime.now(timezone.utc), classification=state['classification'],
        kb_evidence=state['kb_evidence'], operational_evidence=state['operational_evidence'],
        lookup_trace=state['lookup_trace'], graph_trace=trace, errors=state['errors'],
        missing_fields=state['missing_fields'], planner_decisions=state['planner_decisions'],
        lookup_attempts=state['lookup_attempts'],
        synthesis_status=state['synthesis_status'], synthesis_attempts=state['synthesis_attempts'],
        recommendation=state['recommendation'],
    )
    return {'result': result, 'graph_trace': trace}


def build_graph(*, synthesis: bool = False):
    graph = StateGraph(InvestigationState, context_schema=Dependencies)
    for name, node in [('validate', validate_node), ('classify', classify_node), ('retrieve', retrieve_node),
                       ('plan', plan_node), ('guard', guard_node), ('execute', execute_node), ('assemble', assemble_node)]:
        graph.add_node(name, node)
    if synthesis:
        graph.add_node('synthesize', synthesize_node)
        graph.add_edge('synthesize', 'assemble')
    graph.add_edge(START, 'validate')
    graph.add_edge('validate', 'classify')
    for source, target in [('classify', 'retrieve'), ('retrieve', 'plan'), ('plan', 'guard'), ('guard', 'execute'), ('execute', 'plan')]:
        graph.add_conditional_edges(source, lambda state: 'stop' if state['stop_reason'] else 'continue',
                                    {'stop': 'synthesize' if synthesis else 'assemble', 'continue': target})
    graph.add_edge('assemble', END)
    return graph.compile()  # No persistence, checkpointer, interrupt or approval workflow.


def run_investigation(request: InvestigationRequest, *, dependencies: Dependencies) -> InvestigationResult:
    request = InvestigationRequest.model_validate(request.model_dump())
    build_query(request.ticket)  # Reject oversized tickets before component calls.
    limits = Limits.model_validate(dependencies.limits.model_dump())
    state = InvestigationState(
        phase='4B.2' if dependencies.synthesis is not None else dependencies.phase,
        request=request, started_at=datetime.now(timezone.utc), deadline=dependencies.clock() + limits.elapsed_seconds,
        classification=None, kb_evidence=[], operational_evidence=[], lookup_trace=[], graph_trace=[], errors=[],
        missing_fields=[], device_ids=set(), seen=set(), planner_decisions=0, lookup_attempts=0,
        operational_characters=0, decision=None, arguments=None, stop_reason=None, result=None,
        synthesis_status='not_run', synthesis_attempts=0, recommendation=None,
    )
    # Disable external tracing even if a shell has LangSmith tracing enabled.
    with tracing_context(enabled=False):
        try:
            graph = build_graph() if dependencies.synthesis is None else build_graph(synthesis=True)
            for current in graph.stream(state, context=dependencies, config={'recursion_limit': 32}, stream_mode='values'):
                state = current
        except Exception:
            state = state | {'stop_reason': 'graph_failed', 'errors': _error(state, 'assembly', 'graph_failed')}
            # Use the most recent completed node's state, not invented replacements.
            return assemble_node(state, None)['result']
    return state['result']
