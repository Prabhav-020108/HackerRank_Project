import pandas as pd
import os
import glob

dataset_dir = r"C:\Users\Prabhav\HackerRank_Project\dataset"
csv_files = glob.glob(os.path.join(dataset_dir, "*.csv"))

print("=== DATA RECON ===\n")

for file in csv_files:
    file_name = os.path.basename(file)
    print(f"\n--- {file_name} ---")
    try:
        df = pd.read_csv(file)
        print(f"Columns: {list(df.columns)}")
        print(f"Dtypes:\n{df.dtypes}")
        print(f"IS_NA:\n{df.isna().sum()}")
        print(f"Head:\n{df.head(2)}")
        
        # Specific checks
        if file_name == "messages.csv":
            print("\nMessages Edge Cases:")
            print("Null group_id:", df['group_id'].isna().sum() if 'group_id' in df.columns else 'N/A')
            print("Null business_id:", df['business_id'].isna().sum() if 'business_id' in df.columns else 'N/A')
            print("Empty message_text:", df['message_text'].isna().sum() if 'message_text' in df.columns else 'N/A')
            
    except Exception as e:
        print(f"Error reading {file_name}: {e}")

print("\n--- Media Check ---")
images_df = pd.read_csv(os.path.join(dataset_dir, "images.csv"))
print("Images missing files:", images_df['file_path'].apply(lambda x: not os.path.exists(os.path.join(dataset_dir, "media", "images", x))).sum())

voice_df = pd.read_csv(os.path.join(dataset_dir, "voice_notes.csv"))
print("Voice notes missing files:", voice_df['file_path'].apply(lambda x: not os.path.exists(os.path.join(dataset_dir, "media", "audio", x))).sum())

print("\n--- sample_messages.csv Analysis ---")
sample_df = pd.read_csv(os.path.join(dataset_dir, "sample_messages.csv"))
print("Average reason length:", sample_df['reason'].str.len().mean())
print("Confidence distribution:\n", sample_df['confidence'].value_counts(bins=5))
if 'evidence_message_ids' in sample_df.columns:
    print("Evidence message IDs none:", (sample_df['evidence_message_ids'] == 'none').sum(), "/", len(sample_df))
    print("Evidence message IDs single:", sample_df['evidence_message_ids'].str.count(',') == 0, "/", len(sample_df))
