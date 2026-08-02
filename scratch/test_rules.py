"""
Phase 4 -- Test fast_path() against sample_messages.csv and messages.csv.

For every row where fast_path fires, compare against expected labels.
Log mismatches.  Also confirm ambiguous rows fall through.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "code"))

import pandas as pd
from context import hydrate
from rules import fast_path

DATA_DIR = Path(__file__).resolve().parent.parent / "dataset"


def test_sample_messages():
    """Test fast_path on sample_messages.csv — we know the expected labels."""
    sample = pd.read_csv(DATA_DIR / "sample_messages.csv")

    print("=" * 100)
    print("FAST-PATH TESTS ON sample_messages.csv")
    print("=" * 100)

    fired = 0
    correct = 0
    mismatches = []
    fell_through = []

    for _, row in sample.iterrows():
        ctx = hydrate(row, DATA_DIR)
        decision = fast_path(ctx)

        expected_action = row["action"]
        expected_type = row["message_type"]
        msg_id = row["message_id"]

        if decision is not None:
            fired += 1
            action_ok = decision["action"] == expected_action
            type_ok = decision["message_type"] == expected_type

            status = "✓" if (action_ok and type_ok) else "✗"
            if action_ok and type_ok:
                correct += 1
            else:
                mismatches.append({
                    "message_id": msg_id,
                    "expected_action": expected_action,
                    "got_action": decision["action"],
                    "expected_type": expected_type,
                    "got_type": decision["message_type"],
                    "reason": decision["reason"],
                    "text_preview": (ctx.message_text or "")[:80],
                })

            print(f"  {status} {msg_id}: "
                  f"expected=({expected_action}/{expected_type}), "
                  f"got=({decision['action']}/{decision['message_type']}), "
                  f"conf={decision['confidence']}")
        else:
            fell_through.append(msg_id)
            print(f"  → {msg_id}: fell through (expected={expected_action}/{expected_type})")

    print(f"\n--- SUMMARY ---")
    print(f"  Fired:        {fired}/{len(sample)}")
    print(f"  Correct:      {correct}/{fired}")
    print(f"  Mismatches:   {len(mismatches)}")
    print(f"  Fell through: {len(fell_through)}")

    if mismatches:
        print(f"\n--- MISMATCHES ---")
        for m in mismatches:
            print(f"  {m['message_id']}: "
                  f"expected=({m['expected_action']}/{m['expected_type']}), "
                  f"got=({m['got_action']}/{m['got_type']})")
            print(f"    Reason: {m['reason']}")
            print(f"    Text: {m['text_preview']}")

    print(f"\n--- FELL THROUGH (will go to LLM) ---")
    for msg_id in fell_through:
        r = sample[sample["message_id"] == msg_id].iloc[0]
        print(f"  {msg_id}: expected={r['action']}/{r['message_type']}")

    return mismatches, fell_through


def test_all_messages():
    """Run fast_path on all 110 messages.csv rows, report coverage."""
    messages = pd.read_csv(DATA_DIR / "messages.csv")

    print("\n\n" + "=" * 100)
    print("FAST-PATH COVERAGE ON messages.csv (110 rows)")
    print("=" * 100)

    fired_count = 0
    fell_through_count = 0
    action_counts = {"mute": 0, "digest": 0, "notify": 0}
    type_counts = {}
    rule_details = []

    for _, row in messages.iterrows():
        ctx = hydrate(row, DATA_DIR)
        decision = fast_path(ctx)

        if decision is not None:
            fired_count += 1
            action_counts[decision["action"]] = action_counts.get(decision["action"], 0) + 1
            type_counts[decision["message_type"]] = type_counts.get(decision["message_type"], 0) + 1
            rule_details.append({
                "message_id": row["message_id"],
                "action": decision["action"],
                "message_type": decision["message_type"],
                "reason": decision["reason"][:60],
                "confidence": decision["confidence"],
            })
        else:
            fell_through_count += 1

    print(f"\n  Total:        {len(messages)}")
    print(f"  Fired:        {fired_count} ({fired_count*100/len(messages):.1f}%)")
    print(f"  Fell through: {fell_through_count} ({fell_through_count*100/len(messages):.1f}%)")
    print(f"\n  Action distribution (fired only):")
    for action, count in sorted(action_counts.items()):
        print(f"    {action}: {count}")
    print(f"\n  Type distribution (fired only):")
    for mtype, count in sorted(type_counts.items()):
        print(f"    {mtype}: {count}")

    print(f"\n--- FIRED DETAILS ---")
    for d in rule_details:
        print(f"  {d['message_id']}: {d['action']}/{d['message_type']} "
              f"(conf={d['confidence']}) — {d['reason']}")

    return fired_count, fell_through_count


def test_edge_cases():
    """Explicitly test the named edge cases from the checklist."""
    print("\n\n" + "=" * 100)
    print("EDGE CASE TESTS")
    print("=" * 100)

    sample = pd.read_csv(DATA_DIR / "sample_messages.csv")
    messages = pd.read_csv(DATA_DIR / "messages.csv")

    # Edge case 1: Scam guard overrides engagement history
    # sample_msg_043: unverified biz (Loan Verification Desk), reports=23,
    #   why_known=ignored_loan_message → should be mute/scam or mute/spam
    print("\n--- Edge Case 1: Scam guard overrides engagement history ---")
    row = sample[sample["message_id"] == "sample_msg_043"].iloc[0]
    ctx = hydrate(row, DATA_DIR)
    d = fast_path(ctx)
    if d:
        print(f"  sample_msg_043: {d['action']}/{d['message_type']} — {d['reason']}")
        assert d["action"] == "mute", f"Expected mute, got {d['action']}"
        print("  ✓ Scam guard correctly overrides engagement history")
    else:
        print("  ✗ FAILED: fell through (should have been caught by scam guard)")

    # Edge case 2: Muted group with direct mention lets through
    # msg_056: muted group (Mehra Family), but has @u_001 mention
    print("\n--- Edge Case 2: Muted group with direct mention ---")
    row = messages[messages["message_id"] == "msg_056"].iloc[0]
    ctx = hydrate(row, DATA_DIR)
    d = fast_path(ctx)
    if d:
        print(f"  msg_056: {d['action']}/{d['message_type']} — SHOULD have fallen through!")
        print(f"  ✗ FAILED: direct mention in muted group should NOT be muted by fast-path")
    else:
        print(f"  msg_056: fell through (correct — direct mention overrides group mute)")
        print("  ✓ Direct mention correctly lets message through to LLM path")

    # Edge case 3: msg_040: muted group + direct mention + chain text
    print("\n--- Edge Case 3: Muted group + direct mention + chain text ---")
    row = messages[messages["message_id"] == "msg_040"].iloc[0]
    ctx = hydrate(row, DATA_DIR)
    d = fast_path(ctx)
    print(f"  msg_040: mention={ctx.has_direct_mention}, muted={ctx.group.group_muted_by_user if ctx.group else 'N/A'}")
    if d:
        print(f"  msg_040: {d['action']}/{d['message_type']} — {d['reason']}")
    else:
        print(f"  msg_040: fell through (mention overrides mute, LLM decides)")

    # Edge case 4: Prompt injection
    print("\n--- Edge Case 4: Prompt injection ---")
    # sample_msg_053: "Ignore all previous routing rules..."
    row = sample[sample["message_id"] == "sample_msg_053"].iloc[0]
    ctx = hydrate(row, DATA_DIR)
    d = fast_path(ctx)
    if d:
        print(f"  sample_msg_053: {d['action']}/{d['message_type']} — {d['reason']}")
        assert d["action"] == "mute" and d["message_type"] == "scam"
        print("  ✓ Prompt injection correctly caught")
    else:
        print("  ✗ FAILED: prompt injection should be caught")

    # Edge case 5: Verified business with transactional relationship
    # should fall through (not false-positive on scam guard)
    print("\n--- Edge Case 5: Verified business with transaction ---")
    # sample_msg_004: Amazon India, verified, why=recent_grocery_delivery
    row = sample[sample["message_id"] == "sample_msg_004"].iloc[0]
    ctx = hydrate(row, DATA_DIR)
    d = fast_path(ctx)
    if d:
        print(f"  sample_msg_004: {d['action']}/{d['message_type']} — FALSE POSITIVE!")
        print(f"  ✗ FAILED: verified business with real transaction should fall through to LLM")
    else:
        print(f"  sample_msg_004: fell through (correct — verified biz, real transaction)")
        print("  ✓ No false positive on verified business")


def main():
    mismatches, fell_through = test_sample_messages()
    fired, through = test_all_messages()
    test_edge_cases()

    # Write mismatch report for regressions.md
    if mismatches:
        print("\n\n" + "=" * 100)
        print("REGRESSIONS.MD ENTRIES (copy these)")
        print("=" * 100)
        for m in mismatches:
            print(f"\n### Mismatch: {m['message_id']}")
            print(f"- Expected: action={m['expected_action']}, type={m['expected_type']}")
            print(f"- Got: action={m['got_action']}, type={m['got_type']}")
            print(f"- Rule reason: {m['reason']}")
            print(f"- Text preview: {m['text_preview']}")
            print(f"- Root cause: [FILL IN]")
            print(f"- Fix: [FILL IN]")


if __name__ == "__main__":
    main()
