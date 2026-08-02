"""
Main entry point for the Message Notification Router.

Delegates to pipeline.py which implements the full 8-stage pipeline:
  1. Ingest (context hydration)
  2. Fast-path deterministic rules
  3. BM25 evidence retrieval
  4. Signal extraction
  5. Gemini LLM classification
  6. Finalize (code-driven overrides)
  7. Confidence calibration
  8. Output validation

Run from anywhere -- paths are resolved relative to this file:

    python code/main.py
    python code/main.py --data dataset --out output.csv --quiet
"""

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_DATA_DIR = REPO_ROOT / "dataset"
DEFAULT_OUT_PATH = REPO_ROOT / "output.csv"

sys.path.insert(0, str(SCRIPT_DIR))

from pipeline import run_pipeline


def main():
    parser = argparse.ArgumentParser(description="Message Notification Router")
    parser.add_argument(
        "--data", type=Path, default=DEFAULT_DATA_DIR,
        help="Path to the dataset/ directory (default: ./dataset)"
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT_PATH,
        help="Path to write output.csv (default: ./output.csv)"
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-message progress output"
    )
    args = parser.parse_args()

    run_pipeline(data_dir=args.data, out_path=args.out, verbose=not args.quiet)


if __name__ == "__main__":
    main()