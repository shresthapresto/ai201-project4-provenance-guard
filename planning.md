# Provenance Guard — Planning

## 1. Detection Signals

**Signal 1: Groq LLM classification (`llama-3.3-70b-versatile`)**
- Measures: Holistic semantic/stylistic coherence — whether the text "reads as" AI-generated based on the model's learned sense of AI writing patterns (over-hedging, generic transitions, unnaturally even tone).
- Output format: A float 0–1 representing "likelihood AI-generated," parsed from a structured prompt response (I'll ask Groq to return strict JSON: `{"ai_likelihood": 0.0-1.0, "reasoning": "..."}`).
- Why chosen: LLMs pick up subtle distributional patterns across huge volumes of human and AI text that are hard to hand-engineer as rules.
- Blind spot: Black-box — no visibility into *why* it scored something a certain way. Prone to false positives on formal, hedge-heavy human writing (academic writing, non-native English speakers).

**Signal 2: Stylometric heuristics (pure Python)**
- Measures: Concrete statistical properties — sentence length variance, type-token ratio (vocabulary diversity), punctuation density.
- Output format: Each metric normalized to 0–1, then averaged (or weighted) into a single float 0–1 "AI-likelihood" score.
- Why chosen: AI text tends toward statistical uniformity (consistent sentence length, safer vocabulary); human writing is "burstier."
- Blind spot: Skilled human writers with deliberately uniform style (technical writing, legal writing) score AI-ish even when human. Also unreliable on short text samples (not enough tokens for stats to be meaningful).

**Combining into one score:**
`combined_confidence = (0.6 * llm_score) + (0.4 * stylometric_score)`
LLM weighted higher since it captures semantic signal stylometrics can't. If the two signals disagree by more than 0.4, I cap the combined score at 0.7 max — strong disagreement between independent signals is itself a sign of uncertainty, not confidence.

## 2. Uncertainty Representation

- A confidence score is **"how strongly the combined signals point toward AI-generated,"** not a probability in the statistical sense — I'm not claiming calibration against a labeled dataset, just a monotonic scale.
- 0.6 means: "signals lean slightly toward AI, but not strongly enough to be a firm call."
- Mapping raw signals → calibrated score: weighted average above, with the disagreement cap.
- Thresholds:
  - **0.00–0.40** → "likely human"
  - **0.41–0.69** → "uncertain"
  - **0.70–1.00** → "likely AI"
- These thresholds are intentionally asymmetric-in-effect: because a false positive (flagging a human as AI) is worse than a false negative, the "likely AI" band starts at 0.70, not 0.5 — the system needs stronger evidence before making that claim.

## 3. Transparency Label Design

| Variant | Exact text shown to user |
|---|---|
| High-confidence AI | "This content shows strong signals of AI generation (confidence: {score}). This is an automated assessment, not a certainty — the creator can appeal this result." |
| Uncertain | "We can't confidently determine whether this content is AI-generated or human-written (confidence: {score}). Treat this result as inconclusive." |
| High-confidence human | "This content shows strong signals of human authorship (confidence: {score})." |

(`{score}` is the combined confidence score, e.g. "confidence: 0.82".)

## 4. Appeals Workflow

- **Who:** Any creator whose content has been classified (identified by `content_id`).
- **What they provide:** `content_id` and `creator_reasoning` (free text explaining why they believe the classification is wrong).
- **What the system does:** Looks up the audit log entry for `content_id`, sets `status` to `"under_review"`, appends `appeal_reasoning` and an `appeal_timestamp` to that entry. No automatic re-classification.
- **Human reviewer view:** The `GET /log` output filtered to entries where `status == "under_review"` — each entry shows the original signal scores, combined confidence, original label, and the creator's appeal reasoning side by side.

## 5. Anticipated Edge Cases

1. **Short, uniform-but-human text** — e.g., a haiku or a very short blog excerpt. Stylometric signal has too few tokens to compute meaningful variance, and may default to a mid/high AI-ish score simply due to low sample size. Mitigation: I'll note this explicitly as a known limitation rather than trying to "fix" it with arbitrary length thresholds.
2. **Heavily edited AI output** — a human takes AI-drafted text and rewrites parts of it. This sits in a genuine gray zone: LLM signal may catch residual AI phrasing while stylometrics reads the human edits as burstier/human. This is actually the *intended* behavior of an "uncertain" label — the system should land here, not force a binary call.

## Architecture

### Narrative
A creator submits text via `POST /submit`. The Flask app generates a `content_id` and passes the text to two independent signals — the Groq LLM signal and the stylometric heuristic signal — each returning a 0–1 score. The confidence scorer combines both into one calibrated score, which the label generator maps to one of three transparency labels. Every step (both raw scores, combined score, label, timestamp) is written to the audit log, and the final response is returned to the creator.

If a creator disputes their result, `POST /appeal` looks up the `content_id` in the audit log, sets its status to `"under_review"`, and appends the creator's reasoning — no automatic re-classification occurs.

### Diagram

\`\`\`
SUBMISSION FLOW
───────────────
POST /submit {text, creator_id}
        │
        ▼
  [Flask app] ──generates──> content_id
        │
        ├──raw text──> [Signal 1: Groq LLM] ──score(0-1)──┐
        │                                                  │
        ├──raw text──> [Signal 2: Stylometrics] ─score(0-1)┤
        │                                                  ▼
        │                                     [Confidence Scorer]
        │                                       combined score(0-1)
        │                                                  │
        │                                                  ▼
        │                                        [Label Generator]
        │                                       label text (1 of 3)
        │                                                  │
        ▼                                                  │
  [Audit Log] <───────timestamp, scores, label──────────────┘
        │
        ▼
  Response {content_id, attribution, confidence, label}


APPEAL FLOW
───────────
POST /appeal {content_id, creator_reasoning}
        │
        ▼
  [Flask app] ──lookup content_id──> [Audit Log]
        │                                 │
        ▼                                 ▼
  status = "under_review"       append appeal_reasoning + timestamp
        │
        ▼
  Response {confirmation, status}
\`\`\`

## AI Tool Plan

**M3 (submission endpoint + Signal 1):**
- Provide: Detection Signals section (Signal 1 only) + Architecture diagram.
- Ask for: Flask app skeleton with `POST /submit` route stub, plus the Groq LLM signal function.
- Verify: Call the signal function directly on 2–3 test strings before wiring it into the route; confirm output is a float 0–1, not a string or raw API response.

**M4 (Signal 2 + confidence scoring):**
- Provide: Detection Signals (full) + Uncertainty Representation + diagram.
- Ask for: Stylometric signal function + confidence scoring logic combining both signals.
- Verify: Run the 4 test inputs from the assignment (clearly AI, clearly human, 2 borderline) and confirm scores fall in the expected bands per my thresholds; check the weighting/cap logic matches what I specified, not a generic average.

**M5 (production layer):**
- Provide: Transparency Label Design + Appeals Workflow + diagram.
- Ask for: Label generation function mapping score → exact label text, plus the `POST /appeal` endpoint.
- Verify: Submit inputs producing scores in all three bands and confirm exact label text matches; submit a test appeal and confirm `GET /log` shows `status: "under_review"` with `appeal_reasoning` populated.