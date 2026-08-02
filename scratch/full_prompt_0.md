<USER_REQUEST>
# HackerRank Orchestrate — Implementation Roadmap
### WhatsApp Message Notification Router · 24h · $0 budget

This is the execution plan for your submission, built on top of your playbook and cross-checked against `problem_statement.md`, `README.md`, and `AGENTS.md` from the starter repo. It's organized into 13 phases (0–12), each with a **Goal**, **Why it matters**, **Tasks**, a **Deliverable**, and an **Exit Checklist** you (or an AI coding assistant) must pass before moving to the next phase. Don't skip a checklist to "save time" — every skipped check tends to resurface at hour 20 as a much more expensive bug.

---

## Is your fork-and-code plan correct?

Yes. That's exactly the intended flow:

1. Fork `interviewstreet/hackerrank-orchestrate-august26` → clone it locally.
2. Open the repo in your coding assistant (Claude Code, Cursor, etc.). The **first thing it should do is read `AGENTS.md` in full** and run the onboarding flow described there — greet you, show time remaining, recite the rules, and wait for you to type `I agree`. Only after that does it start appending per-turn entries to `log.txt` at the OS-specific path.
3. You then build your actual solution inside `code/` (the layout in §3 of your playbook).

One thing worth being precise about: **the `log.txt` transcript logging is a behavior contract for whatever AI tool you use to build the repo — it is not something you write into `code/` yourself.** Your pipeline (`main.py`, `rules.py`, `llm.py`, etc.) is a separate artifact from the coding-session transcript. Don't conflate the two, and don't let your coding assistant skip the onboarding "I agree" step — it's a required submission file, not boilerplate.

One inconsistency worth flagging: the submission section of the doc you pasted references `dataset/test.csv` in one place while everywhere else (schema, workflow, requirements) says `dataset/messages.csv`. Treat `dataset/messages.csv` as correct per the repeated, detailed spec — but confirm against the live HackerRank platform instructions at hour 0, since a stale filename in a doc is a cheap thing to get wrong.

---

## Phase 0 — Pre-Flight Setup (before the clock starts, or first 15 min)

**Goal:** Zero tool-shopping or account-creation friction once the 24h window is live.

**Why it matters:** Every minute spent signing up for API keys during the challenge is a minute not spent on the rubric. This is also the only phase where "I'll figure it out later" is actually fine to defer — but only for things listed below as deferrable.

**Tasks:**
1. Fork the repo; make it private if your Git host allows.
2. Clone locally, confirm you can see `dataset/`, `AGENTS.md`, `problem_statement.md`, `README.md`.
3. Go to `aistudio.google.com` → generate a free Gemini API key (no card needed) → save as `GEMINI_API_KEY` in a local `.env` (never commit this).
4. `pip install google-genai pandas pydantic python-dotenv rank-bm25` in a fresh virtualenv.
5. Open the AI Studio dashboard and note your **actual** current RPM/RPD free-tier limits — do not trust a remembered or blog-post number, these shift.
6. Set up `.gitignore`: `dataset/`, `venv/`, `cache/`, `node_modules/`, `.env`.
7. Create empty `code/regressions.md` now — you will not want to set this up retroactively at hour 14.
8. Skim `dataset/sample_messages.csv` once, just to internalize the tone/length of a good `reason` field before you write any prompt.
9. Have your coding assistant read `AGENTS.md`, complete onboarding, and confirm `log.txt` is actually being written (open the file and check).

**Deliverable:** A working local environment, a valid Gemini key, and a confirmed, running transcript log.

**Exit Checklist:**
- [ ] Repo forked + cloned, `dataset/` visible locally
- [ ] `GEMINI_API_KEY` set in `.env`, `.env` is gitignored
- [ ] All five packages installed without error
- [ ] Actual RPM/RPD limits written down somewhere you'll see them again (e.g., top of `regressions.md`)
- [ ] `log.txt` exists at the OS-specific path and has a `SESSION START` / `ONBOARDING COMPLETE` entry
- [ ] Empty `code/regressions.md` exists

---

## Phase 1 — Data Recon (Hour 0–1)

