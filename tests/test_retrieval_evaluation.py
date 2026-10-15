import json
from unittest.mock import Mock

import pytest

from app.kb.documents import load_chunks
from app.kb.schemas import SearchResult
from evaluation.retrieval import evaluate, load_cases, score


def test_hit_and_recall_have_different_meanings_and_deduplicate_sections():
    assert score(["a", "a", "x", "b"], ["a", "b"], 3) == {"hit@3": 1.0, "recall@3": 0.5}
    assert score(["x", "y", "z"], ["a"], 3) == {"hit@3": 0.0, "recall@3": 0.0}
    with pytest.raises(ValueError):
        score(["a"], [], 3)


def test_unsupported_queries_record_distances_but_do_not_enter_metrics(tmp_path, monkeypatch):
    doc = tmp_path / "kb"
    doc.mkdir()
    (doc / "a.md").write_text("# A\n## Procedure\nDo this.", encoding="utf-8")
    chunk = load_chunks(doc)[0]
    dataset = tmp_path / "eval.jsonl"
    cases = [
        {"id": "a", "split": "held_out", "query": "Supported", "relevant_sections": [chunk.section_id]},
        {"id": "b", "split": "unsupported", "query": "Unknown", "relevant_sections": []},
    ]
    dataset.write_text("\n".join(json.dumps(case) for case in cases), encoding="utf-8")
    store = Mock()
    store.manifest.return_value = {"section_ids": [chunk.section_id]}
    monkeypatch.setattr("evaluation.retrieval.search", lambda *args, **kwargs: [
        SearchResult(chunk=chunk, distance=0.42),
    ])
    report = evaluate(dataset, embedder=Mock(), store=store)
    assert report["aggregates"]["held_out"]["metrics"] == {"hit@3": 1, "recall@3": 1}
    assert report["aggregates"]["unsupported"]["metrics"] is None
    assert report["aggregates"]["unsupported"]["nearest_distance"]["mean"] == 0.42
    assert report["queries"][1]["results"][0]["source_path"] == "a.md"


def test_wrong_labels_fail_before_search(tmp_path, monkeypatch):
    dataset = tmp_path / "eval.jsonl"
    dataset.write_text(json.dumps({"id": "a", "split": "dev", "query": "Q", "relevant_sections": ["bad"]}))
    store = Mock()
    store.manifest.return_value = {"section_ids": ["known"]}
    retrieval = Mock()
    monkeypatch.setattr("evaluation.retrieval.search", retrieval)
    with pytest.raises(ValueError, match="absent"):
        evaluate(dataset, embedder=Mock(), store=store)
    retrieval.assert_not_called()


def test_duplicate_case_ids_are_rejected(tmp_path):
    dataset = tmp_path / "eval.jsonl"
    line = json.dumps({"id": "a", "split": "dev", "query": "Q", "relevant_sections": ["a"]})
    dataset.write_text(line + "\n" + line)
    with pytest.raises(ValueError, match="unique"):
        load_cases(dataset)
