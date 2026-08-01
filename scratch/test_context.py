"""
Phase 3 -- Test context hydration on real dataset rows.

Tests:
  1. All three conversation_types (personal, group, business) from sample_messages.csv
  2. Missing-data edge cases (null group_id, null business_id, empty text, missing media)
  3. DND detection
  4. @mention detection
  5. Media path resolution
"""

import sys
from pathlib import Path

# Add code/ to path so we can import context
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "code"))

import pandas as pd
from context import hydrate, load_all_tables, MessageContext

DATA_DIR = Path(__file__).resolve().parent.parent / "dataset"


def test_row(label: str, row: pd.Series):
    """Hydrate one row and print a readable summary."""
    ctx = hydrate(row, DATA_DIR)
    print(f"\n{'='*80}")
    print(f"TEST: {label}")
    print(f"{'='*80}")
    print(f"  message_id:        {ctx.message_id}")
    print(f"  user_id:           {ctx.user_id}")
    print(f"  conversation_type: {ctx.conversation_type}")
    print(f"  created_at:        {ctx.created_at}")
    print(f"  message_text:      {(ctx.message_text or '')[:100]}...")
    print(f"  forwarded_count:   {ctx.forwarded_count}")
    print(f"  is_during_dnd:     {ctx.is_during_dnd}")
    print(f"  has_direct_mention:{ctx.has_direct_mention}")

    if ctx.user:
        print(f"  USER: dnd={ctx.user.dnd_start}-{ctx.user.dnd_end}, "
              f"opened={ctx.user.messages_opened_30d}, "
              f"replied={ctx.user.messages_replied_30d}, "
              f"dismissed={ctx.user.notifications_dismissed_30d}, "
              f"reported={ctx.user.messages_reported_30d}")
    else:
        print(f"  USER: None")

    if ctx.group:
        print(f"  GROUP: {ctx.group.group_name} ({ctx.group.group_type}), "
              f"members={ctx.group.member_count}, "
              f"role={ctx.group.user_role}, "
              f"muted={ctx.group.group_muted_by_user}")
    else:
        print(f"  GROUP: None (expected for {ctx.conversation_type})")

    if ctx.business:
        print(f"  BUSINESS: {ctx.business.display_name} ({ctx.business.brand_name}), "
              f"verified={ctx.business.verified}, "
              f"reports={ctx.business.user_reports_30d}, "
              f"allows_promos={ctx.business.allows_promotions}, "
              f"why_known={ctx.business.why_user_knows_account}")
    else:
        print(f"  BUSINESS: None (expected for {ctx.conversation_type})")

    if ctx.notification_load:
        print(f"  NOTIF_LOAD: date={ctx.notification_load.date}, "
              f"sent={ctx.notification_load.notifications_sent}, "
              f"dismissed={ctx.notification_load.notifications_dismissed}")
    else:
        print(f"  NOTIF_LOAD: None")

    if ctx.media:
        print(f"  MEDIA: type={ctx.media.media_type}, "
              f"id={ctx.media.media_id}, "
              f"exists={ctx.media.file_exists}, "
              f"mime={ctx.media.mime_type}, "
              f"path={ctx.media.file_path}")
    else:
        print(f"  MEDIA: None")

    return ctx


