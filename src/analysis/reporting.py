"""RTL-aware daily market PDF report (Arabic shaping + fpdf2, zero-network).

The snapshot builder (``build_dashboard_snapshot``) is a plain dict assembled
from the dashboard objects — fully unit-testable offline. ``PdfReport.build``
then renders it into a formatted A4 document:

  1) Header band — name, timestamp, hero grade + stress score
  2) Market metrics table (gasoil, brent, FX, freight, theoretical pricing)
  3) Sentiment matrix  — weighted sub-scores as bar gauges
  4) Pricing waterfall — transparent cost stack + official baseline vs gap
  5) Active geopolitical triggers (top tagged news + stress index)
  6) Methodology footer

Arabic glyph shaping via ``arabic_reshaper`` + ``python-bidi`` for any installed
Arabic-capable TTF (Tahoma / Segoe UI on Windows); on Linux/CI it degrades to an
English/Latin layout so the report always builds.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from fpdf import FPDF

GRADE_COLORS = {
    "GREEN": (34, 197, 94),
    "YELLOW": (245, 192, 74),
    "RED": (239, 68, 68),
}
GRADE_LABELS_EN = {"GREEN": "RELIEF / GLOBAL COOL-DOWN",
                  "YELLOW": "CAUTION / WATCH",
                  "RED": "SUPPLY-CRUNCH"}


def build_dashboard_snapshot(latest: Dict[str, Any], rates: Dict[str, Any],
                             bd: Dict[str, Any], cmp_result: Dict[str, Any],
                             sentiment: Dict[str, Any], regime: Dict[str, Any],
                             news: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble the pure snapshot consumed by the PDF builder / alert engine."""
    metrics = [
        {"label_ar": "الغازويل الآجل (ICEEUR:ULS1!)",
         "label_en": "Gasoil futures", "value": latest["gasoil"]["value"]},
        {"label_ar": "خام برنت (المرجعي)", "label_en": "Brent",
         "value": latest["brent"]["value"]},
        {"label_ar": "الشحن (BDI/بديل)", "label_en": "Shipping",
         "value": latest["shipping"]["value"]},
        {"label_ar": "سعر الصرف الموازي", "label_en": "Parallel USD/SYP",
         "value": rates["parallel"]},
        {"label_ar": "السعر النظري للمازوت", "label_en": "Theoretical SYP/L",
         "value": bd["theoretical_syp_l"]},
        {"label_ar": "التسعيرة الرسمية — سوق حر", "label_en": "Official free-market",
         "value": cmp_result["official_full"]},
        {"label_ar": "الحصة المدعومة الرسمية", "label_en": "Official rationed",
         "value": cmp_result["official_rationed"]},
    ]
    return {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "grade": sentiment.get("grade", "YELLOW"),
        "grade_label_ar": sentiment.get("label_ar", "—"),
        "score": sentiment.get("score", 0),
        "sub_scores": sentiment.get("sub_scores", {}),
        "metrics": metrics,
        "waterfall": {
            "labels": [s[0] for s in bd["steps"]],
            "values": [round(float(v), 2) for _, v, _ in bd["steps"]],
            "vat": round(float(bd["vat_syp_l"]), 2),
            "total": round(float(bd["theoretical_syp_l"]), 2),
        },
        "official": {
            "rationed": cmp_result.get("official_rationed"),
            "full": cmp_result.get("official_full"),
            "gap_full_pct": cmp_result.get("gap_full_pct"),
        },
        "momentum": {
            "state": regime.get("state", "NEUTRAL"),
            "state_ar": regime.get("state_ar", "—"),
            "c_short": regime.get("c_short"),
            "c_long": regime.get("c_long"),
            "asymmetry": regime.get("asymmetry_index"),
        },
        "news": {
            "stress": news.get("stress_index", 50.0),
            "mode": news.get("mode", "off"),
            "count": news.get("count", 0),
            "items": [{
                "title": str(a.get("title", ""))[:140],
                "severity": float(a.get("severity", 0.0)),
                "labels_ar": list(a.get("labels_ar", []) or []),
                "source": str(a.get("source", "") or ""),
            } for a in news.get("items", [])[:6]],
            "emerging": [str(t.get("topic", "")) for t in news.get("emerging", [])][:6],
        },
    }


