"""
Deep audit of Phase 4 (rules.py) and Phase 5 (retrieval.py).
Validates every checklist item programmatically.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "code"))

import pandas as pd
from context import hydrate, MessageContext
from rules import fast_path, _make_decision
from retrieval import retrieve_evidence, _history, _events, _user_indices

DATA_DIR = Path(__file__).resolve().parent.parent / "dataset"
VALID_ACTIONS = {"notify", "digest", "mute"}
VALID_TYPES = {"personal", "urgent", "event", "payment", "business_update",
               "promotion", "greeting", "forward", "spam", "scam", "unknown"}

errors = []
warnings = []

def err(msg): errors.append(msg); print(f"  ERROR: {msg}")
def warn(msg): warnings.append(msg); print(f"  WARN:  {msg}")
def ok(msg): print(f"  OK:    {msg}")

# ======================================================================
# PHASE 4 AUDIT
# ======================================================================
print("=" * 80)
print("PHASE 4 DEEP AUDIT -- rules.py")
print("=" * 80)

sample = pd.read_csv(DATA_DIR / "sample_messages.csv")
messages = pd.read_csv(DATA_DIR / "messages.csv")

# --- 4.1: Every fast-path return has all 6 fields + valid enums ---
print("\n[4.1] Checking all 6 output fields + valid enums on every fired row")
required_keys = {"action", "message_type", "reason", "confidence", "evidence_message_ids", "message_id"}
for _, row in messages.iterrows():
    ctx = hydrate(row, DATA_DIR)
    d = fast_path(ctx)
    if d is not None:
        missing = required_keys - set(d.keys())
        if missing:
            err(f"{row['message_id']}: missing keys {missing}")
        if d.get("action") not in VALID_ACTIONS:
            err(f"{row['message_id']}: invalid action '{d.get('action')}'")
        if d.get("message_type") not in VALID_TYPES:
            err(f"{row['message_id']}: invalid message_type '{d.get('message_type')}'")
        if not isinstance(d.get("confidence"), (int, float)):
            err(f"{row['message_id']}: confidence is not numeric")
        elif not (0 <= d["confidence"] <= 1):
            err(f"{row['message_id']}: confidence {d['confidence']} out of [0,1]")
        if not d.get("reason") or len(d["reason"].strip()) < 10:
            err(f"{row['message_id']}: reason too short: '{d.get('reason')}'")

if not any("missing keys" in e for e in errors) and not any("invalid" in e for e in errors):
    ok("All fired rows have valid 6-field decisions with correct enums")
else:
    err("Some rows have invalid decisions -- see above")

# --- 4.2: Scam guard overrides engagement history ---
print("\n[4.2] Scam guard overrides engagement history")
# sample_msg_043: unverified biz, reports=23, why=ignored_loan_message
row43 = sample[sample["message_id"] == "sample_msg_043"].iloc[0]
ctx43 = hydrate(row43, DATA_DIR)
d43 = fast_path(ctx43)
if d43 and d43["action"] == "mute":
    ok(f"sample_msg_043: correctly muted as {d43['message_type']} (expected spam)")
    if d43["message_type"] != row43["message_type"]:
        warn(f"sample_msg_043: type={d43['message_type']} vs expected={row43['message_type']}")
else:
    err("sample_msg_043: scam guard did NOT fire on unverified high-report business")

# --- 4.3: Mute guard lets direct mentions through ---
print("\n[4.3] Mute guard lets direct mentions through")
# msg_056: muted group (Mehra Family) but @u_001 mention
row56 = messages[messages["message_id"] == "msg_056"].iloc[0]
ctx56 = hydrate(row56, DATA_DIR)
d56 = fast_path(ctx56)
if d56 is None:
    ok("msg_056: correctly fell through (direct mention in muted group)")
else:
    err(f"msg_056: should have fallen through but got {d56['action']}/{d56['message_type']}")

# Also check a muted group WITHOUT mention IS muted
muted_no_mention = None
for _, row in messages.iterrows():
    ctx = hydrate(row, DATA_DIR)
    if ctx.conversation_type == "group" and ctx.group and ctx.group.group_muted_by_user and not ctx.has_direct_mention:
        d = fast_path(ctx)
        if d and d["action"] == "mute":
            muted_no_mention = row["message_id"]
            break
if muted_no_mention:
    ok(f"Muted group without mention correctly muted (e.g. {muted_no_mention})")
else:
    err("No muted-group-without-mention row was caught by fast_path")

# --- 4.4: Quiet-hours documented ---
print("\n[4.4] Quiet-hours behavior documented")
import inspect
src = inspect.getsource(fast_path)
if "QUIET" in src.upper() or "DND" in src.upper():
    ok("Quiet-hours/DND policy documented in fast_path docstring")
else:
    err("No quiet-hours/DND documentation found in fast_path")

# --- 4.5: Ambiguous rows fall through ---
print("\n[4.5] Ambiguous rows correctly fall through")
fired = 0
fell = 0
for _, row in messages.iterrows():
    ctx = hydrate(row, DATA_DIR)
    d = fast_path(ctx)
    if d: fired += 1
    else: fell += 1
ok(f"Fired: {fired}/110, Fell through: {fell}/110")
if fell == 0:
    err("ZERO rows fell through -- fast_path is force-classifying everything!")
elif fell < 30:
    warn(f"Only {fell} fell through -- fast_path may be too aggressive")
else:
    ok(f"Healthy fall-through rate ({fell/110*100:.0f}%)")

# --- 4.6: Sample accuracy ---
print("\n[4.6] Sample messages accuracy")
correct = 0
total_fired = 0
mismatches = []
for _, row in sample.iterrows():
    ctx = hydrate(row, DATA_DIR)
    d = fast_path(ctx)
    if d:
        total_fired += 1
        if d["action"] == row["action"] and d["message_type"] == row["message_type"]:
            correct += 1
        else:
            mismatches.append((row["message_id"], f"expected {row['action']}/{row['message_type']}, got {d['action']}/{d['message_type']}"))
if total_fired > 0:
    ok(f"Accuracy on fired rows: {correct}/{total_fired} ({correct/total_fired*100:.0f}%)")
    if mismatches:
        for m in mismatches:
            err(f"MISMATCH: {m[0]}: {m[1]}")
    else:
        ok("Zero mismatches on sample_messages.csv!")
else:
    err("No sample rows fired at all")

# --- 4.7: Promo patterns recompile on every call (perf bug) ---
print("\n[4.7] Performance check: regex recompilation inside _rule_muted_group")
import rules as rules_mod
src_muted = inspect.getsource(rules_mod._rule_muted_group)
if "re.compile" in src_muted:
    warn("_PROMO_QUICK_PATTERNS are compiled INSIDE _rule_muted_group -- this recompiles on every call. Should be module-level.")
else:
    ok("No regex recompilation inside hot function")

# --- 4.8: _rule_business_promo_opted_out also recompiles ---
src_promo = inspect.getsource(rules_mod._rule_business_promo_opted_out)
if "re.compile" in src_promo:
    warn("promo_patterns compiled INSIDE _rule_business_promo_opted_out -- should be module-level.")

# ======================================================================
# PHASE 5 AUDIT
# ======================================================================
print("\n\n" + "=" * 80)
print("PHASE 5 DEEP AUDIT -- retrieval.py")
print("=" * 80)

# --- 5.1: BM25 index is user-scoped ---
print("\n[5.1] BM25 index is user-scoped")
history_df = pd.read_csv(DATA_DIR / "message_history.csv")
unique_users_in_history = set(history_df["user_id"].unique())
indexed_users = set(_user_indices.keys())
if indexed_users == unique_users_in_history:
    ok(f"Indices built for all {len(indexed_users)} users in message_history.csv")
else:
    missing = unique_users_in_history - indexed_users
    extra = indexed_users - unique_users_in_history
    if missing: err(f"Missing user indices: {missing}")
    if extra: warn(f"Extra user indices not in history: {extra}")

# --- 5.2: Returns real message_ids that exist in message_history.csv ---
print("\n[5.2] All returned evidence IDs exist in message_history.csv")
valid_ids = set(history_df["message_id"].unique())
bad_ids = []
for _, row in messages.iterrows():
    ctx = hydrate(row, DATA_DIR)
    text = ctx.message_text or ""
    evidence_str, _ = retrieve_evidence(ctx.user_id, text)
    if evidence_str != "none":
        for eid in evidence_str.split(";"):
            if eid.strip() not in valid_ids:
                bad_ids.append((row["message_id"], eid.strip()))
if bad_ids:
    for mid, eid in bad_ids:
        err(f"{mid}: returned evidence ID '{eid}' does NOT exist in message_history.csv")
else:
    ok("All returned evidence IDs are valid message_history.csv IDs")

# --- 5.3: Evidence carries engagement context ---
print("\n[5.3] Evidence carries engagement/reaction context")
events_df = pd.read_csv(DATA_DIR / "message_events.csv")
# Spot-check: retrieve for a message we know has evidence
row_sample = sample[sample["evidence_message_ids"] != "none"].iloc[0]
ctx_spot = hydrate(row_sample, DATA_DIR)
_, context_str = retrieve_evidence(ctx_spot.user_id, ctx_spot.message_text or "")
if context_str:
    has_reaction = any(kw in context_str for kw in ["replied", "opened", "dismissed", "reported", "muted", "ignored"])
    if has_reaction:
        ok(f"Evidence context contains engagement signal for {row_sample['message_id']}")
    else:
        err(f"Evidence context has NO engagement signal: {context_str[:200]}")
else:
    err(f"No context returned for {row_sample['message_id']} (expected evidence)")

# --- 5.4: Cold-start returns "none" ---
print("\n[5.4] Cold-start returns 'none'")
# Test with empty text
ev1, ctx1 = retrieve_evidence("u_001", "")
if ev1 == "none":
    ok("Empty text -> 'none'")
else:
    err(f"Empty text returned '{ev1}' instead of 'none'")

# Test with nonexistent user
ev2, ctx2 = retrieve_evidence("u_NONEXISTENT", "hello world test message")
if ev2 == "none":
    ok("Nonexistent user -> 'none'")
else:
    err(f"Nonexistent user returned '{ev2}' instead of 'none'")

# Test with None text
ev3, ctx3 = retrieve_evidence("u_001", None)
if ev3 == "none":
    ok("None text -> 'none'")
else:
    err(f"None text returned '{ev3}' instead of 'none'")

# --- 5.5: Spot-check sample evidence overlap ---
print("\n[5.5] Spot-check: do retrieved IDs overlap with expected sample evidence?")
evidence_rows = sample[sample["evidence_message_ids"] != "none"]
overlap_count = 0
total_checked = 0
for _, row in evidence_rows.iterrows():
    ctx = hydrate(row, DATA_DIR)
    text = ctx.message_text or ""
    got_evidence, _ = retrieve_evidence(ctx.user_id, text)
    expected_set = set(row["evidence_message_ids"].split(";"))
    got_set = set(got_evidence.split(";")) if got_evidence != "none" else set()
    total_checked += 1
    if got_set & expected_set:
        overlap_count += 1

ok(f"Evidence overlap with sample: {overlap_count}/{total_checked} rows have at least one matching ID")
if overlap_count < total_checked * 0.3:
    warn(f"Low overlap ({overlap_count}/{total_checked}). BM25 may need tuning but not blocking.")

# --- 5.6: Coverage on full messages.csv ---
print("\n[5.6] Evidence coverage on messages.csv")
has_evidence = 0
no_evidence = 0
for _, row in messages.iterrows():
    ctx = hydrate(row, DATA_DIR)
    text = ctx.message_text or ""
    ev, _ = retrieve_evidence(ctx.user_id, text)
    if ev != "none":
        has_evidence += 1
    else:
        no_evidence += 1
ok(f"Has evidence: {has_evidence}/110 ({has_evidence/110*100:.0f}%), No evidence: {no_evidence}/110")
if has_evidence < 20:
    warn("Less than 20% of messages have evidence -- might need to lower threshold or use media captions")

# --- 5.7: Duplicate event index check (pandas gotcha) ---
print("\n[5.7] Checking for duplicate message_ids in events index")
if _events.index.duplicated().any():
    dupes = _events.index[_events.index.duplicated()].unique().tolist()
    warn(f"message_events has duplicate message_ids: {dupes[:5]}... _get_event_summary may return a DataFrame row instead of Series")
else:
    ok("No duplicate message_ids in events index")

# ======================================================================
# SUMMARY
# ======================================================================
print("\n\n" + "=" * 80)
print("AUDIT SUMMARY")
print("=" * 80)
print(f"  Errors:   {len(errors)}")
print(f"  Warnings: {len(warnings)}")
if errors:
    print("\n  ERRORS:")
    for e in errors: print(f"    - {e}")
if warnings:
    print("\n  WARNINGS:")
    for w in warnings: print(f"    - {w}")
if not errors:
    print("\n  ALL CHECKS PASSED. Both phases are complete.")
