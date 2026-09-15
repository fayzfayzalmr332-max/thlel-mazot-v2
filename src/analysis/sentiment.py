"""Weighted market-sentiment oracle.

Combines four sub-scores into one actionable 0-100 *stress* score and a
traffic-light grade:

    geopolitical pressure + momentum regime + local pricing-parity gap
    + shipping-pressure  ->  GREEN / YELLOW / RED

GREEN = global cool-down / relief signal.
RED   = persistent supply crunch / compounding pressure.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def parity_stress_score(gap_pct: float) -> float:
    """Official-vs-theoretical gap (gap>0 => official below fair => local
    pricing creates fiscal/queuing stress). Bounded asymmetric mapping."""
    gap = float(gap_pct)
    if gap > 0:
        return float(min(100.0, 50.0 + gap * 1.35))
    return float(max(0.0, 50.0 + gap * 1.1))


def shipping_stress_score(bdi: float, history: Optional[Any] = None) -> float:
    """Percentile of the current BDI within its recent window (0-100)."""
    try:
        bdi = float(bdi)
    except (TypeError, ValueError):
        return 50.0
    if history is not None and len(history) >= 5:
        lo, hi = float(min(history)), float(max(history))
        if hi > lo:
            return float(min(100.0, max(0.0, (bdi - lo) / (hi - lo) * 100.0)))
    return 50.0


def weight_set(settings: Dict[str, Any]) -> Dict[str, float]:
    w = settings.get("sentiment", {}).get("weights", {})
    default = {"geopolitical": 0.35, "momentum": 0.30, "parity_gap": 0.20, "shipping": 0.15}
    merged = dict(default)
    for k, v in w.items():
        merged[k] = float(v)
    return merged


def evaluate_sentiment(settings: Dict[str, Any],
                       momentum_score: float,
                       geo_score: float,
                       parity_gap_pct: Optional[float],
                       shipping_score: float) -> Dict[str, Any]:
    weights = weight_set(settings)
    total_w = sum(weights.values()) or 1.0
    gap_score = parity_stress_score(parity_gap_pct) if parity_gap_pct is not None else 50.0

    raw = (
        weights.get("geopolitical", 0.35) * float(geo_score)
        + weights.get("momentum", 0.30) * float(momentum_score)
        + weights.get("parity_gap", 0.20) * gap_score
        + weights.get("shipping", 0.15) * float(shipping_score)
    ) / total_w
    score = float(min(100.0, max(0.0, round(raw, 1))))

    labels = {
        "GREEN": "ارتياح / تبريد دولي",
        "YELLOW": "متابعة حذرة — استعد للتقلب",
        "RED": "استمرار أزمة الإمداد / ضغط مضاعف",
    }
    colors = {"GREEN": "#22c55e", "YELLOW": "#f5c04a", "RED": "#ef4444"}
    for band in settings.get("sentiment", {}).get("grade_bands", []):
        if score <= float(band["max_score"]):
            grade = band["grade"]
            break
    else:
        grade = "RED"

    label_ar = labels.get(grade, grade) or grade
    return {
        "score": score,
        "grade": grade,
        "label_ar": label_ar,
        "color": colors.get(grade, "#f5c04a"),
        "sub_scores": {
            "geopolitical": round(float(geo_score), 1),
            "momentum": round(float(momentum_score), 1),
            "parity_gap": round(gap_score, 1),
            "shipping": round(float(shipping_score), 1),
        },
        "weights": dict(weights),
        "explain": [
            "كل مؤشر فرعي يتم تسويته على مقياس توتر 0-100",
            "المرجحات: جيوسياسة + زخم أسعار + فجوة تسعير محلية + شحن",
            "RED تعني ضغط إمداد متصاعد / GREEN تعني انفراجًا ونافذة استقرار",
        ],
    }