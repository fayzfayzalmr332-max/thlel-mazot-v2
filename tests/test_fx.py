"""Zero-network tests for the redesigned FX provider (redenomination-aware)."""
import pandas as pd
import pytest

from src.data.fx import FXProvider, _num, extract_closes


def _settings(syp_unit="new", old_factor=100.0):
    return {
        "market": {"fx": {
            "candidates": ["SYP=X"],
            "official_usd_syp": 121.66,
            "parallel_usd_syp": 134.0,
            "parallel_spread": 0.10,
            "syp_unit": syp_unit,
            "old_factor": old_factor,
        }},
        "app": {"cache_dir": ".cache-test"},
    }


def test_num_parses_commas_and_rejects_garbage():
    assert _num("13,375") == 13375.0
    assert _num("133.75") == 133.75
    assert _num("") is None
    assert _num("abc") is None


def test_extract_closes_flat_series():
    df = pd.DataFrame({"Close": [1.0, 2.0, None, 4.0]})
    s = extract_closes(df)
    assert list(s) == [1.0, 2.0, 4.0]


def test_extract_closes_multiindex_dataframe():
    """Regression: newer yfinance returns MultiIndex columns -> was TypeError."""
    cols = pd.MultiIndex.from_product([["Close"], ["SYP=X"]])
    df = pd.DataFrame([[10.0], [11.0]], columns=cols)
    s = extract_closes(df)
    assert list(s) == [10.0, 11.0]


def test_extract_closes_none_and_missing_col():
    assert extract_closes(None) is None
    assert extract_closes(pd.DataFrame({"X": [1.0]})) is None


def test_manual_override_in_old_units_converts_to_new():
    fx = FXProvider(_settings(syp_unit="old", old_factor=100.0))
    fx.set_override(official=13000.0, parallel=13400.0)
    r = fx.get_rates()
    assert r["official"] == pytest.approx(130.0)
    assert r["parallel"] == pytest.approx(134.0)
    assert r["official_old"] == pytest.approx(13000.0)
    assert "manual" in r["sources"]


def test_waterfall_sp_today_and_er_api(monkeypatch):
    fx = FXProvider(_settings())
    monkeypatch.setattr(fx, "_live_sptoday", lambda: (133.75, 134.25))
    monkeypatch.setattr(fx, "_live_erapi", lambda: 121.66)
    monkeypatch.setattr(fx, "_live_yf", lambda: None)
    r = fx.get_rates()
    assert r["official"] == pytest.approx(121.66)
    assert r["parallel"] == pytest.approx(134.0)
    assert "sp-today" in r["sources"] and "er-api" in r["sources"]
    assert r["parallel"] >= r["official"]
    assert r["official_old"] == pytest.approx(12166.0)


def test_full_config_fallback_when_all_live_fail(monkeypatch):
    fx = FXProvider(_settings())
    monkeypatch.setattr(fx, "_live_sptoday", lambda: None)
    monkeypatch.setattr(fx, "_live_erapi", lambda: None)
    monkeypatch.setattr(fx, "_live_yf", lambda: None)
    r = fx.get_rates()
    assert r["official"] == pytest.approx(121.66)
    assert "config" in r["sources"]


def test_clear_override_restores_live_path(monkeypatch):
    fx = FXProvider(_settings())
    fx.set_override(official=200.0)
    fx.clear_override()
    monkeypatch.setattr(fx, "_live_sptoday", lambda: (130.0, 134.0))
    monkeypatch.setattr(fx, "_live_erapi", lambda: 121.0)
    monkeypatch.setattr(fx, "_live_yf", lambda: None)
    r = fx.get_rates()
    assert r["official"] == pytest.approx(121.0)
    assert "manual" not in r["sources"]
