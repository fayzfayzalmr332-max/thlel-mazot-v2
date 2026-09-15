"""Telegram alerting engine with pure, zero-network trigger logic.

Design
------
The trigger/evaluate layer is pure Python (no I/O — fully unit-testable
offline); the only network touch point is the injected ``sender`` callable
(default ``AlertEngine._telegram_send`` -> Telegram Bot API).

Triggers built in:
  * PRICE_SPIKE/DROP — |dGasoil| >= threshold (USD/tonne) between refreshes.
  * SIGNAL_CHANGE    — hero grade changed (GREEN/YELLOW/RED transitions).
  * NEWS_KEYWORD     — critical local keywords from the news radar.

State (previous price, previous grade, sent news digests) is persisted
through a DiskCache so repeated refreshes never re-alert the same signal.
"""
from __future__ import annotations

import hashlib
import html as _html
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests  # network used only inside AlertEngine._telegram_send

from ..utils.disk_cache import DiskCache

logger = logging.getLogger(__name__)

KIND_PRICE_SPIKE = "PRICE_SPIKE"
KIND_PRICE_DROP = "PRICE_DROP"
KIND_SIGNAL_CHANGE = "SIGNAL_CHANGE"
KIND_NEWS_KEYWORD = "NEWS_KEYWORD"

SEVERITY_INFO = "INFO"
SEVERITY_WARNING = "WARNING"
SEVERITY_CRITICAL = "CRITICAL"

GRADE_LEVEL = {"GREEN": 1, "YELLOW": 2, "RED": 3}


@dataclass(frozen=True)
class AlertEvent:
    """A single alert ready for dispatch (telegram text, metadata, payload)."""

    kind: str
    title_ar: str
    detail_ar: str
    severity: str = SEVERITY_WARNING
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_html(self) -> str:
        """Telegram HTML-safe message body (no parse-mode pitfalls)."""
        esc = _html.escape
        return "<b>" + esc(self.title_ar) + "</b>\n" + esc(self.detail_ar)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "title_ar": self.title_ar,
            "detail_ar": self.detail_ar,
            "severity": self.severity,
            "payload": dict(self.payload),
        }


# ------------------------------------------------------------------ pure checks


def check_price_move(prev_usd_t: Optional[float], curr_usd_t: Optional[float],
                     threshold_usd_t: float = 30.0) -> Optional[AlertEvent]:
    """Move alert when |curr - prev| (USD/tonne) crosses the threshold."""
    if prev_usd_t is None or curr_usd_t is None:
        return None
    p, c = float(prev_usd_t), float(curr_usd_t)
    thr = float(threshold_usd_t)
    diff = c - p
    if abs(diff) < thr:
        return None
    prev_txt = f"{p:,.1f}"
    detail = ("تحرك السعر من " + prev_txt + " إلى " + f"{c:,.1f}" +
              " USD/طن — صافي " + f"{diff:+,.1f}" +
              " (عتبة " + f"{thr:,.0f}" + " USD/طن).")
    if diff > 0:
        return AlertEvent(
            kind=KIND_PRICE_SPIKE,
            title_ar="🔺 الغازويل الآجل (ULS1!) يقفز فوق العتبة",
            detail_ar=detail,
            severity=SEVERITY_CRITICAL,
            payload={"prev": p, "curr": c, "diff": diff, "threshold": thr},
        )
    return AlertEvent(
        kind=KIND_PRICE_DROP,
        title_ar="🔻 الغازويل الآجل (ULS1!) يهبط تحت العتبة",
        detail_ar=detail,
        severity=SEVERITY_CRITICAL,
        payload={"prev": p, "curr": c, "diff": diff, "threshold": thr},
    )


