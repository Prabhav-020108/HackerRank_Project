"""
Phase 7 -- Decision Layer, Confidence Calibration, Output Validation.

Wires the full 8-stage pipeline:
  1. Ingest         -- load messages row, build MessageContext via context.py
  2. Fast-path      -- deterministic rules (rules.py) — fires or falls through
  3. Retrieval      -- BM25 evidence retrieval (retrieval.py)
  4. Signal extract -- derive signals from ctx for override layer
  5. LLM call       -- Gemini classification (llm.py)
  6. Finalize       -- code-driven overrides on top of LLM draft
  7. Calibrate      -- confidence compression/promotion based on rule agreement
  8. Validate       -- schema validation, evidence ID existence, clamping

Public API:
    process_message(msg_row, data_dir) -> dict   # one output row (6 fields + message_id)
    run_pipeline(data_dir, out_path)             # full pipeline over messages.csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

# ── Path setup so this file can be run from any CWD ─────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DATA_DIR = REPO_ROOT / "dataset"
sys.path.insert(0, str(SCRIPT_DIR))

import context as ctx_module
from context import MessageContext, load_all_tables
from rules import fast_path
from retrieval import init_retrieval, retrieve_evidence
import llm

# ── Output schema (exact order required by problem_statement.md) ─────────────
REQUIRED_COLUMNS = [
    "message_id",
    "action",
    "message_type",
    "reason",
    "confidence",
    "evidence_message_ids",
]

VALID_ACTIONS = {"notify", "digest", "mute"}
VALID_TYPES = {
    "personal", "urgent", "event", "payment", "business_update",
    "promotion", "greeting", "forward", "spam", "scam", "unknown",
}

# ── Lazy-loaded valid evidence ID set (built once from message_history.csv) ──
_valid_evidence_ids: Optional[set] = None


def _get_valid_evidence_ids(data_dir: Path) -> set:
    """Load and cache the set of all valid message_id values from history."""
    global _valid_evidence_ids
    if _valid_evidence_ids is None:
        hist = pd.read_csv(data_dir / "message_history.csv")
        _valid_evidence_ids = set(hist["message_id"].astype(str).tolist())
    return _valid_evidence_ids


# ============================================================================
# Stage 6: Finalize — code-driven overrides on top of LLM draft
# ============================================================================

def finalize(ctx: MessageContext, draft: dict) -> dict:
    """Apply deterministic post-LLM overrides.

    Three named overrides (per Phase 7 spec):
      A. Strong scam signal wins outright — LLM cannot override detection.
      B. Direct @-mention in a muted group → force notify.
      C. Notification overload + low marginal message value → downgrade to digest.

    Each override appends a *specific, non-templated* reason clause explaining
    exactly why code overrode the model — generic reasons are an explicitly
    penalized failure mode.
    """
    # Make a mutable copy to avoid modifying the LLM's output dict.
    decision = dict(draft)
    text = ctx.message_text or ""
    original_action = decision.get("action", "digest")
    original_reason = decision.get("reason", "")

    # ── Override A: Strong scam signal wins outright ─────────────────────────
    # Trigger: message_type is "scam" in the fast-path or the LLM flagged it,
    # but the action was NOT already "mute". Also catch cases where the LLM
    # missed a scam signal that fast-path would have caught (belt-and-suspenders).
    from rules import (
        _SCAM_PATTERNS, _INJECTION_PATTERNS, _SAFETY_ADVISORY_PATTERNS,
        _text_matches_any,
    )

    has_scam_text = (
        _text_matches_any(text, _SCAM_PATTERNS)
        and not _text_matches_any(text, _SAFETY_ADVISORY_PATTERNS)
    )
    has_injection = _text_matches_any(text, _INJECTION_PATTERNS)

    # Unverified business with high reports (the primary scam business check)
    has_scam_business = (
        ctx.conversation_type == "business"
        and ctx.business is not None
        and not ctx.business.verified
        and ctx.business.user_reports_30d >= 20
    )

    scam_signal = has_scam_text or has_injection or has_scam_business

    if scam_signal and decision.get("action") != "mute":
        scam_detail = []
        if has_injection:
            scam_detail.append("prompt-injection attempt detected in message content")
        if has_scam_text:
            scam_detail.append("text matches OTP/phishing/account-blocking pattern")
        if has_scam_business:
            reports = ctx.business.user_reports_30d if ctx.business else 0
            scam_detail.append(
                f"sender is an unverified business with {reports} community reports in 30 days"
            )
        clause = "; ".join(scam_detail)
        decision["action"] = "mute"
        decision["message_type"] = "scam"
        decision["reason"] = (
            f"Code override (scam guard): {clause}. "
            f"LLM suggested '{original_action}' but hard safety rules take precedence."
        )
        decision["_override"] = "scam_guard"
        return decision

    # ── Override B: Direct @-mention in a muted group → force notify ─────────
    # Trigger: group is muted AND message has @user_id direct mention.
    # Rationale: the sender specifically targeted this user — suppressing it
    # defeats the purpose of direct mentions.
    if (
        ctx.conversation_type == "group"
        and ctx.group is not None
        and ctx.group.group_muted_by_user
        and ctx.has_direct_mention
        and decision.get("action") != "notify"
    ):
        decision["action"] = "notify"
        decision["reason"] = (
            f"Code override (direct mention): message directly @-mentions {ctx.user_id} "
            f"in a muted group ({ctx.group.group_name or ctx.group_id}). "
            f"Direct mentions always bypass the group mute. "
            f"LLM originally suggested '{original_action}'."
        )
        decision["_override"] = "direct_mention_in_muted_group"
        return decision

    # ── Override C: Notification overload + low marginal value → digest ──────
    # Trigger: user has received many notifications today AND already dismissed
    # a high fraction of them AND the current message type is low-priority.
    # Rationale: avoid notification fatigue for low-value messages when the
    # user is already overwhelmed.
    LOW_VALUE_TYPES = {"promotion", "greeting", "forward", "unknown"}
    notification_load = ctx.notification_load

    if (
        notification_load is not None
        and notification_load.notifications_sent >= 15
        and notification_load.notifications_dismissed >= 8
        and decision.get("action") == "notify"
        and decision.get("message_type") in LOW_VALUE_TYPES
    ):
        dismiss_rate = (
            notification_load.notifications_dismissed / notification_load.notifications_sent
            if notification_load.notifications_sent > 0 else 0
        )
        decision["action"] = "digest"
        decision["reason"] = (
            f"Code override (notification overload): user received "
            f"{notification_load.notifications_sent} notifications today and dismissed "
            f"{notification_load.notifications_dismissed} ({dismiss_rate:.0%}). "
            f"A '{decision['message_type']}' message has low marginal value under these conditions; "
            f"downgraded from notify to digest to reduce fatigue. "
            f"Original LLM reason: {original_reason}"
        )
        decision["_override"] = "notification_overload"
        return decision

    # No override applied — return LLM decision as-is.
    decision["_override"] = None
    return decision


# ============================================================================
# Stage 7: Calibrate — compress or promote confidence based on rule agreement
# ============================================================================

def calibrate(
    draft: dict,
    fast_path_fired: bool,
    fast_path_action: Optional[str],
    fast_path_type: Optional[str],
) -> float:
    """Return a calibrated confidence score.

    Rules:
      - Fast-path fired + agrees with LLM draft → keep LLM confidence (rules confirm)
      - Fast-path fired + DISAGREES → compress LLM confidence (rules and LLM diverge,
        less certainty about the final call)
      - Override applied (finalize changed action) → compress further
      - No fast-path, no override → keep LLM confidence with a small uncertainty floor

    The function NEVER produces a flat value — it always reflects the agreement
    between the rule layer and the LLM.

    Returns a float in [0, 1], rounded to 2 decimal places.
    """
    raw = float(draft.get("confidence", 0.5))
    action = draft.get("action")
    msg_type = draft.get("message_type")
    override = draft.get("_override")

    # Base: clamp raw confidence to valid range immediately.
    raw = max(0.0, min(1.0, raw))

    if fast_path_fired:
        if fast_path_action == action and fast_path_type == msg_type:
            # Fast-path and LLM agree exactly — high certainty, boost slightly.
            calibrated = min(0.97, raw + 0.05)
        elif fast_path_action == action:
            # Same action but different message type — good agreement.
            calibrated = raw
        else:
            # Fast-path and LLM disagree on the action — compress confidence.
            calibrated = max(0.45, raw * 0.80)
    else:
        # No fast-path — LLM had full responsibility.
        calibrated = raw

    # Override applied: the code changed the LLM's recommendation.
    # Compress confidence slightly to reflect the disagreement.
    if override == "scam_guard":
        # Scam guard is very high-confidence — floor it.
        calibrated = max(0.80, calibrated)
    elif override == "direct_mention_in_muted_group":
        calibrated = max(0.78, calibrated)
    elif override == "notification_overload":
        # Least certain of the overrides — compress a bit.
        calibrated = max(0.55, min(0.78, calibrated))

    return round(calibrated, 2)


# ============================================================================
# Stage 8: Validate — ensure output row is schema-valid
# ============================================================================

def validate_row(row: dict, data_dir: Path) -> dict:
    """Validate and sanitize one output row before writing to output.csv.

    Checks performed:
      1. Enum check on `action` — replace invalid with "digest"
      2. Enum check on `message_type` — replace invalid with "unknown"
      3. Evidence ID existence — any ID not in message_history.csv is removed;
         if none survive, falls back to "none"
      4. Confidence clamped to [0.0, 1.0], rounded to 2dp
      5. Reason must be a non-empty string — fallback if blank
      6. Removes internal bookkeeping fields (_override, etc.)

    Returns a clean dict with exactly the 6 required columns.
    """
    valid_eids = _get_valid_evidence_ids(data_dir)

    # ── 1 & 2: Enum validation ───────────────────────────────────────────────
    action = row.get("action", "digest")
    if action not in VALID_ACTIONS:
        action = "digest"

    message_type = row.get("message_type", "unknown")
    if message_type not in VALID_TYPES:
        message_type = "unknown"

    # ── 3: Evidence ID validation ─────────────────────────────────────────────
    raw_eids = str(row.get("evidence_message_ids", "none")).strip()
    if raw_eids and raw_eids.lower() != "none":
        candidates = [eid.strip() for eid in raw_eids.split(";") if eid.strip()]
        valid_found = [eid for eid in candidates if eid in valid_eids]
        evidence_message_ids = ";".join(valid_found) if valid_found else "none"
    else:
        evidence_message_ids = "none"

    # ── 4: Confidence clamping ───────────────────────────────────────────────
    try:
        confidence = round(max(0.0, min(1.0, float(row.get("confidence", 0.5)))), 2)
    except (TypeError, ValueError):
        confidence = 0.5

    # ── 5: Reason must be non-empty ──────────────────────────────────────────
    reason = str(row.get("reason", "")).strip()
    if not reason:
        reason = f"Routing decision: {action} ({message_type})."

    # ── 6: Return only the 6 required fields ─────────────────────────────────
    return {
        "message_id": str(row["message_id"]),
        "action": action,
        "message_type": message_type,
        "reason": reason,
        "confidence": confidence,
        "evidence_message_ids": evidence_message_ids,
    }


# ============================================================================
# Main pipeline: process_message (single message, all 8 stages)
# ============================================================================

def process_message(msg_row: pd.Series, data_dir: Path) -> dict:
    """Run the full 8-stage pipeline for one message row.

    Returns a validated output dict with exactly the 6 required columns
    plus 'message_id'.
    """
    # ── Stage 1: Ingest — hydrate context ────────────────────────────────────
    ctx = ctx_module.hydrate(msg_row, data_dir)

    # ── Stage 3: Retrieval — BM25 evidence (runs for ALL messages) ───────────
    # Must run before the fast-path branch so that even rule-decided rows
    # get real evidence IDs in their output row.
    query_text = ctx.message_text or ""
    evidence_str, evidence_context = retrieve_evidence(ctx.user_id, query_text)

    # ── Stage 2: Fast-path rules ──────────────────────────────────────────────
    fast_path_result = fast_path(ctx)

    fast_path_fired = fast_path_result is not None
    fast_path_action = fast_path_result.get("action") if fast_path_fired else None
    fast_path_type = fast_path_result.get("message_type") if fast_path_fired else None

    if fast_path_fired:
        # Fast-path hit — skip LLM but use the already-retrieved evidence.
        # Still run finalize (may catch scam signals the fast-path missed)
        # and always validate.
        draft = dict(fast_path_result)
        # Use real BM25 evidence; only fall back to "none" if retrieval found nothing.
        draft["evidence_message_ids"] = evidence_str

    else:
        # ── Stage 4: Signal extraction (already in ctx + evidence_context) ───
        # ctx carries: DND flag, notification load, media ref, group/biz info.
        # evidence_context carries human-readable historical evidence strings.
        # Nothing extra to do here — signals are consumed by stages 5 and 6.

        # ── Stage 5: LLM call ─────────────────────────────────────────────────
        draft = llm.classify(ctx, evidence_str, evidence_context)
        draft.setdefault("message_id", ctx.message_id)

    # ── Stage 6: Finalize — code-driven overrides ────────────────────────────
    draft = finalize(ctx, draft)

    # ── Stage 7: Calibrate — confidence ──────────────────────────────────────
    calibrated_conf = calibrate(
        draft,
        fast_path_fired=fast_path_fired,
        fast_path_action=fast_path_action,
        fast_path_type=fast_path_type,
    )
    draft["confidence"] = calibrated_conf

    # ── Stage 8: Validate — schema enforcement ────────────────────────────────
    draft["message_id"] = ctx.message_id
    output_row = validate_row(draft, data_dir)

    return output_row


# ============================================================================
# run_pipeline — iterate over all messages, write output.csv
# ============================================================================

def run_pipeline(
    data_dir: Path = DATA_DIR,
    out_path: Path = REPO_ROOT / "output.csv",
    verbose: bool = True,
) -> list[dict]:
    """Run the full pipeline over dataset/messages.csv.

    Writes output.csv with exactly one row per message_id.
    Returns the list of output rows.

    Guarantees:
      - Exactly one row per message_id (asserted at end)
      - Exact column order (REQUIRED_COLUMNS)
      - All enum values are valid
      - All evidence IDs exist in message_history.csv
      - Confidence is in [0.0, 1.0]
    """
    # ── Init shared resources ─────────────────────────────────────────────────
    if verbose:
        print("Initializing context tables...")
    load_all_tables(data_dir)

    if verbose:
        print("Initializing retrieval index...")
    init_retrieval(data_dir)

    # Pre-load valid evidence IDs once.
    _get_valid_evidence_ids(data_dir)

    # ── Load messages ─────────────────────────────────────────────────────────
    messages_path = data_dir / "messages.csv"
    if not messages_path.exists():
        raise FileNotFoundError(f"messages.csv not found at {messages_path}")

    messages = pd.read_csv(messages_path)
    total = len(messages)
    if verbose:
        print(f"Processing {total} messages...")

    # ── Process each message ──────────────────────────────────────────────────
    rows = []
    fast_path_count = 0
    llm_count = 0
    override_count = 0

    for i, (_, msg_row) in enumerate(messages.iterrows()):
        msg_id = str(msg_row.get("message_id", ""))
        if verbose:
            print(f"  [{i+1}/{total}] {msg_id}", end=" ", flush=True)

        try:
            # Compute fast_path once here for stats; process_message also calls it
            # internally but we capture the result cheaply from the already-built ctx.
            ctx = ctx_module.hydrate(msg_row, data_dir)
            fp_result = fast_path(ctx)
            if fp_result is not None:
                fast_path_count += 1
            else:
                llm_count += 1

            row = process_message(msg_row, data_dir)
            rows.append(row)

            if verbose:
                flag = ""
                if "override" in row.get("reason", "").lower():
                    flag = " [OVERRIDE]"
                    override_count += 1
                print(f"→ {row['action']}/{row['message_type']} conf={row['confidence']}{flag}")

        except Exception as e:
            # Never let one bad message kill the whole run —
            # emit a safe fallback row and continue.
            import traceback
            print(f"\n  ERROR on {msg_id}: {e}")
            traceback.print_exc()
            rows.append({
                "message_id": msg_id,
                "action": "digest",
                "message_type": "unknown",
                "reason": f"Pipeline error on this message; safe fallback applied. ({type(e).__name__})",
                "confidence": 0.3,
                "evidence_message_ids": "none",
            })

    # ── Post-processing validation ────────────────────────────────────────────

    # 1. Exactly one row per message_id (no duplicates, no missing).
    seen_ids = set()
    final_rows = []
    input_ids = set(messages["message_id"].astype(str).tolist())

    for row in rows:
        mid = str(row["message_id"])
        if mid in seen_ids:
            # Duplicate — skip.
            print(f"  WARNING: duplicate row for {mid}, skipping.")
            continue
        seen_ids.add(mid)
        final_rows.append(row)

    # Add missing rows (should never happen, but defensive).
    for mid in input_ids:
        if mid not in seen_ids:
            print(f"  WARNING: missing row for {mid}, adding safe fallback.")
            final_rows.append({
                "message_id": mid,
                "action": "digest",
                "message_type": "unknown",
                "reason": "Missing from pipeline run; safe fallback applied.",
                "confidence": 0.3,
                "evidence_message_ids": "none",
            })

    # 2. Preserve input order.
    id_order = {mid: i for i, mid in enumerate(messages["message_id"].astype(str))}
    final_rows.sort(key=lambda r: id_order.get(str(r["message_id"]), 9999))

    # 3. Final schema validation pass on every row.
    final_rows = [validate_row(r, data_dir) for r in final_rows]

    # 4. Write output.csv.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(final_rows)

    # ── Summary ───────────────────────────────────────────────────────────────
    if verbose:
        print(f"\n{'='*60}")
        print(f"Pipeline complete.")
        print(f"  Total messages    : {total}")
        print(f"  Fast-path hits    : {fast_path_count}")
        print(f"  LLM calls         : {llm_count}")
        print(f"  Overrides applied : {override_count}")
        print(f"  Output rows       : {len(final_rows)}")
        print(f"  Written to        : {out_path}")

        # Confidence distribution check (not flat assertion).
        confs = [r["confidence"] for r in final_rows]
        unique_confs = set(confs)
        print(f"\nConfidence distribution:")
        print(f"  Unique values : {len(unique_confs)}")
        print(f"  Min           : {min(confs):.2f}")
        print(f"  Max           : {max(confs):.2f}")
        print(f"  Mean          : {sum(confs)/len(confs):.2f}")

        if len(unique_confs) < 3:
            print("  WARNING: confidence looks flat! Check calibration.")
        else:
            print("  OK: confidence values are varied.")

        # Action distribution.
        from collections import Counter
        action_dist = Counter(r["action"] for r in final_rows)
        type_dist = Counter(r["message_type"] for r in final_rows)
        print(f"\nAction distribution: {dict(action_dist)}")
        print(f"Type distribution: {dict(type_dist)}")
        print(f"{'='*60}")

    # ── Final assertions ──────────────────────────────────────────────────────
    assert len(final_rows) == total, (
        f"Row count mismatch: input={total}, output={len(final_rows)}"
    )
    output_ids = [r["message_id"] for r in final_rows]
    assert sorted(output_ids) == sorted(input_ids), "Output message_ids don't match input!"
    assert len(set(output_ids)) == len(output_ids), "Duplicate message_ids in output!"

    for row in final_rows:
        assert row["action"] in VALID_ACTIONS, f"Invalid action: {row['action']}"
        assert row["message_type"] in VALID_TYPES, f"Invalid type: {row['message_type']}"
        assert 0.0 <= row["confidence"] <= 1.0, f"Confidence out of range: {row['confidence']}"

    return final_rows


# ============================================================================
# Entry point
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Message Notification Router -- Full Pipeline")
    parser.add_argument("--data", type=Path, default=DATA_DIR, help="Path to dataset/ directory")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "output.csv", help="Output path")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-message output")
    args = parser.parse_args()

    run_pipeline(data_dir=args.data, out_path=args.out, verbose=not args.quiet)
