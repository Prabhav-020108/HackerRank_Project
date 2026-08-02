"""
Test Phase 5 retrieval layer against sample_messages.csv
"""

import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "code"))

from retrieval import retrieve_evidence
from context import hydrate

DATA_DIR = Path(__file__).resolve().parent.parent / "dataset"

def test_retrieval():
    sample = pd.read_csv(DATA_DIR / "sample_messages.csv")
    
    print("=" * 80)
    print("RETRIEVAL TESTS (Phase 5)")
    print("=" * 80)
    
    success_count = 0
    cold_starts = 0
    
    for _, row in sample.iterrows():
        ctx = hydrate(row, DATA_DIR)
        
        # Get expected evidence IDs
        expected_evidence = row.get("evidence_message_ids", "none")
        expected_set = set(expected_evidence.split(";")) if expected_evidence != "none" else set()
        
        # Call retrieval
        # In reality, if there is no message text but there is an image, we might use image caption.
        # But for now, we just test text.
        text_to_search = ctx.message_text or ""
        
        got_evidence, got_context = retrieve_evidence(ctx.user_id, text_to_search)
        
        got_set = set(got_evidence.split(";")) if got_evidence != "none" else set()
        
        if expected_evidence == "none" and got_evidence == "none":
            cold_starts += 1
            success_count += 1
            # print(f"✓ {row['message_id']}: correctly returned 'none'")
        elif expected_evidence != "none" and got_evidence != "none":
            # Check overlap
            overlap = expected_set.intersection(got_set)
            if overlap:
                success_count += 1
                print(f"✓ {row['message_id']}: retrieved {got_evidence} (expected {expected_evidence})")
                print(f"  Context:\n{got_context}\n")
            else:
                print(f"✗ {row['message_id']}: retrieved {got_evidence}, expected {expected_evidence}")
                print(f"  Context:\n{got_context}\n")
        elif expected_evidence == "none" and got_evidence != "none":
            print(f"? {row['message_id']}: retrieved {got_evidence} but expected 'none'.")
            print(f"  Context:\n{got_context}\n")
            # We don't fail this strictly, as BM25 might find things the sample labeler missed
        else:
            print(f"✗ {row['message_id']}: retrieved 'none' but expected {expected_evidence}")
            
    print(f"\nTested {len(sample)} rows.")
    print(f"Matched exact empty or overlapping: {success_count} / {len(sample)}")

if __name__ == "__main__":
    test_retrieval()
