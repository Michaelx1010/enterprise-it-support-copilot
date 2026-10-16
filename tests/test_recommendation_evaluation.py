import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.providers.embeddings import EmbeddingError
from app.providers.recommendation import RecommendationError
from app.rag.schemas import SupportRecommendation
from evaluation import recommendation as evaluation


def write_cases(tmp_path, ticket, labels):
    cases = [{"id": str(i), "group": group, "ticket": ticket.model_dump(),
              "answerable": answerable, "expected_escalation": escalation, "review_notes": "Manual rubric"}
             for i, (group, answerable, escalation) in enumerate(labels)]
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(json.dumps(case) for case in cases), encoding="utf-8")
    return path


def test_metrics_include_rejections_failures_and_incorrect_abstentions(
        tmp_path, monkeypatch, ticket, evidence, recommendation_payload):
    path = write_cases(tmp_path, ticket, [
        ("unsupported", False, False), ("unsupported", False, False),
        ("supported", True, False), ("escalation", True, True),
        ("supported", True, False), ("supported", True, False),
    ])
    monkeypatch.setattr(evaluation, "retrieve_ticket", Mock(return_value=evidence))
    abstention = SupportRecommendation.model_validate(recommendation_payload | {
        "status": "insufficient_evidence", "steps": [],
    })
    invalid_citation = SupportRecommendation.model_validate(recommendation_payload)
    invalid_citation.steps[0].supporting_chunk_ids.append("invented")
    provider = Mock()
    provider.generate.side_effect = [abstention, RecommendationError("private error"), abstention,
                                     SupportRecommendation.model_validate(recommendation_payload),
                                     invalid_citation, RecommendationError("malformed", code="invalid_output")]
    store = Mock()
    store.manifest.return_value = {"corpus_hash": "fixture"}
    report = evaluation.evaluate(path, embedder=Mock(), store=store, provider=provider,
                                 generation_settings={"provider": "fake"})
    metrics = report["aggregates"]
    assert (metrics["accepted"], metrics["rejected"], metrics["failed"]) == (3, 2, 1)
    assert metrics["unsupported_abstention"] == {"abstained": 1, "attempted": 2, "rate": 0.5}
    assert metrics["incorrect_abstentions"] == {"count": 1, "answerable_cases": 4, "rate": 0.25}
    assert metrics["escalation"]["false_negative"] == 1
    assert metrics["escalation"]["unscored_rejected_or_failed"] == 3
    assert metrics["parsed_candidate_citations"]["citation_validity"] == pytest.approx(2 / 3)
    assert metrics["parsed_candidate_citations"]["citation_coverage"] == 1
    assert metrics["accepted_citations"]["citation_validity"] == 1
    assert report["cases"][0]["citation_metrics"]["citation_coverage"] is None
    assert report["cases"][4]["recommendation"] is None
    assert report["cases"][4]["rejected_candidate"] is not None
    assert report["cases"][5]["citation_metrics"] is None
    assert report["cases"][0]["evidence"] == [item.model_dump() for item in evidence]
    assert all(row["manual_review"]["status"] == "pending" for row in report["cases"])
    assert "private error" not in json.dumps(report)
    for call in provider.generate.call_args_list:
        assert set(json.loads(call.kwargs["payload"])) == {"ticket", "evidence"}


def test_unknown_ids_do_not_count_as_coverage(evidence, recommendation_payload):
    recommendation_payload["steps"][0]["supporting_chunk_ids"] = ["invented"]
    metrics = evaluation.citation_metrics(SupportRecommendation.model_validate(recommendation_payload), evidence)
    assert metrics["citation_validity"] == 0
    assert metrics["citation_coverage"] == 0


def test_retrieval_failure_is_recorded_and_does_not_abstain(tmp_path, monkeypatch, ticket):
    path = write_cases(tmp_path, ticket, [("unsupported", False, False)])
    monkeypatch.setattr(evaluation, "retrieve_ticket", Mock(side_effect=EmbeddingError("private")))
    store, provider = Mock(), Mock()
    store.manifest.return_value = {}
    report = evaluation.evaluate(path, embedder=Mock(), store=store, provider=provider, generation_settings={})
    assert report["aggregates"]["failed"] == 1
    assert report["aggregates"]["unsupported_abstention"]["rate"] == 0
    assert report["aggregates"]["accepted_citations"]["citation_validity"] is None
    provider.generate.assert_not_called()


def test_escalation_false_positive_reported(tmp_path, monkeypatch, ticket, evidence, recommendation_payload):
    path = write_cases(tmp_path, ticket, [("supported", True, False)])
    monkeypatch.setattr(evaluation, "retrieve_ticket", Mock(return_value=evidence))
    recommendation_payload["steps"][0]["step_type"] = "escalation"
    recommendation_payload.update(escalation_required=True, escalation_reason="Persistent errors")
    store, provider = Mock(), Mock()
    store.manifest.return_value = {}
    provider.generate.return_value = SupportRecommendation.model_validate(recommendation_payload)
    report = evaluation.evaluate(path, embedder=Mock(), store=store, provider=provider, generation_settings={})
    assert report["aggregates"]["escalation"]["false_positive"] == 1
    assert report["aggregates"]["escalation"]["label_match_over_all_attempts"] == 0


def test_changed_index_rejects_report(tmp_path, monkeypatch, ticket):
    path = write_cases(tmp_path, ticket, [("unsupported", False, False)])
    monkeypatch.setattr(evaluation, "retrieve_ticket", Mock(return_value=[]))
    store = Mock()
    store.manifest.side_effect = [{"corpus_hash": "before"}, {"corpus_hash": "after"}]
    with pytest.raises(ValueError, match="changed"):
        evaluation.evaluate(path, embedder=Mock(), store=store, provider=Mock(), generation_settings={})


def test_case_file_covers_four_groups_and_unique_ids():
    cases = evaluation.load_cases(Path("evaluation/recommendation.jsonl"))
    assert len(cases) == 16
    assert {group: sum(case.group == group for case in cases) for group in (
        "supported", "unsupported", "ambiguous", "escalation"
    )} == {"supported": 4, "unsupported": 4, "ambiguous": 4, "escalation": 4}


def test_duplicate_labels_fail_before_paid_calls(tmp_path, ticket):
    path = write_cases(tmp_path, ticket, [("unsupported", False, False)])
    path.write_text(path.read_text() + "\n" + path.read_text(), encoding="utf-8")
    embedder, store, provider = Mock(), Mock(), Mock()
    with pytest.raises(ValueError, match="unique"):
        evaluation.evaluate(path, embedder=embedder, store=store, provider=provider, generation_settings={})
    store.manifest.assert_not_called()
    provider.generate.assert_not_called()


def test_empty_aggregates_have_null_metrics():
    metrics = evaluation.aggregate([])
    assert metrics["unsupported_abstention"]["rate"] is None
    assert metrics["incorrect_abstentions"]["rate"] is None
    assert metrics["escalation"]["label_match_over_all_attempts"] is None
