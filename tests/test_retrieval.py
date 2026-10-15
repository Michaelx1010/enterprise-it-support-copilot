from unittest.mock import Mock

import pytest

from app.kb.ingest import ingest
from app.kb.retrieval import search
from app.providers.embeddings import EmbeddingError, EmbeddingSpec

SPEC = EmbeddingSpec(provider="fake", model="test", dimensions=1536)
VECTOR = [1.0] + [0.0] * 1535


def test_retrieval_only_embeds_query_and_searches():
    embedder = Mock(spec=["spec", "embed"])
    embedder.spec = SPEC
    embedder.embed.return_value = [VECTOR]
    store = Mock()
    store.manifest.return_value = {"embedding": SPEC.model_dump()}
    store.search.return_value = []
    assert search("  VPN fails  ", embedder=embedder, store=store) == []
    embedder.embed.assert_called_once_with(["VPN fails"])
    store.search.assert_called_once_with(VECTOR, SPEC, 3)


@pytest.mark.parametrize("query,k", [(" ", 3), ("query", 0), ("query", 51), ("x" * 6001, 3)])
def test_invalid_query_prevents_paid_calls(query, k):
    embedder, store = Mock(), Mock()
    with pytest.raises(ValueError):
        search(query, embedder=embedder, store=store, top_k=k)
    embedder.embed.assert_not_called()
    store.manifest.assert_not_called()


def test_model_mismatch_prevents_paid_calls():
    embedder, store = Mock(), Mock()
    embedder.spec = SPEC
    store.manifest.return_value = {"embedding": SPEC.model_dump() | {"model": "other"}}
    with pytest.raises(ValueError, match="differ"):
        search("VPN", embedder=embedder, store=store)
    embedder.embed.assert_not_called()


def test_later_embedding_batch_failure_preserves_index(tmp_path):
    (tmp_path / "many.md").write_text(
        "# Many\n" + "\n".join(f"## Section {i}\nContent {i}." for i in range(40)), encoding="utf-8",
    )
    embedder, store = Mock(), Mock()
    embedder.spec = SPEC
    embedder.embed.side_effect = [[VECTOR] * 32, EmbeddingError("failure")]
    with pytest.raises(EmbeddingError):
        ingest(tmp_path, embedder=embedder, store=store)
    store.replace.assert_not_called()
