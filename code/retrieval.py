"""
Phase 5 -- Evidence Retrieval

Builds a per-user BM25 index over historical messages.
Retrieves relevant past messages given a new message's text.
Cross-references message_events.csv to attach engagement signals.
"""

from pathlib import Path
from typing import Tuple
import pandas as pd
from rank_bm25 import BM25Okapi

DATA_DIR = Path(__file__).resolve().parent.parent / "dataset"

# Global state for caching
_history = None
_events = None
_user_indices = {}
_user_corpus = {}


def init_retrieval(data_dir: Path = DATA_DIR):
    """Load datasets and build per-user BM25 indices."""
    global _history, _events, _user_indices, _user_corpus
    
    if _history is not None:
        return  # already initialized

    _history = pd.read_csv(data_dir / "message_history.csv")
    _events = pd.read_csv(data_dir / "message_events.csv").set_index("message_id")

    # Group by user_id to build per-user indices
    for user_id, group in _history.groupby("user_id"):
        # Fill missing text with empty string
        texts = group["message_text"].fillna("").astype(str).tolist()
        msg_ids = group["message_id"].tolist()
        
        # Simple whitespace tokenizer
        tokenized_corpus = [t.lower().split() for t in texts]
        
        # Build BM25
        bm25 = BM25Okapi(tokenized_corpus)
        
        _user_indices[user_id] = bm25
        _user_corpus[user_id] = msg_ids


def _get_event_summary(msg_id: str) -> str:
    """Summarize the user's reaction to a historical message."""
    if msg_id not in _events.index:
        return "ignored"
    
    row = _events.loc[msg_id]
    
    # Priority order of signals
    if row.get("message_reported") == 1:
        return "reported"
    if row.get("muted_after_message") == 1:
        return "muted_chat_afterwards"
    if row.get("message_replied") == 1:
        return "replied"
    if row.get("notification_dismissed") == 1:
        return "dismissed"
    if row.get("message_opened") == 1:
        return "opened"
        
    return "ignored"


def retrieve_evidence(user_id: str, query_text: str, k: int = 3) -> Tuple[str, str]:
    """
    Retrieve top-k historical messages for the given user.
    
    Returns:
        A tuple of (evidence_message_ids, context_string).
        If no evidence is found, returns ("none", "").
    """
    if not query_text or not query_text.strip():
        return "none", ""
        
    if user_id not in _user_indices:
        return "none", ""
        
    bm25 = _user_indices[user_id]
    msg_ids = _user_corpus[user_id]
    
    tokenized_query = query_text.lower().split()
    scores = bm25.get_scores(tokenized_query)
    
    # Zip scores with message IDs, sort descending
    scored_items = sorted(zip(scores, msg_ids), reverse=True, key=lambda x: x[0])
    
    # Filter out zero-score items and take top k
    # Threshold slightly above 0 to avoid matching very generic words barely
    top_items = [item for item in scored_items if item[0] > 0.1][:k]
    
    if not top_items:
        return "none", ""
        
    evidence_ids = [item[1] for item in top_items]
    
    # Build context string for the LLM
    context_lines = []
    for msg_id in evidence_ids:
        # Find original text
        hist_row = _history[_history["message_id"] == msg_id].iloc[0]
        hist_text = str(hist_row["message_text"])
        reaction = _get_event_summary(msg_id)
        context_lines.append(f"- Past Message [ID: {msg_id}]: \"{hist_text}\" | User reaction: {reaction}")
        
    evidence_str = ";".join(evidence_ids)
    context_str = "\n".join(context_lines)
    
    return evidence_str, context_str


# Auto-initialize on import so it's ready to use
init_retrieval()
