"""Mechanical recommendation checks, explicitly separate from manual review."""

from collections import Counter
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Literal

import psycopg
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.kb.documents import CHUNKER_VERSION
from app.kb.schemas import SearchResult
from app.kb.store import PgvectorStore
from app.providers.embeddings import EmbeddingError, EmbeddingProvider
from app.providers.recommendation import RecommendationError, RecommendationProvider
from app.rag.prompts import PROMPT_VERSION
from app.rag.recommendation import InvalidCitationError, build_query, generate_recommendation, retrieve_ticket
from app.rag.schemas import SupportRecommendation
from app.schemas import TicketInput


class RecommendationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    id: str = Field(min_length=1)
    group: Literal["supported", "unsupported", "ambiguous", "escalation"]
    ticket: TicketInput
    answerable: bool
    expected_escalation: bool
    review_notes: str = Field(min_length=1)

    @model_validator(mode="after")
    def consistent_labels(self):
        build_query(self.ticket)
        if self.group == "unsupported" and self.answerable:
            raise ValueError("Unsupported cases must not be answerable.")
        if self.group in ("supported", "escalation") and not self.answerable:
            raise ValueError("Supported and escalation cases must be answerable.")
        if self.expected_escalation and not self.answerable:
            raise ValueError("Documented escalation is an answerable action.")
        if self.group == "escalation" and not self.expected_escalation:
            raise ValueError("Escalation cases must expect escalation.")
        return self


def load_cases(path: Path) -> list[RecommendationCase]:
    cases = [RecommendationCase.model_validate_json(line)
             for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not cases or len({case.id for case in cases}) != len(cases):
        raise ValueError("Recommendation evaluation requires cases with unique IDs.")
    return cases


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def citation_metrics(candidate: SupportRecommendation, evidence: list[SearchResult]) -> dict:
    known = {item.chunk.chunk_id for item in evidence}
    citations = [chunk_id for step in candidate.steps for chunk_id in step.supporting_chunk_ids]
    valid = sum(chunk_id in known for chunk_id in citations)
    covered = sum(any(chunk_id in known for chunk_id in step.supporting_chunk_ids)
                  for step in candidate.steps)
    return {"citations": len(citations), "valid_citations": valid,
            "steps": len(candidate.steps), "covered_steps": covered,
            "citation_validity": ratio(valid, len(citations)),
            "citation_coverage": ratio(covered, len(candidate.steps))}


def aggregate(rows: list[dict]) -> dict:
    accepted = [row for row in rows if row["outcome"] == "accepted"]
    rejected = [row for row in rows if row["outcome"] == "rejected"]
    failed = [row for row in rows if row["outcome"] == "failed"]

    def citations(selected: list[dict]) -> dict:
        scored = [row["citation_metrics"] for row in selected if row["citation_metrics"] is not None]
        totals = {key: sum(score[key] for score in scored)
                  for key in ("citations", "valid_citations", "steps", "covered_steps")}
        return totals | {"scored_candidates": len(scored),
                         "citation_validity": ratio(totals["valid_citations"], totals["citations"]),
                         "citation_coverage": ratio(totals["covered_steps"], totals["steps"])}

    unsupported = [row for row in rows if row["group"] == "unsupported"]
    abstained = sum(row["outcome"] == "accepted" and row["recommendation"]["status"] == "insufficient_evidence"
                    for row in unsupported)
    answerable = [row for row in rows if row["answerable"]]
    incorrect = sum(row["outcome"] == "accepted" and row["recommendation"]["status"] == "insufficient_evidence"
                    for row in answerable)
    confusion = {key: 0 for key in ("true_positive", "true_negative", "false_positive", "false_negative")}
    for row in accepted:
        expected, actual = row["expected_escalation"], row["recommendation"]["escalation_required"]
        key = ("true_positive" if actual else "false_negative") if expected else (
            "false_positive" if actual else "true_negative")
        confusion[key] += 1
    return {
        "attempted": len(rows), "accepted": len(accepted), "rejected": len(rejected), "failed": len(failed),
        "rejection_rate": ratio(len(rejected), len(rows)), "failure_rate": ratio(len(failed), len(rows)),
        "errors_by_code": dict(Counter(row["error"]["code"] for row in rows if row["error"])),
        "parsed_candidate_citations": citations(rows), "accepted_citations": citations(accepted),
        "unsupported_abstention": {"abstained": abstained, "attempted": len(unsupported),
                                    "rate": ratio(abstained, len(unsupported))},
        "incorrect_abstentions": {"count": incorrect, "answerable_cases": len(answerable),
                                  "rate": ratio(incorrect, len(answerable))},
        "escalation": confusion | {
            "unscored_rejected_or_failed": len(rejected) + len(failed),
            "label_match_over_all_attempts": ratio(confusion["true_positive"] + confusion["true_negative"], len(rows)),
        },
    }


def evaluate(path: Path, *, embedder: EmbeddingProvider, store: PgvectorStore,
             provider: RecommendationProvider, generation_settings: dict, top_k: int = 3) -> dict:
    if not 1 <= top_k <= 50:
        raise ValueError("top_k must be between 1 and 50.")
    dataset_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    cases = load_cases(path)  # Validate every label before paid requests.
    manifest = store.manifest()
    rows = []
    for case in cases:
        row = case.model_dump() | {
            "outcome": "failed", "recommendation": None, "rejected_candidate": None,
            "evidence": [], "citation_metrics": None, "error": None,
            "manual_review": {"status": "pending", "groundedness": None, "correctness": None},
        }
        try:
            evidence = retrieve_ticket(case.ticket, embedder=embedder, store=store, top_k=top_k)
        except (EmbeddingError, psycopg.Error, ValueError):
            row["error"] = {"stage": "retrieval", "code": "retrieval_failure"}
            rows.append(row)
            continue
        row["evidence"] = [item.model_dump() for item in evidence]
        try:
            result = generate_recommendation(case.ticket, evidence, provider=provider)
            row["outcome"] = "accepted"
            row["recommendation"] = result.recommendation.model_dump()
            row["citation_metrics"] = citation_metrics(result.recommendation, evidence)
        except InvalidCitationError as exc:
            row["outcome"] = "rejected"
            row["rejected_candidate"] = exc.candidate.model_dump()
            row["citation_metrics"] = citation_metrics(exc.candidate, evidence)
            row["error"] = {"stage": "validation", "code": exc.code}
        except RecommendationError as exc:
            row["outcome"] = "rejected" if exc.code == "invalid_output" else "failed"
            row["error"] = {"stage": "generation", "code": exc.code,
                            "validation_types": exc.validation_types}
        rows.append(row)
    if store.manifest() != manifest or hashlib.sha256(path.read_bytes()).hexdigest() != dataset_hash:
        raise ValueError("Index or evaluation dataset changed during the run; discard results and rerun.")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "top_k": top_k, "prompt_version": PROMPT_VERSION, "chunker_version": CHUNKER_VERSION,
        "generation_settings": generation_settings, "index": manifest, "dataset_sha256": dataset_hash,
        "aggregates": aggregate(rows),
        "by_group": {group: aggregate([row for row in rows if row["group"] == group])
                     for group in sorted({case.group for case in cases})},
        "cases": rows,
        "note": "Citation metrics check IDs only, not textual support. Summary groundedness and content "
                "correctness require manual review. Abstention does not establish safety or rule out escalation. "
                "Labels describe the whole KB; retrieval misses can cause answerable-case abstentions. "
                "Malformed outputs have no scored candidate; failures never count as successful abstentions.",
    }
