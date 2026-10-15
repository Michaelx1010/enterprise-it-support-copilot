from pathlib import Path

import pytest

from app.kb.documents import chunk_document, load_chunks
from evaluation.retrieval import load_cases


def test_corpus_and_evaluation_labels_are_consistent():
    chunks = load_chunks(Path("knowledge_base"))
    assert len({chunk.document_id for chunk in chunks}) == 12
    assert len(chunks) == 36
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
    sections = {chunk.section_id for chunk in chunks}
    for case in load_cases(Path("evaluation/retrieval.jsonl")):
        assert set(case.relevant_sections) <= sections


def test_headings_inside_fences_are_not_sections(tmp_path):
    path = tmp_path / "vpn.md"
    path.write_text("# VPN\n## Setup\nSteps.\n```sh\n## not a heading\n```\n## Errors\nDetails.", encoding="utf-8")
    chunks = chunk_document(path, tmp_path)
    assert [chunk.section_id for chunk in chunks] == ["vpn#setup", "vpn#errors"]
    assert "## not a heading" in chunks[0].content
    assert chunks[0].source_path == "vpn.md"
    assert chunks == chunk_document(path, tmp_path)


def test_long_sections_are_bounded_and_keep_all_content(tmp_path):
    path = tmp_path / "long.md"
    words = [f"word{index}" for index in range(1100)]
    path.write_text("# Long\n## Procedure\n" + " ".join(words) + "\n## Other\nUnrelated.", encoding="utf-8")
    chunks = chunk_document(path, tmp_path)
    procedure = [chunk for chunk in chunks if chunk.section_id == "long#procedure"]
    assert len(procedure) > 1
    assert all(len(chunk.content) <= 2000 for chunk in chunks)
    retrieved_words = {word for chunk in procedure for word in chunk.content.split()}
    assert set(words) <= retrieved_words
    assert all("Unrelated" not in chunk.content for chunk in procedure)


@pytest.mark.parametrize("text", ["No title", "# Only title", "# A\n## X\nText\n## X\nAgain",
                                     "# A\n## X\n```\nUnclosed"])
def test_invalid_markdown_is_rejected(tmp_path, text):
    path = tmp_path / "bad.md"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        chunk_document(path, tmp_path)


def test_empty_corpus_cannot_clear_database(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        load_chunks(tmp_path)
