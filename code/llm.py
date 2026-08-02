"""
Phase 6 -- Gemini Multimodal Integration.

A single Gemini Flash call per message that reliably returns valid structured
JSON for text, image, and voice inputs.

SDK verified against google-genai 2.16.0:
  - client.models.generate_content(model=..., contents=..., config=...)
  - types.Part.from_bytes(data=bytes, mime_type=str) for inline media
  - GenerateContentConfig(response_mime_type="application/json",
                          response_schema=RoutingDecision) for structured output

Public API:
    classify(ctx: MessageContext, evidence_context: str) -> dict
"""

from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types

from context import MessageContext

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()

_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

# Lazy-initialized client
_client: Optional[genai.Client] = None


def _get_client() -> genai.Client:
    """Lazy-initialize the Gemini client.

    Handles SSL certificate issues on corporate/proxy networks by
    setting HTTPX to use the system certificate store when certifi fails.
    """
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set in environment")

        # Fix SSL issues: try system cert store if certifi fails
        try:
            import ssl
            import httpx
            # Create an SSL context that uses the system certificate store
            ssl_ctx = ssl.create_default_context()
            # Try loading default system certs (works on Windows, macOS, Linux)
            ssl_ctx.load_default_certs()
            http_client = httpx.Client(verify=ssl_ctx)
            _client = genai.Client(api_key=api_key, http_options={"client": http_client})
        except Exception:
            # Fallback: just use the default client
            _client = genai.Client(api_key=api_key)
    return _client


# ---------------------------------------------------------------------------
# Response schema for structured output
# ---------------------------------------------------------------------------

# We define the schema as a plain dict matching JSON Schema,
# which google-genai accepts for response_schema.
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "message_type": {
            "type": "string",
            "enum": [
                "personal", "urgent", "event", "payment",
                "business_update", "promotion", "greeting",
                "forward", "spam", "scam", "unknown",
            ],
        },
        "action": {
            "type": "string",
            "enum": ["notify", "digest", "mute"],
        },
        "reason": {
            "type": "string",
            "description": "Short, specific, human-readable explanation for the routing decision. Reference specific details from the message.",
        },
        "confidence": {
            "type": "number",
            "description": "Confidence in the decision, between 0.0 and 1.0.",
        },
    },
    "required": ["message_type", "action", "reason", "confidence"],
}


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a WhatsApp message notification router. For each incoming message, you must decide:
- action: "notify" (interrupt user now), "digest" (show later), or "mute" (suppress)
- message_type: classify the message into one of the allowed types
- reason: a SHORT, SPECIFIC explanation grounded in the actual message content (no generic templates)
- confidence: a number between 0.0 and 1.0

CRITICAL RULES:
1. The REASON must reference specific details from the message. Never say generic things like "this is spam" — say WHY.
2. Personalize decisions using the user context and historical evidence provided.
3. Scam/phishing messages (OTP requests, fake verification, account blocking threats) → always mute.
4. Messages from muted groups without @-mentions → mute.
5. During Do-Not-Disturb hours, only truly urgent messages should notify — others should digest.
6. A sale poster useful to one user can be noise to another — use the user's history to decide.
7. Direct @-mentions in groups should almost always notify regardless of group mute status.
8. Your output is a DRAFT — downstream code may override your decision based on additional signals.

