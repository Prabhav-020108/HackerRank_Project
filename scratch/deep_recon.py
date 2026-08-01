"""Deep inspection for Phase 3 context hydration design."""
import pandas as pd
import os

d = r"C:\Users\Prabhav\HackerRank_Project\dataset"

# 1. Users: check do_not_disturb_window format
users = pd.read_csv(f"{d}/users.csv")
print("=== USERS ===")
print(users.to_string())

# 2. Messages: check @mention patterns, conversation_type values, timestamps
msgs = pd.read_csv(f"{d}/messages.csv")
print("\n=== MESSAGES conversation_type value_counts ===")
print(msgs['conversation_type'].value_counts())
print("\n=== MESSAGES media_type value_counts ===")
print(msgs['media_type'].value_counts(dropna=False))
print("\n=== MESSAGES sample with text containing @ ===")
at_msgs = msgs[msgs['message_text'].fillna('').str.contains('@')]
print(at_msgs[['message_id','message_text','conversation_type','group_id']].head(10).to_string())

# 3. Sample messages: check @mention patterns too
sample = pd.read_csv(f"{d}/sample_messages.csv")
print("\n=== SAMPLE conversation_type value_counts ===")
print(sample['conversation_type'].value_counts())
at_sample = sample[sample['message_text'].fillna('').str.contains('@')]
print("\n=== SAMPLE messages with @ ===")
print(at_sample[['message_id','message_text','conversation_type','group_id']].to_string())

# 4. Daily notification summary: check date format, how many dates per user
dns = pd.read_csv(f"{d}/daily_notification_summary.csv")
print("\n=== DAILY_NOTIFICATION_SUMMARY sample ===")
print(dns.head(10).to_string())
print("\n=== dates range ===")
print(f"Min: {dns['date'].min()}, Max: {dns['date'].max()}")
print(f"Unique users: {dns['user_id'].nunique()}, Unique dates: {dns['date'].nunique()}")

# 5. Messages created_at format
print("\n=== MESSAGES created_at samples ===")
print(msgs['created_at'].head(10).to_list())

# 6. Images and voice notes - actual file listing
print("\n=== IMAGES.CSV ===")
img = pd.read_csv(f"{d}/images.csv")
print(img.to_string())
print("\n=== VOICE_NOTES.CSV ===")
vn = pd.read_csv(f"{d}/voice_notes.csv")
print(vn.to_string())

# 7. Check which files actually exist
print("\n=== Media files that EXIST ===")
img_dir = f"{d}/media/images"
audio_dir = f"{d}/media/audio"
if os.path.exists(img_dir):
    print("Images:", os.listdir(img_dir))
if os.path.exists(audio_dir):
    print("Audio:", os.listdir(audio_dir))

# 8. Business accounts - check verified values
ba = pd.read_csv(f"{d}/business_accounts.csv")
print("\n=== BUSINESS_ACCOUNTS verified value_counts ===")
print(ba['verified'].value_counts())
print("\n=== BUSINESS_ACCOUNTS user_reports_30d stats ===")
print(ba['user_reports_30d'].describe())

# 9. Group members - check group_muted_by_user values
gm = pd.read_csv(f"{d}/group_members.csv")
print("\n=== GROUP_MEMBERS group_muted_by_user value_counts ===")
print(gm['group_muted_by_user'].value_counts())

# 10. Sample messages full output fields
print("\n=== SAMPLE full output examples ===")
print(sample[['message_id','action','message_type','reason','confidence','evidence_message_ids']].to_string())
