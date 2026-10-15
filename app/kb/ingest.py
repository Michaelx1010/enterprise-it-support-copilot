from pathlib import Path

from app.kb.documents import CHUNKER_VERSION, load_chunks
from app.kb.store import DIMENSIONS, PgvectorStore
from app.providers.embeddings import EmbeddingProvider, validate_vectors


def ingest(root: Path, *, embedder: EmbeddingProvider, store: PgvectorStore) -> dict:
    chunks = load_chunks(root)
    if embedder.spec.dimensions != DIMENSIONS:
        raise ValueError("Database schema requires 1536-dimensional embeddings.")
    vectors = []
    for start in range(0, len(chunks), 32):
        batch = [chunk.embedding_text() for chunk in chunks[start:start + 32]]
        result = embedder.embed(batch)
        validate_vectors(result, len(batch), embedder.spec.dimensions)
        vectors.extend(result)
    # Nothing in the existing index changes until all embedding calls succeed.
    store.replace(chunks, vectors, embedder.spec)
    return {"documents": len({chunk.document_id for chunk in chunks}), "chunks": len(chunks),
            "chunker_version": CHUNKER_VERSION, "embedding": embedder.spec.model_dump()}
