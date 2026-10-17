"""Structural guarantees; these models cannot establish semantic groundedness."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.kb.schemas import SearchResult

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
ChunkID = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class RecommendationStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    step_type: Literal["troubleshooting", "escalation"] = Field(description=
        "Escalation for every documented report, contact, permission or approval request to a "
        "support team, Security or owner, even when initiated by the employee. Troubleshooting "
        "for local checks/actions with no such handoff. Conditional handoffs require a reported trigger.")
    action: Text = Field(description=
        "One action from the branch matching reported symptoms, with its conditions, approvals and identity checks. "
        "No hypothetical future escalation, repeated completed check, invented repair method or promised approval. "
        "Do not mix a local check with a handoff.")
    supporting_chunk_ids: list[ChunkID] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_citations(self) -> Self:
        if len(set(self.supporting_chunk_ids)) != len(self.supporting_chunk_ids):
            raise ValueError("Step citations must be unique.")
        return self


class SupportRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["supported", "insufficient_evidence"]
    summary: Text = Field(description=
        "Briefly state what the ticket reports, not verified diagnoses or promised outcomes. "
        "Do not infer a repair procedure from routing advice. On abstention say escalation need is undetermined.")
    steps: list[RecommendationStep] = Field(max_length=6)
    missing_information: list[Text] = Field(max_length=5, description=
        "Missing context to choose or enable a documented route, or a gap in available documentation. "
        "Do not ask the user to supply the policy answer they requested or any password/MFA code.")
    escalation_required: bool = Field(description=
        "True exactly when a documented handoff/report/permission request is recommended as an escalation step. "
        "False on insufficient evidence means undetermined, not safe or unnecessary.")
    escalation_reason: Text | None = Field(description=
        "When escalating, name the documented trigger actually reported by the ticket. Do not claim "
        "that a future retry failed or a repair method is documented when it is not. Otherwise null.")

    @model_validator(mode="after")
    def consistent_status_and_escalation(self) -> Self:
        if (self.status == "supported") != bool(self.steps):
            raise ValueError("Supported recommendations need steps; abstentions must have none.")
        has_escalation = any(step.step_type == "escalation" for step in self.steps)
        if self.escalation_required != has_escalation:
            raise ValueError("Escalation flag must match the presence of a cited escalation step.")
        if self.escalation_required != (self.escalation_reason is not None):
            raise ValueError("Only a documented escalation needs a nonblank reason.")
        return self


class RecommendationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation: SupportRecommendation
    evidence: list[SearchResult]
