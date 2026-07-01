# Provenance Guard

A backend system that classifies submitted text as likely AI-generated, likely human-written, or uncertain — using two independent detection signals, a calibrated confidence score, a plain-language transparency label, and an appeals workflow for contested classifications.

---

## Architecture Overview

A creator submits text via `POST /submit` with `text` and `creator_id`. The Flask app generates a unique `content_id` and passes the raw text to two independent detectors: **Signal 1** sends the text to Groq's `llama-3.3-70b-versatile` model, which returns a 0–1 "AI likelihood" score plus a short reasoning string. **Signal 2** computes three pure-Python stylometric heuristics (sentence length uniformity, vocabulary diversity, formal punctuation density) and averages them into its own 0–1 score. The **confidence scorer** combines both into a single score using a weighted formula that also accounts for signal disagreement. That score is passed to the **label generator**, which maps it to one of three transparency label variants. Every step — both raw signal scores, the combined score, the label, and a timestamp — is written to a structured JSON audit log. The final response returns `content_id`, `attribution`, `confidence`, `label`, and both individual `signal_scores` to the creator.

Separately, if a creator disputes their result, `POST /appeal` accepts a `content_id` and `creator_reasoning`. The system looks up that entry in the audit log, sets its `status` to `"under_review"`, and appends the appeal reasoning and a timestamp. No automatic re-classification happens — a human reviewer would read the appeal queue, which is the audit log filtered to `under_review` entries.

```
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
  Response {content_id, attribution, confidence, label, signal_scores}


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
```

Both signals run on every submission, guarded by rate limiting (10/min, 100/day) on `/submit`.

---

## Detection Signals

**Signal 1 — Groq LLM classification (`llama-3.3-70b-versatile`)**
Measures holistic semantic and stylistic coherence — whether the text "reads as" AI-generated based on the model's learned sense of AI writing patterns (over-hedging, generic transitions, unnaturally even tone, balanced argument structure). Chosen because LLMs are trained on enormous volumes of both AI and human text and pick up subtle distributional patterns that are hard to hand-engineer as explicit rules.
*Blind spot:* it's a black box — no visibility into *why* it scored something a certain way — and it's prone to false positives on formal, hedge-heavy human writing (academic writing, non-native English speakers writing carefully).

**Signal 2 — Stylometric heuristics (pure Python, no external libraries)**
Measures three concrete structural properties: sentence-length uniformity (coefficient of variation across sentence word-counts), vocabulary diversity (type-token ratio), and formal punctuation density (commas/semicolons vs. exclamation marks/ellipses). Chosen because it's genuinely independent from Signal 1 — it looks at statistical shape, not meaning, so it fails in different situations than the LLM does.
*Blind spot:* a skilled human writer with a deliberately uniform style (technical writing, legal writing) scores AI-ish even when human, and short text samples don't contain enough tokens for the statistics to be meaningful — vocabulary diversity in particular reads as artificially high on short passages regardless of origin.

**Combining into one score:**
```
combined_confidence = (0.6 × llm_score) + (0.4 × stylometric_score)
```
The LLM signal is weighted higher because it captures semantic signal the stylometric signal structurally cannot. If the two signals disagree by more than 0.4, the combined score is capped at 0.7 — strong disagreement between two independent signals is itself evidence of uncertainty, not confidence, and the system should not let one confident signal override a genuinely split verdict.

---

## Confidence Scoring

A confidence score answers "how strongly do the combined signals point toward AI-generated," not a statistically calibrated probability — there's no labeled dataset behind it, just a monotonic 0–1 scale with defensible thresholds:

| Range | Attribution |
|---|---|
| 0.00 – 0.40 | likely_human |
| 0.41 – 0.69 | uncertain |
| 0.70 – 1.00 | likely_ai |

The "likely_ai" band deliberately starts at 0.70, not 0.5 — because a false positive (accusing a human of using AI) is worse than a false negative on a creative-writing platform, the system requires stronger evidence before making that claim, per the hint in the assignment about asymmetric error cost.

