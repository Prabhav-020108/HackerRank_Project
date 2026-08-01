"""
Pydantic schema for a single routing decision.

Not wired into main.py yet -- Phase 2 only defines it so Phase 6 (Gemini
integration) and Phase 7 (output validation) can import RoutingDecision
directly instead of re-deriving the enum lists from problem_statement.md.
"""

from typing import Literal

from pydantic import BaseModel, Field

# Exactly the 11 values allowed by problem_statement.md -- keep in sync with it.
MessageType = Literal[
    "personal",
    "urgent",
    "event",
    "payment",
    "business_update",
    "promotion",
    "greeting",
    "forward",
    "spam",
    "scam",
    "unknown",
]

# Exactly the 3 values allowed by problem_statement.md.
Action = Literal["notify", "digest", "mute"]


class RoutingDecision(BaseModel):
    message_type: MessageType
    action: Action
    reason: str = Field(description="Short, specific, human-readable explanation.")
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_message_ids: str = Field(
        default="none",
        description="Semicolon-separated historical message_ids, or 'none'.",
    )