**Goal:** Know exactly what's in every CSV before writing a line of pipeline code.

**Why it matters:** The playbook's column names (e.g., "sender_report_rate", "group_muted_by_user") are illustrative, not confirmed against the real dataset. Building `rules.py` against guessed field names is the single most common way to lose the first half of the day to silent `KeyError`s or, worse, rules that silently never fire.

**Tasks:**
1. Load every CSV in `dataset/` with pandas; print `.columns`, `.dtypes`, `.head()`, and `.isna().sum()` for each.
2. For each file, write one sentence in `regressions.md` (or a new `notes.md`) on what it actually contains and how it joins to `messages.csv` (which column is the join key: `user_id`, `group_id`, `business_id`, `message_id`, etc.).
3. Explicitly check: does `messages.csv` have a field indicating direct @-mention, or do you need to derive it yourself from `message_text` + the user's display name/handle (check `users.csv` for a name field)?
4. Check `images.csv` / `voice_notes.csv` — confirm the media file paths actually resolve under `dataset/media/images/` and `dataset/media/audio/`, and note the file extensions present (affects the `mime_type` you'll pass to Gemini).
5. Note missing-data edge cases explicitly: rows with null `group_id`, null `business_id`, empty `message_text`, missing media file for a listed `media_id`.
6. Read `dataset/sample_messages.csv` closely — this is your ground truth for tone. Note: average `reason` length, whether `evidence_message_ids` is usually single or multiple IDs, how confidence values are distributed (are they ever exactly 0.5, or always decisive?).

**Deliverable:** A short data dictionary (even informal, in `regressions.md`) mapping every real column name to what you'll actually use it for, plus a list of edge cases to defend against later.

**Exit Checklist:**
- [ ] Every CSV loaded and inspected at least once
- [ ] Real column names recorded for: quiet hours, sender verification, report/dismiss rates, forwarded_count, mute state, daily notification load
- [ ] Confirmed how (or whether) direct @-mentions are represented
- [ ] Confirmed media file paths resolve and noted their formats
- [ ] Missing-data edge cases listed
- [ ] `sample_messages.csv` output style internalized

---

## Phase 2 — Skeleton I/O Pipeline (Hour 1–3)

**Goal:** A dummy end-to-end run that produces a **valid** `output.csv` before any intelligence exists.

**Why it matters:** This proves the boring-but-scoring-critical stuff — exact column order, one row per `message_id`, valid enum values — works before you've spent hours on the interesting parts. Format violations are a cheap way to lose points on every row, not just hard ones.

**Tasks:**
1. `code/main.py` reads `dataset/messages.csv`, iterates every `message_id`, and writes a row per message to `output.csv` with a constant decision (e.g., always `digest` / `unknown` / `"placeholder"` / `0.5` / `none`).
2. Confirm output columns are exactly: `message_id,action,message_type,reason,confidence,evidence_message_ids` — no extra columns, no reordering.
3. Confirm row count in `output.csv` matches row count in `messages.csv` exactly.
4. Write the first version of `code/eval.py`: load `sample_messages.csv`, join on `message_id` against your `output.csv`, print per-field match rate. It'll be near-zero right now — that's expected, you're testing the *scaffold*, not the intelligence.
5. Write `code/schema.py` (the pydantic `RoutingDecision` model from your playbook) now, even though nothing calls it yet — you'll wire it in Phase 6.

**Deliverable:** `python main.py --data dataset/ --out output.csv` runs cleanly and produces a schema-valid (if dumb) CSV.

**Exit Checklist:**
- [ ] `main.py` runs from a clean terminal with no errors
- [ ] `output.csv` has the exact 6 required columns, in order
- [ ] Exactly one row per `message_id` in `messages.csv`, no duplicates, no missing
- [ ] `eval.py` runs and prints a (low, expected) baseline score
- [ ] `schema.py` exists with the `Literal` enums matching the spec exactly (`message_type` has 11 values, `action` has 3)

---

## Phase 3 — Context Hydration (Hour 3–5)

**Goal:** Every message row arrives at the decision layers already carrying its full joined context as one object.

**Why it matters:** Layers 2, 4, and 6 all need this bundle. Building it once, correctly, avoids five different ad-hoc joins scattered across `rules.py` and `llm.py` that quietly drift out of sync.

**Tasks:**
1. In `code/context.py`, write a function that, given one `messages.csv` row, returns a single context object (dataclass or dict) joining:
   - user info (`users.csv`): quiet hours, recent open/reply/dismiss/report behavior
   - group info (`groups.csv` + `group_members.csv`), if `conversation_type == "group"`: group type, size, admins, this user's role/mute-state/activity in that group
   - business info (`business_accounts.csv` + `user_business_history.csv`), if `conversation_type == "business"`: verification, domain, account age, report count, this user's order/booking/opt-in history with that business
   - today's notification load (`daily_notification_summary.csv`) for this user
   - media reference (`images.csv` / `voice_notes.csv`) resolved to an actual local file path + inferred mime type, if `media_type` is set
2. Handle every missing-data case found in Phase 1 explicitly (e.g., `group_id` null → skip group join, don't crash).
3. Unit-test this on 5–10 hand-picked rows from `sample_messages.csv` covering personal / group / business conversation types, and print the resulting bundle to eyeball it.

**Deliverable:** `context.py` exposes one function that turns a raw message row into a fully hydrated context object, tested on real rows of each `conversation_type`.

**Exit Checklist:**
- [ ] Function handles all three `conversation_type` values without crashing
- [ ] All Phase-1 missing-data edge cases are handled (null group/business, missing media file, empty text)
- [ ] Media paths resolve to real files with correct mime types
- [ ] Spot-checked on rows from `sample_messages.csv` and the joined data looks correct by eye

---

## Phase 4 — Fast-Path Rules Layer (Hour 5–8)

**Goal:** A deterministic layer that correctly and cheaply disposes of the obvious majority of messages without ever calling the LLM.

**Why it matters:** This is where `action` correctness is won reliably (rubric criterion #1), and it's also your quota-management strategy if Gemini's free tier gets tight later.

**Tasks:**
1. In `code/rules.py`, implement `fast_path(ctx)` with, at minimum:
   - **Scam guard**: unverified/high-report-rate sender → force `mute` / `scam`, regardless of the user's usual engagement with that sender. This must be able to override even a normally-engaged relationship — that's the named edge case the interview will probe.
   - **Mute guard**: group muted by user AND no direct mention → `mute` / `unknown`.
   - **Quiet-hours guard**: decide how this interacts with urgency — a genuinely urgent message during quiet hours probably shouldn't just get silently muted; decide and document your reasoning (this becomes an interview answer).
   - Any other rule you can express purely from Phase-3's joined context with no ambiguity.
2. Each fast-path rule must return a fully-formed decision (all 6 output fields), not a partial one.
3. Anything that *doesn't* clearly match a rule returns `None` and falls through to the slow path (retrieval + LLM).
4. Test against `sample_messages.csv`: for every row where your fast-path fires, does it match the expected `action`/`message_type`? Log mismatches in `regressions.md` with the specific field and condition that was wrong — this is what makes the interview's "what broke" question answerable with a real example instead of a vague one.

**Deliverable:** `rules.py` with a tested `fast_path()` that correctly handles the clearly-obvious rows in `sample_messages.csv`.

**Exit Checklist:**
- [ ] Scam guard implemented and correctly overrides engagement history on test rows
- [ ] Mute guard implemented and correctly lets direct mentions through
- [ ] Quiet-hours behavior decided and documented (not left implicit)
- [ ] Every fast-path branch returns all 6 fields, matching the enum values exactly
- [ ] Ambiguous rows correctly fall through (return `None`) instead of being force-classified
- [ ] At least 2–3 real mismatches logged in `regressions.md` with cause and fix

---

## Phase 5 — Evidence Retrieval / BM25 (Hour 8–9)

**Goal:** Real, relevant `evidence_message_ids` — not `none` on every row.

**Why it matters:** This is an explicit, separate rubric line item. It's also cheap to build and easy to under-invest in because it doesn't feel like "the AI part."

**Tasks:**
1. In `code/retrieval.py`, build a `rank_bm25` (or TF-IDF) index over `message_history.csv`, scoped **per user** — you're retrieving relevant history for *this* user, not a global corpus.
2. Given a current message's text (or media caption/transcript once Gemini is wired in — see Phase 6), retrieve top-k historically similar/relevant messages for that user.
3. Cross-reference `message_events.csv` so retrieved evidence can carry a signal like "this user previously dismissed 4 similar messages" or "this user replied to 2 similar messages" — this is what makes evidence *useful* to the decision layer, not just topically similar.
4. Return real `message_id`s that exist in `message_history.csv` (Phase 8's output validation will double-check this, but get it right here first).
5. Handle the cold-start case: a user/message with no relevant history → `evidence_message_ids = "none"`, not a crash or a hallucinated ID.

**Deliverable:** `retrieval.py` returning real, per-user-scoped evidence IDs with engagement signal attached.

**Exit Checklist:**
- [ ] BM25 index is user-scoped, not global
- [ ] Returns real `message_id`s that exist in `message_history.csv`
- [ ] Retrieved evidence carries reaction/engagement context, not just text similarity
- [ ] Cold-start (no relevant history) returns `"none"` cleanly
- [ ] Spot-checked against a few `sample_messages.csv` rows that have non-`none` expected evidence

---

## Phase 6 — Gemini Multimodal Integration (Hour 9–13)

**Goal:** A single Gemini Flash call per message that reliably returns valid structured JSON for text, image, and voice inputs.

**Why it matters:** This is the highest-complexity, highest-failure-surface part of the system. Budget the most hours here on purpose.

**Tasks:**
1. In `code/llm.py`, implement the `classify()` call from your playbook. Before wiring it into the pipeline, **verify the exact `google-genai` method names and `response_schema` usage against the package's current quickstart** — the playbook itself flags that SDKs shift, don't assume the skeleton is byte-for-byte current.
2. Build the actual prompt: it should include the message text (or "no text, see attached voice/image"), the Phase-3 context bundle (relevant fields, not everything), and the Phase-5 evidence, and instruct the model to draft `message_type`, a first-pass `action`, `reason`, and `confidence` — remembering that **code, not the model, makes the final call** (Phase 7).
3. Wire in media: for `media_type == "image"`, pass the image bytes with correct mime type; for `"voice"`, pass the audio bytes. Confirm Gemini is actually reading the content (test on 2–3 real media rows and sanity-check the returned `reason` references what's actually in the image/audio).
4. Add basic retry/error handling: a failed call or a JSON parse failure should not crash the whole run — fall back gracefully (this becomes both a code path and an interview answer about failure modes).
5. Run across a representative sample (text + image + voice rows) and confirm JSON parses cleanly every time before moving to the full dataset.

**Deliverable:** `llm.py` reliably classifying text, image, and voice messages into schema-valid JSON.

**Exit Checklist:**
- [ ] SDK method names verified against current `google-genai` docs, not just copied from the playbook
- [ ] Text, image, and voice rows all produce valid, schema-conforming JSON
- [ ] Prompt includes context + evidence, not just raw message text
- [ ] A failed/malformed call degrades gracefully (documented fallback), doesn't crash the run
- [ ] Manually verified on 2–3 media rows that Gemini is actually "looking at" / "listening to" the file, not hallucinating from the filename alone

---

## Phase 7 — Decision Layer, Confidence Calibration, Output Validation

**Goal:** Wire everything into `pipeline.py` so the model *drafts* and code *decides* — and nothing invalid ever reaches `output.csv`.

**Why it matters:** This is the layer the interview will scrutinize hardest ("walk me through your architecture"), and it's where confidence-calibration and reason-quality points are actually earned, not just described.

**Tasks:**
1. In `code/pipeline.py`, wire stages 1→8 in order (as in your playbook's diagram): ingest → fast-path → (if it didn't fire) retrieval → signal extraction → Gemini call → decision-layer overrides → confidence calibration → output validation.
2. Implement `finalize()` overrides from your playbook: strong scam signal wins outright; direct mention in a muted group forces `notify`; notification overload + low marginal value downgrades to `digest`. Each override must append a specific, non-templated reason clause explaining *why* code overrode the model — this is what makes `reason` "useful and consistent" instead of generic filler (an explicitly penalized failure mode per your playbook).
3. Implement `calibrate()`: keep model confidence when rules agree, compress it when rules override. Verify confidence is never flat across the whole output file — check the distribution, not just a few rows.
4. Implement output validation as its own step: enum-check `action`/`message_type` against the schema, verify every `evidence_message_ids` entry actually exists in `message_history.csv` (or the current run's history sources), clamp confidence to [0,1], confirm exact column order, confirm exactly one row per `message_id`.

**Deliverable:** A fully wired `pipeline.py` where every row is either fast-pathed or goes through retrieval → LLM → override → calibration → validation, with no invalid rows possible.

**Exit Checklist:**
- [ ] All three named overrides implemented and each appends a specific reason, not boilerplate
- [ ] Confidence values are not flat — check `output.csv`'s confidence column distribution directly
- [ ] Output validation rejects/fixes any enum violation, any evidence ID that doesn't exist, any confidence outside [0,1]
- [ ] Exactly one row per `message_id`, exact column order, confirmed programmatically not just by eye

---

## Phase 8 — Full Run + Evaluation (Hour 13–16)

**Goal:** A complete `output.csv` over the real dataset, with every mismatch against `sample_messages.csv` understood and logged.

**Tasks:**
1. Run the full pipeline end to end on `dataset/messages.csv`.
2. Run `eval.py` against `sample_messages.csv`: per-field accuracy for `action` and `message_type`, and a manual read-through of `reason` quality on a sample of rows (accuracy metrics won't catch templated/generic reasons — you have to read them).
3. For every mismatch, add an entry to `regressions.md`: what was misclassified, into what, and your hypothesis for why (missing signal? prompt ambiguity? rule too broad/narrow?).
4. Prioritize fixes that touch the most rows first, not the most interesting bug first — you have limited hours left.

**Deliverable:** A complete `output.csv`, an eval report, and a growing `regressions.md` with real, specific entries (your future interview material).

**Exit Checklist:**
- [ ] `output.csv` covers 100% of `messages.csv` rows
- [ ] `eval.py` run and printed accuracy for `action` and `message_type`
- [ ] `reason` field manually spot-read on at least ~15–20 rows for genericness/templating
- [ ] At least 3–5 real, specific mismatches logged in `regressions.md` with root cause

---

## Phase 9 — Named Edge-Case Stress Test (Hour 16–19)

**Goal:** Hand-verify the specific scenarios the problem statement calls out by name — these are almost certainly weighted in the hidden ground truth.

**Tasks:** Manually find or construct, then verify by hand, at least one real row for each of:
1. Muted group + direct @-mention → should still `notify`.
2. Trusted/verified sender making a payment ask vs. a new/unverified sender making the same ask → should route differently.
3. Scam signal overriding a normally-high-engagement history with that sender.
4. Quiet hours interacting with urgency.
5. A sale/promotion poster that's useful to one user's profile and noise to another (personalization, not a global label).
6. Voice-note and image rows specifically — confirm Gemini's read of the media content, not just metadata, drove the decision.

**Deliverable:** A short table (in `regressions.md` or a new `edge_cases.md`) listing each scenario, the `message_id` you tested it on, and confirmation the system handled it correctly — or the fix you made.

**Exit Checklist:**
- [ ] All 6 named scenarios above verified against a real row, not just reasoned about abstractly
- [ ] Any failures fixed and re-verified
- [ ] Findings recorded — this becomes direct interview ammunition for "walk me through a specific case"

---

## Phase 10 — Polish & Reproducibility (Hour 19–21)

**Goal:** A clean, fresh-environment run that produces the same quality output, with no rough edges a judge would notice in 30 seconds of skimming.

**Tasks:**
1. Read through 20–30 random `reason` values — rewrite any that are generic/templated into specific, message-grounded language.
2. Re-check the confidence distribution isn't flat and isn't suspiciously always near 0.9 or 0.5.
3. Delete your virtualenv/cache, recreate it from `requirements.txt` alone, and re-run `main.py` from scratch to confirm reproducibility with zero manual steps.
4. Read `code/README.md` as if you'd never seen the project — does it state the exact run command, the exact env vars needed, and nothing else required?

**Deliverable:** A verified-reproducible run and a README a stranger (or a judge) could follow with zero prior context.

**Exit Checklist:**
- [ ] No generic/templated `reason` strings remain in a spot-check sample
- [ ] Confidence distribution looks reasonable, not flat or bimodal-degenerate
- [ ] Fresh virtualenv + `requirements.txt`-only install reproduces a working run
- [ ] `README.md` gives the exact run command and required env vars, nothing missing

---

## Phase 11 — Packaging & Submission (Hour 21–22)

**Goal:** All three required submission artifacts, correctly formed, with nothing extraneous.

**Tasks:**
1. `code.zip`: zip the `code/` directory, explicitly excluding `venv/`, `cache/`, `dataset/`, `node_modules/`, and `.env`. Double-check the zip by extracting it somewhere clean and confirming it's runnable.
2. `output.csv`: final predictions for **all** rows in `dataset/messages.csv`, exact 6-column schema, one row per `message_id`. Re-run your Phase 7 validation script one last time against this exact file.
3. Chat transcript: copy `log.txt` from its OS-specific path (`$HOME/hackerrank_orchestrate_august26/log.txt` on macOS/Linux) as the transcript upload. Confirm no secrets are present in it (per `AGENTS.md` §5.4) — open and skim it once before uploading.
4. Confirm submission mechanism (HackerRank Community Platform, per the README) and upload all three.

**Deliverable:** `code.zip`, `output.csv`, and `log.txt` — submitted.

**Exit Checklist:**
- [ ] `code.zip` extracted fresh and confirmed runnable, with no dataset/venv/secrets inside
- [ ] `output.csv` re-validated one final time (schema, row count, no invalid enums)
- [ ] `log.txt` skimmed for accidental secrets before upload
- [ ] All three files uploaded via the correct platform mechanism

---

## Phase 12 — Interview Prep (Hour 22–24) — do not skip or shorten this block

**Goal:** Walk into a 30-minute, camera-mandatory AI Judge interview able to point at your actual code and actual regressions, not describe the system abstractly.

**Tasks:**
1. Test mic and camera *before* the interview window opens (it opens immediately after submission and stays open 12 hours — but don't wait to discover a broken mic mid-interview).
2. Rehearse out loud, not silently, at least twice each:
   - The 60–90s pitch: what the system does end to end.
   - Why single-agent-wrapped-in-code, why BM25 over a vector DB, why Gemini Flash over Claude/local Whisper.
   - Failure-mode handling: what happens on a failed/ambiguous call (fallback to `digest`, never silence, never a guess).
   - One real, specific regression from `regressions.md` — not a generic "I fixed some bugs."
   - Where this breaks at real WhatsApp scale: end-to-end encryption means a production version can't ship message content to a third-party API (needs on-device/trusted-enclave inference); cost/latency at scale means deterministic rules need to absorb even more of the obvious majority; media results should be cached by content hash so a forwarded poster isn't reprocessed.
   - One honest, specific thing you deliberately did **not** build, and why — self-awareness scores better than an unconvincing claim of completeness.
3. Have `regressions.md` and your actual prompt template (`llm.py`'s prompt string) open in a second window during the call — you'll be asked to point at specifics.
4. Skim the likely interview arc once more so nothing catches you off guard: pitch → architecture/retrieval → safety/failure modes → implementation familiarity → evaluation/iteration → production/scale → novelty/AI-use split (what you directed vs. what the AI drafted).

**Deliverable:** You, camera-ready, able to answer every question above from a real artifact in your repo rather than from memory of the playbook.

**Exit Checklist:**
- [ ] Mic and camera tested
- [ ] Pitch rehearsed out loud at least twice
- [ ] Architecture, retrieval-choice, and failure-mode answers rehearsed out loud
- [ ] One specific `regressions.md` entry chosen and ready to reference
- [ ] Production/scale answer rehearsed (encryption, cost/latency, caching)
- [ ] One honest "didn't build this, here's why" answer ready
- [ ] `regressions.md` and prompt template open and ready in a second window

---

## Master Submission Gate (final check before you hit submit)

- [ ] `output.csv` has one row per row in `dataset/messages.csv`, exact required columns, exact order
- [ ] No hardcoded test labels or organizer-only files used anywhere in the pipeline
- [ ] All secrets read from environment variables — nothing hardcoded in the repo
- [ ] `code.zip` excludes `dataset/`, `venv/`, `cache/`, `node_modules/`, `.env`
- [ ] `log.txt` has a full session history from onboarding through your final turn, no secrets in it
- [ ] `README.md` inside `code.zip` gives the exact run command
- [ ] You've verified the `messages.csv` vs. `test.csv` naming question against the live platform, not just this doc

---

## Recurring Failure Modes to Actively Guard Against

- Deciding your stack *during* the hackathon instead of in Phase 0.
- Leaving `evidence_message_ids` as `none` everywhere because retrieval felt like the "boring part" — it's an explicit, separate rubric line.
- A flat confidence number across every row — judges explicitly check for calibration.
- A `reason` field that reads as generic/templated even when the label itself is correct — flagged as heavily penalized regardless of label accuracy.
- Building OCR + ASR + text-LLM as three separate systems when Gemini Flash does all three natively in one call — every extra moving part is one more thing that can break at hour 23.
- Skipping or rushing the mandatory `AGENTS.md` onboarding/logging — your transcript is a required submission file, not optional polish.

1. **Pitch** — what does the system do end to end (60-90 seconds)2. **Architecture & retrieval** — why single-agent, why BM25, why Gemini3. **Safety & failure modes** — scams, hallucination, escalation4. **Implementation familiarity** — your actual prompt, your actual schema, your actual code5. **Evaluation & iteration** — what broke, what you changed (this is why `regressions.md` matters)6. **Production/monitoring** — does this work at real WhatsApp scale7. **Novelty/AI use** — what you directed vs what the AI drafted **Cheat sheet — rehearse these out loud, don't just read them:** > **"Walk me through your architecture."**> "One agent, wrapped in code. The model reads the message plus retrieved evidence and drafts a classification; deterministic Python makes the final call and can override the model outright — for example, a scam signal always wins regardless of the user's usual engagement. That split is what keeps the system testable and auditable." > **"Why single-agent instead of multi-agent?"**> "Simple beats flashy in this format specifically — the organizers' own past-edition data showed simpler single-agent-with-tools systems outscoring multi-agent graphs, and a multi-agent loop adds latency and hallucination surface without adding correctness." > **"How do you handle failure modes?"**> "If the model's confidence drops or a call fails, the fallback is digest, not silence and not a guess — it's always safer to delay a message than drop it or wake someone for spam." > **"What broke during testing, and what did you change?"**> (Use a real line from `regressions.md`.) "During the full run, [X] was misclassified as [Y] because [Z]. Prompting alone didn't fix it reliably, so I added a deterministic rule in code that checks [specific field] and overrides the model when [specific condition]." > **"Where does this fall over at real WhatsApp scale?"**> "Real messages are end-to-end encrypted, so a production version can't ship message content to a third-party API — it would need to run on-device or in a trusted enclave. Latency and cost also don't scale: a real system would let cheap deterministic rules absorb the obvious majority instantly and only escalate ambiguous cases to the model, with OCR/media results cached by content hash so a forwarded poster is never re-processed twice." > **"What did you deliberately not build, and why?"**> Have one honest answer ready. Self-awareness scores better than a claim of completeness — the organizers' own writeups note winners were rewarded for naming a real limitation they found and fixed, not for claiming perfection. **Logistics:** test your mic and camera before the interview opens. Keep `regressions.md` and your actual prompt template open in a second window during the call — you'll be asked to point at specifics, not describe them abstractly. --- ## 8. Common Pitfalls (from the 3-idea critique — avoid these) - **Deciding your stack during the hackathon instead of before it** — the pre-flight checklist exists so hour 0-1 is data recon, not tool shopping.- **Skipping retrieval or leaving `evidence_message_ids` as `none` everywhere** — it's one of five explicit grading criteria; don't treat it as optional polish.- **A flat confidence number on every row** — judges explicitly check for "reasonable calibration"; §4's blend function is a five-line fix.- **A `reason` field that's generic/templated** — the organizers' own recap flagged this as heavily penalized even when the label is correct.- **Building the multimodal pipeline as two separate systems (OCR tool + ASR tool + text LLM)** when one Gemini call does all three — every extra moving part is something that can break at hour 23.- **Skipping the mandatory `AGENTS.md` logging** — your transcript is a required submission file, not optional. 


Is your fork-and-code plan correct?

Yes. That's exactly the intended flow:

Fork interviewstreet/hackerrank-orchestrate-august26 → clone it locally.
Open the repo in your coding assistant (Claude Code, Cursor, etc.). The first thing it should do is read AGENTS.md in full and run the onboarding flow described there — greet you, show time remaining, recite the rules, and wait for you to type I agree. Only after that does it start appending per-turn entries to log.txt at the OS-specific path.
You then build your actual solution inside code/ (the layout in §3 of your playbook).

One thing worth being precise about: the log.txt transcript logging is a behavior contract for whatever AI tool you use to build the repo — it is not something you write into code/ yourself. Your pipeline (main.py, rules.py, llm.py, etc.) is a separate artifact from the coding-session transcript. Don't conflate the two, and don't let your coding assistant skip the onboarding "I agree" step — it's a required submission file, not boilerplate.

One inconsistency worth flagging: the submission section of the doc you pasted references dataset/test.csv in one place while everywhere else (schema, workflow, requirements) says dataset/messages.csv. Treat dataset/messages.csv as correct per the repeated, detailed spec — but confirm against the live HackerRank platform instructions at hour 0, since a stale filename in a doc is a cheap thing to get wrong.

Phase 0 — Pre-Flight Setup (before the clock starts, or first 15 min)

Goal: Zero tool-shopping or account-creation friction once the 24h window is live.

Why it matters: Every minute spent signing up for API keys during the challenge is a minute not spent on the rubric. This is also the only phase where "I'll figure it out later" is actually fine to defer — but only for things listed below as deferrable.

Tasks:

Fork the repo; make it private if your Git host allows.
Clone locally, confirm you can see dataset/, AGENTS.md, problem_statement.md, README.md.
Go to aistudio.google.com → generate a free Gemini API key (no card needed) → save as GEMINI_API_KEY in a local .env (never commit this).
pip install google-genai pandas pydantic python-dotenv rank-bm25 in a fresh virtualenv.
Open the AI Studio dashboard and note your actual current RPM/RPD free-tier limits — do not trust a remembered or blog-post number, these shift.
Set up .gitignore: dataset/, venv/, cache/, node_modules/, .env.
Create empty code/regressions.md now — you will not want to set this up retroactively at hour 14.
Skim dataset/sample_messages.csv once, just to internalize the tone/length of a good reason field before you write any prompt.
Have your coding assistant read AGENTS.md, complete onboarding, and confirm log.txt is actually being written (open the file and check).

Deliverable: A working local environment, a valid Gemini key, and a confirmed, running transcript log.

Exit Checklist:

 Repo forked + cloned, dataset/ visible locally
 GEMINI_API_KEY set in .env, .env is gitignored
 All five packages installed without error
 Actual RPM/RPD limits written down somewhere you'll see them again (e.g., top of regressions.md)
 log.txt exists at the OS-specific path and has a SESSION START / ONBOARDING COMPLETE entry
 Empty code/regressions.md exists

lets start with phase 0 and aslo understand the project idea
create me the env and other files i will fill the api key in it and also give me the cmds for terminal to activate the environment venv ok 
properly complete it 
make sure u complete the phase 0 only and check the check list  
</USER_REQUEST>
<ADDITIONAL_METADATA>
The current local time is: 2026-08-01T23:29:07+05:30.
</ADDITIONAL_METADATA>
<USER_SETTINGS_CHANGE>
The user changed setting `Model Selection` from None to Gemini 3.1 Pro (High). No need to comment on this change if the user doesn't ask about it. If reporting what model you are, please use a human readable name instead of the exact string.
</USER_SETTINGS_CHANGE>