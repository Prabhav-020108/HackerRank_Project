# Regressions Log

**Current RPM/RPD Limits (Gemini Flash):**
- RPM (Requests Per Minute): 60
- RPD (Requests Per Day): 100

## Phase 4 Fast-Path Mismatches
*Log mismatches with specific field and condition that was wrong.*

### Mismatch: sample_msg_013
- **Expected:** action=mute, type=greeting
- **Got:** action=mute, type=unknown
- **Rule reason:** The user has muted this group and the message does not contain a direct mention.
- **Root cause:** The muted group rule returned a blanket "unknown" type for all muted group messages, ignoring that the text was actually a greeting.
- **Fix:** Added checks for greeting and promotional patterns inside the muted group rule to return a more accurate message_type.

### Mismatch: sample_msg_043
- **Expected:** action=mute, type=spam
- **Got:** action=mute, type=scam
- **Rule reason:** Unverified business account with high community report rate; content suppressed regardless of user engagement history.
- **Root cause:** Scam guard caught all unverified high-report businesses as "scam", even when the user relationship was marked "ignored_loan_message", which is technically spam.
- **Fix:** Distinguish spam from scam for unverified businesses by checking if `why_user_knows_account` contains "ignored" or "opted_out".

### Mismatch: sample_msg_045
- **Expected:** action=mute, type=promotion
- **Got:** action=mute, type=unknown
- **Rule reason:** The user has muted this group and the message does not contain a direct mention.
- **Root cause:** Similar to `sample_msg_013`, muted group rule blanket-returned "unknown".
- **Fix:** Added promotional pattern checking inside the muted group rule.

### Mismatch: sample_msg_048
- **Expected:** action=digest, type=business_update
- **Got:** action=mute, type=scam
- **Rule reason:** The message asks for urgent OTP or account verification through a suspicious flow.
- **Root cause:** The text mentioned "never ask for OTP" (a safety advisory), but the "OTP" keyword triggered the scam guard false-positively.
- **Fix:** Added `_SAFETY_ADVISORY_PATTERNS` to exclude messages warning about scams from being classified as scams themselves.## Phase 8 Full Run Mismatches
*Log what was misclassified, into what, and your hypothesis for why.*

## Phase 9 Edge Cases
*Log the named edge cases here.*
