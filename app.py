"""THLEL MAZOT — لوحة تحليل أسواق الطاقة العالمية وتأثيراتها المحلية على سوريا.

Streamlit entry point. Runs ``streamlit run app.py`` from the repo root.
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

st.set_page_config(page_title="ثُلَّ المازوت", page_icon="🛢️", layout="wide")

from src.config import load_settings  # noqa: E402
from src.utils.formatting import fmt_num, fmt_pct  # noqa: E402
from src.data.market_data import MarketDataProvider  # noqa: E402
from src.data.fx import FXProvider  # noqa: E402
from src.analysis.momentum import analyze_momentum, score_momentum  # noqa: E402
from src.analysis.pricing import PricingModel  # noqa: E402
from src.analysis.sentiment import evaluate_sentiment, shipping_stress_score  # noqa: E402
from src.analysis.alerts import AlertEngine  # noqa: E402
from src.analysis.reporting import build_dashboard_snapshot, build_pdf_bytes  # noqa: E402
from src.news.scanner import NewsRadar  # noqa: E402
from src.ui.theme import THEME_CSS  # noqa: E402
from src.ui import panels as P  # noqa: E402
from src.ui import charts as C  # noqa: E402

try:  # optional package
    from streamlit_autorefresh import st_autorefresh  # type: ignore
except Exception:  # pylint: disable=broad-except
    st_autorefresh = None

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

settings = load_settings()
st.markdown(THEME_CSS, unsafe_allow_html=True)
alert_engine = AlertEngine(settings)

FX_CFG = settings.get("market", {}).get("fx", {})
OB_CFG = settings.get("pricing", {}).get("official_baseline", {})

DEFAULT_FX_OFFICIAL = float(FX_CFG.get("official_usd_syp", 121.66))
DEFAULT_FX_PARALLEL = float(FX_CFG.get("parallel_usd_syp", 134.0))
DEFAULT_RATIONED = float(OB_CFG.get("rationed_mazot_syp_l", 175.0))
DEFAULT_FULL = float(OB_CFG.get("full_price_mazot_syp_l", 195.0))


# ------------------------------------------------------------------ helpers


def show_chart(fig) -> None:
    try:
        st.plotly_chart(fig, width="stretch")
    except TypeError:
        st.plotly_chart(fig, use_container_width=True)


def show_download(path_label, data, fname) -> None:
    try:
        st.download_button(path_label, data=data, file_name=fname,
                           mime="application/pdf", width="stretch")
    except TypeError:
        st.download_button(path_label, data=data, file_name=fname,
                           mime="application/pdf", use_container_width=True)


def get_providers(force_synthetic: bool):
    providers = st.session_state.get("providers")
    flag = st.session_state.get("force_synthetic", False)
    if providers is None or flag != force_synthetic:
        providers = {
            "market": MarketDataProvider(settings, force_synthetic=force_synthetic),
            "fx": FXProvider(settings),
            "radar": NewsRadar(settings),
        }
        st.session_state.providers = providers
        st.session_state.force_synthetic = force_synthetic
    return providers


def build_pricing_model() -> PricingModel:
    model = PricingModel(settings)
    model.official_rationed = float(st.session_state.get("official_rationed", DEFAULT_RATIONED))
    model.official_full = float(st.session_state.get("official_full", DEFAULT_FULL))
    return model


# ------------------------------------------------------------------ sidebar

CFG_VERSION = "v2-new-lira-2026-09"
if st.session_state.get("cfg_version") != CFG_VERSION:
    # Reset widget state carried over from an older configuration (e.g. the
    # pre-redenomination 3000/14500 baselines) so the UI always starts from
    # the current config + live sources after an upgrade.
    st.session_state["cfg_version"] = CFG_VERSION
    for _k in ("official_rationed", "official_full",
               "fx_official_in", "fx_parallel_in", "fx_manual", "news_scan"):
        st.session_state.pop(_k, None)

# Live FX probe *before* the sidebar so defaults reflect the current market
# (mem/disk-cached inside FXProvider, so this is cheap on reruns).
_fx_probe = FXProvider(settings)
_fx_probe_rates = _fx_probe.get_rates()

with st.sidebar:
    st.markdown("### 🛠️ التحكم والمدخلات")
    tg_status = "مفعّل ✓ (اعتمادات آمنة من secrets/بيئة)" if alert_engine.active else "غير مفعّل — ضع الاعتمادات في .streamlit/secrets.toml"
    if alert_engine.active and getattr(alert_engine, "last_error", None):
        if "chat not found" in str(alert_engine.last_error):
            tg_status = "⚠️ افتح t.me/thlel_mazot_radar_bot واضغط Start لتشغيل الإشعارات"
        else:
            tg_status = "⚠️ مشكلة إرسال: " + str(alert_engine.last_error)[:60]
    st.caption("🔔 Telegram: " + tg_status)
    refresh_sec = st.selectbox(
        "إعادة التحديث التلقائية",
        [30, 60, 120, 300, 0],
        index=1,
        format_func=lambda s: "إيقاف — تحديث يدوي" if s == 0 else f"كل {s} ثانية",
    )
    force_synth = st.checkbox(
        "فرض وضع المحاكاة للأسعار (DEMO، دون إنترنت)",
        value=st.session_state.get("force_synthetic", False),
    )
    st.markdown("---")
    st.markdown("**💱 سعر الصرف (ل.س جديدة/دولار)**")
    st.caption(FX_CFG.get("note_ar", ""))

    # Live waterfall is the default. Manual entry is opt-in ONLY — typed
    # values must never silently kill the multi-source live feed.
    fx_manual = st.checkbox("✍️ إدخال يدوي (تجاوز المصادر الحية)", value=False)
    fx_user_override = None
    if fx_manual:
        fx_off = st.number_input("السعر الرسمي", min_value=0.0,
                                 value=float(_fx_probe_rates["official"]),
                                 step=0.5, key="fx_official_in")
        fx_par = st.number_input("السعر الموازي (السوق)", min_value=0.0,
                                 value=float(_fx_probe_rates["parallel"]),
                                 step=0.5, key="fx_parallel_in")
        if st.button("استعادة القيم الحية"):
            st.session_state.fx_official_in = float(_fx_probe_rates["official"])
            st.session_state.fx_parallel_in = float(_fx_probe_rates["parallel"])
            st.rerun()
        fx_user_override = (float(fx_off), float(fx_par))
    else:
        st.caption(
            f"🔴 حي الآن — رسمي **{fmt_num(_fx_probe_rates['official'], 2)}** · "
            f"موازٍ **{fmt_num(_fx_probe_rates['parallel'], 2)}** · "
            f"فرق {fmt_pct(_fx_probe_rates['spread_pct'], signed=True)}"
        )
        st.caption("المصادر: " + " ← ".join(_fx_probe_rates.get("sources", ["config"])))

    st.markdown("---")
    st.markdown("**📜 التسعيرة الرسمية المرجعية (ل.س جديدة/لتر)**")
    st.caption(OB_CFG.get("decree_label_ar", ""))
    st.session_state.setdefault("official_rationed", DEFAULT_RATIONED)
    st.session_state.setdefault("official_full", DEFAULT_FULL)
    st.number_input("المازوت الرسمي (بعد الرفع)", min_value=0.0,
                    value=DEFAULT_RATIONED, step=1.0, key="official_rationed")
    st.number_input("السوق الموازي التقديري", min_value=0.0,
                    value=DEFAULT_FULL, step=1.0, key="official_full")

    scan_now = st.button("⟳ تشغيل مسح أخبار فوري")
    if st.button("🗑 إعادة تعيين التخزين المؤقت"):
        for p in Path(settings.get("app", {}).get("cache_dir", ".cache")).glob("*"):
            try:
                p.unlink()
            except OSError:
                pass
        st.session_state.pop("news_scan", None)
        st.rerun()


# ------------------------------------------------------- providers + data load

providers = get_providers(force_synth)
mkt: MarketDataProvider = providers["market"]
fx_prov: FXProvider = providers["fx"]
radar: NewsRadar = providers["radar"]

# Apply FX: live waterfall by default; manual override only when explicitly
# enabled via the sidebar checkbox (typed values must not kill the feed).
if fx_user_override is not None:
    fx_prov.set_override(*fx_user_override)
else:
    fx_prov.clear_override()
rates = fx_prov.get_rates()

latest = mkt.get_latest_many(["gasoil", "brent", "shipping", "us_heating"])
gas_df, gas_meta = mkt.get_history("gasoil")
brent_df, brent_meta = mkt.get_history("brent")
ship_df, ship_meta = mkt.get_history("shipping")

ship_hist = ship_df["Close"].dropna() if len(ship_df) else pd.Series(dtype=float)
ship_pct = shipping_stress_score(latest["shipping"]["value"], ship_hist)
regime = analyze_momentum(gas_df["Close"], settings.get("momentum", {}))
mom_score = score_momentum(regime)


def get_news(force: bool):
    cached = st.session_state.get("news_scan")
    if cached and (time.time() - cached[1]) < 900 and not force:
        return cached[0]
    result = radar.scan(force=force)
    st.session_state["news_scan"] = (result, time.time())
    return result


news = get_news(force=scan_now)

model = build_pricing_model()
gasoil_usd_t = latest["gasoil"]["value"]
freight_usd = model.freight_from_percentile(ship_pct)
bd = model.breakdown(gasoil_usd_t=gasoil_usd_t, bdi=float(latest["shipping"]["value"] or 1450),
                     fx_parallel=rates["parallel"], fx_official=rates["official"],
                     freight=freight_usd)
theoretical_now = bd["theoretical_syp_l"]
cmp_result = model.compare(theoretical_now)
parity_gap_pct = cmp_result["gap_full_pct"]

sentiment = evaluate_sentiment(settings, momentum_score=mom_score, geo_score=news["stress_index"],
                               parity_gap_pct=parity_gap_pct, shipping_score=ship_pct)

# ---------- alerts + daily report snapshot (pure logic; send only if enabled)
alert_events = alert_engine.process_and_send(AlertEngine.make_snapshot(
    gasoil_usd_t=latest["gasoil"]["value"], grade=sentiment["grade"],
    articles=news.get("items", [])))
st.session_state["alert_events"] = alert_events

report_snapshot = build_dashboard_snapshot(latest, rates, bd, cmp_result,
                                           sentiment, regime, news)


def _build_pdf():
    try:
        return build_pdf_bytes(settings, report_snapshot)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("PDF build failed: %s", exc)
        return None


pdf_data = _build_pdf()

# ------------------------------------------------------------------ refresh

if st_autorefresh is not None and refresh_sec > 0:
    try:
        st_autorefresh(interval=refresh_sec * 1000, key="tm_autorefresh")
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Autorefresh unavailable: %s", exc)


# ------------------------------------------------------------------ header

from src.utils.formatting import arrow  # noqa: E402
import plotly.graph_objects as go  # noqa: E402

st.markdown(
    f'<div class="tm-wrap">'
    f'<div style="font-size:1.85rem;font-weight:900;color:#fff;line-height:1.2;">'
    f'🛢️ {settings.get("app",{}).get("title","ثُلَّ المازوت")}</div>'
    f'<div class="tm-meta">{settings.get("app",{}).get("subtitle","")}</div>'
    f'</div>',
    unsafe_allow_html=True,
)
clock_col, btn_col = st.columns([2, 1])
with clock_col:
    st.markdown(
        f'<div class="tm-meta">آخر تحديث: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} '
        f'— الوضع: <b>{"محاكاة DEMO" if force_synth else "بيانات حية + وصلات"}</b></div>',
        unsafe_allow_html=True,
    )
with btn_col:
    if st.button("🔄 تحديث الآن", use_container_width=True):
        st.rerun()
st.write("")

# ---------- sentiment hero (top of the board)
st.markdown(P.hero_html(sentiment), unsafe_allow_html=True)
st.write("")

# ---------------------------------------------------------------- metric cards
st.markdown(P.section_header("الأسعار الحية والمؤشرات", "#22d3ee"))
cols = st.columns(4)

d_gas = latest["gasoil"]["change_pct"] or 0.0
d_bre = latest["brent"]["change_pct"] or 0.0
d_shp = latest["shipping"]["change_pct"] or 0.0
delta_cls = lambda d: "tm-up" if d >= 0 else "tm-down"  # noqa: E731

gas_note = latest["gasoil"].get("symbol", "") + (" · " + gas_meta.get("conversion_note", "") if gas_meta.get("conversion_note") else "")
cols[0].markdown(
    P.metric_card("gas", "الغازويل الآجل — زيت التدفئة", fmt_num(latest["gasoil"]["value"], 1),
                  "USD/طن", f"{arrow(d_gas)} {fmt_pct(d_gas, signed=True)} خلال يوم",
                  delta_cls(d_gas), gas_df["Close"].tail(42), latest["gasoil"]["source"], gas_note),
    unsafe_allow_html=True,
)
cols[1].markdown(
    P.metric_card("bre", "خام برنت (المرجع العالمي)", fmt_num(latest["brent"]["value"], 2),
                  "USD/برميل", f"{arrow(d_bre)} {fmt_pct(d_bre, signed=True)} خلال يوم",
                  delta_cls(d_bre), brent_df["Close"].tail(42), latest["brent"]["source"],
                  latest["brent"].get("symbol", "")),
    unsafe_allow_html=True,
)
syp_note = f"الرسمي {fmt_num(rates['official'],0)} ل.س جديدة · فرق {fmt_pct(rates['spread_pct'], signed=True)}"
trend_txt = f'{arrow(rates.get("trend_pct",0) or 0)} {fmt_pct(rates.get("trend_pct"), signed=True)} على 10 أيام' if rates.get("trend_pct") else "مأخوذ من التكوين/إدخال يدوي"
cols[2].markdown(
    P.metric_card("syp", "سعر الصرف الموازي (ل.س/دولار)", fmt_num(rates["parallel"], 0),
                  "", trend_txt, "tm-flat", [], rates["source"], syp_note),
    unsafe_allow_html=True,
)
cols[3].markdown(
    P.metric_card("shp", "مؤشر الشحن (BDI/بديل)", fmt_num(latest["shipping"]["value"], 0),
                  "نقطة", f"{arrow(d_shp)} {fmt_pct(d_shp, signed=True)} · مئين {ship_pct:.0f}%",
                  delta_cls(d_shp), ship_df["Close"].tail(42) if len(ship_df) else [],
                  latest["shipping"]["source"], latest["shipping"].get("symbol", "")),
    unsafe_allow_html=True,
)
st.write("")


# ----------------------------------------------------------------------- tabs
tabs = st.tabs(["📊 النظرة العامة", "🧮 نموذج التسعير النظري",
                "🚀 الصاروخ والريشة", "🛰️ الرادار الجيوسياسي", "🎯 الإشارة والقرار"])

# -------------------------------------------------------------- TAB 1: overview
with tabs[0]:
    c1, c2 = st.columns([1.15, 1])
    with c1:
        st.markdown(P.section_header("شموع الغازويل الآجل (لندن)", "#22d3ee"))
        show_chart(C.candle_chart(gas_df, "الغازويل الآجل"))
    with c2:
        st.markdown(P.section_header("خام برنت — الاتجاه", "#f5c04a"))
        show_chart(C.line_chart(brent_df, "Close", "خام برنت", "USD/bbl", "#f5c04a"))

    st.markdown(P.section_header("ارتباط فيزيائي ومالي: الغازويل مقابل برنت", "#a78bfa"))
    al = gas_df["Close"].dropna().align(brent_df["Close"].dropna(), join="inner")
    corr = None
    if len(al[0]) > 30 and float(al[1].std()) > 0:
        corr = al[0].pct_change().corr(al[1].pct_change())
    k1, k2 = st.columns([1, 2])
    k1.metric("معامل الارتباط اليومي للعائدات", f"{corr:.2f}" if corr is not None else "—",
              help="ارتباط عائدات الغازويل بعائدات برنت — قياس تقارب قوى التسعير")
    last_n = max(5, min(40, len(gas_df) // 2))
    norm = pd.DataFrame({
        "gasoil": (gas_df["Close"] / gas_df["Close"].iloc[-last_n:].min() - 1) * 100,
        "brent": (brent_df["Close"] / brent_df["Close"].iloc[-last_n:].min() - 1) * 100,
    }).dropna()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=norm.index, y=norm["gasoil"].astype(float), name="الغازويل",
                             line=dict(color="#22d3ee", width=2.2)))
    fig.add_trace(go.Scatter(x=norm.index, y=norm["brent"].astype(float), name="برنت",
                             line=dict(color="#f5c04a", width=2.2)))
    from src.ui.charts import _base_layout  # noqa: E402
    fig = _base_layout(fig, 330)
    fig.update_yaxes(title=f"تغيّر منذ {last_n} جلسة (%)")
    with k2:
        st.markdown(P.section_header("التقارب النسبي", "#a78bfa"))
        show_chart(fig)

    with st.expander("مصادر البيانات الحالية وتفاصيلها", expanded=False):
        src_rows = {
            "الغازويل الآجل": f"الرمز {latest['gasoil'].get('symbol')} — {gas_meta.get('source','?')} · الوحدة: USD/طن",
            "برنت": f"الرمز {latest['brent'].get('symbol')} — {brent_meta.get('source','?')}",
            "الشحن": f"الرمز {latest['shipping'].get('symbol')} — {ship_meta.get('source','?')}",
            "سعر الصرف": f"المصدر {rates['source']} — موازٍ: {fmt_num(rates['parallel'],0)} | رسمي: {fmt_num(rates['official'],0)}",
            "الأخبار": f"نظام {news['mode']} — {news['feeds_scanned']} خلاصة مفحوصة · {news['count']} حدث في الذاكرة",
        }
        for label, txt in src_rows.items():
            st.markdown(f"- **{label}**: {txt}")

# ------------------------------------------------------- TAB 2: pricing model
with tabs[1]:
    st.markdown(P.section_header("معادلة التسعير النظري — تحكّم في المتغيرات", "#f5c04a"))
    with st.expander("افتراضات النموذج (شرائح مباشرة تقوّي الشفافية)", expanded=True):
        c1, c2, c3 = st.columns(3)
        refine_m = c1.slider("هامش التكرير (USD/طن)", 0, 200, int(model.refining_margin_usd_t), 5)
        dist_m = c2.slider("هامش التوزيع (ل.س جديدة/لتر)", 0.0, 60.0,
                           float(model.distribution_margin_syp_l), 0.5)
        vat_r = c3.slider("الضريبة (VAT)", 0.0, 0.30, float(model.vat_rate), 0.01)
        c4, c5 = st.columns(2)
        san_p = c4.slider("علاوة العقوبات/التأمين القسري (USD/طن)", 0, 500,
                          int(model.sanction_premium_usd_t), 10)
        ship_span = c5.slider("مدى الشحن عند أقصى ضغط (USD/طن)", 10, 120, 65, 5)

    model_t = build_pricing_model()
    model_t.refining_margin_usd_t = float(refine_m)
    model_t.distribution_margin_syp_l = float(dist_m)
    model_t.vat_rate = float(vat_r)
    model_t.sanction_premium_usd_t = float(san_p)
    freight_t = model_t.freight_from_percentile(ship_pct, span=float(ship_span))
    bd_t = model_t.breakdown(gasoil_usd_t=gasoil_usd_t, bdi=float(latest["shipping"]["value"] or 1450),
                             fx_parallel=rates["parallel"], fx_official=rates["official"],
                             freight=freight_t)
    theo_t = bd_t["theoretical_syp_l"]
    cmp_t = model_t.compare(theo_t)

    m1, m2, m3 = st.columns(3)
    m1.metric("السعر النظري (ل.س/لتر)", fmt_num(theo_t, 0),
              help="ناتج معادلة التسعير من السعر العالمي حتى أرضية المستهلك")
    m2.metric("التسعير الرسمي — سوق حر (ل.س/لتر)", fmt_num(model_t.official_full, 0),
              delta=f"{fmt_pct(cmp_t['gap_full_pct'], signed=True)} الوضع النظري")
    m3.metric("التسعير الرسمي — حصة مدعومة (ل.س/لتر)", fmt_num(model_t.official_rationed, 0),
              delta=f"{fmt_pct(cmp_t['gap_rationed_pct'], signed=True)} الوضع النظري")

    st.markdown("")
    st.markdown(
        P.status_line_html("الفجوة مقابل السوق الحر الرسمي",
                           f"{fmt_num(cmp_t['gap_full_syp_l'],0)} ل.س/لتر ({fmt_pct(cmp_t['gap_full_pct'], signed=True)})",
                           "#22c55e" if cmp_t['gap_full_pct'] > 0 else "#ef4444"),
        unsafe_allow_html=True,
    )
    st.markdown(
        P.status_line_html("الفجوة مقابل الحصة المدعومة",
                           f"{fmt_num(cmp_t['gap_rationed_syp_l'],0)} ل.س/لتر ({fmt_pct(cmp_t['gap_rationed_pct'], signed=True)})",
                           "#f5c04a"),
        unsafe_allow_html=True,
    )
    st.markdown(
        P.status_line_html("فرق السعر الموازي عن الرسمي",
                           f"{fmt_pct(rates['spread_pct'], signed=True)} — سعر الصرف المستخدم: موازٍ {fmt_num(rates['parallel'],0)}",
                           "#22d3ee"),
        unsafe_allow_html=True,
    )

    st.markdown(P.section_header("تفكيك السعر النظري — شلال التكاليف", "#22d3ee"))
    cw1, cw2 = st.columns([1.4, 1])
    with cw1:
        show_chart(C.waterfall_chart(bd_t["steps"], bd_t["vat_syp_l"], theo_t))
    with cw2:
        st.markdown("**مكونات المحفظة (USD/طن CIF)**")
        st.markdown(
            P.status_line_html("السلعة العالمية FOB", f"{fmt_num(bd_t['usd_components']['product_fob'],2)} USD/t", "#22d3ee"),
            unsafe_allow_html=True,
        )
        st.markdown(
            P.status_line_html("الشحن البحري (حسب مئين الضغط)", f"{fmt_num(bd_t['usd_components']['freight'],2)} USD/t", "#60a5fa"),
            unsafe_allow_html=True,
        )
        st.markdown(
            P.status_line_html("التأمين/مخاطر الحرب", f"{fmt_num(bd_t['usd_components']['insurance'],2)} USD/t", "#a78bfa"),
            unsafe_allow_html=True,
        )
        st.markdown(
            P.status_line_html("علاوة العقوبات", f"{fmt_num(bd_t['usd_components']['sanction'],2)} USD/t", "#ef4444"),
            unsafe_allow_html=True,
        )
        st.markdown(
            P.status_line_html("الإجمالي CIF", f"{fmt_num(bd_t['cif_usd_t'],2)} USD/t", "#f5c04a"),
            unsafe_allow_html=True,
        )
        st.caption("مؤشر الشحن الحالي: " + f"{fmt_num(latest['shipping']['value'],0)} · مئين الضغط {ship_pct:.0f}%")

    st.markdown(P.section_header("المسار التاريخي: السعر النظري مقابل الرسمي", "#a78bfa"))
    theo_series = model_t.theoretical_series(gas_df["Close"], float(latest["shipping"]["value"] or 1450),
                                             rates["parallel"], freight=freight_t)
    show_chart(C.parity_conflict_chart(theo_series, model_t.official_rationed, model_t.official_full))

    with st.expander("منهجية المعادلة والتنبيهات", expanded=False):
        st.markdown(
            "**المعادلة:** السعر النظري = [(سعر الغازويل العالمي + الشحن + التأمين + علاوة العقوبات) "
            "× سعر الصرف الموازي ÷ 1190 لتر/طن] + (هامش التكرير + هامش التوزيع)] × (1 + VAT).\n\n"
            "هذا نموذج تقديري شفاف لأغراض الرصد والمقارنة، وليس آلية تسعير رسمية. الترقيم المرجعي "
            "(الحصة المدعومة/السوق الحر) هو خط أساس تحريري يُمثَّل بالتسعيرة المعلنة لشهر أيلول 2026 "
            "ويمكن ضبطه من الشريط الجانبي. سعر الصرف المستخدم هو السعر الموازي لأنه يعكس تكلفة "
            "الاستيراد الفعلية في غياب سوق صرف رسمي فاعل."
        )

# ----------------------------------------------------- TAB 3: rocket & feather
with tabs[2]:
    st.markdown(P.regime_html(regime, mom_score), unsafe_allow_html=True)
    if regime.get("rolling_short") is not None and len(regime["rolling_short"]):
        rf_df = pd.DataFrame({"rolling_short": regime["rolling_short"]}).dropna()
        mom_cfg = settings.get("momentum", {})
        show_chart(C.momentum_bars(rf_df, spike_thr=float(mom_cfg.get("spike_5d_pct", 6.0)),
                                   purge_thr=float(mom_cfg.get("purging_5d_pct", -6.0))))
    st.markdown(P.section_header("قراءة مؤشر عدم التماثل (Asymmetry)", "#a78bfa"))
    st.markdown(
        "· **عالٍ (أكبر من " + str(settings.get("momentum", {}).get("asymmetry_threshold", 1.8)) + ")** معناه أن السعر يصعد بسرعة شرسة "
        "ويهبط ببطء — النمط الكلاسيكي لسلعة حساسة للإمداد (صاروخ ثم ريشة).\n\n"
        "· **منخفض** يعني تحركات متوازنة أو انحدار سريع يستنزف التوتر بسرعة.",
        help="مؤشر عدم التماثل = متوسط سرعة الصعود المعاصرة ÷ متوسط سرعة الهبوط المعاصرة (نافذة قصيرة)",
    )
    with st.expander("تفاصيل الحساب وقواعد الحالة", expanded=False):
        st.markdown("؛ ".join(regime.get("details", [])))
        code_txt = (
            "ROCKET  ⟸  R5d ≥ +6%   ∨   (R5d > 0 ∧ ū > 2·d̄)\n"
            "FEATHER ⟸  R30d ≤ −4% ∧ أيام هابطة ≥ 12 ∧ متوسط الزحف ≤ 0.35%/يوم\n"
            "PURGE   ⟸  R5d ≤ −6%\n"
            "MIXED   ⟸  كلا الشرطين معًا (ارتفاع صاروخي يتبعه انحدار ريشي)"
        )
        st.code(code_txt, language="text")

# -------------------------------------------------------- TAB 4: geo radar
with tabs[3]:
    geo_color = "#ef4444" if news["stress_index"] >= 65 else ("#f5c04a" if news["stress_index"] >= 35 else "#22c55e")
    g1, g2 = st.columns([1, 1.6])
    with g1:
        show_chart(C.gauge_chart(news["stress_index"], "مؤشر الضغط الجيوسياسي", geo_color))
        st.markdown(
            f"نظام المسح: <code>{news['mode']}</code> · خلاصات مفحوصة: {news['feeds_scanned']} · أحداث في الذاكرة: {news['count']}",
            unsafe_allow_html=True,
        )
        if news["errors"]:
            st.warning("تعذّر جزء من المصادر: " + " | ".join(news["errors"][:4]))
    with g2:
        st.markdown(P.section_header("توزيع الأحداث حسب الفئة", "#f5c04a"))
        if len(news["df"]):
            cat_counts = (
                news["df"]["الفئة"]
                .map(lambda s: s.split("، ") if isinstance(s, str) else [s])
                .explode()
                .value_counts()
            )
            chips_html = " ".join(P.chip(f"{k} ×{v}", "#f5c04a") for k, v in cat_counts.head(8).items())
            st.markdown(chips_html, unsafe_allow_html=True)
        else:
            st.markdown('<span class="tm-meta">لا توجد أحداث مصنّفة بعد.</span>', unsafe_allow_html=True)

    st.markdown(P.section_header("آخر الأحداث", "#22d3ee"))
    ndf = news["df"]
    if len(ndf):
        column_config = {"رابط": st.column_config.LinkColumn("رابط", display_text="افتح")}
        try:
            st.dataframe(ndf, column_config=column_config, width="stretch", hide_index=True)
        except TypeError:
            st.dataframe(ndf, use_container_width=True, hide_index=True)
    else:
        st.info("لم يُرصد أي حدث — تُعرض السيناريوهات التجريبية عند غياب الشبكة.")

    st.markdown(P.section_header("مواضيع ناشئة لم تُصنَّف ضمن التصنيف الحالي (فتح النطاق)", "#a78bfa"))
    st.markdown(P.emerging_html(news["emerging"]), unsafe_allow_html=True)

# -------------------------------------------------------- TAB 5: signal
with tabs[4]:
    st.markdown(P.hero_html(sentiment), unsafe_allow_html=True)

    al_col, dl_col = st.columns([1.4, 1])
    with dl_col:
        st.markdown(P.section_header("تصدير — تقرير الوضع اليومي", "#22d3ee"))
        if pdf_data:
            fname = "thlel_mazot_daily_" + datetime.now().strftime("%Y%m%d_%H%M") + ".pdf"
            show_download("📄 تحميل تقرير الوضع اليومي (PDF)", pdf_data, fname)
            st.caption("يشمل: شلال التسعير، مصفوفة الإشارة، والمحفزات الجيوسياسية النشطة.")
        else:
            st.warning("تعذر توليد PDF — تأكد من توفر fpdf2 وخط يدعم العربية (Tahoma).")
    with al_col:
        st.markdown(P.section_header("آخر التنبيهات المُقيّمة", "#f97316"))
        evts = st.session_state.get("alert_events") or []
        if evts:
            for ev in evts:
                st.markdown(f"- **{ev.title_ar}** — {ev.detail_ar}")
        else:
            st.caption("لا أحداث جديدة منذ آخر تقييم (حركة سعر ≥ عتبة، تغيّر إشارة، أو كلمة حرجة).")
        st.caption("🔔 حالة البوت: " + ("مفعّل — سيبلغ فورًا" if alert_engine.active
                                        else "غير مفعّل — ضع الاعتماديات في .streamlit/secrets.toml أو متغيرات البيئة (لا تُكتب في settings.yaml)"))
    s1, s2 = st.columns([1.3, 1])
    with s1:
        show_chart(C.sub_scores_bars(sentiment["sub_scores"], sentiment["color"]))
    with s2:
        st.markdown(P.section_header("الأوزان الحالية", "#f5c04a"))
        w = sentiment["weights"]
        st.markdown(
            " ".join(P.chip(f"{k}: {v * 100:.0f}%", "#64748b")
                     for k, v in [("جيوسياسي", w.get("geopolitical", 0.35)),
                                  ("زخم", w.get("momentum", 0.3)),
                                  ("فجوة التسعير", w.get("parity_gap", 0.2)),
                                  ("الشحن", w.get("shipping", 0.15))]),
            unsafe_allow_html=True,
        )
        st.markdown("**المنطق:** المؤشر المرجح الفردي مقيّد بين 0-100 (توتر)؛ "
                    "التجميع عبر الأوزان يُخرج إشارة قابلة للترجمة.")

    st.markdown(P.section_header("قواعد الترجمة إلى إجراءات", "#22c55e"))
    table_rows = [
        ("🟢 GREEN (ارتياح)", "نافذة تموين جيدة: محاولة تعاقد على شحنات وتعبئة مخزون بتكاليف أقل؛ "
         "مراجعة أثر تبريد الأسعار على التسعيرة الرسمية المحلية."),
        ("🟡 YELLOW (متابعة حذرة)", "مراجعة أسبوعية؛ تحوط جزئي، ومراقبة هامش الانحراف بين النظري والرسمي؛ "
         "تعطيل أي رفع تسعيري رسمي حتى نضوج المؤشر."),
        ("🔴 RED (أزمة إمداد)", "تفعيل خطط تقنين الطلب والاستعداد لارتفاع السوق الموازي؛ "
         "الضغط لرفع الطاقة التكريرية المحلية، ومراقبة مصافي بانياس/حمص وحركة الناقلات يوميًا."),
    ]
    st.markdown("\n".join(f"- **{a}** — {b}" for a, b in table_rows))

    st.markdown(P.section_header("منهجية الإشارة", "#64748b"))
    st.markdown("؛ ".join(sentiment["explain"]))

# ------------------------------------------------------------------ footer
st.markdown("---")
st.markdown(
    '<div class="tm-meta" style="text-align:center;">'
    "ثُلَّ المازوت — أداة رصد وتحليل لأغراض البحث والاسترشاد، لا تُعدّ نصيحة استثمارية أو سعرًا رسميًا. "
    "تُشتق البيانات من مصادر عامة (Yahoo Finance, Google News RSS) مع مسارات احتياطية، وتُحدَّث من إعدادات "
    "config/settings.yaml. الخطوط المرجعية للتسعير قابلة للتحرير في الشريط الجانبي."
    "</div>",
    unsafe_allow_html=True,
)