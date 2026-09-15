"""Rocket-and-feather regime detection for energy prices.

The classic asymmetry of oil products: prices "rocket" up on supply shocks
(fast, sharp) but drift slowly down as demand/refining normalise ("feather").

Detection logic (configurable via ``momentum`` in settings.yaml):

* ``ROCKET``  -> short-window cumulative gain >= spike threshold (e.g. +6% in 5
  days) OR recent up-speed clearly exceeds recent down-speed while net-rising.
* ``FEATHER`` -> long-window cumulative decline, many down-days, and a small
  average daily decline (a slow melt, not a crash).
* ``MIXED``   -> both signatures active at once (rocket-then-feather).
* ``PURGE``   -> a sharp short-window crash (fast clean-out, not a feather).
* ``NEUTRAL`` -> no dominant pattern.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

import pandas as pd


def analyze_momentum(prices: Sequence[float], cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or {}
    out: Dict[str, Any] = {
        "state": "NEUTRAL",
        "state_ar": "متوازن",
        "c_short": None,
        "c_long": None,
        "up_velocity": None,
        "down_velocity": None,
        "up_speed_short": None,
        "down_speed_short": None,
        "asymmetry_index": None,
        "spike_flag": False,
        "feather_flag": False,
        "details": [],
        "rolling_short": None,
    }

    s = pd.Series(list(prices), dtype="float64").dropna().reset_index(drop=True)
    short_win = max(int(cfg.get("short_window", 5)), 2)
    long_win = max(int(cfg.get("long_window", 30)), short_win + 2)
    if len(s) < max(long_win + 2, 20):
        out["details"].append("عيّنة البيانات غير كافية للتحليل (نحتاج ≥ 30 نقطة).")
        return out

    closes = s.values
    ret = s.pct_change().dropna()
    c_short = (closes[-1] / closes[-short_win] - 1.0) * 100.0
    c_long = (closes[-1] / closes[-long_win] - 1.0) * 100.0

    up = ret[ret > 0]
    down = ret[ret < 0]
    up_velocity = float(up.mean() * 100.0) if len(up) else 0.0
    down_velocity = float((-down).mean() * 100.0) if len(down) else 0.0

    r_s = ret.tail(short_win)
    up_s = r_s[r_s > 0]
    dn_s = r_s[r_s < 0]
    up_speed = float(up_s.mean() * 100.0) if len(up_s) else 0.0
    down_speed = float((-dn_s).mean() * 100.0) if len(dn_s) else 0.0
    asym = (up_speed + 1e-9) / (down_speed + 1e-9)

    spike_thr = float(cfg.get("spike_5d_pct", 6.0))
    purge_thr = float(cfg.get("purging_5d_pct", -6.0))
    drift_thr = float(cfg.get("drift_long_pct", 4.0))
    min_feather_days = int(cfg.get("feather_min_down_days", 12))
    max_daily_decline = float(cfg.get("feather_max_daily_decline", 0.35))

    r_l = ret.tail(long_win)
    down_days = int((r_l < 0).sum())
    decline_total = float(r_l[r_l < 0].sum() * 100.0)
    avg_daily_decline = decline_total / max(float(len(r_l)), 1.0)

    spike_flag = bool(c_short >= spike_thr or (c_short > 0 and up_speed > 2.0 * down_speed))
    feather_flag = bool(
        down_days >= min_feather_days
        and abs(c_long) >= drift_thr
        and avg_daily_decline <= max_daily_decline
    )

    if spike_flag and feather_flag:
        state, state_ar = "MIXED", "ارتفاع صاروخي ثم انحدار ريشي"
    elif spike_flag:
        state, state_ar = "ROCKET", "انطلاق صاروخي (ارتفاع حاد)"
    elif feather_flag:
        state, state_ar = "FEATHER", "انحدار ريشي (زحف هابط بطيء)"
    elif c_short <= purge_thr:
        state, state_ar = "PURGE", "تطهير/تصحيح حاد سريع"
    else:
        state, state_ar = "NEUTRAL", "متوازن"

    details = []
    details.append(f"حركة 5 أيام: {c_short:+.2f}% | حركة 30 يومًا: {c_long:+.2f}%")
    details.append(f"متوسط سرعة الصعود اليومية: {up_velocity:.3f}% | السرعة الهبوطية: {down_velocity:.3f}%")
    details.append(f"سرعة الصعود/الهبوط المعاصرة: {up_speed:.3f}% vs {down_speed:.3f}% | مؤشر عدم التماثل: {asym:.2f}")

    # Historical short-window momentum series (for the annotated chart).
    rolling_short = s.pct_change(short_win) * 100.0
    rolling_short.index = s.index

    out.update({
        "state": state,
        "state_ar": state_ar,
        "c_short": c_short,
        "c_long": c_long,
        "up_velocity": up_velocity,
        "down_velocity": down_velocity,
        "up_speed_short": up_speed,
        "down_speed_short": down_speed,
        "asymmetry_index": asym,
        "spike_flag": spike_flag,
        "feather_flag": feather_flag,
        "details": details,
        "rolling_short": rolling_short,
        "down_days_30": down_days,
        "avg_daily_decline": avg_daily_decline,
        "latex_hint": (
            "ROCKET  ⟸  R_5 ≥ +6%  ∨  (R_5>0 ∧ ū>2·d̄)    "
            "FEATHER ⟸  R_30 ≤ −4% ∧ أيام هابطة≥12 ∧ زحف≤0.35%/يوم"
        ),
    })
    return out


def score_momentum(regime: Dict[str, Any]) -> float:
    """Map a regime dict onto a 0-100 *stress* scale (100 = tightest)."""
    state = regime.get("state", "NEUTRAL")
    if state == "ROCKET":
        base = float(regime.get("c_short", 6.0) or 6.0)
        score = 55.0 + max(base, 0.0) * 5.0
    elif state == "MIXED":
        score = 78.0
    elif state == "FEATHER":
        score = 35.0
    elif state == "PURGE":
        score = 20.0
    else:
        score = 45.0
    return float(min(100.0, max(0.0, round(score, 1))))