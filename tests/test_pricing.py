"""Tests for the transparent theoretical-pricing model."""
from __future__ import annotations

import pandas as pd
import pytest

from src.analysis.pricing import PricingModel

PRICING_CFG = {
    "pricing": {
        "litres_per_tonne": 1190.0,
        "insurance_rate": 0.008,
        "freight_base_usd_t": 18.0,
        "freight_bdi_sensitivity": 0.012,
        "refining_margin_usd_t": 55.0,
        "distribution_margin_syp_l": 950.0,
        "vat_rate": 0.10,
        "sanction_premium_usd_t": 120.0,
        "official_baseline": {
            "rationed_mazot_syp_l": 3000.0,
            "full_price_mazot_syp_l": 14500.0,
            "decree_date": "2026-09-01",
        },
    }
}


@pytest.fixture
def model():
    return PricingModel(PRICING_CFG)


def test_breakdown_adds_to_theoretical(model):
    bd = model.breakdown(705.0, 1450.0, 15200.0)
    parts = bd["breakdown_syp_l"]
    pre_vat = sum(v for k, v in parts.items() if k != "الضريبة")
    assert pre_vat == pytest.approx(bd["pre_vat_syp_l"], rel=1e-6)
    assert (pre_vat * (1 + model.vat_rate)) == pytest.approx(bd["theoretical_syp_l"], rel=1e-6)


def test_breakdown_monotonic_in_price_and_fx(model):
    low = model.breakdown(600.0, 1450.0, 15000.0)["theoretical_syp_l"]
    high = model.breakdown(900.0, 1450.0, 18000.0)["theoretical_syp_l"]
    assert high > low


def test_freight_rises_with_bdi(model):
    assert model.freight_usd_t(1800) > model.freight_usd_t(900)


def test_freight_from_percentile_bounds(model):
    assert model.freight_from_percentile(0) == pytest.approx(model.freight_base)
    assert model.freight_from_percentile(100) == pytest.approx(model.freight_base + 45.0)


def test_compare_gap_signs(model):
    theo = 20000.0
    cmp_result = model.compare(theo)
    assert cmp_result["gap_full_pct"] > 0
    assert cmp_result["gap_rationed_pct"] > cmp_result["gap_full_pct"]


def test_theoretical_series(model):
    s = pd.Series([700.0, 710.0, 720.0])
    out = model.theoretical_series(s, 1450.0, 15200.0)
    assert len(out) == 3
    assert out.iloc[2] > out.iloc[0]