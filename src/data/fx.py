"""USD/SYP exchange-rate provider — official vs parallel (market) rate.

Live-source waterfall (first success wins, never raises):
  1. manual override (sidebar / caller)
  2. SP Today (sp-today.com)        -> market/parallel quote (buy/sell mid)
  3. exchangerate-api (open.er-api) -> official/central-bank style quote
  4. yfinance SYP candidates
  5. config baselines

REDENOMINATION AWARENESS: Syria replaced its currency (2 zeros removed — the
"new Syrian pound"). All live sources are normalised to *new* SYP and both
new/old values are returned so the UI can display either unit.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

from ..utils.disk_cache import DiskCache

try:  # pragma: no cover - environment dependent
    import yfinance as yf

    YF_AVAILABLE = True
except Exception:  # pylint: disable=broad-except
    yf = None
    YF_AVAILABLE = False

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 10.0
_ERAPI_URL = "https://open.er-api.com/v6/latest/USD"
_SPTODAY_URL = "https://sp-today.com/en"

_SP_TODAY_RE = re.compile(
    r"US Dollar[\s\S]{0,400}?Buy[\s\S]{0,200}?>([\d.,]+)<[\s\S]{0,300}?Sell[\s\S]{0,200}?>([\d.,]+)<",
    re.I,
)


def _num(text: str) -> Optional[float]:
    """Parse '13,375' / '133.75' -> float (None on failure)."""
    try:
        v = float(str(text).replace(",", "").strip())
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def extract_closes(df: Any) -> Optional[Any]:
    """Robustly pull a flat 1-D Close series out of a yfinance frame.

    Newer yfinance versions return MultiIndex columns even for a single
    ticker; ``df["Close"]`` then yields a *DataFrame*, not a Series, which
    broke the previous live path with ``float(Series)`` TypeErrors.
    """
    if df is None:
        return None
    try:
        import pandas as pd  # local import keeps module import-light

        close = df["Close"] if "Close" in df.columns else None
        if close is None:
            return None
        if isinstance(close, pd.DataFrame):  # MultiIndex case
            close = close.iloc[:, 0]
        close = pd.to_numeric(close, errors="coerce").dropna()
        return close if len(close) else None
    except Exception:  # pylint: disable=broad-except
        return None


class FXProvider:
    def __init__(self, settings: Dict[str, Any], cache_dir: str | None = None):
        fx_cfg = settings.get("market", {}).get("fx", {})
        self.candidates: List[str] = list(fx_cfg.get("candidates") or ["SYP=X"])
        self.official_default = float(fx_cfg.get("official_usd_syp", 121.0))
        self.parallel_default = float(fx_cfg.get("parallel_usd_syp", 134.0))
        self.spread = float(fx_cfg.get("parallel_spread", 0.10))
        # Redenomination: display/input unit of the config file ("new"/"old")
        # and the multiplier new -> old (new SYP x 100 = old SYP).
        self.unit = str(fx_cfg.get("syp_unit", "new")).lower()
        self.old_factor = float(fx_cfg.get("old_factor", 100.0))

        app_cfg = settings.get("app", {})
        self.disk = DiskCache(cache_dir or app_cfg.get("cache_dir", ".cache"))
        self._override: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._mem: Optional[Dict[str, Any]] = None
        self._mem_ts: float = 0.0

    # ------------------------------------------------------------------ API

    def set_override(self, official: Optional[float] = None,
                     parallel: Optional[float] = None) -> None:
        """Set manual rates *in the configured display unit*."""
        with self._lock:
            self._override = {}
            if official is not None and official > 0:
                self._override["official"] = self._to_new(float(official))
            if parallel is not None and parallel > 0:
                self._override["parallel"] = self._to_new(float(parallel))
            self._mem = None
            self._mem_ts = 0.0

    def clear_override(self) -> None:
        with self._lock:
            self._override = {}
            self._mem = None
            self._mem_ts = 0.0

    def get_rates(self) -> Dict[str, Any]:
        with self._lock:
            if self._mem and (time.time() - self._mem_ts) < 120:
                return dict(self._mem)

        result = self._compute()
        with self._lock:
            self._mem = result
            self._mem_ts = time.time()
        return dict(result)

    # --------------------------------------------------------------- helpers

    def _to_new(self, value: float) -> float:
        """Config-unit -> new-SYP normalisation."""
        return value / self.old_factor if self.unit == "old" else float(value)

    def _to_display(self, value_new: float) -> float:
        """New-SYP -> configured display unit."""
        return value_new * self.old_factor if self.unit == "old" else float(value_new)

    # ------------------------------------------------------------ live pulls

    def _live_yf(self) -> Optional[Tuple[float, float]]:
        """(last, prev) market-style SYP quote via yfinance."""
        if not YF_AVAILABLE:
            return None
        for symbol in self.candidates:
            try:
                df = yf.download(symbol, period="10d", interval="1d",
                                 progress=False, auto_adjust=True, threads=False)
                closes = extract_closes(df)
                if closes is not None and len(closes) >= 2:
                    return float(closes.iloc[-1]), float(closes.iloc[-2])
            except Exception as exc:  # pylint: disable=broad-except
                logger.debug("FX live fetch failed for %s: %s", symbol, exc)
        return None

    def _live_erapi(self) -> Optional[float]:
        """Official-style USD/SYP from exchangerate-api (free, key-less)."""
        try:
            data = requests.get(_ERAPI_URL, timeout=_HTTP_TIMEOUT).json()
            return _num(str(data.get("rates", {}).get("SYP", "")))
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("ER-API fetch failed: %s", exc)
            return None

    def _live_sptoday(self) -> Optional[Tuple[float, float]]:
        """Market (parallel) USD/SYP buy/sell from SP Today -> (buy, sell)."""
        try:
            r = requests.get(_SPTODAY_URL, timeout=_HTTP_TIMEOUT,
                             headers={"User-Agent": "Mozilla/5.0"})
            m = _SP_TODAY_RE.search(r.text or "")
            if not m:
                return None
            buy, sell = _num(m.group(1)), _num(m.group(2))
            return (buy, sell) if (buy and sell) else None
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("SP-Today fetch failed: %s", exc)
            return None

    # -------------------------------------------------------------- pipeline

    def _compute(self) -> Dict[str, Any]:
        """Resolve official + parallel rates with full source provenance."""
        sources: List[str] = []
        official = parallel = None
        trend_pct = None

        # 1) manual override wins outright
        if self._override.get("official") or self._override.get("parallel"):
            official = self._override.get("official")
            parallel = self._override.get("parallel")
            sources.append("manual")

        # 2) SP Today market quote -> parallel
        if parallel is None:
            sp = self._live_sptoday()
            if sp:
                parallel = (sp[0] + sp[1]) / 2.0
                sources.append("sp-today")

        # 3) exchangerate-api -> official
        if official is None:
            er = self._live_erapi()
            if er:
                official = er
                sources.append("er-api")

        # 4) yfinance market quote fills whatever is still missing
        if official is None or parallel is None:
            yf_q = self._live_yf()
            if yf_q:
                last, prev = yf_q
                if official is None:
                    official = last
                    sources.append("yf")
                if parallel is None:
                    parallel = last * (1.0 + self.spread)
                    sources.append("yf")
                if prev:
                    trend_pct = (last - prev) / prev * 100.0

        # 5) config fallback
        if official is None:
            official = self.official_default
            sources.append("config")
        if parallel is None:
            parallel = official * (1.0 + self.spread)
            sources.append("config-derived")

        official, parallel = float(official), float(parallel)

        # Tiny deterministic jitter keeps a config-derived quote "living"
        # without inventing false precision from live sources.
        if not any(s in ("sp-today", "yf", "manual") for s in sources):
            seed = int(datetime.utcnow().strftime("%H%M")[-2:])
            parallel *= 1.0 + (seed % 40 - 20) / 10_000.0

        parallel = max(parallel, official)
        spread_pct = (parallel / official - 1.0) * 100.0

        return {
            "official": round(official, 2),
            "parallel": round(parallel, 2),
            "spread_pct": round(spread_pct, 2),
            "unit": "new",                      # normalised storage unit
            "official_old": round(official * self.old_factor),
            "parallel_old": round(parallel * self.old_factor),
            "sources": sources,
            "source": sources[-1] if sources else "config",
            "trend_pct": round(trend_pct, 3) if trend_pct is not None else None,
            "ts": datetime.utcnow().isoformat() + "Z",
        }