"""
Phase 3 -- Context Hydration.

Given one raw message row from messages.csv, produce a single fully-hydrated
context dict that carries every piece of joined information the downstream
layers (fast-path rules, retrieval, Gemini prompt, decision overrides) need.

This module loads all reference CSVs once at import time (they're small) and
exposes a single public function:

    hydrate(msg_row: pd.Series, data_dir: Path) -> dict

The returned dict has a stable, documented key set -- see MessageContext below.
Every missing-data edge case from Phase 1 is handled explicitly so that
downstream code never has to worry about KeyErrors or NaN surprises.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, time
from pathlib import Path
from typing import Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Module-level caches -- loaded once per process via load_all_tables()
# ---------------------------------------------------------------------------
_tables: dict[str, pd.DataFrame] = {}
_loaded = False


def load_all_tables(data_dir: Path) -> None:
    """Load every reference CSV into module-level dicts, indexed for fast
    lookup.  Called once; subsequent calls are no-ops."""
    global _tables, _loaded
    if _loaded:
        return

    _tables["users"] = pd.read_csv(data_dir / "users.csv").set_index("user_id")
    _tables["groups"] = pd.read_csv(data_dir / "groups.csv").set_index("group_id")
    _tables["group_members"] = pd.read_csv(data_dir / "group_members.csv")
    _tables["business_accounts"] = pd.read_csv(data_dir / "business_accounts.csv").set_index("business_id")
    _tables["user_business_history"] = pd.read_csv(data_dir / "user_business_history.csv")
    _tables["daily_notification_summary"] = pd.read_csv(data_dir / "daily_notification_summary.csv")
    _tables["images"] = pd.read_csv(data_dir / "images.csv").set_index("image_id")
    _tables["voice_notes"] = pd.read_csv(data_dir / "voice_notes.csv").set_index("voice_note_id")

    _loaded = True


# ---------------------------------------------------------------------------
# Data classes for structured context
# ---------------------------------------------------------------------------

@dataclass
class UserInfo:
    """User-level notification behaviour from users.csv."""
    user_id: str
    dnd_start: Optional[str] = None        # "HH:MM" or None
    dnd_end: Optional[str] = None          # "HH:MM" or None
    messages_opened_30d: int = 0
    messages_replied_30d: int = 0
    notifications_dismissed_30d: int = 0
    messages_reported_30d: int = 0


@dataclass
class GroupInfo:
    """Group metadata from groups.csv + this user's membership from
    group_members.csv."""
    group_id: str
    group_name: str = ""
    group_type: str = ""
    member_count: int = 0
    admin_count: int = 0
    messages_30d: int = 0
    # User-specific membership fields
    user_role: str = "member"
    user_messages_sent_30d: int = 0
    user_messages_read_30d: int = 0
    user_replies_sent_30d: int = 0
    user_notifications_dismissed_30d: int = 0
    group_muted_by_user: bool = False


@dataclass
class BusinessInfo:
    """Business metadata from business_accounts.csv + this user's history
    from user_business_history.csv."""
    business_id: str
    display_name: str = ""
    brand_name: str = ""
    category: str = ""
    verified: bool = False
    official_domain: Optional[str] = None
    domain_used_by_sender: Optional[str] = None
    account_age_days: int = 0
    messages_sent_30d: int = 0
    user_reports_30d: int = 0
    domain_used_by_sender_age_days: int = 0
    # User-specific history
    why_user_knows_account: Optional[str] = None
    allows_promotions: bool = False
    activity_count_180d: int = 0
    user_messages_opened_30d: int = 0
    user_messages_dismissed_30d: int = 0
    user_messages_replied_30d: int = 0


@dataclass
class NotificationLoad:
    """Today's (or most recent available) notification summary for this user
    from daily_notification_summary.csv."""
    date: Optional[str] = None
    notifications_sent: int = 0
    notifications_dismissed: int = 0


@dataclass
class MediaRef:
    """Resolved media file reference."""
    media_type: str = ""                   # "image" or "voice"
    media_id: str = ""
    file_path: Optional[str] = None        # absolute path, or None if missing
    mime_type: Optional[str] = None        # "image/jpeg" or "audio/mpeg"
    file_exists: bool = False


@dataclass
class MessageContext:
    """The fully-hydrated context bundle for one message.  Every downstream
    layer reads from this single object."""
    # Core message fields
    message_id: str = ""
    user_id: str = ""
    conversation_type: str = ""            # "personal" | "group" | "business"
    group_id: Optional[str] = None
    business_id: Optional[str] = None
    sender_user_id: Optional[str] = None
    created_at: Optional[str] = None
    message_text: Optional[str] = None
    media_type: Optional[str] = None
    media_id: Optional[str] = None
    forwarded_count: int = 0

    # Derived fields
    is_during_dnd: bool = False
    has_direct_mention: bool = False       # @user_id found in message_text

    # Joined context
    user: Optional[UserInfo] = None
    group: Optional[GroupInfo] = None
    business: Optional[BusinessInfo] = None
    notification_load: Optional[NotificationLoad] = None
    media: Optional[MediaRef] = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_dnd_window(window_str: str) -> tuple[str, str]:
    """Parse 'HH:MM-HH:MM' into (start, end) strings."""
    parts = window_str.strip().split("-")
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return "", ""


def _is_during_dnd(created_at_str: str, dnd_start_str: str, dnd_end_str: str) -> bool:
    """Check if the message's timestamp falls within the user's DND window.

    DND windows typically span midnight (e.g. 22:00-07:00), meaning the user
    is in DND from 22:00 to 23:59 and from 00:00 to 07:00.
    """
    try:
        # created_at format: "2026-07-30 22:19"
        msg_time = datetime.strptime(created_at_str.strip(), "%Y-%m-%d %H:%M").time()
        start = datetime.strptime(dnd_start_str.strip(), "%H:%M").time()
        end = datetime.strptime(dnd_end_str.strip(), "%H:%M").time()
    except (ValueError, AttributeError):
        return False

    if start <= end:
        # Same-day window (rare in this dataset but handle it)
        return start <= msg_time <= end
    else:
        # Overnight window (e.g. 22:00 -> 07:00)
        return msg_time >= start or msg_time <= end


def _check_direct_mention(message_text: Optional[str], user_id: str) -> bool:
    """Check if the message text contains a direct @mention of this user.

    Pattern observed in data: '@u_007', '@u_010', etc. — the @ is followed
    by the exact user_id string.
    """
    if not message_text or not isinstance(message_text, str):
        return False
    # Use word boundary to avoid partial matches like @u_0070
    pattern = r"@" + re.escape(user_id) + r"(?:\s|$|[^a-zA-Z0-9_])"
    return bool(re.search(pattern, message_text))


def _get_user_info(user_id: str) -> Optional[UserInfo]:
    """Look up user info from users.csv."""
    users = _tables.get("users")
    if users is None or user_id not in users.index:
        return None

    row = users.loc[user_id]
    dnd_start, dnd_end = _parse_dnd_window(str(row.get("do_not_disturb_window", "")))

    return UserInfo(
        user_id=user_id,
        dnd_start=dnd_start or None,
        dnd_end=dnd_end or None,
        messages_opened_30d=int(row.get("messages_opened_30d", 0)),
        messages_replied_30d=int(row.get("messages_replied_30d", 0)),
        notifications_dismissed_30d=int(row.get("notifications_dismissed_30d", 0)),
        messages_reported_30d=int(row.get("messages_reported_30d", 0)),
    )


def _get_group_info(group_id: str, user_id: str) -> Optional[GroupInfo]:
    """Look up group metadata + this user's membership."""
    groups = _tables.get("groups")
    gm = _tables.get("group_members")
    if groups is None or gm is None:
        return None
    if group_id not in groups.index:
        return None

    g = groups.loc[group_id]
    info = GroupInfo(
        group_id=group_id,
        group_name=str(g.get("group_name", "")),
        group_type=str(g.get("group_type", "")),
        member_count=int(g.get("member_count", 0)),
        admin_count=int(g.get("admin_count", 0)),
        messages_30d=int(g.get("messages_30d", 0)),
    )

    # Find this user's membership row
    mask = (gm["group_id"] == group_id) & (gm["user_id"] == user_id)
    membership = gm[mask]
    if not membership.empty:
        m = membership.iloc[0]
        info.user_role = str(m.get("role", "member"))
        info.user_messages_sent_30d = int(m.get("messages_sent_30d", 0))
        info.user_messages_read_30d = int(m.get("messages_read_30d", 0))
        info.user_replies_sent_30d = int(m.get("replies_sent_30d", 0))
        info.user_notifications_dismissed_30d = int(m.get("notifications_dismissed_30d", 0))
        info.group_muted_by_user = bool(int(m.get("group_muted_by_user", 0)))

    return info


