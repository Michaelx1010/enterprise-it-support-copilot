"""Retrieval never calls classification or answer generation."""

from app.kb.schemas import SearchResult
from app.kb.store import PgvectorStore
from app.providers.embeddings import EmbeddingProvider, validate_vectors


def search(query: str, *, embedder: EmbeddingProvider, store: PgvectorStore,
           top_k: int = 3) -> list[SearchResult]:
    query = query.strip()
    if not query or len(query) > 6000:
        raise ValueError("Search query must contain 1–6000 characters.")
    if not 1 <= top_k <= 50:
        raise ValueError("top_k must be between 1 and 50.")
    manifest = store.manifest()
    if manifest["embedding"] != embedder.spec.model_dump():
        raise ValueError("Query and index embedding models differ; re-ingest before searching.")
    vectors = embedder.embed([query])
    validate_vectors(vectors, 1, embedder.spec.dimensions)
    return store.search(vectors[0], embedder.spec, top_k)
