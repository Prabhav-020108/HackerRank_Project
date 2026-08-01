# Phase 1 Data Recon Notes

## Data Dictionary & Join Keys
*   **messages.csv**: Core message table. Join key: `message_id`.
*   **users.csv**: User notification behavior (e.g., `do_not_disturb_window`, `messages_reported_30d`, `notifications_dismissed_30d`). Joined to messages via `user_id`.
*   **groups.csv**: Group metadata. Joined to messages via `group_id`.
*   **group_members.csv**: User-group relationships (e.g., `group_muted_by_user`). Joined to messages via `group_id` and `user_id`.
*   **business_accounts.csv**: Business metadata (e.g., `verified`). Joined to messages via `business_id`.
*   **user_business_history.csv**: User history with businesses. Joined to messages via `user_id` and `business_id`.
*   **daily_notification_summary.csv**: Daily notifications per user (e.g., `notifications_sent`). Joined to messages via `user_id` and date from `created_at`.
*   **message_history.csv**: Historical messages for BM25 retrieval. Same structure as messages.csv.
*   **message_events.csv**: Reactions to history (e.g., `message_opened`, `message_replied`). Joined to history via `message_id`.
*   **images.csv**: Image paths. Joined to messages via `media_id`.
*   **voice_notes.csv**: Voice note paths. Joined to messages via `media_id`.

## Edge Cases to Defend Against
*   **Missing FKs in Messages**: `group_id` (47 nulls), `business_id` (80 nulls), `message_text` (8 nulls), `media_type`/`media_id` (87 nulls).
*   **Missing Media Files**: 20 images and 13 voice notes have entries but lack actual files in `dataset/media/...`.
*   **Missing Values in other tables**: `user_business_history.csv` has 92 null `promotions_opted_out_at` and 42 null `last_reply_at`. `message_events.csv` has 134 null `reaction_time_minutes`.

## Specific Checks
*   **@-Mentions**: `users.csv` does NOT contain a display name. Thus, direct mentions must be derived by looking for `@<user_id>` in the `message_text`.
*   **Media Extensions**: Images use `.jpg` (mime_type: `image/jpeg`). Voice notes use `.mp3` (mime_type: `audio/mp3`). 
*   **sample_messages.csv Tone**: 
    *   Reasons are ~82 characters on average (concise, specific).
    *   `evidence_message_ids` are always a single ID (or `"none"`).
    *   `confidence` values are decisive, typically distributed between 0.77 and 0.91 (never exactly 0.5).