def _get_business_info(business_id: str, user_id: str) -> Optional[BusinessInfo]:
    """Look up business metadata + this user's history with that business."""
    ba = _tables.get("business_accounts")
    ubh = _tables.get("user_business_history")
    if ba is None or ubh is None:
        return None
    if business_id not in ba.index:
        return None

    b = ba.loc[business_id]
    info = BusinessInfo(
        business_id=business_id,
        display_name=str(b.get("display_name", "")),
        brand_name=str(b.get("brand_name", "")),
        category=str(b.get("category", "")),
        verified=bool(int(b.get("verified", 0))),
        official_domain=str(b.get("official_domain", "")) if pd.notna(b.get("official_domain")) else None,
        domain_used_by_sender=str(b.get("domain_used_by_sender", "")) if pd.notna(b.get("domain_used_by_sender")) else None,
        account_age_days=int(b.get("account_age_days", 0)),
        messages_sent_30d=int(b.get("messages_sent_30d", 0)),
        user_reports_30d=int(b.get("user_reports_30d", 0)),
        domain_used_by_sender_age_days=int(b.get("domain_used_by_sender_age_days", 0)),
    )

    # Find this user's history with this business
    mask = (ubh["user_id"] == user_id) & (ubh["business_id"] == business_id)
    history = ubh[mask]
    if not history.empty:
        h = history.iloc[0]
        info.why_user_knows_account = str(h.get("why_user_knows_account", "")) if pd.notna(h.get("why_user_knows_account")) else None
        info.allows_promotions = bool(int(h.get("allows_promotions", 0)))
        info.activity_count_180d = int(h.get("activity_count_180d", 0))
        info.user_messages_opened_30d = int(h.get("messages_opened_30d", 0))
        info.user_messages_dismissed_30d = int(h.get("messages_dismissed_30d", 0))
        info.user_messages_replied_30d = int(h.get("messages_replied_30d", 0))

    return info


