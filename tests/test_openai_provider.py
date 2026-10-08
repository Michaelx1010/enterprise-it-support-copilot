"""Exercise the real SDK serialization/parser with an offline HTTP transport."""

import json

import httpx
from openai import OpenAI
import pytest

from app.providers.base import ClassificationError
from app.providers.openai import OpenAIProvider


def response_body(payload=None, *, status="completed", refusal=False):
    content = (
        {"type": "refusal", "refusal": "Cannot comply."}
        if refusal else {
            "type": "output_text", "annotations": [],
            "text": json.dumps(payload or {
                "category": "Network", "priority": "High", "summary": "VPN is unavailable.",
            }),
        }
    )
    return {
        "id": "resp_test", "object": "response", "created_at": 0,
        "model": "test-model", "status": status,
        "output": [{"id": "msg_test", "type": "message", "role": "assistant",
                    "status": "completed", "content": [content]}],
        "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
        "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
    }


def make_client(handler):
    return OpenAI(
        api_key="test-placeholder", max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_sdk_sends_strict_schema_and_parses_output():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response_body())

    with make_client(handler) as client:
        result = OpenAIProvider(client, model="test-model").generate(
            instructions="Classify the ticket.", ticket_text="VPN failure",
        )
    assert result.category == "Network"
    assert result.priority == "High"
    request = requests[0]
    assert request["model"] == "test-model"
    assert request["store"] is False
    output_format = request["text"]["format"]
    assert output_format["type"] == "json_schema"
    assert output_format["strict"] is True
    schema = output_format["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"category", "priority", "summary"}
    assert len(schema["properties"]["category"]["enum"]) == 11


@pytest.mark.parametrize("body,error", [
    (response_body(refusal=True), "refused"),
    (response_body(status="incomplete"), "not completed"),
    (response_body() | {"output": []}, "no structured"),
    (response_body({"category": "Other", "priority": "High", "summary": "Issue."}), "invalid"),
    (response_body({"category": "Network", "priority": "High", "summary": "  "}), "invalid"),
])
def test_unusable_model_responses_fail_explicitly(body, error):
    with make_client(lambda request: httpx.Response(200, json=body)) as client:
        with pytest.raises(ClassificationError, match=error):
            OpenAIProvider(client).generate(instructions="Classify", ticket_text="Ticket")


def test_api_failure_is_wrapped_without_exposing_response_body():
    body = {"error": {"message": "sensitive ticket content", "type": "invalid_request_error"}}
    with make_client(lambda request: httpx.Response(401, json=body)) as client:
        with pytest.raises(ClassificationError, match="AuthenticationError") as error:
            OpenAIProvider(client).generate(instructions="Classify", ticket_text="Ticket")
    assert "sensitive ticket content" not in str(error.value)


def test_missing_key_fails_before_network_access(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="Set OPENAI_API_KEY"):
        OpenAIProvider.from_environment()
