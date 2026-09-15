"""Deterministic synthetic market-data generator (offline/DEMO mode).

Used only when no live or cached feed is available, so the dashboard always
renders and remains fully interactive. Streams are seeded per asset so the
"demo market" is reproducible, but each fresh run evolves them.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def generate_synthetic_history(
    base: float,
    vol: float,
    drift: float,
    days: int,
    seed: int,
) -> pd.DataFrame:
    """Geometric-Brownian OHLCV series, business days only."""
    days = max(int(days), 60)
    rng = np.random.default_rng(int(seed))
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    daily_vol = vol / np.sqrt(252)
    log_ret = rng.normal(loc=drift / 252.0, scale=daily_vol, size=days)

    # Blend in a persistent regime so charts look realistic, not pure noise.
    regime = np.linspace(-vol * 0.15, vol * 0.15, days) * (rng.random() - 0.5)
    log_ret = log_ret + regime

    close = base * np.exp(np.cumsum(log_ret))
    open_ = close * (1 + rng.normal(0.0, daily_vol * 0.25, size=days))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0.0, daily_vol * 0.3, size=days)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0.0, daily_vol * 0.3, size=days)))
    volume = rng.integers(80_000, 420_000, size=days).astype(float)

    df = pd.DataFrame(
        {
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
        },
        index=dates,
    )
    df.index.name = "Date"
    return df


def generate_synthetic_intraday(base: float, vol: float, rows: int = 160, end=None) -> pd.DataFrame:
    """Short intraday series (~2 days of 5m bars) used for the 'live' estimate."""
    rows = max(int(rows), 40)
    rng = np.random.default_rng(int(base * 1000) % (2**31))
    if end is None:
        end = pd.Timestamp.utcnow().floor("min")
    idx = pd.date_range(end=end, periods=rows, freq="5min")
    ret = rng.normal(loc=0.0, scale=vol / np.sqrt(252 * 24 * 12), size=rows)
    close = base * np.exp(np.cumsum(ret))
    df = pd.DataFrame({"Close": close}, index=idx)
    df.index.name = "Date"
    return df