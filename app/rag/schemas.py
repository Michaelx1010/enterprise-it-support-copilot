"""Structural guarantees; these models cannot establish semantic groundedness."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.kb.schemas import SearchResult

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
ChunkID = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class RecommendationStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    step_type: Literal["troubleshooting", "escalation"]
    action: Text
    supporting_chunk_ids: list[ChunkID] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_citations(self) -> Self:
        if len(set(self.supporting_chunk_ids)) != len(self.supporting_chunk_ids):
            raise ValueError("Step citations must be unique.")
        return self


class SupportRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["supported", "insufficient_evidence"]
    summary: Text
    steps: list[RecommendationStep] = Field(max_length=6)
    missing_information: list[Text] = Field(max_length=5)
    escalation_required: bool
    escalation_reason: Text | None

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
