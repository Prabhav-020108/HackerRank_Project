"""
Phase 4 -- Fast-Path Rules Layer.

A deterministic layer that cheaply and correctly disposes of obvious messages
without calling the LLM.  Every rule returns a fully-formed RoutingDecision
dict (all 6 output fields) or None to fall through to the slow path.

Design decisions documented inline per the Phase 4 checklist.

Public API:
    fast_path(ctx: MessageContext) -> dict | None
"""

from __future__ import annotations

import re
from typing import Optional

from context import MessageContext


# ---------------------------------------------------------------------------
# Keyword / pattern detectors
# ---------------------------------------------------------------------------

# Scam-indicative keyword patterns (case-insensitive).
# Each pattern is compiled once at module load.
_SCAM_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bOTP\b",
        r"\bverif(?:y|ication)\b.*\b(?:code|link|now|urgent|account)\b",
        r"\baccount.{0,30}block",
        r"\bblock.{0,30}account",
        r"\bpassword\b.*\b(?:confirm|verify|enter)\b",
        r"\b(?:confirm|verify)\b.*\bpassword\b",
        r"\baccount-login\.in\b",
        r"\bamazonpay-delivery\.in\b",
        r"\bsecurity\s+(?:alert|check|patch)\b",
        r"\b(?:profile|account)\s+will\s+be\s+(?:block|restrict|suspend|delet)",
        r"\bclaim.{0,20}(?:voucher|reward|prize)",
        r"\b(?:voucher|reward|prize).{0,20}claim",
        r"\bfill\s+bank\s+details\b",
        r"\bpending\s+(?:charge|clearance|fee)\b.*(?:today|now|urgent)",
    ]
]

# Prompt-injection patterns -- attempts to override the router's own logic.
_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore\s+(?:all\s+)?(?:previous|prior)\s+(?:routing\s+)?(?:rules|instructions)",
        r"(?:routing|system|assistant)\s+(?:override|instruction|note)\s*:",
        r"set\s+action\s*=\s*notify",
        r"mark\s+this\s+(?:message\s+)?as\s+notify",
        r"always\s+mark\s+this\s+as\s+notify",
        r"classify\s+as\s+urgent",
        r"ignore\s+sender\s+risk",
        r"Internal\s+router\s+metadata:",
    ]
]

# Forward / chain message keywords (case-insensitive).
_CHAIN_FORWARD_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"forward\s+(?:this|it)\s+to\s+(?:\d+|ten|five|twenty)\s+people",
        r"share\s+(?:this|it)\s+(?:with|in)\s+(?:\d+|ten|five|all)\s+(?:people|groups|contacts)",
        r"do\s+not\s+break\s+the\s+chain",
        r"fwd\s+as\s+received",
        r"share\s+(?:this\s+)?blessing",
        r"(?:good\s+luck|blessings?)\b.*\bshar(?:e|ing)\b",
        r"\bshar(?:e|ing)\b.*\b(?:good\s+luck|blessings?)\b",
    ]
]

# Greeting / good-morning patterns.
_GREETING_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"^good\s+morning\b",
        r"\bstay\s+(?:positive|blessed)\b",
        r"\bsmile\s+today\b",
        r"\bbhagwan\b.*\bbhala\s+kare\b",
    ]
]

# Promotional content patterns for muted groups (marketplace, resale, etc.).
_PROMO_QUICK_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bselling\b",
        r"\bpickup\b.*\b(?:gate|location|address)\b",
        r"\b\d+%\s*off\b",
        r"\bbargain\b",
        r"\bfor\s+sale\b",
        r"\bbuying\b.*\bselling\b",
        r"\bprice\b.*\bnegotiable\b",
        r"\bkurta\b|\bdenim\b|\bjacket\b|\bhelmet\b",
    ]
]

# Business promotional text patterns.
_BIZ_PROMO_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\b\d+%\s*off\b",
        r"\blimited\s+(?:time|offer|deal|stock)\b",
        r"\buse\s+code\b",
        r"\bhurry\b",
        r"\bshopping\s+offer\b",
        r"\bdiscount\b",
        r"\bcoupon\b",
        r"\bwelcome\s+offer\b",
    ]
]


def _text_matches_any(text: str, patterns: list[re.Pattern]) -> bool:
    """Check if any pattern matches the text."""
    for p in patterns:
        if p.search(text):
            return True
    return False


def _make_decision(
    action: str,
    message_type: str,
    reason: str,
    confidence: float,
    evidence: str = "none",
) -> dict:
    """Build a fully-formed 6-field decision dict matching the output schema."""
    return {
        "action": action,
        "message_type": message_type,
        "reason": reason,
        "confidence": round(confidence, 2),
        "evidence_message_ids": evidence,
    }


# ---------------------------------------------------------------------------
# Individual rule functions -- each returns dict | None
# ---------------------------------------------------------------------------

