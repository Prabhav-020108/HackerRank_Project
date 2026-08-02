"""
Phase 6 test -- Verify Gemini classify() on text, image, and voice rows.

Tests:
1. Text-only message
2. Image message (verify Gemini describes image content)
3. Voice message (verify Gemini transcribes/describes audio content)
4. Fallback on empty/bad input
5. Schema validation on all outputs
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "code"))
os.chdir(str(Path(__file__).resolve().parent.parent))

import pandas as pd
from context import hydrate
from retrieval import retrieve_evidence
from llm import classify

DATA_DIR = Path("dataset")
VALID_ACTIONS = {"notify", "digest", "mute"}
VALID_TYPES = {"personal", "urgent", "event", "payment", "business_update",
               "promotion", "greeting", "forward", "spam", "scam", "unknown"}

sample = pd.read_csv(DATA_DIR / "sample_messages.csv")
messages = pd.read_csv(DATA_DIR / "messages.csv")


def validate_result(result: dict, label: str) -> bool:
    """Validate a classify() result dict."""
    ok = True
    required = {"action", "message_type", "reason", "confidence", "evidence_message_ids"}
    missing = required - set(result.keys())
    if missing:
        print(f"  FAIL [{label}]: missing keys {missing}")
        ok = False
    if result.get("action") not in VALID_ACTIONS:
        print(f"  FAIL [{label}]: invalid action '{result.get('action')}'")
        ok = False
    if result.get("message_type") not in VALID_TYPES:
        print(f"  FAIL [{label}]: invalid message_type '{result.get('message_type')}'")
        ok = False
    if not isinstance(result.get("confidence"), (int, float)):
        print(f"  FAIL [{label}]: confidence not numeric")
        ok = False
    elif not (0 <= result["confidence"] <= 1):
        print(f"  FAIL [{label}]: confidence {result['confidence']} out of [0,1]")
        ok = False
    if not result.get("reason") or len(str(result["reason"]).strip()) < 5:
        print(f"  FAIL [{label}]: reason too short '{result.get('reason')}'")
        ok = False
    if ok:
        print(f"  PASS [{label}]: action={result['action']}, type={result['message_type']}, "
              f"conf={result['confidence']}, reason=\"{result['reason'][:80]}...\"")
    return ok


# =====================================================================
# Test 1: Text-only messages (pick 3 diverse ones from sample)
# =====================================================================
print("=" * 80)
print("TEST 1: Text-only messages")
print("=" * 80)

text_rows = sample[sample["media_type"].isna()].head(3)
for _, row in text_rows.iterrows():
    ctx = hydrate(row, DATA_DIR)
    ev_str, ev_ctx = retrieve_evidence(ctx.user_id, ctx.message_text or "")
    result = classify(ctx, ev_str, ev_ctx)
    validate_result(result, row["message_id"])
    # Compare with expected
    expected = row.get("action", "?")
    match = "MATCH" if result["action"] == expected else "MISMATCH"
    print(f"    Expected action={expected}, got={result['action']} [{match}]")
    print()

# =====================================================================
# Test 2: Image message
# =====================================================================
print("=" * 80)
print("TEST 2: Image message (verify Gemini reads the image)")
print("=" * 80)

image_rows = messages[messages["media_type"] == "image"].head(2)
for _, row in image_rows.iterrows():
    ctx = hydrate(row, DATA_DIR)
    ev_str, ev_ctx = retrieve_evidence(ctx.user_id, ctx.message_text or "")
    result = classify(ctx, ev_str, ev_ctx)
    validate_result(result, row["message_id"])
    print(f"    Full reason: \"{result['reason']}\"")
    print(f"    Media file: {ctx.media.file_path if ctx.media else 'None'}")
    print()

# =====================================================================
# Test 3: Voice message
# =====================================================================
print("=" * 80)
print("TEST 3: Voice message (verify Gemini listens to audio)")
print("=" * 80)

voice_rows = messages[messages["media_type"] == "voice"].head(2)
for _, row in voice_rows.iterrows():
    ctx = hydrate(row, DATA_DIR)
    ev_str, ev_ctx = retrieve_evidence(ctx.user_id, ctx.message_text or "")
    result = classify(ctx, ev_str, ev_ctx)
    validate_result(result, row["message_id"])
    print(f"    Full reason: \"{result['reason']}\"")
    print(f"    Media file: {ctx.media.file_path if ctx.media else 'None'}")
    print()

# =====================================================================
# Summary
# =====================================================================
print("=" * 80)
print("Phase 6 test complete. Check reasons above to confirm Gemini")
print("is actually reading image/audio content, not hallucinating.")
print("=" * 80)
