"""Section-level Hit@k and Recall@k; unsupported queries never enter the denominator."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from statistics import mean
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.kb.documents import CHUNKER_VERSION
from app.kb.retrieval import search
from app.kb.store import PgvectorStore
from app.providers.embeddings import EmbeddingProvider


class QueryCase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1)
    split: Literal["dev", "held_out", "unsupported"]
    query: str = Field(min_length=1, max_length=6000)
    relevant_sections: list[str]

    @model_validator(mode="after")
    def check_labels(self):
        if (self.split == "unsupported") != (len(self.relevant_sections) == 0):
            raise ValueError("Only unsupported queries must have no relevant sections.")
        if len(set(self.relevant_sections)) != len(self.relevant_sections):
            raise ValueError("Relevant sections must be unique.")
        return self


def load_cases(path: Path) -> list[QueryCase]:
    cases = [QueryCase.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    if not cases or len({case.id for case in cases}) != len(cases):
        raise ValueError("Evaluation requires cases with unique IDs.")
    return cases


def score(retrieved_sections: list[str], relevant_sections: list[str], k: int) -> dict:
    if not relevant_sections or k < 1:
        raise ValueError("Recall requires relevant labels and a positive k.")
    relevant = set(relevant_sections)
    found = set(retrieved_sections[:k]) & relevant
    return {f"hit@{k}": float(bool(found)), f"recall@{k}": len(found) / len(relevant)}


def evaluate(path: Path, *, embedder: EmbeddingProvider, store: PgvectorStore,
             top_k: int = 3) -> dict:
    cases = load_cases(path)
    manifest = store.manifest()
    known = set(manifest["section_ids"])
    missing = {label for case in cases for label in case.relevant_sections} - known
    if missing:
        raise ValueError(f"Evaluation labels absent from the index: {sorted(missing)}")
    rows = []
    for case in cases:
        results = search(case.query, embedder=embedder, store=store, top_k=top_k)
        metrics = None if case.split == "unsupported" else score(
            [item.chunk.section_id for item in results], case.relevant_sections, top_k,
        )
        rows.append(case.model_dump() | {"metrics": metrics, "results": [
            {"chunk_id": item.chunk.chunk_id, "section_id": item.chunk.section_id,
             "source_path": item.chunk.source_path, "section_path": item.chunk.section_path,
             "distance": item.distance} for item in results
        ]})
    if store.manifest() != manifest:
        raise ValueError("Index changed during evaluation; discard results and rerun.")
    aggregates = {}
    for split in ("dev", "held_out", "unsupported"):
        group = [row for row in rows if row["split"] == split]
        if not group:
            continue
        distances = [row["results"][0]["distance"] for row in group if row["results"]]
        aggregates[split] = {
            "queries": len(group),
            "metrics": None if split == "unsupported" else {
                metric: mean(row["metrics"][metric] for row in group)
                for metric in (f"hit@{top_k}", f"recall@{top_k}")
            },
            "nearest_distance": {"min": min(distances), "mean": mean(distances), "max": max(distances)}
            if distances else None,
        }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(), "top_k": top_k,
        "chunker_version": CHUNKER_VERSION, "index": manifest,
        "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "aggregates": aggregates, "queries": rows,
        "note": "No relevance threshold. Distances are not probabilities. Unsupported metrics are undefined.",
    }
