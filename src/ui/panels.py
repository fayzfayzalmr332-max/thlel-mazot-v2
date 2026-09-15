"""HTML panel builders for the Streamlit dashboard (RTL-aware, dark theme)."""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

from .charts import sparkline_svg

SRC_CHIP = {
    "live": ("مباشر", "#22c55e"),
    "ttl-cache": ("ذاكرة TTL", "#f5c04a"),
    "synthetic": ("محاكاة DEMO", "#64748b"),
    "config": ("من الإعدادات", "#8b9bb4"),
    "manual": ("إدخال يدوي", "#22d3ee"),
}


def chip(text: str, color: str = "#22d3ee", solid: bool = False) -> str:
    style = (
        f"background:{color};color:#0b1220;"
        if solid
        else f"background:transparent;color:{color};border:1px solid {color};"
    )
    return f'<span class="tm-chip" style="{style}">{text}</span>'


def source_chip(source: str) -> str:
    text, color = SRC_CHIP.get(source, (source, "#8b9bb4"))
    return chip(text, color, solid=False)


def metric_card(uid: str, title_ar: str, value_str: str, unit: str,
                delta_str: str, delta_class: str, spark_values: Sequence[float],
                source: str, chip_note: str = "") -> str:
    dot = f'<span class="tm-dot" style="background:{SRC_CHIP.get(source,("#8b9bb4","#8b9bb4"))[1]}"></span>'
    spark = sparkline_svg(spark_values, uid=uid)
    note = f' <span class="tm-meta">· {chip_note}</span>' if chip_note else ""
    return f"""
    <div class="tm-card">
      <div class="tm-card-title">{title_ar} {dot} {source_chip(source)} {note}</div>
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
        <div>
          <div class="tm-card-value">{value_str} <span class="tm-card-unit">{unit}</span></div>
          <div class="{delta_class}" style="font-size:0.85rem;font-weight:700;">{delta_str}</div>
        </div>
        <div>{spark}</div>
      </div>
    </div>"""


def hero_html(result: Dict[str, Any]) -> str:
    css = {"GREEN": "hGREEN", "YELLOW": "hYELLOW", "RED": "hRED"}.get(
        result.get("grade", "YELLOW"), "hYELLOW"
    )
    sub = result.get("sub_scores", {})
    sub_txt = " · ".join(
        f"{k}: {v}/100"
        for k, v in [
            ("جيوسياسة", sub.get("geopolitical", 0)),
            ("زخم", sub.get("momentum", 0)),
            ("فجوة تسعير", sub.get("parity_gap", 0)),
            ("شحن", sub.get("shipping", 0)),
        ]
    )
    return f"""
    <div class="tm-hero {css}">
      <div style="display:flex;justify-content:space-between;align-items:flex-end;gap:12px;flex-wrap:wrap;">
        <div>
          <div class="big">🛢️ {result.get('label_ar', '—')}</div>
          <div class="sub">النظام: {result.get('grade', '?')} — مؤشر التوتر الكلي {result.get('score', 0):.0f}/100</div>
        </div>
        <div style="text-align:left;">
          <div class="more">{sub_txt}</div>
        </div>
      </div>
    </div>"""


def regime_html(regime: Dict[str, Any], momentum_score: float) -> str:
    state = regime.get("state", "NEUTRAL")
    state_color = {
        "ROCKET": "#ef4444",
        "MIXED": "#f97316",
        "FEATHER": "#f5c04a",
        "PURGE": "#a78bfa",
        "NEUTRAL": "#22d3ee",
    }.get(state, "#22d3ee")
    c_short = regime.get("c_short")
    c_long = regime.get("c_long")
    asym = regime.get("asymmetry_index")
    return f"""
    <div class="tm-card">
      <div class="tm-card-title">حالة الزخم — <span style="color:{state_color};font-weight:800;">{regime.get('state_ar','—')}</span></div>
      <div class="tm-card-value" style="font-size:1.4rem;">{state}
        <span class="tm-card-unit">إسهام التوتر: {momentum_score:.0f}/100</span>
      </div>
      <div style="display:flex;gap:18px;flex-wrap:wrap;margin-top:8px;">
        <div class="tm-meta">5 أيام: <b style="color:{"#22c55e" if (c_short or 0)>=0 else "#ef4444"}">{c_short:+.2f}%</b></div>
        <div class="tm-meta">30 يومًا: <b style="color:{"#22c55e" if (c_long or 0)>=0 else "#ef4444"}">{c_long:+.2f}%</b></div>
        <div class="tm-meta">عدم تماثل: <b>{asym:.2f}</b></div>
        <div class="tm-meta">صعود↗ {regime.get("up_speed_short",0):.3f}%/ي | هبوط↘ {regime.get("down_speed_short",0):.3f}%/ي</div>
      </div>
      <div style="margin-top:6px;">
        {"".join(chip(d, "#8b9bb4") for d in regime.get("details", [])[:2])}
      </div>
    </div>"""


def section_header(text: str, color: str = "#f5c04a") -> str:
    return f'<div class="tm-sec-h"><span class="tm-dot" style="background:{color}"></span>{text}</div>'


def status_line_html(label: str, value: str, color: str = "#cbd5e1") -> str:
    return f'<div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px dashed #1a2740;"><span class="tm-meta">{label}</span><span style="color:{color};font-weight:700;">{value}</span></div>'


def emerging_html(topics: List[Dict[str, Any]]) -> str:
    if not topics:
        return '<span class="tm-meta">لا توجد مواضيع ناشئة جديدة — منحنى المعلومات هادئ.</span>'
    return " ".join(chip(f"{t['topic']} ×{t['freq']}", "#a78bfa") for t in topics)


def articles_dataframe_note(mode: str) -> str:
    return {
        "live": "مسح حي متصل بالمصادر",
        "ttl-cache": "من ذاكرة المسح السابقة",
        "demo": "سيناريوهات تجريبية — الشبكة غير متاحة حاليًا",
    }.get(mode, mode)