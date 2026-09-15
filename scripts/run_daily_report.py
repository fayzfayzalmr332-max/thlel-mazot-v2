"""Automated daily brief generator + optional generic webhook alert.

What it produces:
  * a Markdown brief  -> data/reports/daily_brief_<ts>.md  (clean Arabic summary)
  * machine-readable  -> data/reports/daily_metrics.json    (for your own alerting)
  * optional POST to a webhook URL when --notify-webhook <URL> (works with any
    endpoint / gateway / bot bridge that accepts JSON).

Usage:
    python scripts/run_daily_report.py [--notify-webhook https://hooks.example/x]
                                       [--out-dir data/reports]
This is cron-friendly and fails safe to synthetic data when offline.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests  # noqa: E402
import pandas as pd  # noqa: E402

from src.config import load_settings  # noqa: E402
from src.data.market_data import MarketDataProvider  # noqa: E402
from src.data.fx import FXProvider  # noqa: E402
from src.analysis.momentum import analyze_momentum, score_momentum  # noqa: E402
from src.analysis.pricing import PricingModel  # noqa: E402
from src.analysis.sentiment import evaluate_sentiment, shipping_stress_score  # noqa: E402
from src.news.scanner import NewsRadar  # noqa: E402


def _fmt(value, digits: int = 2, suffix: str = "") -> str:
    try:
        return f"{float(value):,.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return "—"


def sent_emoji(grade: str) -> str:
    return {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(str(grade).upper(), "⚪")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notify-webhook", default="", help="POST JSON snapshot to this URL")
    parser.add_argument("--notify-telegram", action="store_true",
                        help="send the daily brief to Telegram via AlertEngine")
    parser.add_argument("--out-dir", default=str(ROOT / "data" / "reports"))
    parser.add_argument("--skip-news-scan", action="store_true")
    args = parser.parse_args()

    settings = load_settings()
    mkt = MarketDataProvider(settings)
    fx = FXProvider(settings)
    radar = NewsRadar(settings)

    latest = mkt.get_latest_many(["gasoil", "brent", "shipping", "us_heating"])
    gas_df, _ = mkt.get_history("gasoil")
    ship_df, _ = mkt.get_history("shipping")
    rates = fx.get_rates()

    ship_hist = ship_df["Close"].dropna() if len(ship_df) else pd.Series(dtype=float)
    ship_pct = shipping_stress_score(latest["shipping"]["value"], ship_hist)
    regime = analyze_momentum(gas_df["Close"], settings.get("momentum", {}))
    mom_score = score_momentum(regime)

    news = {"stress_index": 50.0, "mode": "off", "count": 0,
            "emerging": [], "errors": []}
    if not args.skip_news_scan:
        news = radar.scan(force=True)

    model = PricingModel(settings)
    bd = model.breakdown(gasoil_usd_t=latest["gasoil"]["value"],
                         bdi=float(latest["shipping"]["value"] or 1450),
                         fx_parallel=rates["parallel"], fx_official=rates["official"])
    cmp_result = model.compare(bd["theoretical_syp_l"])
    sentiment = evaluate_sentiment(settings, mom_score, news["stress_index"],
                                   cmp_result["gap_full_pct"], ship_pct)

    snapshot = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "sentiment": {"grade": sentiment["grade"], "score": sentiment["score"],
                      "label_ar": sentiment["label_ar"]},
        "prices": {
            "gasoil_usd_t": latest["gasoil"]["value"],
            "brent_usd_bbl": latest["brent"]["value"],
            "shipping": latest["shipping"]["value"],
            "parallel_usd_syp": rates["parallel"],
            "official_usd_syp": rates["official"],
        },
        "momentum": {"state": regime["state"], "c_short_pct": regime.get("c_short"),
                     "asymmetry": regime.get("asymmetry_index")},
        "theoretical_syp_l": round(bd["theoretical_syp_l"], 0),
        "gap_full_pct": round(cmp_result["gap_full_pct"], 1),
        "geo_stress": news["stress_index"],
        "shipping_percentile": round(ship_pct, 0),
        "news_mode": news["mode"],
        "emerging_topics": [t["topic"] for t in news.get("emerging", [])][:8],
        "source": "live-or-fallback",
    }

    # ---------- write outputs ----------
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    c5 = regime.get("c_short")
    gap_full = cmp_result["gap_full_pct"]
    md = "\n".join([
        f"# 📋 ملخص الوضع اليومي — ثُلَّ المازوت — {now_str}",
        "",
        f"**الإشارة:** {sentiment['label_ar']} — {sentiment['grade']} ({sentiment['score']:.0f}/100)",
        "",
        "| المؤشر | القيمة |",
        "|---|---|",
        f"| الغازويل الآجل | {_fmt(latest['gasoil']['value'], 1)} USD/طن |",
        f"| خام برنت | {_fmt(latest['brent']['value'], 1)} USD/برميل |",
        f"| الشحن | {_fmt(latest['shipping']['value'] or 0, 0)} · مئين {ship_pct:.0f}% |",
        f"| سعر الصرف الموازي | {_fmt(rates['parallel'], 0)} ل.س/دولار |",
        f"| السعر النظري | {_fmt(bd['theoretical_syp_l'], 0)} ل.س/لتر |",
        f"| فجوة السوق الحر الرسمي | {_fmt(gap_full, 1)}% |",
        f"| الضغط الجيوسياسي | {news['stress_index']:.0f}/100 ({news['mode']}) |",
        "",
        f"**الزخم:** {regime['state']} — حركة 5 أيام {_fmt(c5 or 0, 2)}% · عدم تماثل {_fmt(regime.get('asymmetry_index') or 0, 2)}",
        "",
        "**ملاحظات منهجية:** تقرير آلي لأغراض الرصد، القيم قابلة للمراجعة يدويًا، "
        "والتسعيرة المرجعية تُحدَّث من المراسيم الرسمية.",
        "",
    ]) + "\n"
    md_path = out_dir / f"daily_brief_{stamp}.md"
    md_path.write_text(md, encoding="utf-8")

    json_path = out_dir / f"daily_metrics_{stamp}.json"
    json_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "daily_metrics.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[daily] grade={sentiment['grade']} score={sentiment['score']:.0f} "
          f"theoretical={_fmt(bd['theoretical_syp_l'], 0)} SYP/L -> {md_path}")

    # ---------- optional telegram brief ----------
    if args.notify_telegram:
        from src.analysis.alerts import AlertEngine
        engine = AlertEngine(settings)
        if not engine.configured:
            print("[daily] telegram skipped: لا اعتماديات (ضع token/chat_id في .streamlit/secrets.toml أو المتغيرات)")
        else:
            brief_text = "\n".join([
                f"📋 ملخص الوضع اليومي — ثُلَّ المازوت — {now_str}",
                f"الإشارة: {sent_emoji(sentiment['grade'])} {sentiment['label_ar']} "
                f"({sentiment['grade']} — {sentiment['score']:.0f}/100)",
                f"الغازويل: {_fmt(latest['gasoil']['value'], 1)} USD/طن",
                f"برنت: {_fmt(latest['brent']['value'], 1)} USD/برميل",
                f"سعر الصرف الموازي: {_fmt(rates['parallel'], 0)} ل.س/دولار",
                f"السعر النظري: {_fmt(bd['theoretical_syp_l'], 0)} ل.س/لتر "
                f"(فجوة السوق الحر {_fmt(gap_full, 1)}%)",
                f"الضغط الجيوسياسي: {news['stress_index']:.0f}/100",
            ])
            ok = engine.send_message(brief_text)
            print("[daily] telegram:", "OK" if ok else "FAILED — تأكد من تفعيل البوت وبدء المحادثة (/start)")

    # ---------- optional webhook ----------
    if args.notify_webhook:
        try:
            resp = requests.post(args.notify_webhook, json=snapshot, timeout=10)
            print(f"[daily] webhook HTTP {resp.status_code}")
        except Exception as exc:  # pylint: disable=broad-except
            print(f"[daily] webhook failed: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())