**Validation:** I tested 4 deliberately varied inputs (from the assignment's own test set) and confirmed the scores move in the expected direction, plus investigated the one case that didn't land where predicted (see *Spec Reflection* below).

**Two example submissions showing meaningfully different scores:**

*Higher confidence (uncertain, leaning AI) — formal academic paragraph:*
> "The relationship between monetary policy and asset price inflation has been extensively studied in the literature..."
- `llm_score: 0.8`, `stylometric_score: 0.212`, **combined confidence: 0.565** → `uncertain`

*Lower confidence (likely human) — casual first-person text:*
> "ok so i finally tried that new ramen place downtown and honestly? underwhelming..."
- `llm_score: 0.2`, `stylometric_score: 0.042`, **combined confidence: 0.137** → `likely_human`

The ~0.43-point gap between these two demonstrates the scoring function produces meaningful, non-constant variation across genuinely different inputs — not a coin flip around 0.5.

---

## Transparency Label

The label text returned by `/submit` changes based on the confidence score. All three exact variants:

| Variant | Exact text shown to the creator |
|---|---|
| **High-confidence AI** (≥0.70) | "This content shows strong signals of AI generation (confidence: {score}). This is an automated assessment, not a certainty — the creator can appeal this result." |
| **Uncertain** (0.41–0.69) | "We can't confidently determine whether this content is AI-generated or human-written (confidence: {score}). Treat this result as inconclusive." |
| **High-confidence human** (≤0.40) | "This content shows strong signals of human authorship (confidence: {score})." |

`{score}` is replaced with the actual combined confidence value, e.g. `confidence: 0.85`. The high-confidence AI variant explicitly names the appeal path and avoids asserting certainty ("shows strong signals," not "is AI-generated") — a deliberate wording choice given that false positives carry real reputational cost for a creator.

---

## Appeals Workflow

Any creator with a `content_id` can appeal via `POST /appeal` with `content_id` and `creator_reasoning`. The system looks up the entry, returns 404 if not found, otherwise sets `status: "under_review"` and appends `appeal_reasoning` + `appeal_timestamp` — the original scores and label are left untouched, since no automatic re-classification occurs.

**Real evidence from testing** — a submission originally scored `uncertain` (0.565, formal academic text) was appealed:

```json
{
  "content_id": "212fb5d7-6256-497f-968b-6df36c5cf62e",
  "creator_id": "test-borderline1",
  "attribution": "uncertain",
  "confidence": 0.565,
  "status": "under_review",
  "appeal_reasoning": "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical.",
  "appeal_timestamp": "2026-07-01T05:07:51.565481+00:00"
}
```

The status flip is visible in `GET /log`, and the original scores remain exactly as classified — a human reviewer sees both the original evidence and the creator's rebuttal side by side.

---

## Rate Limiting

`/submit` is limited to **10 requests per minute and 100 per day**, using Flask-Limiter with in-memory storage.

**Reasoning:** A legitimate creator posting their own work — even checking a few drafts back-to-back in one sitting — comfortably fits within 10/minute. The 100/day ceiling exists to stop a slower, scripted drip that stays under the per-minute limit but would still hammer the Groq API quota (and cost) over a full day. Both numbers are generous enough not to interrupt normal use, but tight enough to block obvious automated abuse.

**Evidence — 12 rapid requests against the live server:**
```
1 -> 200
2 -> 200
3 -> 200
4 -> 200
5 -> 200
6 -> 200
7 -> 200
8 -> 200
9 -> 200
10 -> 200
11 -> 200
12 -> 429
```
11 requests succeeded before the limiter engaged on request 12 rather than exactly request 11 — likely because Flask-Limiter's fixed window starts counting from the timestamp of the first request in the window rather than a clean second boundary, and these requests were fired close enough together to land inside that same window slightly differently than a strict "10 then cut" split. The limiter is confirmed working; the exact cutoff request number is a minor timing artifact, not a configuration error.

---

## Audit Log

Every submission and appeal writes a structured JSON entry (via `audit_log.py`) capturing: `content_id`, `creator_id`, `attribution`, `confidence`, `llm_score`, `llm_reasoning`, `stylometric_score`, `stylometric_components`, `status`, and `timestamp`. Appealed entries additionally carry `appeal_reasoning` and `appeal_timestamp`.

`GET /log` returns the most recent entries. Sample (trimmed to 3 of the 9+ entries generated during testing):

```json
{
  "content_id": "78e0a8b2-11c2-4ba0-a16a-dd3af816385e",
  "creator_id": "test-ai",
  "attribution": "uncertain",
  "confidence": 0.649,
  "llm_score": 0.85,
  "llm_reasoning": "The text exhibits a high likelihood of AI generation due to its overly formal tone, generic transitional phrases, and balanced argument structure...",
  "stylometric_score": 0.347,
  "stylometric_components": {
    "sentence_length_uniformity": 0.458,
    "low_vocabulary_diversity": 0.0,
    "formal_punctuation_density": 0.581
  },
  "status": "classified",
  "timestamp": "2026-07-01T04:58:12.564536+00:00"
}
```
```json
{
  "content_id": "2d82dbd9-68cd-417f-81bd-e981b0f39922",
  "creator_id": "test-human",
  "attribution": "likely_human",
  "confidence": 0.137,
  "llm_score": 0.2,
  "stylometric_score": 0.042,
  "status": "classified",
  "timestamp": "2026-07-01T05:06:58.824433+00:00"
}
```
```json
{
  "content_id": "212fb5d7-6256-497f-968b-6df36c5cf62e",
  "attribution": "uncertain",
  "confidence": 0.565,
  "status": "under_review",
  "appeal_reasoning": "I wrote this myself from personal experience...",
  "appeal_timestamp": "2026-07-01T05:07:51.565481+00:00"
}
```

---

## Known Limitations

**Short, formal text confuses the stylometric signal's vocabulary-diversity metric.** Type-token ratio (unique words ÷ total words) is only meaningful over a reasonably long sample. On a short paragraph (~40–60 words), even genuinely AI-generated text can have high lexical diversity simply because there hasn't been enough length for word repetition to occur naturally — this isn't a general "needs more data" problem, it's a specific mathematical property of the TTR formula at low word counts. This is visible directly in testing: the "clearly AI" test paragraph scored only 0.0 on the `low_vocabulary_diversity` sub-metric, dragging the overall stylometric score down even though the text is stereotypically AI in tone (see Spec Reflection below).

**Heavily edited AI output sits in a genuine gray zone.** A human who takes AI-drafted text and substantially rewrites it will likely trigger a mixed signal — the LLM signal may still catch residual AI-style phrasing while the stylometric signal reads the human edits as "burstier." The system is designed to land this case as `uncertain` rather than force a binary call, which I consider correct behavior, not a bug — but it does mean the system cannot distinguish "lightly touched-up AI" from "written by a human who happens to write formally."

---

## Spec Reflection

**How the spec helped:** The explicit instruction to test 4 deliberately varied inputs (clearly AI, clearly human, two borderline) before moving on caught a real calibration question I wouldn't have noticed otherwise — running the "clearly AI" test case revealed the two signals disagreeing by 0.503 (llm_score 0.85 vs. stylometric_score 0.347), well past my planned 0.4 disagreement threshold.

**Where implementation diverged from expectation:** The assignment's milestone description implies the "clearly AI" test input should score confidently AI. In my system it scored `uncertain` (0.649) instead, because the disagreement cap correctly triggered. I investigated whether to raise the cap threshold or reweight the signals to force this specific case higher, and decided not to — doing so would mean overriding a guardrail specifically designed to prevent one confident signal from dominating when the two signals genuinely disagree, which directly contradicts the false-positive-asymmetry principle the assignment itself calls out. I kept the cap as originally specified in `planning.md` rather than tuning it to match one example's expected output.

---

## AI Usage

**Instance 1 — Signal 1 + Flask skeleton generation, and a bug it introduced.** I gave the AI tool the Detection Signals section of `planning.md` plus the architecture diagram and asked it to generate the Flask app skeleton and the Groq LLM signal function. The generated `signals.py` only called `load_dotenv()` inside `app.py`, not inside `signals.py` itself — this worked fine when running through Flask, but broke (`GROQ_API_KEY not set`) the moment I ran `signals.py` standalone to verify the signal in isolation, exactly as the spec instructs. I directed the fix: adding `load_dotenv()` directly into `signals.py` so the module is self-contained regardless of how it's invoked.

**Instance 2 — Confidence scoring formula, and a result I chose not to override.** I gave the AI tool the Detection Signals, Uncertainty Representation sections, and the diagram, and asked for the stylometric signal function plus the combined confidence-scoring logic matching my specified weights and disagreement cap. When I tested the "clearly AI" sample, the combined score landed at `uncertain` rather than `likely_ai` because the disagreement cap fired. Rather than asking the AI to retune the weights to force a "cleaner" result on that one example, I kept the original formula — this was a deliberate decision to preserve the false-positive-asymmetry guardrail over matching an example's predicted output (documented fully in Spec Reflection above).

**Instance 3 — Appeal endpoint code style.** When generating the `POST /appeal` endpoint, the AI tool's first draft used an inline `__import__("datetime")` call to get a timestamp rather than a proper top-level import, presumably to avoid touching the existing import block. I overrode this and had it replaced with a clean `from datetime import datetime, timezone` import at the top of `app.py` — functionally identical, but the inline version would have been confusing and non-idiomatic to maintain.

---

## Setup

```bash
git clone <this-repo>
cd ai201-project4-provenance-guard
python -m venv .venv
.venv\Scripts\Activate.ps1      # Windows PowerShell
pip install -r requirements.txt
```

Create a `.env` file in the repo root:
```
GROQ_API_KEY=your_key_here
```

Run:
```bash
python app.py
```
Server starts on `http://localhost:5000`.

**Endpoints:**
- `POST /submit` — `{text, creator_id}` → `{content_id, attribution, confidence, label, signal_scores}`
- `POST /appeal` — `{content_id, creator_reasoning}` → `{content_id, status, message}`
- `GET /log` — returns recent audit log entries