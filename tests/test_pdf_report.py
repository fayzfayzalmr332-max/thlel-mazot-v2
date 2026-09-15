"""Zero-network unit tests for the RTL-aware PDF report builder."""
from __future__ import annotations

from src.analysis.reporting import build_dashboard_snapshot, build_pdf_bytes

SETTINGS = {"reporting": {"pdf": {"author": "TEST", "page_size": "A4",
                                  "include_geo_triggers": True}}}


def _minimal_snapshot():
    return {
        "ts": "2026-09-15T10:00:00",
        "grade": "RED",
        "grade_label_ar": "أزمة إمداد",
        "score": 72.5,
        "sub_scores": {"geopolitical": 60, "momentum": 70,
                       "parity_gap": 80, "shipping": 40},
        "metrics": [
            {"label_ar": "الغازويل الآجل", "label_en": "Gasoil", "value": 760.4},
            {"label_ar": "خام برنت", "label_en": "Brent", "value": 89.5},
            {"label_ar": "السعر النظري", "label_en": "Theoretical", "value": 13500},
        ],
        "waterfall": {"labels": ["السلعة", "الشحن", "علاوة العقوبات"],
                      "values": [9.0, 1.0, 1.4], "vat": 1.1, "total": 12.5},
        "official": {"rationed": 3000, "full": 14500, "gap_full_pct": -3.2},
        "momentum": {"state": "ROCKET", "state_ar": "انطلاق صاروخي",
                     "c_short": 7.2, "c_long": 3.1, "asymmetry": 2.4},
        "news": {"stress": 55.0, "mode": "live", "count": 3,
                 "items": [{"title": "أعمال صيانة في مصفاة بانياس", "severity": 0.9,
                            "labels_ar": ["عمليات المصافي"], "source": "ن"}],
                 "emerging": ["map"]},
    }


def test_pdf_startswith_magic_header():
    data = build_pdf_bytes(SETTINGS, _minimal_snapshot())
    assert data.startswith(b"%PDF")
    assert len(data) > 1000


def test_pdf_contains_catalog_and_pages():
    data = build_pdf_bytes(SETTINGS, _minimal_snapshot())
    assert b"Catalog" in data
    assert data.count(b"/Type /Page") >= 1


def test_snapshot_builder_from_dashboard_objects():
    latest = {"gasoil": {"value": 760.4}, "brent": {"value": 89.5},
              "shipping": {"value": 1400.0}}
    rates = {"parallel": 15200.0, "official": 13000.0}
    bd = {"steps": [("السلعة", 9.0, "USD/t"), ("الشحن", 1.0, "USD/t")],
          "vat_syp_l": 1.1, "theoretical_syp_l": 12.6}
    cmp_res = {"official_full": 14500, "official_rationed": 3000, "gap_full_pct": -3.2}
    sentiment = {"grade": "GREEN", "label_ar": "ارتياح", "score": 25,
                 "sub_scores": {"geopolitical": 10, "momentum": 20,
                                "parity_gap": 30, "shipping": 15}}
    regime = {"state": "NEUTRAL", "state_ar": "متوازن", "c_short": -0.5,
              "c_long": 1.0, "asymmetry_index": 1.1}
    news = {"stress_index": 30, "mode": "demo", "count": 2,
            "items": [{"title": "عنوان تجريبي", "severity": 0.7,
                       "labels_ar": ["فئة"], "source": "ن"}],
            "emerging": []}
    snap = build_dashboard_snapshot(latest, rates, bd, cmp_res, sentiment, regime, news)
    assert snap["grade"] == "GREEN"
    assert len(snap["metrics"]) == 7
    assert snap["waterfall"]["total"] == 12.6
    data = build_pdf_bytes(SETTINGS, snap)
    assert data.startswith(b"%PDF")