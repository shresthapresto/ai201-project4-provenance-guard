import re
import statistics


def _split_sentences(text: str):
    # Simple sentence splitter on . ! ? — good enough for stylometric purposes,
    # doesn't need to be perfect since we're measuring variance, not parsing grammar.
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s for s in sentences if s.strip()]


def _split_words(text: str):
    return re.findall(r"[A-Za-z']+", text.lower())


def _sentence_length_variance_score(sentences) -> float:
    """
    AI text tends toward uniform sentence length; human text is 'burstier'
    (mixes short punchy sentences with long rambling ones).
    Returns 0-1 where HIGHER = more uniform = more AI-like.
    """
    if len(sentences) < 2:
        # Not enough sentences to compute meaningful variance -- neutral score.
        return 0.5

    lengths = [len(_split_words(s)) for s in sentences]
    if not any(lengths):
        return 0.5

    mean_len = statistics.mean(lengths)
    if mean_len == 0:
        return 0.5

    stdev = statistics.pstdev(lengths)
    coefficient_of_variation = stdev / mean_len

    # Low CV (uniform lengths) -> high AI-likeness score.
    # Empirically, human writing often has CV > 0.5; AI text often < 0.35.
    # Map CV to a 0-1 "AI-likeness" score, inverted and clamped.
    score = 1.0 - min(coefficient_of_variation / 0.7, 1.0)
    return max(0.0, min(1.0, score))


def _type_token_ratio_score(words) -> float:
    """
    Type-token ratio = unique words / total words. AI text tends to reuse
    a narrower, 'safer' vocabulary; human text is often more lexically diverse
    (or, at low word counts, TTR can swing either way -- we account for that).
    Returns 0-1 where HIGHER = lower diversity = more AI-like.
    """
    if len(words) < 5:
        return 0.5  # too short to be meaningful

    unique_words = set(words)
    ttr = len(unique_words) / len(words)

    # Typical human TTR for medium-length text: ~0.55-0.75
    # Typical AI TTR: tends to sit lower, ~0.40-0.55, due to safer word choice.
    # Invert: low TTR -> high AI-likeness score.
    score = 1.0 - min(ttr / 0.75, 1.0)
    return max(0.0, min(1.0, score))


def _punctuation_density_score(text: str, words) -> float:
    """
    AI text often uses punctuation (commas, semicolons, em-dashes) in a
    very regular, 'correct' way; human writing is more erratic -- run-ons,
    missing commas, exclamation points, ellipses, ALL CAPS for emphasis.
    Returns 0-1 where HIGHER = more 'regular' punctuation = more AI-like.
    """
    if not words:
        return 0.5

    commas = text.count(",")
    semicolons = text.count(";")
    exclamations = text.count("!")
    ellipses = text.count("...")

    word_count = len(words)
    formal_punct_rate = (commas + semicolons) / word_count
    informal_punct_rate = (exclamations + ellipses) / word_count

    # High formal punctuation rate + low informal punctuation rate -> AI-like.
    # Normalize against rough empirical ranges.
    formal_score = min(formal_punct_rate / 0.08, 1.0)
    informal_penalty = min(informal_punct_rate / 0.03, 1.0)

    score = formal_score - (informal_penalty * 0.5)
    return max(0.0, min(1.0, score))


def stylometric_signal(text: str) -> dict:
    """
    Signal 2: Stylometric heuristics.

    Measures concrete statistical properties -- sentence length variance,
    type-token ratio, punctuation density -- per planning.md.

    Returns: {"score": float 0.0-1.0, "components": dict of sub-scores}
    score = likelihood the text is AI-generated, based on structural features.
    """
    sentences = _split_sentences(text)
    words = _split_words(text)

    sentence_score = _sentence_length_variance_score(sentences)
    ttr_score = _type_token_ratio_score(words)
    punct_score = _punctuation_density_score(text, words)

    # Equal weighting across the three sub-metrics, per planning.md.
    combined = (sentence_score + ttr_score + punct_score) / 3.0

    return {
        "score": round(combined, 3),
        "components": {
            "sentence_length_uniformity": round(sentence_score, 3),
            "low_vocabulary_diversity": round(ttr_score, 3),
            "formal_punctuation_density": round(punct_score, 3),
        },
    }


if __name__ == "__main__":
    test_texts = [
        ("clearly AI", "Artificial intelligence represents a transformative paradigm shift "
         "in modern society. It is important to note that while the benefits of AI are "
         "numerous, it is equally essential to consider the ethical implications. "
         "Furthermore, stakeholders across various sectors must collaborate to ensure "
         "responsible deployment."),
        ("clearly human", "ok so i finally tried that new ramen place downtown and honestly? "
         "underwhelming. the broth was fine but they put WAY too much sodium in it and i was "
         "thirsty for like three hours after. my friend got the spicy version and said it was "
         "better. probably won't go back unless someone drags me there"),
        ("borderline formal human", "The relationship between monetary policy and asset price "
         "inflation has been extensively studied in the literature. Central banks face a "
         "fundamental tension between their mandate for price stability and the unintended "
         "consequences of prolonged low interest rates on equity and real estate valuations."),
        ("borderline lightly-edited AI", "I've been thinking a lot about remote work lately. "
         "There are genuine tradeoffs -- flexibility and no commute on one side, isolation and "
         "blurred work-life boundaries on the other. Studies show productivity varies widely by "
         "individual and role type."),
    ]
    for label, t in test_texts:
        result = stylometric_signal(t)
        print(f"[{label}] score={result['score']:.2f}  components={result['components']}")