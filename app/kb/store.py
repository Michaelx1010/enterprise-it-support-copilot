"""Small PostgreSQL store; exact cosine search and atomic full replacement."""

from contextlib import contextmanager
import hashlib
from importlib.resources import files
import os

from pgvector import Vector
from pgvector.psycopg import register_vector
import psycopg
from psycopg.rows import dict_row

from app.kb.schemas import Chunk, SearchResult
from app.providers.embeddings import EmbeddingSpec, validate_vectors

DIMENSIONS = 1536


class PgvectorStore:
    def __init__(self, database_url: str) -> None:
        if not database_url.strip():
            raise ValueError("Set DATABASE_URL locally before using the knowledge base.")
        self.database_url = database_url

    @classmethod
    def from_environment(cls) -> "PgvectorStore":
        return cls(os.getenv("DATABASE_URL", ""))

    def initialize(self) -> None:
        with psycopg.connect(self.database_url, connect_timeout=10) as conn:
            conn.execute(files("app.kb").joinpath("schema.sql").read_text())

    @contextmanager
    def _connection(self):
        with psycopg.connect(self.database_url, autocommit=True, connect_timeout=10,
                             row_factory=dict_row) as conn:
            register_vector(conn)
            yield conn

    def replace(self, chunks: list[Chunk], vectors: list[list[float]], spec: EmbeddingSpec) -> None:
        if not chunks:
            raise ValueError("Refusing to replace the index with an empty corpus.")
        if spec.dimensions != DIMENSIONS:
            raise ValueError("Database schema requires 1536-dimensional embeddings.")
        validate_vectors(vectors, len(chunks), DIMENSIONS)
        rows = [tuple(chunk.model_dump().values()) + (spec.provider, spec.model, Vector(vector))
                for chunk, vector in zip(chunks, vectors, strict=True)]
        with self._connection() as conn, conn.transaction():
            # Serialize ingestions, while existing readers can still use the old snapshot.
            conn.execute("LOCK TABLE kb_chunks IN EXCLUSIVE MODE")
            conn.execute("DELETE FROM kb_chunks")
            with conn.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO kb_chunks
                    (chunk_id, document_id, source_path, title, section_id, section_path,
                     chunk_index, content, content_hash, embedding_provider, embedding_model, embedding)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows,
                )

    def manifest(self) -> dict:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT chunk_id, section_id, embedding_provider, embedding_model "
                "FROM kb_chunks ORDER BY chunk_id"
            ).fetchall()
        if not rows:
            raise ValueError("Knowledge-base index is empty; run kb ingest first.")
        specs = {(row["embedding_provider"], row["embedding_model"]) for row in rows}
        if len(specs) != 1:
            raise ValueError("Index contains mixed embedding models; re-ingest the corpus.")
        provider, model = specs.pop()
        return {
            "chunks": len(rows), "section_ids": sorted({row["section_id"] for row in rows}),
            "corpus_hash": hashlib.sha256("\n".join(row["chunk_id"] for row in rows).encode()).hexdigest(),
            "embedding": EmbeddingSpec(provider=provider, model=model, dimensions=DIMENSIONS).model_dump(),
        }

    def search(self, vector: list[float], spec: EmbeddingSpec, top_k: int) -> list[SearchResult]:
        if not 1 <= top_k <= 50:
            raise ValueError("top_k must be between 1 and 50.")
        if spec.dimensions != DIMENSIONS:
            raise ValueError("Query embedding dimensions do not match the database.")
        validate_vectors([vector], 1, DIMENSIONS)
        with self._connection() as conn, conn.transaction():
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            stored = conn.execute(
                "SELECT DISTINCT embedding_provider, embedding_model FROM kb_chunks"
            ).fetchall()
            if not stored:
                raise ValueError("Knowledge-base index is empty; run kb ingest first.")
            if len(stored) != 1 or stored[0] != {
                "embedding_provider": spec.provider, "embedding_model": spec.model,
            }:
                raise ValueError("Query and index embedding models differ; re-ingest before searching.")
            rows = conn.execute(
                """SELECT chunk_id, document_id, source_path, title, section_id,
                          section_path, chunk_index, content, content_hash,
                          embedding <=> %s AS distance
                   FROM kb_chunks ORDER BY distance, chunk_id LIMIT %s""",
                (Vector(vector), top_k),
            ).fetchall()
        return [SearchResult(distance=row.pop("distance"), chunk=Chunk(**row)) for row in rows]