def main():
    # Load sample_messages.csv for testing across conversation types
    sample = pd.read_csv(DATA_DIR / "sample_messages.csv")
    messages = pd.read_csv(DATA_DIR / "messages.csv")

    print("="*80)
    print("PHASE 3 CONTEXT HYDRATION TESTS")
    print("="*80)

    # --- Test 1: Personal conversation ---
    personal_rows = sample[sample["conversation_type"] == "personal"]
    if not personal_rows.empty:
        ctx = test_row("PERSONAL conversation (from sample)", personal_rows.iloc[0])
        assert ctx.conversation_type == "personal"
        assert ctx.group is None, "Personal messages should NOT have group info"
        assert ctx.user is not None, "User info should always be present"

    # --- Test 2: Group conversation ---
    group_rows = sample[sample["conversation_type"] == "group"]
    if not group_rows.empty:
        ctx = test_row("GROUP conversation (from sample)", group_rows.iloc[0])
        assert ctx.conversation_type == "group"
        assert ctx.group is not None, "Group messages MUST have group info"
        assert ctx.business is None, "Group messages should NOT have business info"

    # --- Test 3: Business conversation ---
    biz_rows = sample[sample["conversation_type"] == "business"]
    if not biz_rows.empty:
        ctx = test_row("BUSINESS conversation (from sample)", biz_rows.iloc[0])
        assert ctx.conversation_type == "business"
        assert ctx.business is not None, "Business messages MUST have business info"
        assert ctx.group is None, "Business messages should NOT have group info"

    # --- Test 4: @mention detection ---
    at_rows = sample[sample["message_text"].fillna("").str.contains("@")]
    if not at_rows.empty:
        ctx = test_row("@MENTION in message_text (from sample)", at_rows.iloc[0])
        assert ctx.has_direct_mention, f"Expected direct mention for msg with '@' in text"

    # --- Test 5: Messages with media (from real messages.csv) ---
    img_rows = messages[messages["media_type"] == "image"]
    if not img_rows.empty:
        ctx = test_row("IMAGE message (from messages.csv)", img_rows.iloc[0])
        assert ctx.media is not None, "Image messages should have media ref"
        assert ctx.media.media_type == "image"
        assert ctx.media.mime_type == "image/jpeg"
        print(f"  >>> Image file exists: {ctx.media.file_exists}")

    voice_rows = messages[messages["media_type"] == "voice"]
    if not voice_rows.empty:
        ctx = test_row("VOICE message (from messages.csv)", voice_rows.iloc[0])
        assert ctx.media is not None, "Voice messages should have media ref"
        assert ctx.media.media_type == "voice"
        assert ctx.media.mime_type == "audio/mpeg"
        print(f"  >>> Voice file exists: {ctx.media.file_exists}")

    # --- Test 6: Null text (media-only messages) ---
    null_text_rows = messages[messages["message_text"].isna()]
    if not null_text_rows.empty:
        ctx = test_row("NULL message_text (from messages.csv)", null_text_rows.iloc[0])
        assert ctx.message_text is None, "Null text should be None, not 'nan'"

    # --- Test 7: Null group_id (personal or business conv) ---
    null_group_rows = messages[messages["group_id"].isna()]
    if not null_group_rows.empty:
        ctx = test_row("NULL group_id (from messages.csv)", null_group_rows.iloc[0])
        assert ctx.group_id is None
        assert ctx.group is None

    # --- Test 8: Null business_id ---
    null_biz_rows = messages[messages["business_id"].isna()]
    if not null_biz_rows.empty:
        ctx = test_row("NULL business_id (from messages.csv)", null_biz_rows.iloc[0])
        assert ctx.business_id is None
        assert ctx.business is None

    # --- Test 9: DND check ---
    # Find a message during typical DND hours (e.g. 22:00+)
    late_msgs = messages[messages["created_at"].str.contains(" 22:") | messages["created_at"].str.contains(" 23:")]
    if not late_msgs.empty:
        ctx = test_row("LATE NIGHT message (DND check)", late_msgs.iloc[0])
        print(f"  >>> DND expected=True, actual={ctx.is_during_dnd}")

    # --- Test 10: Run on ALL 110 messages.csv rows to check no crashes ---
    print(f"\n{'='*80}")
    print("STRESS TEST: Hydrating ALL {len(messages)} messages.csv rows...")
    errors = []
    for idx, row in messages.iterrows():
        try:
            ctx = hydrate(row, DATA_DIR)
        except Exception as e:
            errors.append(f"  CRASH on {row['message_id']}: {e}")
    if errors:
        print(f"FAILED: {len(errors)} rows crashed:")
        for e in errors:
            print(e)
    else:
        print(f"PASSED: All {len(messages)} rows hydrated without errors.")

    # --- Summary stats ---
    print(f"\n{'='*80}")
    print("SUMMARY STATS across all messages.csv rows:")
    all_ctxs = [hydrate(row, DATA_DIR) for _, row in messages.iterrows()]
    print(f"  Total messages:      {len(all_ctxs)}")
    print(f"  With user info:      {sum(1 for c in all_ctxs if c.user)}")
    print(f"  With group info:     {sum(1 for c in all_ctxs if c.group)}")
    print(f"  With business info:  {sum(1 for c in all_ctxs if c.business)}")
    print(f"  With notif load:     {sum(1 for c in all_ctxs if c.notification_load)}")
    print(f"  With media ref:      {sum(1 for c in all_ctxs if c.media)}")
    print(f"  During DND:          {sum(1 for c in all_ctxs if c.is_during_dnd)}")
    print(f"  With @mention:       {sum(1 for c in all_ctxs if c.has_direct_mention)}")
    print(f"  Media files exist:   {sum(1 for c in all_ctxs if c.media and c.media.file_exists)}")

    print("\nAll Phase 3 tests complete.")


if __name__ == "__main__":
    main()
