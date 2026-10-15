"""The embedding contract, with validation shared by ingestion and search."""

import math
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class EmbeddingError(RuntimeError):
    pass


class EmbeddingSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    dimensions: int = Field(gt=0)


class EmbeddingProvider(Protocol):
    spec: EmbeddingSpec

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def validate_vectors(vectors: list[list[float]], count: int, dimensions: int) -> None:
    if len(vectors) != count:
        raise EmbeddingError("Embedding response count does not match the input count.")
    for vector in vectors:
        if len(vector) != dimensions:
            raise EmbeddingError("Embedding dimension mismatch.")
        if not all(math.isfinite(value) for value in vector) or not any(vector):
            raise EmbeddingError("Embeddings must be finite, nonzero vectors.")
