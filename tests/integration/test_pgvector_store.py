"""Actual PostgreSQL/pgvector tests; never run against the application database."""

import os

import psycopg
from psycopg.conninfo import conninfo_to_dict
import pytest

from app.kb.documents import load_chunks
from app.kb.store import PgvectorStore
from app.providers.embeddings import EmbeddingSpec

pytestmark = pytest.mark.integration
SPEC = EmbeddingSpec(provider="fake", model="integration-v1", dimensions=1536)


def vector(x, y):
    return [float(x), float(y)] + [0.0] * 1534


@pytest.fixture
def store():
    url = os.getenv("TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable database ending in _test.")
    if not conninfo_to_dict(url).get("dbname", "").endswith("_test") or url == os.getenv("DATABASE_URL"):
        pytest.fail("Integration tests require a separate disposable database ending in _test.")
    store = PgvectorStore(url)
    store.initialize()
    with psycopg.connect(url) as conn:
        conn.execute("DELETE FROM kb_chunks")
    yield store
    with psycopg.connect(url) as conn:
        conn.execute("DELETE FROM kb_chunks")


@pytest.fixture
def chunks(tmp_path):
    (tmp_path / "a.md").write_text("# A\n## One\nFirst.\n## Two\nSecond.", encoding="utf-8")
    return load_chunks(tmp_path)


def test_exact_cosine_order_and_source_roundtrip(store, chunks):
    store.replace(chunks, [vector(1, 0), vector(0, 1)], SPEC)
    results = store.search(vector(1, 0), SPEC, 3)
    assert [result.chunk for result in results] == chunks
    assert results[0].distance == pytest.approx(0)
    assert results[1].distance == pytest.approx(1)
    assert results[0].chunk.source_path == "a.md"


def test_reingestion_replaces_stale_chunks_without_duplicates(store, chunks):
    store.replace(chunks, [vector(1, 0), vector(0, 1)], SPEC)
    store.replace(chunks[:1], [vector(1, 0)], SPEC)
    store.replace(chunks[:1], [vector(1, 0)], SPEC)
    assert store.manifest()["chunks"] == 1


def test_failed_insert_rolls_back_entire_replacement(store, chunks):
    store.replace(chunks, [vector(1, 0), vector(0, 1)], SPEC)
    before = store.manifest()
    with pytest.raises(psycopg.errors.UniqueViolation):
        store.replace([chunks[0], chunks[0]], [vector(1, 0), vector(0, 1)], SPEC)
    assert store.manifest() == before
    assert len(store.search(vector(1, 0), SPEC, 3)) == 2


def test_empty_index_and_wrong_model_fail_clearly(store, chunks):
    with pytest.raises(ValueError, match="empty"):
        store.search(vector(1, 0), SPEC, 3)
    store.replace(chunks[:1], [vector(1, 0)], SPEC)
    with pytest.raises(ValueError, match="differ"):
        store.search(vector(1, 0), SPEC.model_copy(update={"model": "other"}), 3)
