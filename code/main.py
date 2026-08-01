"""
Phase 2 -- Skeleton I/O pipeline.

Reads dataset/messages.csv and writes a schema-valid output.csv where every
row uses the SAME placeholder decision. This proves the file handling, exact
column schema, and one-row-per-message contract works BEFORE any real logic
(fast-path rules / retrieval / Gemini) is added in later phases.

Run from anywhere -- paths are resolved relative to this file's location,
not your current working directory:

    python code/main.py
    python code/main.py --data dataset --out output.csv
"""

import argparse
import csv
from pathlib import Path

import pandas as pd

# Resolve paths relative to this file's location (repo_root/code/main.py),
# so it works whether you run it from the repo root or from inside code/.
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_DATA_DIR = REPO_ROOT / "dataset"
DEFAULT_OUT_PATH = REPO_ROOT / "output.csv"

# Exact column order required by problem_statement.md -- do not reorder.
REQUIRED_COLUMNS = [
    "message_id",
    "action",
    "message_type",
    "reason",
    "confidence",
    "evidence_message_ids",
]

# Same decision for every row, on purpose. This is the "dumb but valid"
# baseline Phase 2 exists to prove -- real intelligence arrives in Phase 4+.
PLACEHOLDER_DECISION = {
    "action": "digest",
    "message_type": "unknown",
    "reason": "Placeholder decision from the Phase 2 skeleton pipeline.",
    "confidence": 0.5,
    "evidence_message_ids": "none",
}


def load_messages(data_dir: Path) -> pd.DataFrame:
    messages_path = data_dir / "messages.csv"
    if not messages_path.exists():
        raise FileNotFoundError(f"Could not find messages.csv at {messages_path}")
    return pd.read_csv(messages_path)


def build_output_rows(messages: pd.DataFrame) -> list:
    rows = []
    for message_id in messages["message_id"]:
        row = {"message_id": message_id, **PLACEHOLDER_DECISION}
        rows.append(row)
    return rows


def write_output(rows: list, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" is required on Windows so the csv module doesn't double up \r\n.
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Message Notification Router -- Phase 2 skeleton")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_DIR, help="Path to the dataset/ directory")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH, help="Path to write output.csv")
    args = parser.parse_args()

    messages = load_messages(args.data)
    rows = build_output_rows(messages)
    write_output(rows, args.out)

    print(f"Read  {len(messages)} rows from {args.data / 'messages.csv'}")
    print(f"Wrote {len(rows)} rows to {args.out}")
    assert len(rows) == len(messages), "Row count mismatch between input and output!"
    print("OK: row counts match.")


if __name__ == "__main__":
    main()