class PdfReport:
    """fpdf2 renderer with Arabic shaping, RTL alignment and grade theming."""

    FONT_CANDIDATES = [
        ("C:/Windows/Fonts/tahoma.ttf", True),
        ("C:/Windows/Fonts/segoeui.ttf", True),
        ("C:/Windows/Fonts/arial.ttf", True),
        ("C:/Windows/Fonts/arialuni.ttf", True),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", False),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", False),
        ("/System/Library/Fonts/GeezaPro.ttc", True),
    ]

    def __init__(self, settings: Dict[str, Any]):
        cfg = settings.get("reporting", {}).get("pdf", {})
        self.author = str(cfg.get("author", "THLEL MAZOT"))
        self.page_size = str(cfg.get("page_size", "A4"))
        self.include_geo = bool(cfg.get("include_geo_triggers", True))
        self._font_path: Optional[str] = None
        self._arabic_ok = False
        self._reshape = None
        self._bidi = None
        for path, arabic in self.FONT_CANDIDATES:
            if os.path.exists(path):
                self._font_path = path
                self._arabic_ok = arabic
                break
        if self._arabic_ok:
            try:  # graceful degradation if libs missing
                import arabic_reshaper  # type: ignore
                from bidi.algorithm import get_display  # type: ignore
                self._reshape = arabic_reshaper.reshape
                self._bidi = get_display
            except Exception:  # pylint: disable=broad-except
                self._arabic_ok = False

    # ------------------------------------------------------------------ text

    def display(self, text: str) -> str:
        """Shaped + bidi-reordered text (visual LTR for fpdf2, RTL visually)."""
        if not text:
            return ""
        if self._arabic_ok and self._reshape and self._bidi:
            return str(self._bidi(self._reshape(text)))
        return text

    def _t(self, ar: str, en: str) -> str:
        """Pick/brand side: Arabic visual text, else English label."""
        if self._arabic_ok:
            return self.display(ar)
        return en

    def _value(self, v, digits: int = 0) -> str:
        try:
            return f"{float(v):,.{digits}f}"
        except (TypeError, ValueError):
            return "—"

    # ------------------------------------------------------------------ build

    def build(self, snapshot: Dict[str, Any]) -> bytes:
        """Render the snapshot into PDF bytes (latin-1 encoded fpdf2 buffer)."""
        pdf = FPDF(orientation="P", unit="mm", format=self.page_size)
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()
        M: float = 14.0
        W: float = pdf.w - 2 * M
        align = "R" if self._arabic_ok else "L"
        grade = str(snapshot.get("grade", "YELLOW"))
        band = GRADE_COLORS.get(grade, GRADE_COLORS["YELLOW"])

        font = "Ar"
        if self._font_path:
            pdf.add_font(font, "", self._font_path)
            pdf.add_font(font, "B", self._font_path)  # same TTF serves bold
        else:
            font = "helvetica"

        # ---- header band ----
        pdf.set_fill_color(*band)
        pdf.rect(0, 0, pdf.w, 26, style="F")
        pdf.set_text_color(6, 18, 31)
        pdf.set_xy(M, 7)
        pdf.set_font(font, "B", 15)
        pdf.cell(W, 7, self._t("ثُلَّ المازوت — التقرير اليومي لأسواق الطاقة",
                               "THLEL MAZOT — Daily Energy Market Report"), align=align)
        pdf.set_xy(M, 16)
        pdf.set_font(font, "B", 9)
        grad = str(snapshot.get("grade_label_ar", grade))
        score = float(snapshot.get("score", 0) or 0)
        pdf.cell(W, 6, self._t(f"{grad} — {score:.0f}/100",
                               f"{GRADE_LABELS_EN.get(grade, grade)} — {score:.0f}/100"), align=align)

        # ---- timestamp line ----
        pdf.set_y(30)
        pdf.set_font(font, "", 8)
        pdf.set_text_color(148, 163, 184)
        ts = str(snapshot.get("ts", ""))
        pdf.cell(W, 4, self._t("وقت الإصدار: " + ts, "Issued: " + ts), align=align)
        pdf.ln(7)

        # ---- section: market metrics ----
        self._section(pdf, font, W, align, "1) الأسعار والمؤشرات الحية", "1) Live market indicators")
        pdf.set_font(font, "", 9)
        row_h = 6.2
        for r in snapshot.get("metrics", []):
            label = self._t(str(r.get("label_ar", "")), str(r.get("label_en", "")))
            raw = r.get("value")
            if isinstance(raw, (int, float)):
                val = self._value(raw, 1 if float(raw) < 10000 else 0)
            else:
                val = str(raw or "")
            y = pdf.get_y()
            if y > pdf.h - 30:
                pdf.add_page(); y = pdf.get_y()
            col_w = (W - 6) / 2
            if self._arabic_ok:
                pdf.set_xy(M, y); pdf.cell(col_w, row_h, val, align="L")
                pdf.set_xy(M + col_w, y); pdf.cell(col_w, row_h, label, align="R")
            else:
                pdf.set_xy(M, y); pdf.cell(col_w, row_h, label, align="L")
                pdf.set_xy(M + col_w, y); pdf.cell(col_w, row_h, val, align="R")
            pdf.set_draw_color(31, 43, 66)
            pdf.line(M, y + row_h, M + W, y + row_h)
            pdf.set_y(y + row_h)
        pdf.ln(4)

        # ---- section: sentiment matrix ----
        self._section(pdf, font, W, align, "2) مصفوفة الإشارة والمشاعر", "2) Sentiment matrix")
        subs = snapshot.get("sub_scores", {})
        entries = [
            ("geopolitical", "ضغط جيوسياسي", "Geopolitical pressure"),
            ("momentum", "زخم الأسعار", "Price momentum"),
            ("parity_gap", "فجوة التسعير المحلي", "Local pricing gap"),
            ("shipping", "ضغط الشحن", "Shipping pressure"),
        ]
        pdf.set_font(font, "", 8.5)
        pdf.set_text_color(231, 237, 247)
        bar_w = 46.0
        for key, ar, en in entries:
            val = max(0.0, min(100.0, float(subs.get(key, 0) or 0)))
            y = pdf.get_y()
            if y > pdf.h - 30:
                pdf.add_page(); y = pdf.get_y()
            label = self._t(ar, en)
            pdf.set_xy(M, y)
            pdf.cell(W - bar_w - 14, 5.5, label, align="R" if self._arabic_ok else "L")
            bx = M + (W - bar_w - 14)
            pdf.set_fill_color(22, 35, 59)
            pdf.rect(bx, y + 1.2, bar_w, 3, style="F")
            pdf.set_fill_color(*band)
            pdf.rect(bx, y + 1.2, bar_w * val / 100.0, 3, style="F")
            pdf.set_text_color(203, 213, 225)
            pdf.text(bx + bar_w + 2, y + 4, f"{val:.0f}")
            pdf.set_y(y + 6.2)
        pdf.ln(2)

        # ---- momentum note ----
        m = snapshot.get("momentum", {})
        if m.get("state_ar"):
            self._section(pdf, font, W, align, "3) زخم الأسعار — الصاروخ والريشة", "3) Rocket & Feather momentum")
            pdf.set_font(font, "", 8.5)
            pdf.set_text_color(203, 213, 225)
            c5 = m.get("c_short")
            c5_txt = f"{c5:+.2f}%" if isinstance(c5, (int, float)) else "—"
            pdf.multi_cell(W, 4.5, self._t(
                f"الحالة: {m.get('state_ar')} — حركة 5 أيام: {c5_txt}",
                f"State: {m.get('state', 'NEUTRAL')} — 5d move: {c5_txt}"), align=align)
            pdf.ln(4)

        # ---- section: pricing waterfall ----
        self._section(pdf, font, W, align, "4) تفكيك السعر النظري (شلال التكاليف)", "4) Pricing waterfall (SYP/L)")
        wf = snapshot.get("waterfall", {})
        labels = list(wf.get("labels", [])) + ["الضريبة (VAT)", "السعر النظري الكلي"]
        values = list(wf.get("values", [])) + [wf.get("vat", 0), wf.get("total", 0)]
        pdf.set_font(font, "", 8.5)
        for i, (label, val) in enumerate(zip(labels, values)):
            y = pdf.get_y()
            if y > pdf.h - 30:
                pdf.add_page(); y = pdf.get_y()
            is_total = i == len(values) - 1
            pdf.set_font(font, "B" if is_total else "", 8.5)
            pdf.set_text_color(6, 18, 31) if is_total else pdf.set_text_color(231, 237, 247)
            col_w = (W - 6) / 2
            if self._arabic_ok:
                pdf.set_xy(M, y); pdf.cell(col_w, 5.5, self._value(val, 0), align="L")
                pdf.set_xy(M + col_w, y); pdf.cell(col_w, 5.5, self._t(str(label), " "), align="R")
            else:
                pdf.set_xy(M, y); pdf.cell(col_w, 5.5, str(label), align="L")
                pdf.set_xy(M + col_w, y); pdf.cell(col_w, 5.5, self._value(val, 0), align="R")
            pdf.set_y(y + 5.5)
        pdf.ln(4)

        # ---- section: geopolitical triggers ----
        if self.include_geo:
            nw = snapshot.get("news", {})
            self._section(pdf, font, W, align, "5) المحفزات الجيوسياسية النشطة", "5) Active geopolitical triggers")
            pdf.set_font(font, "", 8.5)
            pdf.set_text_color(203, 213, 225)
            pdf.multi_cell(W, 4.5, self._t(
                f"مؤشر الضغط الجيوسياسي: {float(nw.get('stress', 0) or 0):.0f}/100 — وضع المسح: {nw.get('mode', 'off')}",
                f"Geo-stress index: {float(nw.get('stress', 0) or 0):.0f}/100 — scan: {nw.get('mode', 'off')}"),
                align=align)
            pdf.ln(1.5)
            for item in nw.get("items", []):
                sev = float(item.get("severity", 0) or 0)
                labels_txt = "، ".join(item.get("labels_ar", []) or [])
                title_txt = str(item.get("title", ""))
                src_txt = f" · {item.get('source')}" if item.get("source") else ""
                line = self._t(f"{sev:.2f} — {title_txt} — {labels_txt}{src_txt}",
                               f"{sev:.2f} — {title_txt} — {labels_txt}{src_txt}")
                pdf.set_text_color(148, 163, 184)
                pdf.multi_cell(W, 4.2, line, align=align)
                pdf.ln(0.6)
            emerging = nw.get("emerging", [])
            if emerging:
                pdf.set_text_color(245, 192, 74)
                pdf.multi_cell(W, 4.2, self._t(
                    "مواضيع ناشئة: " + "، ".join(emerging),
                    "Emerging topics: " + ", ".join(emerging)), align=align)

        # ---- footer / disclaimer ----
        pdf.set_y(-22)
        pdf.set_fill_color(7, 13, 24)
        pdf.set_text_color(100, 116, 139)
        pdf.set_font(font, "", 7)
        note = ("تقرير آلي صادر عن «ثُلَّ المازوت» لأغراض الاسترشاد والرصد؛ لا يُعدّ سعرًا رسميًا "
                "ولا نصيحة استثمارية. التسعيرة المرجعية تُحدَّث من المراسيم الرسمية وتعديلات "
                "config/settings.yaml.")
        pdf.multi_cell(W, 4, self._t(note,
                                    "Automated report for monitoring/research only — not an official price "
                                    "or investment advice."), align=align)
        pdf.ln(2)
        pdf.cell(W, 4, self._t("أعدّ من قبل " + self.author + " — " + str(snapshot.get("ts", "")),
                               "Produced by " + self.author), align=align)

        raw = pdf.output()  # fpdf2 >= 2.2 returns a bytes-like buffer
        if isinstance(raw, (bytearray, bytes)):
            return bytes(raw)
        return str(raw).encode("latin-1")

    # ------------------------------------------------------------------ sect

    def _section(self, pdf, font: str, width: float, align: str, ar: str, en: str) -> None:
        pdf.set_font(font, "B", 10.5)
        pdf.set_text_color(245, 192, 74)
        pdf.set_fill_color(22, 35, 59)
        y = pdf.get_y()
        pdf.set_xy(14, y)
        pdf.cell(width, 7, self._t(ar, en), fill=True, align=align)
        pdf.set_y(y + 8.2)


def build_pdf_bytes(settings: Dict[str, Any], snapshot: Dict[str, Any]) -> bytes:
    """Render a snapshot to PDF bytes through a fresh PdfReport instance."""
    return PdfReport(settings).build(snapshot)