def generate_label(confidence: float) -> str:
    """
    Maps a confidence score to one of three transparency label variants.
    Thresholds and text are verbatim from planning.md Section 3.
    """
    if confidence >= 0.70:
        return (
            f"This content shows strong signals of AI generation "
            f"(confidence: {confidence}). This is an automated assessment, "
            f"not a certainty -- the creator can appeal this result."
        )
    elif confidence <= 0.40:
        return (
            f"This content shows strong signals of human authorship "
            f"(confidence: {confidence})."
        )
    else:
        return (
            f"We can't confidently determine whether this content is "
            f"AI-generated or human-written (confidence: {confidence}). "
            f"Treat this result as inconclusive."
        )


if __name__ == "__main__":
    # Verify all three variants are reachable at representative scores.
    for score in [0.85, 0.55, 0.15]:
        print(f"confidence={score} -> {generate_label(score)}\n")