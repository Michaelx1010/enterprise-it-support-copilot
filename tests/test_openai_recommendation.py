"""Real SDK parsing via offline HTTP; no model calls or secrets."""

import json

import httpx
from openai import OpenAI
import pytest

from app.providers.openai_recommendation import OpenAIRecommendation
from app.providers.recommendation import RecommendationError


def response_body(payload, *, status="completed", refusal=False, empty=False, raw_text=None):
    content = {"type": "refusal", "refusal": "Cannot comply."} if refusal else {
        "type": "output_text", "annotations": [],
        "text": raw_text if raw_text is not None else json.dumps(payload),
    }
    return {
        "id": "resp_fixture", "object": "response", "created_at": 0, "model": "test-model",
        "status": status,
        "output": [] if empty else [{"id": "msg_fixture", "type": "message", "role": "assistant",
                                     "status": "completed", "content": [content]}],
        "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
        "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
    }


def make_client(handler):
    return OpenAI(api_key="test-placeholder", max_retries=0,
                  http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_sdk_strict_schema_and_parse(recommendation_payload):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response_body(recommendation_payload))

    with make_client(handler) as client:
        result = OpenAIRecommendation(client).generate(instructions="Rules", payload="Evidence")
    assert result.steps[0].step_type == "troubleshooting"
    request = requests[0]
    assert request["store"] is False
    assert "tools" not in request
    assert request["input"] == [{"role": "system", "content": "Rules"},
                                {"role": "user", "content": "Evidence"}]
    output_format = request["text"]["format"]
    assert output_format["strict"] is True
    schema = output_format["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(recommendation_payload)
    assert schema["$defs"]["RecommendationStep"]["properties"]["step_type"]["enum"] == [
        "troubleshooting", "escalation"]


@pytest.mark.parametrize("options,code", [
    ({"refusal": True}, "refusal"),
    ({"empty": True}, "missing_output"),
    ({"status": "incomplete"}, "incomplete"),
    ({"raw_text": '{"status":'}, "invalid_output"),
    ({"raw_text": '{}'}, "invalid_output"),
])
def test_unusable_responses(recommendation_payload, options, code):
    body = response_body(recommendation_payload, **options)
    with make_client(lambda request: httpx.Response(200, json=body)) as client:
        with pytest.raises(RecommendationError) as error:
            OpenAIRecommendation(client).generate(instructions="Rules", payload="Evidence")
    assert error.value.code == code


def test_missing_citations_rejected_by_sdk(recommendation_payload):
    recommendation_payload["steps"][0]["supporting_chunk_ids"] = []
    with make_client(lambda request: httpx.Response(200, json=response_body(recommendation_payload))) as client:
        with pytest.raises(RecommendationError) as error:
            OpenAIRecommendation(client).generate(instructions="Rules", payload="Evidence")
    assert error.value.code == "invalid_output"
    assert error.value.validation_types == ["too_short"]


@pytest.mark.parametrize("status", [401, 429, 500])
def test_provider_errors_are_sanitized(status):
    body = {"error": {"message": "sensitive content", "type": "invalid_request_error"}}
    with make_client(lambda request: httpx.Response(status, json=body)) as client:
        with pytest.raises(RecommendationError) as error:
            OpenAIRecommendation(client).generate(instructions="Rules", payload="Evidence")
    assert error.value.code == "provider_failure"
    assert "sensitive" not in str(error.value)


def test_connection_failure():
    def handler(request):
        raise httpx.ConnectError("private address", request=request)

    with make_client(handler) as client:
        with pytest.raises(RecommendationError) as error:
            OpenAIRecommendation(client).generate(instructions="Rules", payload="Evidence")
    assert "private address" not in str(error.value)


def test_missing_key_and_independent_model_setting(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="Set OPENAI_API_KEY"):
        OpenAIRecommendation.from_environment()
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")
    monkeypatch.setenv("OPENAI_MODEL", "classification-model")
    monkeypatch.setenv("OPENAI_RECOMMENDATION_MODEL", "recommendation-model")
    provider = OpenAIRecommendation.from_environment()
    try:
        assert provider.model == "recommendation-model"
    finally:
        provider.client.close()