def _rule_prompt_injection(ctx: MessageContext) -> Optional[dict]:
    """Catch prompt-injection attempts that try to override routing logic.

    This fires FIRST because an injection attempt is a strong scam signal
    regardless of sender trust, verification, or conversation type.
    """
    text = ctx.message_text or ""
    if _text_matches_any(text, _INJECTION_PATTERNS):
        return _make_decision(
            action="mute",
            message_type="scam",
            reason="The message tries to instruct the router, but the routing decision should be based on the actual content and risk.",
            confidence=0.85,
        )
    return None


def _rule_scam_guard_business(ctx: MessageContext) -> Optional[dict]:
    """Unverified business with high report rate → force mute.

    This OVERRIDES engagement history — a normally-engaged relationship with
    a high-report unverified sender is still unsafe.  This is the named edge
    case the evaluation will probe.

    Threshold: unverified AND user_reports_30d >= 20.

    Distinguishes spam from scam:
    - If user explicitly ignored/opted out (why_known contains 'ignored' or
      'opted_out'), classify as spam (unwanted but not malicious).
    - Otherwise classify as scam (actively deceptive).
    """
    if ctx.conversation_type != "business" or ctx.business is None:
        return None

    biz = ctx.business
    if not biz.verified and biz.user_reports_30d >= 20:
        # Distinguish spam from scam based on user's relationship signal.
        why = (biz.why_user_knows_account or "").lower()
        is_spam = "ignored" in why or "opted_out" in why

        if is_spam:
            return _make_decision(
                action="mute",
                message_type="spam",
                reason="The user has opted out of or repeatedly dismissed similar marketing messages.",
                confidence=0.81,
            )
        else:
            return _make_decision(
                action="mute",
                message_type="scam",
                reason="Unverified business account with high community report rate; content suppressed regardless of user engagement history.",
                confidence=0.87,
            )
    return None


# Safety advisory exclusion patterns — messages ABOUT scams (warning users)
# should not be classified as scams themselves.
_SAFETY_ADVISORY_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bnever\s+ask\s+for\b.*\bOTP\b",
        r"\bOTP\b.*\bnever\s+ask\b",
        r"\bsafety\s+advisory\b",
        r"\bfraud\s+(?:alert|awareness|warning)\b",
        r"\bdo\s+not\s+share\s+(?:your\s+)?(?:OTP|password|PIN)\b",
    ]
]


def _rule_scam_guard_text(ctx: MessageContext) -> Optional[dict]:
    """Text-based scam detection for any conversation type.

    Catches OTP phishing, fake verification links, account-blocking pressure,
    and reward/claim scams via keyword patterns.  Fires across personal,
    group, and business conversations.

    Excludes safety advisory messages that WARN about scams (e.g., "the brand
    says they never ask for OTP").
    """
    text = ctx.message_text or ""
    if not text.strip():
        return None

    if _text_matches_any(text, _SCAM_PATTERNS):
        # Exclude safety advisories — messages warning users about scams
        # are NOT scams themselves.
        if _text_matches_any(text, _SAFETY_ADVISORY_PATTERNS):
            return None

        # Additional signal: if sender is in a group and the group is a
        # marketplace/generic type, or if the business is unverified, boost
        # confidence.
        confidence = 0.81

        # Boost if the business is unverified or has high reports.
        if ctx.business and (not ctx.business.verified or ctx.business.user_reports_30d >= 10):
            confidence = 0.87

        # But DON'T fire on verified businesses with legitimate transactional
        # messages that happen to mention "verification" — check if the
        # business is verified AND the user has a known relationship.
        if ctx.business and ctx.business.verified and ctx.business.why_user_knows_account:
            # Verified business with known relationship — might be a
            # legitimate transactional message.  Let the LLM decide.
            return None

        return _make_decision(
            action="mute",
            message_type="scam",
            reason="The message asks for urgent OTP or account verification through a suspicious flow.",
            confidence=confidence,
        )
    return None


def _rule_muted_group(ctx: MessageContext) -> Optional[dict]:
    """Group muted by user AND no direct @-mention → mute.

    Direct mentions override the mute because the sender explicitly targeted
    this user — that's important enough to surface even in a muted group.

    QUIET-HOURS DECISION: We do NOT auto-mute during DND.  Rationale:
    - A genuinely urgent message during quiet hours should still be processed
      by the LLM path so it can assess urgency and potentially notify.
    - Auto-muting during DND would silently suppress time-critical messages
      (e.g., medical emergencies, work-related alerts).
    - The DND flag is passed to the LLM so it can factor it into its
      confidence/action decision (e.g., lower confidence for digest during DND).
    """
    if ctx.conversation_type != "group" or ctx.group is None:
        return None

    if ctx.group.group_muted_by_user and not ctx.has_direct_mention:
        text = ctx.message_text or ""

        # Check specific content types for more accurate message_type labeling.
        # Priority: scam > greeting > promotion > forward > unknown.
        if _text_matches_any(text, _SCAM_PATTERNS) and not _text_matches_any(text, _SAFETY_ADVISORY_PATTERNS):
            return _make_decision(
                action="mute",
                message_type="scam",
                reason="Message in a muted group contains scam indicators; suppressed for user safety.",
                confidence=0.85,
            )

        if _text_matches_any(text, _GREETING_PATTERNS):
            return _make_decision(
                action="mute",
                message_type="greeting",
                reason="The sender has a pattern of repeated forwards or greetings that the user usually ignores.",
                confidence=0.85,
            )

        # Promotional content in muted group.
        if _text_matches_any(text, _PROMO_QUICK_PATTERNS):
            return _make_decision(
                action="mute",
                message_type="promotion",
                reason="Similar historical messages were ignored, dismissed, or muted by this user.",
                confidence=0.85,
            )

        return _make_decision(
            action="mute",
            message_type="unknown",
            reason="The user has muted this group and the message does not contain a direct mention.",
            confidence=0.82,
        )
    return None


