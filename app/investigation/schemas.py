"""Application-owned scope, evidence and trace contracts; no model SDK types."""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, TypeAdapter, model_validator

from app.kb.schemas import SearchResult
from app.operations.records import EmployeeID, ServiceID, SoftwareID, Model
from app.operations.schemas import (
    EmployeeAccountResult, EmployeeDevicesResult, DeviceDetailsResult,
    SoftwareEntitlementResult, RecentTicketsResult, ActiveIncidentsResult,
)
from app.schemas import TicketClassification, TicketInput

ToolName = Literal[
    'get_employee_account_status', 'get_employee_devices', 'get_device_details',
    'check_software_entitlement', 'get_recent_support_tickets', 'get_active_service_incidents',
]


class InvestigationRequest(Model):
    ticket: TicketInput
    employee_id: EmployeeID | None = None
    service_ids: list[ServiceID] = Field(default_factory=list, max_length=5)
    software_ids: list[SoftwareID] = Field(default_factory=list, max_length=5)

    @model_validator(mode='after')
    def unique_scope(self) -> Self:
        if len(set(self.service_ids)) != len(self.service_ids) or len(set(self.software_ids)) != len(self.software_ids):
            raise ValueError('Scope identifiers must be unique.')
        return self


class LookupDecision(Model):
    kind: Literal['lookup']
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict


class FinishDecision(Model):
    kind: Literal['finish']


class ClarifyDecision(Model):
    kind: Literal['clarify']
    missing_fields: list[Literal['employee_id', 'service_ids', 'software_ids', 'ticket_details']] = Field(min_length=1, max_length=4)


Decision = Annotated[LookupDecision | FinishDecision | ClarifyDecision, Field(discriminator='kind')]
DECISION_ADAPTER = TypeAdapter(Decision)


class Limits(Model):
    # May only be lowered. Recursion limit 32 is a separate graph safety backstop.
    planner_decisions: int = Field(default=4, ge=1, le=4, strict=True)
    lookup_attempts: int = Field(default=4, ge=1, le=4, strict=True)
    elapsed_seconds: float = Field(default=120, gt=0, le=120, allow_inf_nan=False)
    operational_characters: int = Field(default=24000, ge=1, le=24000, strict=True)


class KBReference(Model):
    kind: Literal['kb_chunk'] = 'kb_chunk'
    chunk_id: str


class ObservationReference(Model):
    kind: Literal['operational_observation'] = 'operational_observation'
    lookup_id: str


EvidenceReference = Annotated[KBReference | ObservationReference, Field(discriminator='kind')]


class KBEvidence(Model):
    reference: KBReference
    result: SearchResult


class AccountObservation(Model):
    tool: Literal['get_employee_account_status']
    result: EmployeeAccountResult


class DevicesObservation(Model):
    tool: Literal['get_employee_devices']
    result: EmployeeDevicesResult


class DeviceObservation(Model):
    tool: Literal['get_device_details']
    result: DeviceDetailsResult


class EntitlementObservation(Model):
    tool: Literal['check_software_entitlement']
    result: SoftwareEntitlementResult


class TicketsObservation(Model):
    tool: Literal['get_recent_support_tickets']
    result: RecentTicketsResult


class IncidentsObservation(Model):
    tool: Literal['get_active_service_incidents']
    result: ActiveIncidentsResult


ObservationData = Annotated[
    AccountObservation | DevicesObservation | DeviceObservation | EntitlementObservation | TicketsObservation | IncidentsObservation,
    Field(discriminator='tool'),
]


class OperationalEvidence(Model):
    reference: ObservationReference
    observation: ObservationData


class LookupOutcome(Model):
    lookup_id: str
    # Unknown/unvalidated proposals are not echoed into output or logs.
    tool: ToolName | None
    arguments: dict | None
    executed: bool
    status: Literal['ok', 'not_found', 'blocked', 'duplicate', 'error', 'rejected']
    code: str | None = None
    evidence: ObservationReference | None = None


class RunError(Model):
    stage: Literal['classification', 'retrieval', 'planner', 'guard', 'lookup', 'assembly', 'budget']
    code: str


class TraceEvent(Model):
    node: Literal['validate', 'classify', 'retrieve', 'plan', 'guard', 'execute', 'assemble']
    outcome: str
    lookup_id: str | None = None


class InvestigationResult(Model):
    phase: Literal['4A', '4B.1'] = '4A'
    status: Literal['completed', 'partial', 'failed']
    stop_reason: str
    started_at: AwareDatetime
    finished_at: AwareDatetime
    classification: TicketClassification | None
    kb_evidence: list[KBEvidence]
    operational_evidence: list[OperationalEvidence]
    lookup_trace: list[LookupOutcome]
    graph_trace: list[TraceEvent]
    errors: list[RunError]
    missing_fields: list[str]
    planner_decisions: int
    lookup_attempts: int
    human_review_required: Literal[True] = True
    mutating_actions_executed: Literal[False] = False
    synthesis_status: Literal['not_run'] = 'not_run'
    recommendation: None = None

    @model_validator(mode='after')
    def valid_references(self) -> Self:
        ids = [e.reference.lookup_id for e in self.operational_evidence]
        chunk_ids = [e.reference.chunk_id for e in self.kb_evidence]
        if len(ids) != len(set(ids)) or len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError('Duplicate evidence references.')
        if any(e.reference.chunk_id != e.result.chunk.chunk_id for e in self.kb_evidence):
            raise ValueError('KB reference mismatch.')
        linked = [t.evidence.lookup_id for t in self.lookup_trace if t.evidence]
        if sorted(linked) != sorted(ids):
            raise ValueError('Observation references must resolve to recorded lookups.')
        for item in self.lookup_trace:
            if item.evidence and (not item.executed or item.status not in ('ok', 'not_found')):
                raise ValueError('Only validated lookup results are evidence.')
            if item.evidence:
                observation = next(e.observation for e in self.operational_evidence if e.reference == item.evidence)
                if observation.tool != item.tool or observation.result.status != item.status:
                    raise ValueError('Lookup and observation mismatch.')
        if self.lookup_attempts != sum(t.executed for t in self.lookup_trace):
            raise ValueError('Lookup attempt count mismatch.')
        return self
