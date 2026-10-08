import pytest
from pydantic import ValidationError

from app.schemas import TicketClassification


def test_valid_classification_is_normalized_and_serializable():
    result = TicketClassification(category="Network", priority="High", summary="  VPN is unavailable.  ")
    assert result.model_dump() == {
        "category": "Network", "priority": "High", "summary": "VPN is unavailable.",
    }


@pytest.mark.parametrize("change", [
    {"category": "Other"}, {"priority": "Critical"}, {"summary": " \n "},
    {"summary": "x" * 401}, {"confidence": 0.9},
])
def test_invalid_classifications_are_rejected(change):
    payload = {"category": "Network", "priority": "High", "summary": "VPN is unavailable."}
    with pytest.raises(ValidationError):
        TicketClassification.model_validate(payload | change)
