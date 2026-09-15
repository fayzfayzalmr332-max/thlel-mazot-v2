"""Robust multi-source market-data provider.

Resolution order per ticker key:
  1. in-process memory (short TTL)  -> smooth auto-refresh
  2. yfinance live pull (multi-candidate + retries)
  3. disk cache (TTL hours)
  4. deterministic synthetic DEMO series (dashboard never dies offline)

Every call returns ``(DataFrame, meta_dict)`` where ``meta["source"]`` is one
of ``"live" | "ttl-cache" | "synthetic"`` so the UI can display honest badges.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import numpy as np  # noqa: F401  (re-exported convenience)
import pandas as pd

from ..utils.disk_cache import DiskCache
from .synthetic import generate_synthetic_history, generate_synthetic_intraday

try:  # pragma: no cover - environment dependent
    import yfinance as yf

    YF_AVAILABLE = True
except Exception:  # pylint: disable=broad-except
    yf = None
    YF_AVAILABLE = False

logger = logging.getLogger(__name__)

OHLCV_COLS = ["Open", "High", "Low", "Close", "Volume"]


class MarketDataProvider:
    def __init__(self, settings: Dict[str, Any], cache_dir: str | None = None,
                 force_synthetic: bool = False):
        self.settings = settings
        self.force_synthetic = force_synthetic
        app_cfg = settings.get("app", {})
        hist_cfg = settings.get("market", {}).get("history", {})
        self.period = hist_cfg.get("period", "1y")
        self.interval = hist_cfg.get("interval", "1d")
        self.days = int(hist_cfg.get("days", 252))
        self.intraday_interval = hist_cfg.get("intraday_interval", "5m")
        self.intraday_days = int(hist_cfg.get("intraday_days", 3))

        cache_path = cache_dir or app_cfg.get("cache_dir", ".cache")
        self.disk = DiskCache(cache_path)
        self._mem_ttl_s = int(app_cfg.get("mem_cache_seconds", 300))

        self.tickers: Dict[str, dict] = settings.get("market", {}).get("tickers", {})
        self._mem: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- public

    def get_history(self, key: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        tick = self.tickers.get(key)
        if not tick:
            raise KeyError(f"Unknown ticker key: {key}")
        hit = self._mem.get(key)
        if hit and (time.time() - hit["ts"]) < self._mem_ttl_s:
            return hit["df"], dict(hit["meta"])

        df, meta = self._resolve_history(tick)
        if len(df) == 0:
            df = generate_synthetic_history(
                base=float(tick.get("synthetic_base", 100.0)),
                vol=float(tick.get("synthetic_vol", 0.25)),
                drift=float(tick.get("synthetic_drift", 0.02)),
                days=self.days,
                seed=int(hash(str(tick.get("display", key))) % (2**31)),
            )
            meta = {"source": "synthetic", "symbol": self._display(tick),
                    "ticker_key": key, "ts": datetime.utcnow().isoformat() + "Z"}

        with self._lock:
            self._mem[key] = {"df": df, "meta": meta, "ts": time.time()}
        return df, dict(meta)

    def get_intraday(self, key: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Short high-frequency window for the 'live' reading."""
        tick = self.tickers.get(key)
        if not tick:
            raise KeyError(f"Unknown ticker key: {key}")
        for symbol in tick.get("candidates", [tick.get("symbol")]) or []:
            df, ok = self._fetch_yf(symbol, interval=self.intraday_interval,
                                    period=f"{self.intraday_days}d")
            if ok and len(df):
                return df, {"source": "live", "symbol": symbol, "interval": self.intraday_interval,
                            "ts": datetime.utcnow().isoformat() + "Z"}
        base = float(tick.get("synthetic_base", 100.0))
        vol = float(tick.get("synthetic_vol", 0.25))
        sdf = generate_synthetic_intraday(base, vol)
        return sdf, {"source": "synthetic", "symbol": self._display(tick),
                     "interval": self.intraday_interval,
                     "ts": datetime.utcnow().isoformat() + "Z"}

    def get_latest(self, key: str) -> Dict[str, Any]:
        """Latest close, its daily change, and metadata for a metric card."""
        df, meta = self.get_history(key)
        closes = df["Close"].dropna()
        if len(closes) == 0:
            return {"value": None, "change_pct": None, "source": "synthetic"}
        last = float(closes.iloc[-1])
        prev = float(closes.iloc[-2]) if len(closes) > 1 else last
        change_pct = ((last - prev) / prev * 100.0) if prev else 0.0
        return {
            "value": last,
            "prev": prev,
            "change_pct": change_pct,
            "source": meta.get("source", "?"),
            "symbol": meta.get("symbol", self._display(self.tickers.get(key, {}))),
            "ts": meta.get("ts", ""),
        }

    def get_latest_many(self, keys) -> Dict[str, Dict[str, Any]]:
        return {k: self.get_latest(k) for k in keys}

    def _display(self, tick: dict) -> str:
        return tick.get("display") or tick.get("primary") or tick.get("symbol") or "?"

    def _apply_unit_factor(self, df: pd.DataFrame, tick: dict, symbol: str) -> pd.DataFrame:
        """Convert an alternate instrument to the canonical unit (USD/tonne)."""
        factor = float(tick.get("unit_factors", {}).get(symbol, 1.0) or 1.0)
        if abs(factor - 1.0) > 1e-9:
            df = df.copy()
            for col in OHLCV_COLS:
                if col in df.columns:
                    df[col] = df[col].astype(float) * factor
        return df

    def _resolve_history(self, tick: dict) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        if self.force_synthetic:
            df = generate_synthetic_history(
                base=float(tick.get("synthetic_base", 100.0)),
                vol=float(tick.get("synthetic_vol", 0.25)),
                drift=float(tick.get("synthetic_drift", 0.02)),
                days=self.days,
                seed=int(hash(str(tick.get("display")) or "x") % (2**31)),
            )
            return df, {"source": "synthetic", "symbol": self._display(tick),
                        "ticker_key": tick.get("display"),
                        "ts": datetime.utcnow().isoformat() + "Z"}

        candidates = list(tick.get("candidates") or [tick.get("symbol")])
        # 1) live pull
        for symbol in candidates:
            if not symbol:
                continue
            df, ok = self._fetch_yf(symbol, period=self.period, interval=self.interval)
            if ok and len(df) >= 5:
                df = self._apply_unit_factor(df, tick, symbol)
                self.disk.set(f"h:{symbol}", df.to_dict(orient="split"))
                meta = {"source": "live", "symbol": symbol,
                        "ticker_key": tick.get("display"),
                        "ts": datetime.utcnow().isoformat() + "Z",
                        "conversion_note": tick.get("conversion_notes", {}).get(symbol, "")}
                return df, meta

        # 2) disk TTL cache
        for symbol in candidates:
            if not symbol:
                continue
            raw = self.disk.get(f"h:{symbol}", max_age_hours=24.0)
            if raw:
                try:
                    df = pd.DataFrame.from_dict(raw, orient="split")
                    df.index = pd.to_datetime(df.index)
                    if len(df) >= 5:
                        return df, {"source": "ttl-cache", "symbol": symbol,
                                    "ticker_key": tick.get("display"),
                                    "ts": datetime.utcnow().isoformat() + "Z"}
                except Exception:  # pylint: disable=broad-except
                    continue

        # 3) synthetic fallback
        df = generate_synthetic_history(
            base=float(tick.get("synthetic_base", 100.0)),
            vol=float(tick.get("synthetic_vol", 0.25)),
            drift=float(tick.get("synthetic_drift", 0.02)),
            days=self.days,
            seed=int(hash(str(tick.get("display")) or "x") % (2**31)),
        )
        return df, {"source": "synthetic", "symbol": self._display(tick),
                    "ticker_key": tick.get("display"), "ts": datetime.utcnow().isoformat() + "Z"}

    def _fetch_yf(self, symbol: str, interval: Optional[str] = None,
                  period: Optional[str] = None, attempts: int = 2) -> Tuple[Optional[pd.DataFrame], bool]:
        """Fetch OHLCV for one symbol with light retry. Never raises."""
        if not YF_AVAILABLE:
            return None, False
        interval = interval or self.interval
        period = period or self.period
        for attempt in range(max(attempts, 1)):
            try:
                df = yf.download(symbol, period=period, interval=interval,
                                 progress=False, auto_adjust=True, threads=False)
                if df is None or len(df) == 0:
                    df = None
                else:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    keep = [c for c in OHLCV_COLS if c in df.columns]
                    if "Close" not in keep or len(df) < 2:
                        df = None
                    else:
                        df = df[keep].dropna(subset=["Close"])
            except Exception as exc:  # pylint: disable=broad-except
                logger.debug("yfinance %s failed (attempt %s): %s", symbol, attempt + 1, exc)
                df = None
            if df is not None and len(df):
                return df, True
            time.sleep(0.8 + attempt * 0.7)
        return None, False