def check_signal_change(prev_grade: Optional[str], curr_grade: Optional[str]) -> Optional[AlertEvent]:
    """Hero signal state transition alert (GREEN/YELLOW/RED).
    No event when there is no previous grade (first run / cold start)."""
    if not curr_grade or prev_grade is None or prev_grade == curr_grade:
        return None
    labels = {"GREEN": "🟢 ارتياح / تبريد دولي",
              "YELLOW": "🟡 متابعة حذرة",
              "RED": "🔴 أزمة إمداد / ضغط مضاعف"}
    frm = labels.get(str(prev_grade), str(prev_grade or "—"))
    to = labels.get(str(curr_grade), str(curr_grade))
    return AlertEvent(
        kind=KIND_SIGNAL_CHANGE,
        title_ar="🔔 تغيّر إشارة اللوحة الرئيسية",
        detail_ar="انتقلت حالة النظام من «" + frm + "» إلى «" + to + "».",
        severity=SEVERITY_CRITICAL,
        payload={"prev_grade": prev_grade, "curr_grade": curr_grade},
    )


def check_news_keywords(articles: List[Dict[str, Any]],
                        critical_terms: List[str],
                        min_severity: float = 0.65) -> List[AlertEvent]:
    """Critical local keyword alert over tagged news items (zero network)."""
    terms = [str(t).lower() for t in critical_terms if t]
    if not terms:
        return []
    events: List[AlertEvent] = []
    for art in articles:
        if not isinstance(art, dict):
            continue
        title = str(art.get("title") or "")
        text = (title + " " + str(art.get("summary") or "")).lower()
        raw_sev = art.get("severity")
        sev = float(raw_sev) if isinstance(raw_sev, (int, float)) else 0.35
        if sev < float(min_severity):
            continue
        hits = [t for t in terms if t in text]
        if not hits:
            continue
        digest = hashlib.sha1(title.strip().lower().encode("utf-8")).hexdigest()
        events.append(AlertEvent(
            kind=KIND_NEWS_KEYWORD,
            title_ar="📰 كلمة محلية حرجة رُصدت في الرادار",
            detail_ar=("«" + title[:140] + "» — فئة: " + _html.escape(str(art.get("labels_ar") or art.get("label_ar") or "عام/مراقبة"))
                       + " · شدة " + f"{sev:.2f}" + (" · " + str(art.get("source")) if art.get("source") else "")),
            severity=SEVERITY_CRITICAL if sev >= 0.8 else SEVERITY_WARNING,
            payload={"title": title, "terms": hits, "severity": sev, "key": digest},
        ))
    return events


# ------------------------------------------------------------------ engine

