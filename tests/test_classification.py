import json

import pytest
from pydantic import ValidationError

from app.classification import classify_ticket
from app.providers.base import ClassificationError
from app.schemas import TicketClassification


class FakeProvider:
    def __init__(self):
        self.calls = []
        self.result = TicketClassification(category="Network", priority="High", summary="VPN is down.")

    def generate(self, *, instructions: str, ticket_text: str) -> TicketClassification:
        self.calls.append((instructions, ticket_text))
        return self.result


def test_classifies_with_a_provider_that_has_no_openai_dependency():
    provider = FakeProvider()
    result = classify_ticket(" VPN issue ", "Cannot connect.", provider=provider)
    assert result == provider.result
    assert len(provider.calls) == 1
    assert json.loads(provider.calls[0][1]) == {
        "subject": "VPN issue", "description": "Cannot connect.",
    }


@pytest.mark.parametrize("subject,description", [(" ", "Details"), ("Subject", "\n")])
def test_blank_input_never_calls_provider(subject, description):
    provider = FakeProvider()
    with pytest.raises(ValidationError):
        classify_ticket(subject, description, provider=provider)
    assert provider.calls == []


def test_unchecked_provider_output_cannot_bypass_validation():
    provider = FakeProvider()
    provider.result = TicketClassification.model_construct(
        category="Other", priority="High", summary="Invalid label."
    )
    with pytest.raises(ClassificationError, match="invalid classification"):
        classify_ticket("Subject", "Details", provider=provider)
