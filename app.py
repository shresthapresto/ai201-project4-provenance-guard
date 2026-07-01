import uuid
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

from signals import llm_signal
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