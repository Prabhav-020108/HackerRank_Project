"""
Phase 2 -- output validator (NOT an accuracy scorer).

IMPORTANT, found during Phase 2 testing: dataset/sample_messages.csv uses a
completely separate ID space (sample_msg_001, sample_msg_002, ...) from
dataset/messages.csv (msg_023, msg_091, ...) -- ZERO message_id overlap
between the two files, confirmed by inspection. So sample_messages.csv can
NEVER be used to compute a match-rate / accuracy score against your real
predictions for messages.csv -- there is no local ground truth to compare
against. Per problem_statement.md, it exists only "to understand the
expected output format and style." HackerRank scores output.csv against
hidden ground truth after submission; there is no accuracy number to chase
locally.

So this script does two separate, honest things instead:
  1. VALIDATE -- schema/format checks on your real output.csv: exact
     columns, one row per message_id, no dupes, valid action/message_type
     enums, confidence in [0, 1], no empty reasons. These ARE fully
     automatable and directly protect rubric-relevant format correctness.
  2. CALIBRATE -- print a few of your own predictions next to a few
     sample_messages.csv rows so you can eyeball whether your `reason`
     tone/length and `confidence` decisiveness match the expected style.
     This is a manual read, not a metric.

Run from anywhere:
    python code/evaluation/main.py
    python code/evaluation/main.py --data dataset --pred output.csv
"""

import argparse
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "dataset"
DEFAULT_PRED_PATH = REPO_ROOT / "output.csv"

REQUIRED_COLUMNS = ["message_id", "action", "message_type", "reason", "confidence", "evidence_message_ids"]
VALID_ACTIONS = {"notify", "digest", "mute"}
VALID_MESSAGE_TYPES = {
    "personal", "urgent", "event", "payment", "business_update",
    "promotion", "greeting", "forward", "spam", "scam", "unknown",
}


def validate(messages: pd.DataFrame, pred: pd.DataFrame) -> list:
    """Returns a list of human-readable problem strings. Empty list = clean."""
    problems = []

    if list(pred.columns) != REQUIRED_COLUMNS:
        problems.append(f"Column mismatch. Expected {REQUIRED_COLUMNS}, got {list(pred.columns)}")

    if not pred["message_id"].is_unique:
        dupes = pred["message_id"][pred["message_id"].duplicated()].tolist()
        problems.append(f"Duplicate message_id rows: {dupes}")

    missing = set(messages["message_id"]) - set(pred["message_id"])
    if missing:
        problems.append(f"{len(missing)} message_id(s) from messages.csv missing in output: {sorted(missing)[:5]}")

    extra = set(pred["message_id"]) - set(messages["message_id"])
    if extra:
        problems.append(f"{len(extra)} message_id(s) in output that aren't in messages.csv: {sorted(extra)[:5]}")

    bad_actions = pred.loc[~pred["action"].isin(VALID_ACTIONS), "message_id"].tolist()
    if bad_actions:
        problems.append(f"Invalid action value on: {bad_actions[:5]}")

    bad_types = pred.loc[~pred["message_type"].isin(VALID_MESSAGE_TYPES), "message_id"].tolist()
    if bad_types:
        problems.append(f"Invalid message_type value on: {bad_types[:5]}")

    bad_conf = pred.loc[~pred["confidence"].between(0.0, 1.0), "message_id"].tolist()
    if bad_conf:
        problems.append(f"confidence outside [0, 1] on: {bad_conf[:5]}")

    empty_reason = pred.loc[pred["reason"].isna() | (pred["reason"].astype(str).str.strip() == ""), "message_id"].tolist()
    if empty_reason:
        problems.append(f"Empty reason on: {empty_reason[:5]}")

    return problems


def print_style_comparison(sample: pd.DataFrame, pred: pd.DataFrame, n: int = 3) -> None:
    print(f"\n--- Style calibration: {n} of YOUR predictions vs {n} SAMPLE rows (manual read only) ---")
    print("\nYour predictions:")
    print(pred[["message_id", "action", "message_type", "reason", "confidence"]].head(n).to_string(index=False))
    print("\nExpected-style examples from sample_messages.csv:")
    print(sample[["message_id", "action", "message_type", "reason", "confidence"]].head(n).to_string(index=False))


def main():
    parser = argparse.ArgumentParser(description="Validate output.csv and show style calibration")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--pred", type=Path, default=DEFAULT_PRED_PATH)
    args = parser.parse_args()

    messages = pd.read_csv(args.data / "messages.csv")
    sample = pd.read_csv(args.data / "sample_messages.csv")
    pred = pd.read_csv(args.pred)

    problems = validate(messages, pred)
    if problems:
        print(f"FOUND {len(problems)} PROBLEM(S):")
        for p in problems:
            print(f" - {p}")
    else:
        print(f"VALID: {len(pred)} rows, schema OK, all enums valid, confidence in range, no dupes.")

    print_style_comparison(sample, pred)


if __name__ == "__main__":
    main()