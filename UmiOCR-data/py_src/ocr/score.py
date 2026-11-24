"""Confidence-score helpers shared by OCR task and result paths."""

import math


def isFiniteScore(value):
    """Whether ``value`` is a real confidence value suitable for aggregation."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def averageScore(items):
    """Average only real finite numeric confidences.

    Vision-language spotting does not provide a calibrated confidence today;
    returning ``None`` keeps that fact intact instead of inventing a zero.
    """
    scores = [
        float(item.get("score"))
        for item in (items or [])
        if isinstance(item, dict) and isFiniteScore(item.get("score"))
    ]
    return sum(scores) / len(scores) if scores else None
