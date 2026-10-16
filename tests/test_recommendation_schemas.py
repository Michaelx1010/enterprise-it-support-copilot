import pytest
from pydantic import ValidationError

from app.rag.schemas import SupportRecommendation


def test_documented_escalation_can_be_supported_without_resolution(recommendation_payload):
    recommendation_payload.update(escalation_required=True, escalation_reason="Persistent gateway errors.")
    recommendation_payload["steps"][0].update(step_type="escalation", action="Contact Network Support.")
    result = SupportRecommendation.model_validate(recommendation_payload)
    assert result.status == "supported"
    assert result.escalation_required


@pytest.mark.parametrize("change", [
    {"status": "supported", "steps": []},
    {"status": "insufficient_evidence"},
    {"summary": " "},
    {"summary": "x" * 601},
    {"extra": "not permitted"},
    {"escalation_required": True, "escalation_reason": "Reason without escalation step"},
    {"escalation_reason": "Reason while flag is false"},
    {"missing_information": [" "]},
    {"missing_information": ["Question?"] * 6},
    {"escalation_required": "false"},
])
def test_invalid_recommendation_shapes(recommendation_payload, change):
    with pytest.raises(ValidationError):
        SupportRecommendation.model_validate(recommendation_payload | change)


@pytest.mark.parametrize("change", [
    {"supporting_chunk_ids": []},
    {"supporting_chunk_ids": [" "]},
    {"supporting_chunk_ids": ["vpn-chunk-1", "vpn-chunk-1"]},
    {"step_type": "tool"},
    {"step_type": "escalation"},  # Flag false is inconsistent.
    {"action": " "},
    {"unexpected": "field"},
])
def test_invalid_steps(recommendation_payload, change):
    recommendation_payload["steps"][0].update(change)
    with pytest.raises(ValidationError):
        SupportRecommendation.model_validate(recommendation_payload)


def test_missing_citation_field_is_invalid(recommendation_payload):
    del recommendation_payload["steps"][0]["supporting_chunk_ids"]
    with pytest.raises(ValidationError):
        SupportRecommendation.model_validate(recommendation_payload)


@pytest.mark.parametrize("reason", [None, " "])
def test_escalation_requires_reason(recommendation_payload, reason):
    recommendation_payload["steps"][0]["step_type"] = "escalation"
    recommendation_payload.update(escalation_required=True, escalation_reason=reason)
    with pytest.raises(ValidationError):
        SupportRecommendation.model_validate(recommendation_payload)


def test_insufficient_evidence_has_no_actions(recommendation_payload):
    recommendation_payload.update(status="insufficient_evidence", steps=[])
    assert not SupportRecommendation.model_validate(recommendation_payload).escalation_required


def test_too_many_steps_rejected(recommendation_payload):
    recommendation_payload["steps"] *= 7
    with pytest.raises(ValidationError):
        SupportRecommendation.model_validate(recommendation_payload)
