"""Small manually labelled next-decision cases; no model calls or runtime routing.

Ratings apply only to a case's recorded context. Unlisted choices need review.
Passing mocked tests validates the evaluator, not live planner quality.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from app.investigation.planner import PlannerResponse
from app.investigation.schemas import Decision, InvestigationRequest, InvestigationResult, LookupDecision
from app.operations.records import Model


Rating = Literal['preferred', 'redundant', 'unnecessary', 'premature_finish', 'budget_risk']


def decision_key(decision: dict) -> str:
    # Use the real structured decision contract, including tool argument types.
    value = PlannerResponse.model_validate({'decision': decision}).graph_decision()
    return json.dumps(value, sort_keys=True)


class Candidate(Model):
    decision: Decision
    rating: Rating
    review_notes: str = Field(min_length=1)


class EfficiencyCase(Model):
    id: str = Field(min_length=1)
    request: InvestigationRequest
    prior_lookups: list[LookupDecision] = Field(max_length=3)
    required_evidence: list[LookupDecision] = Field(min_length=1)
    candidates: list[Candidate] = Field(min_length=2)
    review_notes: str = Field(min_length=1)

    @model_validator(mode='after')
    def valid_case(self):
        choices = [decision_key(c.decision.model_dump(mode='json')) for c in self.candidates]
        for decision in self.prior_lookups + self.required_evidence:
            decision_key(decision.model_dump(mode='json'))
        if len(choices) != len(set(choices)) or not any(c.rating == 'preferred' for c in self.candidates):
            raise ValueError('Cases require distinct choices and at least one preferred choice.')
        return self


def load_cases(path: Path = Path('evaluation/planner_efficiency.jsonl')) -> list[EfficiencyCase]:
    cases = [EfficiencyCase.model_validate_json(line)
             for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not cases or len({c.id for c in cases}) != len(cases):
        raise ValueError('Efficiency cases must be nonempty with unique IDs.')
    return cases


def rate_choice(case: EfficiencyCase, decision: dict) -> str:
    key = decision_key(decision)
    for candidate in case.candidates:
        if key == decision_key(candidate.decision.model_dump(mode='json')):
            return candidate.rating
    return 'unreviewed'  # Never assume an unlabelled choice is good or bad.


def evidence_coverage(case: EfficiencyCase, result: InvestigationResult) -> dict:
    """Count requested lookups with validated observations, not resolution or truth.

    Labels are manual per-case expectations. Missing/error/blocked lookups do not
    count; a validated not_found observation does, as recorded negative evidence.
    Tool names alone cannot establish coverage of the requested entity.
    """
    expected = {decision_key(d.model_dump(mode='json')) for d in case.required_evidence}
    observed = {decision_key({'kind': 'lookup', 'tool': t.tool, 'arguments': t.arguments})
                for t in result.lookup_trace if t.executed and t.evidence is not None}
    covered = len(expected & observed)
    return {'covered': covered, 'expected': len(expected), 'ratio': covered / len(expected)}
