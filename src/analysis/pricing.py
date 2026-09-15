"""Transparent theoretical-retail-price model for Syria (mazot/heating oil).

Global gasoil (ICE, USD/tonne) is carried through every cost layer into a
theoretical local litre price (SYP):

    FOB London gasoil
        + freight (BDI-linked) + war-risk insurance + sanction premium  -> CIF
        converted with the parallel USD/SYP rate
        + local refining value-add + distribution margin
        + VAT
    = theoretical retail price (SYP/litre)

The result is compared with the *official* September-2026 decree baselines
(rationed subsidised mazot and open-market price). All assumptions are
explicit, configurable in ``config/settings.yaml`` and editable in the UI.

* Disclaimer: this is an estimation model, not a market quote.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

DEFAULT_BDI = 1450.0


class PricingModel:
    def __init__(self, settings: Dict[str, Any]):
        p = settings.get("pricing", {})
        self.litres_per_tonne = float(p.get("litres_per_tonne", 1190.0))
        self.insurance_rate = float(p.get("insurance_rate", 0.008))
        self.freight_base = float(p.get("freight_base_usd_t", 18.0))
        self.freight_bdi_sens = float(p.get("freight_bdi_sensitivity", 0.012))
        self.refining_margin_usd_t = float(p.get("refining_margin_usd_t", 55.0))
        self.distribution_margin_syp_l = float(p.get("distribution_margin_syp_l", 950.0))
        self.vat_rate = float(p.get("vat_rate", 0.10))
        self.sanction_premium_usd_t = float(p.get("sanction_premium_usd_t", 120.0))

        ob = p.get("official_baseline", {})
        self.official_rationed = float(ob.get("rationed_mazot_syp_l", 3000.0))
        self.official_full = float(ob.get("full_price_mazot_syp_l", 14500.0))
        self.decree_date = str(ob.get("decree_date", "2026-09-01"))

    # ------------------------------------------------------------------ rates

    def freight_usd_t(self, bdi: float) -> float:
        bdi = float(bdi) if bdi else DEFAULT_BDI
        return self.freight_base + (bdi - DEFAULT_BDI) * self.freight_bdi_sens

    def insurance_usd_t(self, gasoil_usd_t: float) -> float:
        return float(gasoil_usd_t) * self.insurance_rate

    def freight_from_percentile(self, pct: float, span: float = 45.0) -> float:
        """Robust freight estimate from the *percentile* of the shipping proxy
        series (BDI-era/proxy-agnostic: 0% -> ~base, 100% -> base+span USD/t)."""
        pct = min(100.0, max(0.0, float(pct)))
        span = max(float(span), 5.0)
        return self.freight_base + (pct / 100.0) * span

    # ================================================================= breakdown

    def breakdown(self, gasoil_usd_t: float, bdi: float, fx_parallel: float,
                  fx_official: Optional[float] = None,
                  freight: Optional[float] = None) -> Dict[str, Any]:
        """Full cost stack in both USD/tonne and SYP/litre."""
        fx = float(fx_parallel)
        gasoil = float(gasoil_usd_t)
        lpt = self.litres_per_tonne

        freight = self.freight_usd_t(bdi) if freight is None else float(freight)
        insurance = self.insurance_usd_t(gasoil)
        sanction = self.sanction_premium_usd_t

        # USD/tonne stack
        usd_components = {
            "product_fob": gasoil,
            "freight": freight,
            "insurance": insurance,
            "sanction": sanction,
        }
        cif_usd_t = gasoil + freight + insurance + sanction

        # SYP/litre stack
        product_syp_l = gasoil * fx / lpt
        freight_syp_l = freight * fx / lpt
        insurance_syp_l = insurance * fx / lpt
        sanction_syp_l = sanction * fx / lpt
        refining_syp_l = self.refining_margin_usd_t * fx / lpt
        distribution_syp_l = self.distribution_margin_syp_l

        pre_vat = product_syp_l + freight_syp_l + insurance_syp_l + sanction_syp_l + refining_syp_l + distribution_syp_l
        vat_syp_l = pre_vat * self.vat_rate
        theoretical = pre_vat + vat_syp_l

        steps = [
            ("السلعة العالمية (فوب لندن)", product_syp_l, "USD/t"),
            ("الشحن البحري (مرتبط بمؤشر البلطيق)", freight_syp_l, "USD/t"),
            ("التأمين ومخاطر الحرب", insurance_syp_l, "USD/t"),
            ("هامش التكرير/القيمة المحلية", refining_syp_l, "USD/t"),
            ("هامش التوزيع المحلي", distribution_syp_l, "ثابت"),
            ("علاوة العقوبات والتأمين القسري", sanction_syp_l, "USD/t"),
        ]

        return {
            "steps": steps,
            "breakdown_syp_l": {
                "السلعة العالمية": product_syp_l,
                "الشحن": freight_syp_l,
                "التأمين": insurance_syp_l,
                "التكرير": refining_syp_l,
                "التوزيع": distribution_syp_l,
                "علاوة العقوبات": sanction_syp_l,
                "الضريبة": vat_syp_l,
            },
            "usd_components": usd_components,
            "cif_usd_t": cif_usd_t,
            "pre_vat_syp_l": pre_vat,
            "vat_syp_l": vat_syp_l,
            "theoretical_syp_l": theoretical,
            "fx_used": fx_parallel,
            "fx_official": fx_official,
        }

    # ------------------------------------------------------------------ compare

    def compare(self, theoretical_syp_l: float) -> Dict[str, Any]:
        g_rationed = theoretical_syp_l - self.official_rationed
        g_full = theoretical_syp_l - self.official_full
        return {
            "official_rationed": self.official_rationed,
            "official_full": self.official_full,
            "gap_rationed_syp_l": g_rationed,
            "gap_full_syp_l": g_full,
            "gap_rationed_pct": g_rationed / self.official_rationed * 100.0,
            "gap_full_pct": g_full / self.official_full * 100.0,
            "decree_date": self.decree_date,
        }

    # ------------------------------------------------------------------ series

    def theoretical_series(self, gasoil_usd_t: pd.Series, bdi: float,
                           fx_parallel: float, freight: Optional[float] = None) -> pd.Series:
        """Theoretical SYP/litre over a historical gasoil series (spot view)."""
        bdi = float(bdi) if bdi else DEFAULT_BDI
        fx = float(fx_parallel)
        lpt = self.litres_per_tonne
        freight = self.freight_usd_t(bdi) if freight is None else float(freight)

        def row_to_price(g):
            g = float(g)
            cif = g + freight + g * self.insurance_rate + self.sanction_premium_usd_t
            pre = cif * fx / lpt + self.refining_margin_usd_t * fx / lpt + self.distribution_margin_syp_l
            return pre * (1.0 + self.vat_rate)

        return gasoil_usd_t.dropna().apply(row_to_price)