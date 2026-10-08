"""Descriptive dataset exploration, independent of classification and model calls."""

import hashlib
from pathlib import Path
from typing import Any, get_args

import pandas as pd

from app.data import DATASET_ID, DATASET_REVISION, DATASET_URL
from app.schemas import Category, Priority


def profile_tickets(frame: pd.DataFrame) -> dict[str, Any]:
    """Report blank cells, label distributions, duplicates, and text lengths."""
    blank = frame.apply(lambda column: column.isna() | column.str.strip().eq(""))
    distributions = {}
    for column in ("category", "priority"):
        counts = frame.loc[~blank[column], column].value_counts()
        distributions[column] = [
            {"label": label, "count": int(count), "percent": round(count / len(frame) * 100, 2)}
            for label, count in counts.items()
        ]
    return {
        "rows": len(frame),
        "schema": {name: str(dtype) for name, dtype in frame.dtypes.items()},
        "missing_or_blank": {name: int(count) for name, count in blank.sum().items()},
        "distributions": distributions,
        "unknown_labels": {
            column: sorted(set(frame.loc[~blank[column], column]) - set(get_args(labels)))
            for column, labels in (("category", Category), ("priority", Priority))
        },
        "duplicates": {
            "full_rows": int(frame.duplicated().sum()),
            "extra_nonblank_ids": int(frame.loc[~blank["id"], "id"].duplicated().sum()),
            "extra_subject_description_pairs": int(frame.duplicated(["subject", "description"]).sum()),
        },
        "text_lengths": {
            column: frame[column].str.len().describe().to_dict()
            for column in ("subject", "description")
        },
        "examples": frame[["subject", "description", "category", "priority"]]
        .head(3).to_dict(orient="records"),
    }


def render_report(frame: pd.DataFrame, source: Path) -> str:
    """Render a reproducible Markdown report; lengths are measured in characters."""
    profile = profile_tickets(frame)
    lines = [
        "# IT helpdesk dataset profile", "",
        f"- Source file: `{source.as_posix()}`",
        f"- SHA-256: `{hashlib.sha256(source.read_bytes()).hexdigest()}`",
        f"- Expected upstream dataset: [{DATASET_ID}]({DATASET_URL})",
        f"- Pinned download revision: `{DATASET_REVISION}`",
        "- The checksum identifies the inspected file; custom input files may differ from upstream.",
        "- Upstream license metadata: MIT. Data is synthetic.",
        f"- Tickets: **{profile['rows']}**", "",
        "## Schema and missing values", "",
        "All CSV fields are deliberately loaded as strings to preserve the raw text.",
        "`createdAt` is timestamp text; it is not parsed for classification.",
        "Missing counts include null, empty, and whitespace-only cells. No rows are dropped.", "",
        "| Column | Loaded dtype | Missing or blank |",
        "| --- | --- | ---: |",
    ]
    for column, dtype in profile["schema"].items():
        lines.append(f"| {column} | {dtype} | {profile['missing_or_blank'][column]} |")
    for column, distribution in profile["distributions"].items():
        lines.extend(["", f"## {column.title()} distribution", "",
                      "Percentages use all rows, including any rows with missing labels.", "",
                      "| Label | Count | Percent |", "| --- | ---: | ---: |"])
        lines.extend(f"| {row['label']} | {row['count']} | {row['percent']:.2f}% |" for row in distribution)
        lines.extend(["", f"Unknown labels: {profile['unknown_labels'][column] or 'none'}."])
    lines.extend(["", "## Duplicates", "", "Counts are extra rows beyond the first occurrence.", ""])
    lines.extend(f"- {name}: {count}" for name, count in profile["duplicates"].items())
    lines.extend(["", "## Text lengths (characters)", "",
                  "| Field | Min | Median | Mean | 95th percentile | Max |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"])
    for column, stats in profile["text_lengths"].items():
        p95 = frame[column].str.len().quantile(0.95)
        lines.append(f"| {column} | {stats['min']:.0f} | {stats['50%']:.0f} | "
                     f"{stats['mean']:.1f} | {p95:.1f} | {stats['max']:.0f} |")
    lines.extend(["", "## Representative records", "",
                  "First three rows in file order; descriptions are truncated to 240 characters.", ""])
    for row in profile["examples"]:
        lines.extend([f"- **{row['category']} / {row['priority']}**",
                      f"  - Subject: {' '.join(row['subject'].split())}",
                      f"  - Description excerpt: {' '.join(row['description'].split())[:240]}"])
    lines.extend(["", "## Phase 1 interpretation", "",
                  "Only subject and description enter the model. Category and priority are reference labels;",
                  "ID, timestamp, and requester email are metadata. There are no reference summaries.", "",
                  "Check class imbalance before interpreting future accuracy results. Rare labels have",
                  "too few examples for dependable per-class conclusions. Synthetic examples do not",
                  "establish performance on real enterprise tickets. The prompt's category descriptions",
                  "and priority rubric are project assumptions, not an official dataset labeling guide.", ""])
    return "\n".join(line.rstrip() for line in lines)
