"""OpenAI configuration, SDK calls, and response handling stay in this adapter."""

import os

from openai import APIError, OpenAI
from pydantic import ValidationError

from app.providers.base import ClassificationError
from app.schemas import TicketClassification

DEFAULT_MODEL = "gpt-4.1-mini-2025-04-14"


class OpenAIProvider:
    def __init__(self, client: OpenAI, *, model: str = DEFAULT_MODEL) -> None:
        if not model.strip():
            raise ValueError("OpenAI model must not be blank.")
        self.client = client
        self.model = model

    @classmethod
    def from_environment(cls) -> "OpenAIProvider":
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise ValueError("Set OPENAI_API_KEY before classifying a ticket.")
        return cls(
            OpenAI(api_key=api_key, timeout=30.0, max_retries=2),
            model=os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
        )

    def generate(self, *, instructions: str, ticket_text: str) -> TicketClassification:
        try:
            response = self.client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": ticket_text},
                ],
                text_format=TicketClassification,
                max_output_tokens=500,
                store=False,
            )
        except APIError as exc:
            # Avoid displaying raw responses, which may contain ticket content.
            raise ClassificationError(
                f"OpenAI request failed ({type(exc).__name__}); check credentials, "
                "model access, quota, and connectivity."
            ) from exc
        except ValidationError as exc:
            raise ClassificationError("OpenAI returned an invalid classification.") from exc

        if response.status != "completed":
            raise ClassificationError(
                f"OpenAI response was not completed (status: {response.status})."
            )
        for item in response.output:
            if item.type == "message":
                for content in item.content:
                    if content.type == "refusal":
                        raise ClassificationError("OpenAI refused to classify this ticket.")
        if response.output_parsed is None:
            raise ClassificationError("OpenAI returned no structured classification.")
        return response.output_parsed
