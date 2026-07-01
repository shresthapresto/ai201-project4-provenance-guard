import uuid
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

from signals import llm_signal
import audit_log

app = Flask(__name__)

import uuid
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

from signals import llm_signal
from stylometrics import stylometric_signal
import audit_log

app = Flask(__name__)


@app.route("/submit", methods=["POST"])
def submit():
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    creator_id = data.get("creator_id")

    if not text or not creator_id:
        return jsonify({"error": "Both 'text' and 'creator_id' are required."}), 400

    content_id = str(uuid.uuid4())

    # --- Signal 1: Groq LLM classification ---
    try:
        signal1 = llm_signal(text)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    llm_score = signal1["score"]

    # --- Signal 2: Stylometric heuristics ---
    signal2 = stylometric_signal(text)
    stylo_score = signal2["score"]

    # --- Confidence scoring: weighted combination per planning.md ---
    # LLM weighted higher (0.6) since it captures semantic signal stylometrics
    # can't. If the two signals disagree by more than 0.4, cap the combined
    # score at 0.7 -- strong disagreement between independent signals is
    # itself a sign of uncertainty, not confidence.
    confidence = (0.6 * llm_score) + (0.4 * stylo_score)
    if abs(llm_score - stylo_score) > 0.4:
        confidence = min(confidence, 0.7)
    confidence = round(max(0.0, min(1.0, confidence)), 3)

    # NOTE: label text is still placeholder -- Milestone 5 replaces it with
    # the exact verbatim text from planning.md's label variants.
    if confidence >= 0.70:
        attribution = "likely_ai"
        label = "PLACEHOLDER label -- finalized in Milestone 5"
    elif confidence <= 0.40:
        attribution = "likely_human"
        label = "PLACEHOLDER label -- finalized in Milestone 5"
    else:
        attribution = "uncertain"
        label = "PLACEHOLDER label -- finalized in Milestone 5"

    entry = {
        "content_id": content_id,
        "creator_id": creator_id,
        "attribution": attribution,
        "confidence": confidence,
        "llm_score": llm_score,
        "llm_reasoning": signal1["reasoning"],
        "stylometric_score": stylo_score,
        "stylometric_components": signal2["components"],
        "status": "classified",
    }
    audit_log.add_entry(entry)

    return jsonify({
        "content_id": content_id,
        "attribution": attribution,
        "confidence": confidence,
        "label": label,
        "signal_scores": {
            "llm_score": llm_score,
            "stylometric_score": stylo_score,
        },
    })


@app.route("/log", methods=["GET"])
def get_log():
    entries = audit_log.get_entries(limit=50)
    return jsonify({"entries": entries})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
@app.route("/submit", methods=["POST"])
def submit():
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    creator_id = data.get("creator_id")

    if not text or not creator_id:
        return jsonify({"error": "Both 'text' and 'creator_id' are required."}), 400

    content_id = str(uuid.uuid4())

    # --- Signal 1: Groq LLM classification ---
    try:
        signal1 = llm_signal(text)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    llm_score = signal1["score"]

    # NOTE: this is placeholder scoring/labeling for Milestone 3 only.
    # Milestone 4 replaces `confidence` with the real 2-signal weighted score.
    # Milestone 5 replaces `label` with the exact verbatim text from planning.md.
    confidence = llm_score
    if confidence >= 0.70:
        attribution = "likely_ai"
        label = "PLACEHOLDER label -- finalized in Milestone 5"
    elif confidence <= 0.40:
        attribution = "likely_human"
        label = "PLACEHOLDER label -- finalized in Milestone 5"
    else:
        attribution = "uncertain"
        label = "PLACEHOLDER label -- finalized in Milestone 5"

    entry = {
        "content_id": content_id,
        "creator_id": creator_id,
        "attribution": attribution,
        "confidence": confidence,
        "llm_score": llm_score,
        "llm_reasoning": signal1["reasoning"],
        "status": "classified",
    }
    audit_log.add_entry(entry)

    return jsonify({
        "content_id": content_id,
        "attribution": attribution,
        "confidence": confidence,
        "label": label,
        "signal_scores": {
            "llm_score": llm_score,
        },
    })


@app.route("/log", methods=["GET"])
def get_log():
    entries = audit_log.get_entries(limit=50)
    return jsonify({"entries": entries})


if __name__ == "__main__":
    app.run(debug=True, port=5000)