"""Plotly chart builders + a dependency-free SVG sparkline generator."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import pandas as pd
import plotly.graph_objects as go

# ---------------------------------------------------------------- helpers


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def _base_layout(fig: go.Figure, height: int = 350) -> go.Figure:
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#cbd5e1", family="Cairo, Segoe UI, Tahoma, sans-serif"),
        height=height,
        margin=dict(l=8, r=8, t=34, b=8),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    fig.update_xaxes(gridcolor="#1a2740", zerolinecolor="#1a2740")
    fig.update_yaxes(gridcolor="#1a2740", zerolinecolor="#1a2740")
    return fig


def sparkline_svg(values: Sequence[float], width: int = 170, height: int = 46,
                  color: str = "#22d3ee", uid: str = "") -> str:
    """Tiny inline SVG sparkline (zero dependency) for metric cards."""
    vals = [float(v) for v in values if v is not None]
    if len(vals) < 2:
        return ""
    mn, mx = min(vals), max(vals)
    rng = (mx - mn) or 1.0
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = 4 + i * (width - 8) / (n - 1)
        y = height - 6 - (v - mn) / rng * (height - 14)
        pts.append(f"{x:.1f},{y:.1f}")
    poly = " ".join(pts)
    area = f"M {pts[0].split(',')[0]},{height-6} L " + " L ".join(pts) + f" L {width-4},{height-6} Z"
    gid = f"sg{uid}"
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{color}" stop-opacity="0.35"/>'
        f'<stop offset="100%" stop-color="{color}" stop-opacity="0.0"/></linearGradient></defs>'
        f'<path d="{area}" fill="url(#{gid})"/>'
        f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>'
        f'<circle cx="{pts[-1].split(",")[0]}" cy="{pts[-1].split(",")[1]}" r="3" fill="{color}"/>'
        "</svg>"
    )


# ---------------------------------------------------------------- series charts


def line_chart(df: pd.DataFrame, value_col: str = "Close", title: str = "",
               unit: str = "", color: str = "#22d3ee",
               ref_lines: Optional[List[Dict[str, Any]]] = None,
               height: int = 350) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df.index, y=df[value_col].astype(float),
        mode="lines", name=title,
        line=dict(color=color, width=2.4),
        fill="tozeroy", fillcolor=_rgba(color, 0.10),
    ))
    for rl in ref_lines or []:
        fig.add_hline(
            y=rl["y"], line_dash="dot", line_color=rl.get("color", "#f5c04a"),
            annotation_text=rl.get("label", ""),
            annotation_position="top left",
            annotation_font=dict(size=11, color=rl.get("color", "#f5c04a")),
        )
    fig = _base_layout(fig, height)
    return fig


def candle_chart(df: pd.DataFrame, title: str = "", height: int = 380) -> go.Figure:
    fig = go.Figure(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"],
        increasing_line_color="#22c55e", decreasing_line_color="#ef4444",
        name=title,
    ))
    if "Volume" in df.columns:
        fig.add_trace(go.Bar(
            x=df.index, y=df["Volume"].astype(float), name="الحجم",
            marker_color=_rgba("#22d3ee", 0.35), yaxis="y2",
        ))
        fig.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False, range=[0, df["Volume"].max() * 4]))
    fig = _base_layout(fig, height)
    return fig


def gauge_chart(score: float, title: str, color: str = "#f5c04a",
                height: int = 210) -> go.Figure:
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=float(score),
        number={"suffix": "/100", "font": {"color": color, "size": 30}},
        title={"text": title, "font": {"size": 13, "color": "#8b9bb4"}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": "#475569", "tickwidth": 1,
                     "tickfont": {"size": 9, "color": "#64748b"}},
            "bar": {"color": color, "thickness": 0.30},
            "bgcolor": "#101a2c",
            "borderwidth": 1,
            "bordercolor": "#1f2b42",
            "steps": [
                {"range": [0, 35], "color": _rgba("#22c55e", 0.16)},
                {"range": [35, 65], "color": _rgba("#f5c04a", 0.16)},
                {"range": [65, 100], "color": _rgba("#ef4444", 0.16)},
            ],
            "threshold": {"line": {"color": "#ffffff", "width": 2}, "thickness": 1, "value": float(score)},
        },
    ))
    fig = _base_layout(fig, height)
    fig.update_layout(margin=dict(l=12, r=12, t=46, b=6))
    return fig


def waterfall_chart(steps: List[tuple], vat_syp_l: float, total_syp_l: float,
                    title: str = "تفكيك السعر النظري (ل.س/لتر)") -> go.Figure:
    """steps = [(label_ar, syp_l, unit_src), ...] -> cumulative waterfall."""
    labels = [s[0] for s in steps] + ["الضريبة (VAT)"] + ["السعر النظري"]
    rel = [float(s[1]) for s in steps] + [float(vat_syp_l)]
    fig = go.Figure(go.Waterfall(
        x=labels, y=rel,
        measure=["relative"] * len(rel) + ["total"],
        connector={"line": {"color": "#334155", "dash": "dot", "width": 1}},
        increasing={"marker": {"color": "#22d3ee"}},
        decreasing={"marker": {"color": "#ef4444"}},
        totals={"marker": {"color": "#f5c04a"}},
        text=[f"{v:,.0f}" for v in rel] + [f"{total_syp_l:,.0f}"],
        textposition="outside",
        textfont=dict(size=11, color="#cbd5e1"),
        hovertemplate="%{x}: %{y:,.1f} ل.س/لتر<extra></extra>",
    ))
    fig = _base_layout(fig, 400)
    fig.update_yaxes(title="ل.س/لتر")
    return fig


def momentum_bars(df: pd.DataFrame, value_col: str = "rolling_short",
                  spike_thr: float = 6.0, purge_thr: float = -6.0,
                  height: int = 300) -> go.Figure:
    """Colored bars of short-window momentum with spike/purge thresholds."""
    s = df[value_col].astype(float)
    colors = ["#ef4444" if v <= purge_thr else "#22c55e" if v >= spike_thr else "#22d3ee" for v in s]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df.index, y=s, marker_color=colors, name="زخم 5 أيام"))
    fig.add_hline(y=0, line_color="#334155", line_width=1)
    fig.add_hline(y=spike_thr, line_dash="dot", line_color="#ef4444",
                  annotation_text="عتبة الانطلاق (صاروخ)", annotation_position="top left")
    fig.add_hline(y=purge_thr, line_dash="dot", line_color="#f97316",
                  annotation_text="عتبة التطهير", annotation_position="bottom left")
    fig = _base_layout(fig, height)
    return fig


def parity_conflict_chart(theoretical: pd.Series, rationed: float, full_price: float,
                          title: str = "السعر النظري مقابل التسعيرة الرسمية") -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=theoretical.index, y=theoretical.astype(float),
        mode="lines", name="السعر النظري (ل.س/لتر)",
        line=dict(color="#22d3ee", width=2.2),
        fill="tozeroy", fillcolor=_rgba("#22d3ee", 0.08),
    ))
    fig.add_hline(y=rationed, line_dash="dash", line_color="#22c55e",
                  annotation_text="الرسمي المدعوم (حصة)", annotation_position="top left")
    fig.add_hline(y=full_price, line_dash="dash", line_color="#f5c04a",
                  annotation_text="السوق الحر الرسمي", annotation_position="top left")
    fig = _base_layout(fig, 380)
    fig.update_yaxes(title="ل.س/لتر")
    return fig


def sub_scores_bars(sub_scores: Dict[str, float], color: str = "#f5c04a") -> go.Figure:
    order = ["geopolitical", "momentum", "parity_gap", "shipping"]
    labels = {
        "geopolitical": "ضغط جيوسياسي",
        "momentum": "زخم الأسعار",
        "parity_gap": "فجوة التسعير المحلي",
        "shipping": "ضغط الشحن",
    }
    y = [labels[k] for k in order]
    x = [sub_scores.get(k, 0.0) for k in order]
    fig = go.Figure(go.Bar(
        x=x, y=y, orientation="h",
        marker_color=[_rgba(color, 0.9), _rgba(color, 0.7), _rgba(color, 0.55), _rgba(color, 0.4)],
        text=[f"{v:.0f}/100" for v in x], textposition="auto",
    ))
    fig.update_layout(xaxis=dict(range=[0, 100], title="مقياس التوتر 0-100"))
    fig = _base_layout(fig, 240)
    return fig