"""Download and load the original CSV without silently dropping or filling rows."""

from pathlib import Path
from urllib.request import urlopen

import pandas as pd

DATASET_ID = "Console-AI/IT-helpdesk-synthetic-tickets"
DATASET_REVISION = "165693849d955c6da4c00bc8be8e541afec0514e"
DATASET_URL = (
    f"https://huggingface.co/datasets/{DATASET_ID}/resolve/"
    f"{DATASET_REVISION}/tickets.csv"
)
DEFAULT_DATA_PATH = Path("data/raw/tickets.csv")
REQUIRED_COLUMNS = (
    "id", "subject", "description", "priority", "category", "createdAt", "requesterEmail",
)


def download_dataset(destination: Path = DEFAULT_DATA_PATH) -> Path:
    """Download the pinned CSV. Refuse to overwrite an existing local dataset."""
    if destination.exists():
        raise FileExistsError(f"Dataset already exists: {destination}")
    with urlopen(DATASET_URL, timeout=60) as response:
        contents = response.read()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output:
        output.write(contents)
    return destination


def load_tickets(path: Path = DEFAULT_DATA_PATH) -> pd.DataFrame:
    """Preserve text and blank cells; 'NA' and 'null' remain literal ticket text."""
    frame = pd.read_csv(path, dtype="string", keep_default_na=False, encoding="utf-8-sig")
    missing = set(REQUIRED_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"Dataset is missing required columns: {', '.join(sorted(missing))}")
    if frame.empty:
        raise ValueError("Dataset contains no tickets.")
    return frame