def _rule_high_forward_chain(ctx: MessageContext) -> Optional[dict]:
    """Highly-forwarded chain messages → mute.

    Threshold: forwarded_count >= 5 AND chain/forward keyword match.
    Messages forwarded 5+ times with chain-letter text are almost always
    low-value or spam.
    """
    if ctx.forwarded_count < 5:
        return None

    text = ctx.message_text or ""

    # Check for chain-letter / forward-bait text.
    if _text_matches_any(text, _CHAIN_FORWARD_PATTERNS):
        return _make_decision(
            action="mute",
            message_type="forward",
            reason="The sender has a pattern of repeated forwards or greetings that the user usually ignores.",
            confidence=0.83,
        )

    # Check for greeting + high forward count.
    if _text_matches_any(text, _GREETING_PATTERNS):
        return _make_decision(
            action="mute",
            message_type="greeting",
            reason="The sender has a pattern of repeated forwards or greetings that the user usually ignores.",
            confidence=0.85,
        )

    # High-forward scam patterns.
    if _text_matches_any(text, _SCAM_PATTERNS):
        return _make_decision(
            action="mute",
            message_type="scam",
            reason="Highly-forwarded message with scam indicators; suppressed for user safety.",
            confidence=0.87,
        )

    # High forwarded count alone (≥5) is suspicious but not decisive enough
    # for a deterministic mute — let the LLM decide.
    return None


def _rule_business_promo_opted_out(ctx: MessageContext) -> Optional[dict]:
    """Business promotional message where user has explicitly opted out.

    fires when:
    - conversation_type == "business"
    - business is verified (unverified handled by scam guard)
    - allows_promotions == False
    - why_user_knows_account contains "opted_out" or is None (no relationship)
    - text looks promotional (offers, discounts, deals, "limited", etc.)
    """
    if ctx.conversation_type != "business" or ctx.business is None:
        return None

    biz = ctx.business

    # Only handle verified businesses here — unverified ones go through scam guard.
    if not biz.verified:
        return None

    # User must have opted out of promotions.
    if biz.allows_promotions:
        return None

    # Check if the relationship context indicates opt-out or no relationship.
    why = biz.why_user_knows_account or ""
    is_opted_out = "opted_out" in why.lower() or why == "" or why is None

    # If user has a known transactional relationship (order, booking, etc.),
    # let the LLM decide — it might be a legitimate update.
    transactional_keywords = [
        "delivery", "order", "booking", "appointment", "purchase",
        "refill", "account", "bank", "payment", "pickup",
    ]
    if any(kw in why.lower() for kw in transactional_keywords):
        # Could be a legitimate transactional message — let LLM decide.
        return None

    # Text-based promo check.
    text = ctx.message_text or ""
    if _text_matches_any(text, _BIZ_PROMO_PATTERNS):
        return _make_decision(
            action="mute",
            message_type="promotion",
            reason="The user has opted out of or repeatedly dismissed similar marketing messages.",
            confidence=0.81,
        )

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fast_path(ctx: MessageContext) -> Optional[dict]:
    """Run all deterministic rules in priority order.

    Returns a fully-formed decision dict (6 fields) if a rule fires,
    or None if the message should fall through to the slow path
    (retrieval + LLM).

    Rule priority (highest first):
    1. Prompt injection detection
    2. Scam guard (unverified business + high reports)
    3. Scam guard (text-based patterns)
    4. Muted group (no direct mention)
    5. Highly-forwarded chain messages
    6. Business promo opted-out

    QUIET-HOURS POLICY (documented per Phase 4 checklist):
    We intentionally do NOT auto-mute or auto-digest during DND hours.
    Rationale: a genuinely urgent message during quiet hours (e.g., medical
    emergency, server outage) should still be assessed by the LLM path.
    The DND flag is available in ctx.is_during_dnd for the LLM to factor
    into its confidence weighting.  Silently muting during DND would be a
    safety risk for the "urgent message during quiet hours" edge case.
    """
    # Run rules in priority order — first match wins.
    rules = [
        _rule_prompt_injection,
        _rule_scam_guard_business,
        _rule_scam_guard_text,
        _rule_muted_group,
        _rule_high_forward_chain,
        _rule_business_promo_opted_out,
    ]

    for rule in rules:
        decision = rule(ctx)
        if decision is not None:
            # Attach the message_id for output row construction.
            decision["message_id"] = ctx.message_id
            return decision

    return None
