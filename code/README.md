# HackerRank Orchestrate — Message Notification Router

An AI-powered WhatsApp message routing system that classifies every incoming message as `notify`, `digest`, or `mute` using a personalized 8-stage pipeline: deterministic fast-path rules, BM25 evidence retrieval, and Gemini LLM classification.

---

## Quick Start

### 1. Install dependencies

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Set up environment variables

Copy the example file and fill in your Gemini API key(s):

```bash
cp .env.example .env
```

Open `.env` and set:

```
# Option A — single key (simplest):
GEMINI_API_KEY=your_key_here

# Option B — multiple keys for automatic rotation on quota hit:
GEMINI_API_KEYS=key_one,key_two,key_three
```

> **Required:** either `GEMINI_API_KEY` (single) or `GEMINI_API_KEYS` (comma-separated list). The code checks `GEMINI_API_KEYS` first, then falls back to `GEMINI_API_KEY`.

### 3. Run the pipeline

```bash
python code/main.py
```

This reads `dataset/messages.csv` and all context files from `dataset/`, runs the full 8-stage pipeline, and writes predictions to `output.csv`.

---

## Pipeline Architecture

The system runs 8 stages per message:

| Stage | Module | Description |
|---|---|---|
| 1 | `context.py` | Hydrate `MessageContext` — joins all tables for the message |
| 2 | `rules.py` | Fast-path deterministic rules (scam guard, muted-group, prompt injection) |
| 3 | `retrieval.py` | BM25 evidence retrieval over `message_history.csv` |
| 4 | — | Signal extraction (carried by context) |
| 5 | `llm.py` | Gemini Flash LLM classification with structured JSON schema |
| 6 | `pipeline.py` | Finalize: code-driven overrides (scam guard, DND, direct @-mention) |
| 7 | `pipeline.py` | Confidence calibration based on fast-path/LLM agreement |
| 8 | `pipeline.py` | Schema validation and output clamping |

### Key design decisions

- **Fast-path rules short-circuit before the LLM** for obvious cases (unverified high-report businesses, muted groups with no @-mention, prompt injection attempts, chain-letter forwards). This saves API quota and is deterministic.
- **Scam guard cannot be overridden** by LLM or engagement history — safety always wins.
- **DND is a context signal, not an auto-mute** — urgent messages during quiet hours still notify; only low-value types are suppressed.
- **Personalization** comes from `user_business_history.csv` (opt-out status, engagement), `group_members.csv` (muted status, role), and `message_events.csv` (historical reactions).

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | ✅ Yes (if not using `GEMINI_API_KEYS`) | Single Gemini API key |
| `GEMINI_API_KEYS` | ✅ Yes (if not using `GEMINI_API_KEY`) | Comma-separated list of keys; rotated automatically on quota hit |

Keys are loaded from `.env` in the project root. Never commit `.env` to git (it is already in `.gitignore`).

---

## Output Format

`output.csv` columns (exact order required):

| Column | Type | Allowed values |
|---|---|---|
| `message_id` | string | Must match `dataset/messages.csv` |
| `action` | string | `notify`, `digest`, `mute` |
| `message_type` | string | `personal`, `urgent`, `event`, `payment`, `business_update`, `promotion`, `greeting`, `forward`, `spam`, `scam`, `unknown` |
| `reason` | string | Short, specific, message-grounded explanation |
| `confidence` | float | 0.0 – 1.0 |
| `evidence_message_ids` | string | Semicolon-separated IDs from `message_history.csv`, or `none` |

---

## Validation

Run the built-in evaluator to confirm schema compliance:

```bash
python code/evaluation/main.py
```

Expected output: `VALID: 110 rows, schema OK, all enums valid, confidence in range, no dupes.`

---

## Repository Layout

```text
.
├── README.md                         # This file — setup and run instructions
├── AGENTS.md                         # AI coding agent rules + logging
├── problem_statement.md              # Full challenge specification
├── .env.example                      # Template for required environment variables
├── output.csv                        # Final predictions (110 rows)
└── code/
    ├── main.py                       # Entry point — runs the full pipeline
    ├── pipeline.py                   # 8-stage orchestration
    ├── context.py                    # MessageContext hydration
    ├── rules.py                      # Fast-path deterministic rules
    ├── retrieval.py                  # BM25 evidence retrieval
    ├── llm.py                        # Gemini LLM integration + key pool
    ├── schema.py                     # Shared schema definitions
    ├── requirements.txt              # Python dependencies
    ├── regressions.md                # Mismatch log and Phase 9 edge-case results
    ├── README.md                     # This file (copied for code/ submission zip)
    ├── .env.example                  # Template (copied for code/ submission zip)
    ├── evaluation/
    │   └── main.py                   # Schema + enum validation script
├── dataset/
    ├── messages.csv                  # 110 messages to route
    ├── sample_messages.csv           # Solved examples (style calibration only)
    ├── users.csv
    ├── groups.csv
    ├── group_members.csv
    ├── business_accounts.csv
    ├── user_business_history.csv
    ├── message_history.csv
    ├── message_events.csv
    ├── images.csv
    ├── voice_notes.csv
    ├── daily_notification_summary.csv
    └── media/
        ├── images/
        └── audio/
```

---

## Submission

1. `output.csv` — final predictions for all 110 messages
2. Code zip — this full repository
3. Chat transcript — `%USERPROFILE%\hackerrank_orchestrate_august26\log.txt` (Windows) or `$HOME/hackerrank_orchestrate_august26/log.txt` (macOS/Linux)
