"""Tests for the weighted sentiment oracle."""
from __future__ import annotations

from src.analysis.sentiment import (
    evaluate_sentiment,
    parity_stress_score,
    shipping_stress_score,
)

SENT_CFG = {
    "sentiment": {
        "weights": {
            "geopolitical": 0.35,
            "momentum": 0.30,
            "parity_gap": 0.20,
            "shipping": 0.15,
        },
        "grade_bands": [
            {"max_score": 35, "grade": "GREEN"},
            {"max_score": 65, "grade": "YELLOW"},
            {"max_score": 100, "grade": "RED"},
        ],
    }
}


def test_low_stress_gives_green():
    result = evaluate_sentiment(SENT_CFG, momentum_score=10, geo_score=10,
                                parity_gap_pct=-15, shipping_score=10)
    assert result["grade"] == "GREEN"
    assert result["score"] <= 35


def test_high_stress_gives_red():
    result = evaluate_sentiment(SENT_CFG, momentum_score=95, geo_score=95,
                                parity_gap_pct=30, shipping_score=90)
    assert result["grade"] == "RED"
    assert result["score"] >= 65


def test_score_clamped():
    result = evaluate_sentiment(SENT_CFG, momentum_score=200, geo_score=300,
                                parity_gap_pct=500, shipping_score=1)
    assert 0 <= result["score"] <= 100


def test_parity_mapping_edges():
    assert parity_stress_score(-40) < 10
    assert parity_stress_score(40) > 90


def test_shipping_percentile():
    hist = [100.0, 200.0, 300.0, 400.0, 500.0]
    assert shipping_stress_score(500.0, hist) == pytest_almost(100.0)
    assert shipping_stress_score(250.0, hist) == pytest_almost(37.5)


def pytest_almost(value, place: int = 6):
    return round(float(value), place)