def _get_notification_load(user_id: str, created_at_str: str) -> Optional[NotificationLoad]:
    """Get the notification summary for this user on the message's date,
    falling back to the most recent available date if the exact date isn't
    in the summary table.

    The daily_notification_summary covers 2026-07-04 to 2026-07-17, while
    messages are from 2026-07-20+.  So we always fall back to the latest
    available date for this user, which is the best proxy for "current load".
    """
    dns = _tables.get("daily_notification_summary")
    if dns is None:
        return None

    user_rows = dns[dns["user_id"] == user_id]
    if user_rows.empty:
        return None

    # Try exact date match first
    try:
        msg_date = created_at_str.strip()[:10]  # "2026-07-30" from "2026-07-30 22:19"
    except (AttributeError, TypeError):
        msg_date = None

    if msg_date is not None:
        exact = user_rows[user_rows["date"] == msg_date]
        if not exact.empty:
            r = exact.iloc[0]
            return NotificationLoad(
                date=str(r["date"]),
                notifications_sent=int(r["notifications_sent"]),
                notifications_dismissed=int(r["notifications_dismissed"]),
            )

    # Fall back to the most recent date available for this user
    latest = user_rows.sort_values("date", ascending=False).iloc[0]
    return NotificationLoad(
        date=str(latest["date"]),
        notifications_sent=int(latest["notifications_sent"]),
        notifications_dismissed=int(latest["notifications_dismissed"]),
    )


