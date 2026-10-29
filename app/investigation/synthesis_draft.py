"""Versioned model-facing drafts; current escalation derives only from typed steps."""

from copy import deepcopy
from typing import Literal, Self

from pydantic import model_validator
from pydantic_core import PydanticCustomError

from app.investigation.schemas import (
    CitedStatement, ConditionalGuidanceEntries, InvestigationStep, InvestigationSynthesis, TriggerBasis,
)
from app.operations.records import Model
from app.rag.schemas import Text

DRAFT_VERSION = 'investigation-synthesis-draft-v1'
CURRENT_DRAFT_VERSION = 'investigation-synthesis-draft-v3'


class InvestigationSynthesisDraftV1(Model):
    schema_version: Literal['investigation-synthesis-draft-v1']
    # Reuse the canonical field constraints/descriptions without inheriting its
    # independently supplied Boolean or changing its public JSON Schema.
    status: Literal['supported', 'insufficient_evidence'] = deepcopy(InvestigationSynthesis.model_fields['status'])
    summary: CitedStatement = deepcopy(InvestigationSynthesis.model_fields['summary'])
    findings: list[CitedStatement] = deepcopy(InvestigationSynthesis.model_fields['findings'])
    steps: list[InvestigationStep] = deepcopy(InvestigationSynthesis.model_fields['steps'])
    missing_information: list[Text] = deepcopy(InvestigationSynthesis.model_fields['missing_information'])
    uncertainties: list[CitedStatement] = deepcopy(InvestigationSynthesis.model_fields['uncertainties'])
    escalation_reason: CitedStatement | None = deepcopy(InvestigationSynthesis.model_fields['escalation_reason'])

    def to_canonical(self) -> InvestigationSynthesis:
        fields = self.model_dump(exclude={'schema_version'})
        fields['escalation_required'] = any(step.step_type == 'escalation' for step in self.steps)
        # No relabeling, reason removal, status repair or inference from prose.
        return InvestigationSynthesis.model_validate(fields)

    @model_validator(mode='after')
    def valid_canonical_contract(self) -> Self:
        self.to_canonical()
        return self


class InvestigationSynthesisDraftV2(InvestigationSynthesisDraftV1):
    schema_version: Literal['investigation-synthesis-draft-v2']
    # Required at the SDK boundary; [] explicitly means no future guidance.
    conditional_guidance: ConditionalGuidanceEntries


class InvestigationSynthesisDraftV3(InvestigationSynthesisDraftV2):
    schema_version: Literal['investigation-synthesis-draft-v3']
    trigger_basis: TriggerBasis  # Required key, nullable only without current escalation.

    def to_canonical(self) -> InvestigationSynthesis:
        report = super().to_canonical()
        # V1/V2 and canonical archives keep their legacy default; live V3 never does.
        if report.escalation_required and report.trigger_basis is None:
            raise PydanticCustomError('escalation_trigger_mismatch', 'Current escalation requires a trigger basis in draft V3.')
        return report
