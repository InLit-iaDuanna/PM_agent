from typing import Iterable


PROMPT_INJECTION_MARKERS = (
    "ignore previous instructions",
    "system prompt",
    "developer message",
    "reveal hidden instructions",
    "override the instructions",
)


def score_prompt_injection_risk(texts: Iterable[str]) -> float:
    lowered = " ".join(texts).lower()
    hits = sum(marker in lowered for marker in PROMPT_INJECTION_MARKERS)
    return round(min(1.0, hits * 0.2), 2)

