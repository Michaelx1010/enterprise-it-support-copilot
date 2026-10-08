from pathlib import Path

import pandas as pd
import pytest

from app.data import load_tickets
from app.profiling import profile_tickets


def write_fixture(path: Path) -> None:
    pd.DataFrame([
        {"id": "001", "subject": "NA", "description": "Line 1, detail\nLine 2",
         "category": "Software", "priority": "Medium", "createdAt": "2024-01-01", "requesterEmail": "a@example.com"},
        {"id": "001", "subject": "NA", "description": "Line 1, detail\nLine 2",
         "category": "Software", "priority": "Medium", "createdAt": "2024-01-01", "requesterEmail": "a@example.com"},
        {"id": "003", "subject": " ", "description": "", "category": "Unexpected",
         "priority": "", "createdAt": "", "requesterEmail": ""},
    ]).to_csv(path, index=False)


def test_loader_preserves_text_and_profile_reports_missing_and_duplicates(tmp_path):
    path = tmp_path / "tickets.csv"
    write_fixture(path)
    frame = load_tickets(path)
    assert frame.iloc[0]["id"] == "001"
    assert frame.iloc[0]["subject"] == "NA"
    assert frame.iloc[0]["description"] == "Line 1, detail\nLine 2"
    profile = profile_tickets(frame)
    assert profile["rows"] == 3
    assert profile["missing_or_blank"]["subject"] == 1
    assert profile["missing_or_blank"]["description"] == 1
    assert profile["missing_or_blank"]["priority"] == 1
    assert profile["duplicates"] == {
        "full_rows": 1, "extra_nonblank_ids": 1, "extra_subject_description_pairs": 1,
    }
    assert profile["unknown_labels"]["category"] == ["Unexpected"]
    assert profile["distributions"]["priority"] == [
        {"label": "Medium", "count": 2, "percent": 66.67},
    ]


def test_missing_columns_are_reported(tmp_path):
    path = tmp_path / "incomplete.csv"
    path.write_text("subject,description\nHello,Details\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        load_tickets(path)
