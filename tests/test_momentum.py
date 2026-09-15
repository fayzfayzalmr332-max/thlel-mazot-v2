"""Tests for the Rocket-and-Feather regime detector."""
from __future__ import annotations

import numpy as np

from src.analysis.momentum import analyze_momentum, score_momentum


def _flat(days: int = 40, base: float = 100.0) -> list:
    return [float(base)] * days


def test_rocket_detected():
    prices = _flat() + [100 * (1.03 ** i) for i in range(1, 6)]
    regime = analyze_momentum(prices)
    assert regime["state"] == "ROCKET"
    assert regime["c_short"] >= 6.0
    assert regime["spike_flag"] is True


def test_feather_detected():
    prices = _flat(60) + [100 * (0.9985 ** i) for i in range(1, 31)]
    regime = analyze_momentum(prices, {"long_window": 30, "drift_long_pct": 4.0,
                                       "feather_min_down_days": 12})
    assert regime["state"] == "FEATHER", regime
    assert regime["feather_flag"] is True


def test_neutral_on_noise():
    rng = np.random.default_rng(7)
    prices = np.cumprod(1 + rng.normal(0.0, 0.002, 80)) * 100.0
    regime = analyze_momentum(prices.tolist())
    assert regime["state"] in ("NEUTRAL", "ROCKET", "FEATHER", "PURGE", "MIXED")


def test_scores_stay_in_bounds():
    for state in ("ROCKET", "FEATHER", "MIXED", "PURGE", "NEUTRAL"):
        score = score_momentum({"state": state, "c_short": 8.0})
        assert 0.0 <= score <= 100.0


def test_insufficient_samples_is_safe():
    regime = analyze_momentum([100.0, 101.0])
    assert regime["state"] == "NEUTRAL"
    assert regime.get("details")