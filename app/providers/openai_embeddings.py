"""OpenAI embedding configuration and SDK response handling."""

import os

from openai import APIError, OpenAI

from app.providers.embeddings import EmbeddingError, EmbeddingSpec, validate_vectors


class OpenAIEmbeddings:
    def __init__(self, client: OpenAI, model: str = "text-embedding-3-small") -> None:
        if not model.strip():
            raise ValueError("OPENAI_EMBEDDING_MODEL must not be blank.")
        self.client = client
        self.spec = EmbeddingSpec(provider="openai", model=model, dimensions=1536)

    @classmethod
    def from_environment(cls) -> "OpenAIEmbeddings":
        # Credentials are used by the SDK, never returned, logged, or inspected.
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            raise ValueError("Set OPENAI_API_KEY locally before requesting embeddings.")
        return cls(OpenAI(timeout=30, max_retries=2),
                   os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"))

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("Embedding input must contain nonblank text.")
        try:
            response = self.client.embeddings.create(
                model=self.spec.model, input=texts,
                dimensions=self.spec.dimensions, encoding_format="float",
            )
        except APIError as exc:
            raise EmbeddingError(
                f"OpenAI embeddings failed ({type(exc).__name__}); check local "
                "credentials, connectivity, model access, and quota."
            ) from exc
        ordered = sorted(response.data, key=lambda item: item.index)
        if [item.index for item in ordered] != list(range(len(texts))):
            raise EmbeddingError("Embedding response indices are missing or duplicated.")
        vectors = [item.embedding for item in ordered]
        validate_vectors(vectors, len(texts), self.spec.dimensions)
        return vectors
