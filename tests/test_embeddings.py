import json

import httpx
from openai import OpenAI
import pytest

from app.providers.embeddings import EmbeddingError, validate_vectors
from app.providers.openai_embeddings import OpenAIEmbeddings


def test_sdk_request_and_response_order():
    requests = []
    vector = [1.0] + [0.0] * 1535

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "object": "list", "model": "text-embedding-3-small",
            "data": [{"object": "embedding", "index": 1, "embedding": [-v for v in vector]},
                     {"object": "embedding", "index": 0, "embedding": vector}],
            "usage": {"prompt_tokens": 5, "total_tokens": 5},
        })

    with OpenAI(api_key="test-placeholder", http_client=httpx.Client(
        transport=httpx.MockTransport(handler)), max_retries=0,
    ) as client:
        result = OpenAIEmbeddings(client).embed(["First", "Second"])
    assert result[0] == vector
    assert result[1][0] == -1
    assert requests[0]["dimensions"] == 1536
    assert requests[0]["encoding_format"] == "float"


@pytest.mark.parametrize("vectors,count,dimensions", [
    ([], 1, 2), ([[1.0]], 1, 2), ([[float("nan"), 1]], 1, 2),
    ([[float("inf"), 1]], 1, 2), ([[0, 0]], 1, 2),
])
def test_bad_vectors_are_rejected(vectors, count, dimensions):
    with pytest.raises(EmbeddingError):
        validate_vectors(vectors, count, dimensions)


def test_failure_does_not_expose_credentials_or_response():
    with OpenAI(api_key="test-placeholder", max_retries=0, http_client=httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(
            401, json={"error": {"message": "sensitive provider response"}},
        )),
    )) as client:
        with pytest.raises(EmbeddingError, match="AuthenticationError") as failure:
            OpenAIEmbeddings(client).embed(["Text"])
    assert "sensitive" not in str(failure.value)


def test_missing_key_is_actionable(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        OpenAIEmbeddings.from_environment()
