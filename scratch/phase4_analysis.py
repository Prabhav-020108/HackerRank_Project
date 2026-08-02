"""Phase 4 deep analysis: study sample messages + all messages to design
deterministic fast-path rules."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "code"))

import pandas as pd
from context import hydrate, load_all_tables

DATA_DIR = Path(__file__).resolve().parent.parent / "dataset"

sample = pd.read_csv(DATA_DIR / "sample_messages.csv")
messages = pd.read_csv(DATA_DIR / "messages.csv")

# --- 1. Full sample analysis: for each sample row, hydrate and show
#     the key signals alongside the expected action/type ---
print("=" * 120)
print("SAMPLE MESSAGES -- FULL SIGNAL ANALYSIS")
print("=" * 120)

for _, row in sample.iterrows():
    ctx = hydrate(row, DATA_DIR)
    print(f"\n--- {ctx.message_id} ---")
    print(f"  EXPECTED: action={row['action']}, type={row['message_type']}")
    print(f"  conv_type={ctx.conversation_type}, user={ctx.user_id}, sender={ctx.sender_user_id}")
    print(f"  text_preview: {(ctx.message_text or '')[:120]}")
    print(f"  forwarded_count={ctx.forwarded_count}, media={ctx.media_type or 'none'}")
    print(f"  is_during_dnd={ctx.is_during_dnd}, has_direct_mention={ctx.has_direct_mention}")
    if ctx.group:
        print(f"  GROUP: name={ctx.group.group_name}, type={ctx.group.group_type}, "
              f"muted={ctx.group.group_muted_by_user}, role={ctx.group.user_role}")
    if ctx.business:
        print(f"  BIZ: name={ctx.business.display_name}, verified={ctx.business.verified}, "
              f"reports={ctx.business.user_reports_30d}, allows_promos={ctx.business.allows_promotions}, "
              f"why_known={ctx.business.why_user_knows_account}")
    if ctx.user:
        print(f"  USER: reported={ctx.user.messages_reported_30d}, "
              f"dismissed={ctx.user.notifications_dismissed_30d}")

# --- 2. Messages.csv: analyze all scam/spam-like patterns ---
print("\n\n" + "=" * 120)
print("MESSAGES.CSV -- SIGNAL ANALYSIS FOR RULE DESIGN")
print("=" * 120)

# Business messages: check verified vs unverified, report rates
print("\n--- BUSINESS MESSAGES ---")
biz_msgs = messages[messages["conversation_type"] == "business"]
for _, row in biz_msgs.iterrows():
    ctx = hydrate(row, DATA_DIR)
    biz = ctx.business
    if biz:
        print(f"  {ctx.message_id}: verified={biz.verified}, reports={biz.user_reports_30d}, "
              f"allows_promos={biz.allows_promotions}, why_known={biz.why_user_knows_account}, "
              f"text: {(ctx.message_text or '')[:80]}")

# Group messages: muted groups
print("\n--- MUTED GROUP MESSAGES ---")
group_msgs = messages[messages["conversation_type"] == "group"]
for _, row in group_msgs.iterrows():
    ctx = hydrate(row, DATA_DIR)
    if ctx.group and ctx.group.group_muted_by_user:
        print(f"  {ctx.message_id}: group={ctx.group.group_name}, muted=True, "
              f"mention={ctx.has_direct_mention}, text: {(ctx.message_text or '')[:80]}")

# Personal messages: check for scam patterns
print("\n--- PERSONAL MESSAGES ---")
personal_msgs = messages[messages["conversation_type"] == "personal"]
for _, row in personal_msgs.iterrows():
    ctx = hydrate(row, DATA_DIR)
    print(f"  {ctx.message_id}: sender={ctx.sender_user_id}, user={ctx.user_id}, "
          f"forwarded={ctx.forwarded_count}, text: {(ctx.message_text or '')[:100]}")

# High forwarded count
print("\n--- HIGH FORWARDED COUNT (>= 3) ---")
for _, row in messages.iterrows():
    if row.get("forwarded_count", 0) >= 3:
        ctx = hydrate(row, DATA_DIR)
        print(f"  {ctx.message_id}: fwd_count={ctx.forwarded_count}, conv={ctx.conversation_type}, "
              f"text: {(ctx.message_text or '')[:80]}")

# DND messages
print("\n--- DND MESSAGES ---")
for _, row in messages.iterrows():
    ctx = hydrate(row, DATA_DIR)
    if ctx.is_during_dnd:
        print(f"  {ctx.message_id}: conv={ctx.conversation_type}, "
              f"text: {(ctx.message_text or '')[:100]}")

# Check message_history and message_events structure
print("\n\n" + "=" * 120)
print("MESSAGE_HISTORY.CSV -- STRUCTURE")
print("=" * 120)
mh = pd.read_csv(DATA_DIR / "message_history.csv")
print(f"Columns: {list(mh.columns)}")
print(f"Shape: {mh.shape}")
print(f"conversation_type: {mh['conversation_type'].value_counts().to_dict()}")
print(mh.head(5).to_string())

print("\n\n" + "=" * 120)
print("MESSAGE_EVENTS.CSV -- STRUCTURE")
print("=" * 120)
me = pd.read_csv(DATA_DIR / "message_events.csv")
print(f"Columns: {list(me.columns)}")
print(f"Shape: {me.shape}")
print(f"event_type: {me['event_type'].value_counts().to_dict()}")
print(me.head(10).to_string())

# Check if sender_user_id is in users.csv for personal messages
# (if sender is not in users.csv, it's an unknown sender — potential scam signal)
print("\n\n" + "=" * 120)
print("SENDER TRUST ANALYSIS")
print("=" * 120)
users = pd.read_csv(DATA_DIR / "users.csv")
user_ids = set(users["user_id"].tolist())
for _, row in messages.iterrows():
    if row["conversation_type"] == "personal":
        sender = row.get("sender_user_id")
        in_users = sender in user_ids if pd.notna(sender) else False
        ctx = hydrate(row, DATA_DIR)
        print(f"  {row['message_id']}: sender={sender}, sender_in_users={in_users}, "
              f"text: {(ctx.message_text or '')[:100]}")
