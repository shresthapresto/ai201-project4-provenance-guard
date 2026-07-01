import uuid
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

load_dotenv()

from signals import llm_signal
from stylometrics import stylometric_signal
from labels import generate_label
import audit_log

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
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

    # Label text is generated from the exact verbatim variants in planning.md.
    label = generate_label(confidence)
    if confidence >= 0.70:
        attribution = "likely_ai"
    elif confidence <= 0.40:
        attribution = "likely_human"
    else:
        attribution = "uncertain"

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


@app.route("/appeal", methods=["POST"])
def appeal():
    data = request.get_json(silent=True) or {}
    content_id = data.get("content_id")
    creator_reasoning = data.get("creator_reasoning")

    if not content_id or not creator_reasoning:
        return jsonify({"error": "Both 'content_id' and 'creator_reasoning' are required."}), 400

    existing = audit_log.find_entry(content_id)
    if existing is None:
        return jsonify({"error": f"No submission found with content_id '{content_id}'."}), 404

    updated = audit_log.update_entry(content_id, {
        "status": "under_review",
        "appeal_reasoning": creator_reasoning,
        "appeal_timestamp": datetime.now(timezone.utc).isoformat(),
    })

    return jsonify({
        "content_id": content_id,
        "status": updated["status"],
        "message": "Appeal received. This content is now under human review.",
    })


@app.route("/log", methods=["GET"])
def get_log():
    entries = audit_log.get_entries(limit=50)
    return jsonify({"entries": entries})


if __name__ == "__main__":
    app.run(debug=True, port=5000)