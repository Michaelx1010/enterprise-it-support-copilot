"""One-method boundary for recommendation providers, without retrieval logic."""

from typing import Protocol

from app.rag.schemas import SupportRecommendation


class RecommendationError(RuntimeError):
    def __init__(self, message: str, *, code: str = "provider_failure",
                 validation_types: list[str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        # Error types only: never keep raw model output, validation inputs, or API bodies.
        self.validation_types = validation_types or []


class RecommendationProvider(Protocol):
    def generate(self, *, instructions: str, payload: str) -> SupportRecommendation: ...