def _get_media_ref(media_type_str: str, media_id: str, data_dir: Path) -> Optional[MediaRef]:
    """Resolve a media reference to an actual file path + mime type."""
    if not media_type_str or not isinstance(media_type_str, str) or media_type_str.lower() == "nan":
        return None
    if not media_id or not isinstance(media_id, str) or media_id.lower() == "nan":
        return None

    media_type_str = media_type_str.strip().lower()

    ref = MediaRef(media_type=media_type_str, media_id=media_id)

    if media_type_str == "image":
        images = _tables.get("images")
        if images is not None and media_id in images.index:
            rel_path = str(images.loc[media_id, "file_path"])
            abs_path = str(data_dir / rel_path)
            ref.file_path = abs_path
            ref.mime_type = "image/jpeg"
            ref.file_exists = os.path.isfile(abs_path)
    elif media_type_str == "voice":
        vn = _tables.get("voice_notes")
        if vn is not None and media_id in vn.index:
            rel_path = str(vn.loc[media_id, "file_path"])
            abs_path = str(data_dir / rel_path)
            ref.file_path = abs_path
            ref.mime_type = "audio/mpeg"
            ref.file_exists = os.path.isfile(abs_path)

    return ref


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def hydrate(msg_row: pd.Series, data_dir: Path) -> MessageContext:
    """Turn a raw messages.csv row into a fully-hydrated MessageContext.

    Parameters
    ----------
    msg_row : pd.Series
        One row from messages.csv (or sample_messages.csv).
    data_dir : Path
        Path to the dataset/ directory.

    Returns
    -------
    MessageContext with all available joined context populated.
    """
    # Ensure reference tables are loaded
    load_all_tables(data_dir)

    # --- Core fields (handle NaN gracefully) ---
    message_id = str(msg_row.get("message_id", ""))
    user_id = str(msg_row.get("user_id", ""))
    conversation_type = str(msg_row.get("conversation_type", ""))
    group_id = str(msg_row.get("group_id", "")) if pd.notna(msg_row.get("group_id")) else None
    business_id = str(msg_row.get("business_id", "")) if pd.notna(msg_row.get("business_id")) else None
    sender_user_id = str(msg_row.get("sender_user_id", "")) if pd.notna(msg_row.get("sender_user_id")) else None
    created_at = str(msg_row.get("created_at", "")) if pd.notna(msg_row.get("created_at")) else None
    message_text = str(msg_row.get("message_text", "")) if pd.notna(msg_row.get("message_text")) else None
    media_type = str(msg_row.get("media_type", "")) if pd.notna(msg_row.get("media_type")) else None
    media_id = str(msg_row.get("media_id", "")) if pd.notna(msg_row.get("media_id")) else None
    forwarded_count = int(msg_row.get("forwarded_count", 0))

    # --- User info ---
    user_info = _get_user_info(user_id)

    # --- DND check ---
    is_during_dnd = False
    if user_info and user_info.dnd_start and user_info.dnd_end and created_at:
        is_during_dnd = _is_during_dnd(created_at, user_info.dnd_start, user_info.dnd_end)

    # --- Direct mention check ---
    has_direct_mention = _check_direct_mention(message_text, user_id)

    # --- Group info (only for group conversations) ---
    group_info = None
    if conversation_type == "group" and group_id:
        group_info = _get_group_info(group_id, user_id)

    # --- Business info (only for business conversations) ---
    business_info = None
    if conversation_type == "business" and business_id:
        business_info = _get_business_info(business_id, user_id)

    # --- Notification load ---
    notification_load = None
    if created_at:
        notification_load = _get_notification_load(user_id, created_at)

    # --- Media reference ---
    media_ref = None
    if media_type and media_id:
        media_ref = _get_media_ref(media_type, media_id, data_dir)

    return MessageContext(
        message_id=message_id,
        user_id=user_id,
        conversation_type=conversation_type,
        group_id=group_id,
        business_id=business_id,
        sender_user_id=sender_user_id,
        created_at=created_at,
        message_text=message_text,
        media_type=media_type,
        media_id=media_id,
        forwarded_count=forwarded_count,
        is_during_dnd=is_during_dnd,
        has_direct_mention=has_direct_mention,
        user=user_info,
        group=group_info,
        business=business_info,
        notification_load=notification_load,
        media=media_ref,
    )


def context_to_dict(ctx: MessageContext) -> dict:
    """Convert a MessageContext to a plain dict for serialisation or prompt
    building.  Nested dataclasses are converted recursively."""
    return asdict(ctx)
