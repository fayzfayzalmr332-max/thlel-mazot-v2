"""Zero-network unit tests for the Telegram alert engine (pure triggers +
injected fake sender — the network sender is never touched)."""
from __future__ import annotations

from src.analysis.alerts import (
    AlertEngine,
    KIND_NEWS_KEYWORD,
    KIND_PRICE_DROP,
    KIND_PRICE_SPIKE,
    KIND_SIGNAL_CHANGE,
    check_news_keywords,
    check_price_move,
    check_signal_change,
)

SETTINGS = {
    "app": {"cache_dir": ".cache_test_alerts"},
    "alerting": {
        "telegram": {"enabled": True, "bot_token": "TOK", "chat_id": "123"},
        "price_move_threshold_usd_t": 30.0,
        "min_news_severity": 0.65,
        "critical_keywords": ["بانياس", "مضيق هرمز"],
    },
}


def test_price_spike_crosses_threshold():
    ev = check_price_move(700.0, 745.0, 30.0)
    assert ev is not None
    assert ev.kind == KIND_PRICE_SPIKE
    assert ev.payload["diff"] == 45.0


def test_price_drop_crosses_threshold():
    ev = check_price_move(700.0, 655.0, 30.0)
    assert ev is not None
    assert ev.kind == KIND_PRICE_DROP
    assert ev.detail_ar and ev.title_ar


def test_price_small_move_no_alert():
    assert check_price_move(700.0, 720.0, 30.0) is None
    assert check_price_move(None, 700.0, 30.0) is None


def test_signal_transition_alerted_only():
    ev = check_signal_change("GREEN", "RED")
    assert ev is not None and ev.kind == KIND_SIGNAL_CHANGE
    assert ev.payload["curr_grade"] == "RED"
    assert check_signal_change("RED", "RED") is None
    assert check_signal_change(None, "GREEN") is None  # cold start


def test_news_keyword_hit_and_severity_gate():
    arts = [{"title": "أعمال صيانة في مصفاة بانياس", "severity": 0.85,
            "labels_ar": ["عمليات المصافي"], "source": "ن"}]
    evs = check_news_keywords(arts, ["بانياس"], 0.65)
    assert len(evs) == 1
    assert evs[0].kind == KIND_NEWS_KEYWORD
    assert evs[0].payload["key"]
    # below severity gate -> skipped
    arts_low = [{"title": "مصفاة بانياس", "severity": 0.3, "labels_ar": []}]
    assert check_news_keywords(arts_low, ["بانياس"], 0.65) == []


def test_engine_sends_once_and_dedupes(tmp_path):
    sent = []
    engine = AlertEngine(SETTINGS, cache_dir=str(tmp_path),
                         sender=lambda text: (sent.append(text) or True))
    art = {"title": "مصفاة بانياس تعمل", "severity": 0.9,
           "labels_ar": ["عمليات المصافي"], "source": "ن"}
    snap1 = AlertEngine.make_snapshot(700.0, "GREEN", [art])
    events1 = engine.process_and_send(snap1)
    # first run: news trigger only (no prev price/grade, no price or signal event)
    assert len(events1) == 1 and events1[0].kind == KIND_NEWS_KEYWORD
    assert len(sent) == 1

    # identical state again -> no new events (dedupe via persisted state)
    events2 = engine.process_and_send(snap1)
    assert events2 == []

    # second snapshot with price move + grade change -> spike + signal
    snap2 = AlertEngine.make_snapshot(790.0, "RED", [art])
    events3 = engine.process_and_send(snap2)
    kinds = {e.kind for e in events3}
    assert KIND_PRICE_SPIKE in kinds
    assert KIND_SIGNAL_CHANGE in kinds
    assert sent


def test_disabled_engine_sends_nothing(tmp_path):
    sent = []
    settings_off = {
        "app": {"cache_dir": str(tmp_path)},
        "alerting": {"telegram": {"enabled": False, "bot_token": "", "chat_id": ""}},
    }
    engine = AlertEngine(settings_off, cache_dir=str(tmp_path),
                         sender=lambda text: (sent.append(text) or True))
    snap = AlertEngine.make_snapshot(850.0, "RED", [])
    events = engine.process_and_send(snap)
    assert sent == []


def test_event_html_escaped():
    from src.analysis.alerts import AlertEvent, KIND_PRICE_SPIKE
    ev = AlertEvent(kind=KIND_PRICE_SPIKE, title_ar="<b>خطر</b>", detail_ar=">x&y")
    html_out = ev.to_html()
    # The wrapper <b>..</b> is allowed; the injected tag must be escaped away,
    # and special chars inside the payload text must be HTML-escaped.
    assert html_out.startswith("<b>")
    assert "<b>خطر</b>" not in html_out
    assert "&amp;" in html_out