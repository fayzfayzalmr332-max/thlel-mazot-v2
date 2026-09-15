"""Number, currency and badge formatting helpers (Syrian-market flavored)."""
from __future__ import annotations

from datetime import datetime


def fmt_num(value, digits: int = 2, suffix: str = "") -> str:
    try:
        return f"{float(value):,.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return "—"


def fmt_syp(amount, digits: int = 0) -> str:
    return f"{fmt_num(amount, digits)} ل.س"


def fmt_usd(amount, digits: int = 2) -> str:
    return f"${fmt_num(amount, digits)}"


def fmt_pct(value, signed: bool = False) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = ""
    if signed and v > 0:
        sign = "+"
    return f"{sign}{v:,.2f}%"


def arrow(delta) -> str:
    """▲/▼/· glyphs for deltas."""
    try:
        d = float(delta)
    except (TypeError, ValueError):
        return "·"
    if d > 1e-9:
        return "▲"
    if d < -1e-9:
        return "▼"
    return "·"


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")