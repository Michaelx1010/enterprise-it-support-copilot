"""OpenAI Structured Outputs adapter; no retrieval or classification coupling."""

import os

from openai import APIError, OpenAI
from pydantic import ValidationError

from app.providers.recommendation import RecommendationError
from app.rag.schemas import SupportRecommendation

DEFAULT_MODEL = "gpt-4.1-mini-2025-04-14"
MAX_OUTPUT_TOKENS = 2500
TEMPERATURE = 0


class OpenAIRecommendation:
    def __init__(self, client: OpenAI, *, model: str = DEFAULT_MODEL) -> None:
        if not model.strip():
            raise ValueError("Recommendation model must not be blank.")
        self.client = client
        self.model = model

    @classmethod
    def from_environment(cls) -> "OpenAIRecommendation":
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise ValueError("Set OPENAI_API_KEY before generating recommendations.")
        return cls(OpenAI(api_key=api_key, timeout=30.0, max_retries=2),
                   model=os.getenv("OPENAI_RECOMMENDATION_MODEL", DEFAULT_MODEL))

    def generate(self, *, instructions: str, payload: str) -> SupportRecommendation:
        try:
            response = self.client.responses.parse(
                model=self.model,
                input=[{"role": "system", "content": instructions},
                       {"role": "user", "content": payload}],
                text_format=SupportRecommendation,
                max_output_tokens=MAX_OUTPUT_TOKENS, temperature=TEMPERATURE, store=False,
            )
        except APIError as exc:
            raise RecommendationError("OpenAI recommendation request failed; check model access, "
                                      "credentials, quota, and connectivity.") from exc
        except ValidationError as exc:
            raise RecommendationError(
                "OpenAI returned an invalid recommendation.", code="invalid_output",
                validation_types=sorted({error["type"] for error in exc.errors(include_input=False)}),
            ) from exc
        if response.status != "completed":
            raise RecommendationError("OpenAI recommendation was not completed.", code="incomplete")
        for item in response.output:
            if item.type == "message" and any(content.type == "refusal" for content in item.content):
                raise RecommendationError("OpenAI refused this recommendation.", code="refusal")
        if response.output_parsed is None:
            raise RecommendationError("OpenAI returned no structured recommendation.", code="missing_output")
        return response.output_parsed
