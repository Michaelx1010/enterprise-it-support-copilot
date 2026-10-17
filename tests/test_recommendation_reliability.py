"""Mechanical regression tests; live semantic behavior requires separate review."""

import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.rag.recommendation import generate_recommendation, InvalidCitationError
from app.rag.prompts import EXAMPLES, build_payload
from app.rag.schemas import SupportRecommendation
from evaluation.recommendation import aggregate, load_cases


def row(case_id, expected, actual=None, *, code=None, stage="generation"):
    return {"id": case_id, "expected_escalation": expected, "answerable": True,
            "group": "supported", "outcome": "accepted" if code is None else (
                "rejected" if code == "invalid_output" else "failed"),
            "recommendation": {"status": "supported", "escalation_required": actual} if code is None else None,
            "error": None if code is None else {"code": code, "stage": stage}, "citation_metrics": None}


def test_precision_recall_and_failure_denominators():
    rows = [row("tp", True, True), row("fp", False, True), row("fn", True, False),
            row("tn", False, False), row("bad", True, code="invalid_output"),
            row("api", True, code="provider_failure"), row("db", False, code="retrieval_failure", stage="retrieval")]
    report = aggregate(rows)
    assert report["escalation"]["precision"] == 0.5
    assert report["escalation"]["recall"] == 0.5
    assert report["escalation"]["recall_over_all_positive_attempts"] == 0.25
    assert report["escalation"]["false_negative_ids"] == ["fn"]
    assert report["schema_rejections"] == {"count": 1, "rate": 1 / 7}
    assert report["provider_failures"] == {"count": 1, "rate": 1 / 7}
    assert report["failure_rate"] == 2 / 7


def test_no_positive_predictions_has_undefined_precision():
    metrics = aggregate([row("fn", True, False)])["escalation"]
    assert metrics["precision"] is None
    assert metrics["recall"] == 0
    empty = aggregate([])
    assert empty["escalation"]["recall"] is None
    assert empty["schema_rejections"]["rate"] is None
    assert empty["provider_failures"]["rate"] is None


def test_splits_are_frozen_disjoint_and_original_is_preserved():
    manifest = json.loads(Path("evaluation/recommendation_splits.json").read_text())
    all_ids, all_tickets = [], []
    for name, metadata in manifest["datasets"].items():
        path = Path(name)
        assert hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest() == metadata["sha256"]
        cases = load_cases(path)
        assert len(cases) == metadata["cases"]
        all_ids.extend(case.id for case in cases)
        all_tickets.extend((case.ticket.subject, case.ticket.description) for case in cases)
    assert len(all_ids) == len(set(all_ids)) == 36
    assert len(all_tickets) == len(set(all_tickets))


def test_validation_does_not_guess_escalation_from_words(ticket, evidence, recommendation_payload):
    # Deliberately wrong semantic label: existing structural validation cannot detect it.
    recommendation_payload["steps"][0]["action"] = "Contact Network Support."
    provider = Mock()
    provider.generate.return_value = SupportRecommendation.model_validate(recommendation_payload)
    result = generate_recommendation(ticket, evidence, provider=provider)
    assert result.recommendation.steps[0].step_type == "troubleshooting"
    assert result.recommendation.escalation_required is False


def test_known_citation_does_not_prove_applicability(ticket, evidence, recommendation_payload):
    # A citation gate must not be presented as a semantic judge of these misleading passages.
    evidence[0] = evidence[0].model_copy(update={"chunk": evidence[0].chunk.model_copy(update={
        "content": "Unrelated archive retention guidance; no VPN procedure."})})
    provider = Mock()
    provider.generate.return_value = SupportRecommendation.model_validate(recommendation_payload)
    assert generate_recommendation(ticket, evidence, provider=provider).recommendation.status == "supported"


def test_example_id_leak_is_rejected(ticket, evidence, recommendation_payload):
    recommendation_payload["steps"][0]["supporting_chunk_ids"] = ["demo-export"]
    provider = Mock()
    provider.generate.return_value = SupportRecommendation.model_validate(recommendation_payload)
    with pytest.raises(InvalidCitationError):
        generate_recommendation(ticket, evidence, provider=provider)


@pytest.mark.parametrize("example", EXAMPLES)
def test_teaching_outputs_follow_schema_and_use_only_their_own_sources(example):
    recommendation = SupportRecommendation.model_validate(example["output"])
    ids = {item["chunk_id"] for item in example["evidence"]}
    assert all(chunk_id in ids for step in recommendation.steps for chunk_id in step.supporting_chunk_ids)


def test_contrast_examples_distinguish_unmet_and_met_handoff_trigger(ticket, evidence):
    first, repeated = [SupportRecommendation.model_validate(example["output"]) for example in EXAMPLES[:2]]
    assert not first.escalation_required
    assert repeated.escalation_required
    assert repeated.steps[0].step_type == "escalation"
    # Examples do not pollute the live evidence payload or source list.
    payload = json.loads(build_payload(ticket, evidence))
    assert all(not item["chunk_id"].startswith("demo-") for item in payload["evidence"])
