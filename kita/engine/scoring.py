"""Schedule quality scoring utilities."""


def score_label(score: int) -> str:
    """Return a German label for a score value."""
    if score >= 90:
        return "Sehr gut"
    if score >= 75:
        return "Gut"
    if score >= 50:
        return "Ausreichend"
    return "Mangelhaft"


def score_color(score: int) -> str:
    """Return a CSS color for a score value."""
    if score >= 90:
        return "#22C55E"
    if score >= 75:
        return "#EAB308"
    if score >= 50:
        return "#F97316"
    return "#EF4444"
