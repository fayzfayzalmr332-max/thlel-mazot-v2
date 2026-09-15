"""USD/SYP exchange-rate provider — official vs parallel (market) rate.

Because live USD/SYP feeds are unreliable, resolution is:
  manual override (sidebar) -> yfinance SYP candidate -> config baseline.
The parallel rate defaults to ``official * (1 + spread)`` but can be given
explicitly. The returned dict is immutable for consumers.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

from ..utils.disk_cache import DiskCache

try:  # pragma: no cover - environment dependent
    import yfinance as yf

    YF_AVAILABLE = True
except Exception:  # pylint: disable=broad-except
    yf = None
    YF_AVAILABLE = False

logger = logging.getLogger(__name__)


class FXProvider:
    def __init__(self, settings: Dict[str, Any], cache_dir: str | None = None):
        fx_cfg = settings.get("market", {}).get("fx", {})
        self.candidates = list(fx_cfg.get("candidates") or ["SYP=X"])
        self.official_default = float(fx_cfg.get("official_usd_syp", 13_000.0))
        self.parallel_default = float(fx_cfg.get("parallel_usd_syp", 15_200.0))
        self.spread = float(fx_cfg.get("parallel_spread", 0.06))

        app_cfg = settings.get("app", {})
        self.disk = DiskCache(cache_dir or app_cfg.get("cache_dir", ".cache"))
        self._override: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._mem: Optional[Dict[str, Any]] = None
        self._mem_ts: float = 0.0

    # ------------------------------------------------------------------ API

    def set_override(self, official: Optional[float] = None, parallel: Optional[float] = None) -> None:
        with self._lock:
            self._override = {}
            if official is not None and official > 0:
                self._override["official"] = float(official)
            if parallel is not None and parallel > 0:
                self._override["parallel"] = float(parallel)
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

    # --------------------------------------------------------------- internals

    def _live_syp(self) -> Optional[tuple]:
        """Return (last_close, prev_close) if a live SYP rate is reachable."""
        if not YF_AVAILABLE:
            return None
        for symbol in self.candidates:
            try:
                df = yf.download(symbol, period="10d", interval="1d",
                                 progress=False, auto_adjust=True, threads=False)
                if df is not None and len(df) and "Close" in df.columns:
                    closes = df["Close"].dropna()
                    if len(closes) >= 2:
                        return float(closes.iloc[-1]), float(closes.iloc[-2])
            except Exception as exc:  # pylint: disable=broad-except
                logger.debug("FX live fetch failed for %s: %s", symbol, exc)
        return None

    def _compute(self) -> Dict[str, Any]:
        live = self._live_syp()
        source = "config"

        live_official = (live[0] if live else None)
        prev_official = (live[1] if live else None)

        official = float(self._override.get("official", live_official if live_official else self.official_default))
        source = "live" if live_official else source

        explicit_parallel = self._override.get("parallel")
        if explicit_parallel:
            parallel = float(explicit_parallel)
            source = "manual"
        else:
            parallel_official = live_official if live_official else official
            parallel = float(self._override.get("official", parallel_official * (1.0 + self.spread)))

        trend_pct = None
        if prev_official and live_official:
            trend_pct = ((live_official - prev_official) / prev_official) * 100.0

        # A tiny deterministic "market jitter" keeps the parallel quote living
        # when it is derived from config, without inventing false precision.
        if source not in ("live", "manual"):
            seed = int((datetime.utcnow().strftime("%H%M"))[-2:])
            jitter = 1.0 + (seed % 40 - 20) / 10_000.0
            parallel = parallel * jitter

        return {
            "official": round(official, 2),
            "parallel": round(max(parallel, official), 2),
            "spread_pct": round((max(parallel, official) / official - 1.0) * 100.0, 2),
            "source": source,
            "trend_pct": round(trend_pct, 3) if trend_pct is not None else None,
            "ts": datetime.utcnow().isoformat() + "Z",
        }