Keep reasons concise (under 100 characters ideally). Be decisive with confidence — avoid 0.5."""


def _build_user_prompt(ctx: MessageContext, evidence_context: str) -> str:
    """Build the user prompt with context and evidence."""
    parts = []

    # --- Message info ---
    parts.append("=== INCOMING MESSAGE ===")
    parts.append(f"Message ID: {ctx.message_id}")
    parts.append(f"Conversation type: {ctx.conversation_type}")
    parts.append(f"Timestamp: {ctx.created_at}")
    parts.append(f"Forwarded count: {ctx.forwarded_count}")

    if ctx.message_text:
        parts.append(f"Text: \"{ctx.message_text}\"")
    elif ctx.media_type:
        parts.append(f"Text: [No text — see attached {ctx.media_type} file below]")
    else:
        parts.append("Text: [empty]")

    # --- User context ---
    parts.append("\n=== USER CONTEXT ===")
    if ctx.user:
        parts.append(f"Messages opened (30d): {ctx.user.messages_opened_30d}")
        parts.append(f"Messages replied (30d): {ctx.user.messages_replied_30d}")
        parts.append(f"Notifications dismissed (30d): {ctx.user.notifications_dismissed_30d}")
        parts.append(f"Messages reported (30d): {ctx.user.messages_reported_30d}")
    parts.append(f"Currently in Do-Not-Disturb: {ctx.is_during_dnd}")
    parts.append(f"Direct @-mention of user: {ctx.has_direct_mention}")

    if ctx.notification_load:
        parts.append(f"Notifications sent today: {ctx.notification_load.notifications_sent}")
        parts.append(f"Notifications dismissed today: {ctx.notification_load.notifications_dismissed}")

    # --- Group context ---
    if ctx.group:
        parts.append("\n=== GROUP CONTEXT ===")
        parts.append(f"Group: {ctx.group.group_name} ({ctx.group.group_type})")
        parts.append(f"Members: {ctx.group.member_count}")
        parts.append(f"User role: {ctx.group.user_role}")
        parts.append(f"Group muted by user: {ctx.group.group_muted_by_user}")
        parts.append(f"User messages read (30d): {ctx.group.user_messages_read_30d}")
        parts.append(f"User replies sent (30d): {ctx.group.user_replies_sent_30d}")
        parts.append(f"User notifications dismissed (30d): {ctx.group.user_notifications_dismissed_30d}")

    # --- Business context ---
    if ctx.business:
        parts.append("\n=== BUSINESS CONTEXT ===")
        parts.append(f"Business: {ctx.business.display_name} ({ctx.business.brand_name})")
        parts.append(f"Category: {ctx.business.category}")
        parts.append(f"Verified: {ctx.business.verified}")
        parts.append(f"Account age: {ctx.business.account_age_days} days")
        parts.append(f"User reports (30d): {ctx.business.user_reports_30d}")
        parts.append(f"User relationship: {ctx.business.why_user_knows_account or 'none'}")
        parts.append(f"Allows promotions: {ctx.business.allows_promotions}")
        parts.append(f"User messages opened (30d): {ctx.business.user_messages_opened_30d}")
        parts.append(f"User messages dismissed (30d): {ctx.business.user_messages_dismissed_30d}")

    # --- Historical evidence ---
    if evidence_context:
        parts.append("\n=== HISTORICAL EVIDENCE (from this user's past messages) ===")
        parts.append(evidence_context)
    else:
        parts.append("\n=== HISTORICAL EVIDENCE ===")
        parts.append("No relevant historical messages found for this user.")

    parts.append("\n=== YOUR TASK ===")
    parts.append("Classify this message. Return JSON with: message_type, action, reason, confidence.")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Media handling
# ---------------------------------------------------------------------------

def _load_media_part(ctx: MessageContext) -> Optional[types.Part]:
    """Load media bytes and create a Part for the Gemini call."""
    if not ctx.media or not ctx.media.file_exists or not ctx.media.file_path:
        return None

    try:
        with open(ctx.media.file_path, "rb") as f:
            data = f.read()

        mime_type = ctx.media.mime_type or "application/octet-stream"
        return types.Part.from_bytes(data=data, mime_type=mime_type)
    except Exception as e:
        print(f"  [llm.py] Warning: failed to load media {ctx.media.file_path}: {e}")
        return None


# ---------------------------------------------------------------------------
# Fallback decision
# ---------------------------------------------------------------------------

def _fallback_decision(ctx: MessageContext, error_msg: str) -> dict:
    """Return a safe fallback decision when the LLM call fails.

    Design decision: fallback to 'digest', never 'mute' (don't silently
    suppress) and never 'notify' (don't wake the user on a guess).
    This is the safest middle ground — the message shows up later in
    the digest where the user can triage it manually.
    """
    return {
        "action": "digest",
        "message_type": "unknown",
        "reason": f"LLM classification failed ({error_msg}); defaulting to digest for safety.",
        "confidence": 0.3,
        "evidence_message_ids": "none",
    }


# ---------------------------------------------------------------------------
# Main classify function
# ---------------------------------------------------------------------------

# Rate limiting state
_last_call_time = 0.0
_MIN_CALL_INTERVAL = 4.0  # seconds between calls (15 RPM = 4s/call)
_MAX_RETRIES = 3          # retries for normal errors
_MAX_RATE_LIMIT_RETRIES = 5  # extra retries specifically for 429s


def _parse_retry_delay(error_str: str) -> float:
    """Extract retryDelay seconds from a 429 error message."""
    import re
    # Match patterns like "retryDelay': '52s'" or "retry in 52.4s"
    match = re.search(r"retry\s*(?:Delay|in)\D*?(\d+(?:\.\d+)?)\s*s", error_str, re.IGNORECASE)
    if match:
        return min(float(match.group(1)), 65.0)  # Cap at 65s
    return 10.0  # Default fallback


def classify(ctx: MessageContext, evidence_str: str, evidence_context: str) -> dict:
    """Classify a message using Gemini Flash.

    Parameters
    ----------
    ctx : MessageContext
        The fully-hydrated context from Phase 3.
    evidence_str : str
        Semicolon-separated evidence message IDs (or "none").
    evidence_context : str
        Human-readable context string from retrieval (or "").

    Returns
    -------
    dict with keys: action, message_type, reason, confidence, evidence_message_ids
    """
    global _last_call_time

    client = _get_client()

    # Build prompt
    user_prompt = _build_user_prompt(ctx, evidence_context)

    # Build contents list
    contents = []

    # Add media part if present
    media_part = _load_media_part(ctx)
    if media_part is not None:
        contents.append(media_part)

    # Add text prompt
    contents.append(user_prompt)

    # Config with structured JSON output + system instruction
    config = types.GenerateContentConfig(
        system_instruction=_SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_schema=_RESPONSE_SCHEMA,
        temperature=0.2,  # Low temperature for consistent, decisive outputs
    )

    # Rate limiting
    elapsed = time.time() - _last_call_time
    if elapsed < _MIN_CALL_INTERVAL:
        time.sleep(_MIN_CALL_INTERVAL - elapsed)

    # Retry loop
    last_error = ""
    max_attempts = _MAX_RETRIES + 1
    rate_limit_retries = 0

    for attempt in range(max_attempts + _MAX_RATE_LIMIT_RETRIES):
        try:
            _last_call_time = time.time()
            response = client.models.generate_content(
                model=_MODEL,
                contents=contents,
                config=config,
            )

            # Parse the structured JSON response
            text = response.text
            if not text:
                last_error = "empty response text"
                continue

            result = json.loads(text)

            # Validate required fields
            required = {"message_type", "action", "reason", "confidence"}
            if not required.issubset(result.keys()):
                missing = required - set(result.keys())
                last_error = f"missing fields: {missing}"
                continue

            # Validate enum values
            valid_actions = {"notify", "digest", "mute"}
            valid_types = {
                "personal", "urgent", "event", "payment",
                "business_update", "promotion", "greeting",
                "forward", "spam", "scam", "unknown",
            }
            if result["action"] not in valid_actions:
                last_error = f"invalid action: {result['action']}"
                continue
            if result["message_type"] not in valid_types:
                last_error = f"invalid message_type: {result['message_type']}"
                continue

            # Clamp confidence
            conf = float(result["confidence"])
            result["confidence"] = round(max(0.0, min(1.0, conf)), 2)

            # Attach evidence
            result["evidence_message_ids"] = evidence_str

            return result

        except json.JSONDecodeError as e:
            last_error = f"JSON parse error: {e}"
            if attempt < max_attempts - 1:
                time.sleep(2 ** attempt)
                continue

        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            error_str = str(e)
            print(f"  [llm.py] Attempt {attempt+1} failed: {type(e).__name__}")

            # Check for rate limiting (429)
            is_rate_limit = "429" in error_str or "quota" in error_str.lower() or "RESOURCE_EXHAUSTED" in error_str
            if is_rate_limit and rate_limit_retries < _MAX_RATE_LIMIT_RETRIES:
                rate_limit_retries += 1
                wait_time = _parse_retry_delay(error_str)
                # Add small jitter to avoid thundering herd
                wait_time = wait_time + 2.0
                print(f"  [llm.py] Rate limited ({rate_limit_retries}/{_MAX_RATE_LIMIT_RETRIES}). "
                      f"Waiting {wait_time:.0f}s...")
                time.sleep(wait_time)
                continue

            if attempt < max_attempts - 1:
                time.sleep(2 ** attempt)
                continue

            # All retries exhausted
            break

    # All retries exhausted — return safe fallback
    print(f"  [llm.py] All retries exhausted for {ctx.message_id}: {last_error[:120]}")
    return _fallback_decision(ctx, last_error[:200])