class AlertEngine:
    """Orchestrator: state persistence, same-signal de-dup, delivery."""

    def __init__(self, settings: Dict[str, Any], cache_dir: Optional[str] = None,
                 sender: Optional[Callable[[str], bool]] = None):
        self.cfg = settings.get("alerting", {}) or {}
        tg = self.cfg.get("telegram", {}) or {}
        self.enabled = bool(tg.get("enabled", False))
        self.bot_token = str(tg.get("bot_token", "") or "")
        self.chat_id = str(tg.get("chat_id", "") or "")
        self.parse_mode = str(tg.get("parse_mode", "HTML"))
        self.api_base = str(tg.get(
            "send_api_base", "https://api.telegram.org/bot{token}/sendMessage"))
        self.price_threshold = float(self.cfg.get("price_move_threshold_usd_t", 30.0))
        self.min_news_severity = float(self.cfg.get("min_news_severity", 0.65))
        self.critical_terms = [str(t) for t in self.cfg.get("critical_keywords", []) if t]
        self.state_key = str(self.cfg.get("state_cache_key", "alerts_state"))
        cache_base = cache_dir or settings.get("app", {}).get("cache_dir", ".cache")
        self.disk = DiskCache(cache_base)
        self._sender = sender if sender is not None else self._telegram_send
        self.last_events = []
        self.last_delivery = []

    # ------------------------------------------------------------------ state

    def _load_state(self) -> Dict[str, Any]:
        st = self.disk.get(self.state_key, max_age_hours=24.0)
        if not isinstance(st, dict):
            return {"gasoil_usd_t": None, "grade": None, "sent_keys": []}
        return {
            "gasoil_usd_t": st.get("gasoil_usd_t"),
            "grade": st.get("grade"),
            "sent_keys": set(st.get("sent_keys") or []),
        }

    def _save_state(self, state: Dict[str, Any]) -> None:
        self.disk.set(self.state_key, {
            "gasoil_usd_t": state.get("gasoil_usd_t"),
            "grade": state.get("grade"),
            "sent_keys": sorted(state.get("sent_keys") or []),
        })

    @staticmethod
    def make_snapshot(gasoil_usd_t, grade: str, articles=None) -> Dict[str, Any]:
        """A minimal state snapshot the engine expects (see app.py wiring)."""
        return {"gasoil_usd_t": gasoil_usd_t, "grade": grade,
                "articles": articles or []}

    # --------------------------------------------------------------- evaluate

    def evaluate(self, snapshot: Dict[str, Any],
                 prev_state: Optional[Dict[str, Any]] = None) -> List[AlertEvent]:
        """Pure evaluation: compare snapshot against persisted/prev state."""
        prev = prev_state if isinstance(prev_state, dict) else self._load_state()
        events: List[AlertEvent] = []

        ev = check_price_move(prev.get("gasoil_usd_t"), snapshot.get("gasoil_usd_t"),
                              self.price_threshold)
        if ev:
            events.append(ev)

        ev = check_signal_change(prev.get("grade"), snapshot.get("grade"))
        if ev:
            events.append(ev)

        known = set(prev.get("sent_keys") or [])
        news_events, fresh_keys = self._news_events(snapshot.get("articles") or [], known)
        events.extend(news_events)
        self.last_events = events
        self._fresh_keys = fresh_keys
        return events

    def _news_events(self, articles: List[Dict[str, Any]],
                     sent_keys) -> Tuple[List[AlertEvent], List[str]]:
        terms = [str(t).lower() for t in self.critical_terms]
        if not terms:
            return [], []
        events: List[AlertEvent] = []
        fresh: List[str] = []
        for art in articles:
            if not isinstance(art, dict):
                continue
            title = str(art.get("title") or "")
            text = (title + " " + str(art.get("summary") or "")).lower()
            raw_sev = art.get("severity")
            sev = float(raw_sev) if isinstance(raw_sev, (int, float)) else 0.35
            if sev < self.min_news_severity:
                continue
            hits = [t for t in terms if t in text]
            if not hits:
                continue
            digest = hashlib.sha1(title.strip().lower().encode("utf-8")).hexdigest()
            if digest in sent_keys:
                continue
            fresh.append(digest)
            label_txt = ", ".join(str(x) for x in art.get("labels_ar") or ["عام/مراقبة"])
            detail = ("«" + title[:140] + "» — فئة: " + label_txt
                      + " · شدة " + f"{sev:.2f}"
                      + (" · " + str(art.get("source")) if art.get("source") else ""))
            events.append(AlertEvent(
                kind=KIND_NEWS_KEYWORD,
                title_ar="📰 كلمة محلية حرجة رُصدت في الرادار",
                detail_ar=detail,
                severity=SEVERITY_CRITICAL if sev >= 0.8 else SEVERITY_WARNING,
                payload={"title": title, "terms": hits, "severity": sev, "key": digest},
            ))
        return events, fresh

    # ------------------------------------------------------------------ process

    def process_and_send(self, snapshot: Dict[str, Any]) -> List[AlertEvent]:
        """Evaluate, dispatch (if enabled/configured), persist new state.

        Never raises: delivery failures are recorded in ``last_delivery``.
        """
        events = self.evaluate(snapshot)
        for ev in events:
            try:
                ok = bool(self._sender(ev.to_html()))
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Alert delivery failed: %s", exc)
                ok = False
            self.last_delivery.append(ok)

        merged = set(self._load_state().get("sent_keys") or [])
        merged.update(getattr(self, "_fresh_keys", []))
        self._save_state({
            "gasoil_usd_t": snapshot.get("gasoil_usd_t"),
            "grade": snapshot.get("grade"),
            "sent_keys": sorted(merged),
        })
        return events

    # ------------------------------------------------------------- delivery

    def _telegram_send(self, text: str) -> bool:
        """Real Telegram Bot API call — the ONLY network touch point."""
        if not self.enabled or not self.bot_token or not self.chat_id:
            return False
        url = self.api_base.format(token=self.bot_token)
        resp = requests.post(url, data={
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": self.parse_mode,
            "disable_web_page_preview": "true",
        }, timeout=10)
        resp.raise_for_status()
        return bool(resp.json().get("ok", False))

    @property
    def configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    @property
    def active(self) -> bool:
        return self.enabled and self.configured