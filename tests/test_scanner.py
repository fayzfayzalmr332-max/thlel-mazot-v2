"""Offline tests for the news radar (pure tagging/scoring paths only)."""
from __future__ import annotations

from src.config import load_settings
from src.news.scanner import NewsRadar, _norm_key, synthetic_demo_news


def _radar():
    return NewsRadar(load_settings())


def test_norm_key_dedupes_titles():
    assert _norm_key("  سعر المازوت! اليوم ") == _norm_key("سعر المازوت اليوم")
    assert _norm_key("عنوان أ") != _norm_key("عنوان ب")


def test_demo_news_tags_baniyas():
    radar = _radar()
    tagged = [radar._tag(a) for a in synthetic_demo_news()]  # pylint: disable=protected-access
    baniyas = next(a for a in tagged if "بانياس" in a["title"])
    assert any("مصفاة" in label or "مصافي" in label for label in baniyas["labels_ar"]), baniyas["labels_ar"]
    assert baniyas["severity"] >= 0.7
    assert baniyas["boosted"] is True


def test_stress_index_in_bounds():
    radar = _radar()
    tagged = [radar._tag(a) for a in synthetic_demo_news()]  # pylint: disable=protected-access
    idx = radar.stress_index(tagged)
    assert 0.0 <= idx <= 100.0


def test_stress_index_monotonic_with_more_events():
    radar = _radar()
    tagged = [radar._tag(a) for a in synthetic_demo_news()]  # pylint: disable=protected-access
    single = radar.stress_index(tagged[:2])
    double = radar.stress_index(tagged[:4])
    assert double >= single


def test_emerging_topics_returns_list():
    radar = _radar()
    tagged = [radar._tag(a) for a in synthetic_demo_news()]  # pylint: disable=protected-access
    topics = radar.emerging_topics(tagged, min_freq=1)
    assert isinstance(topics, list)
    if topics:
        assert "topic" in topics[0] and "freq" in topics[0]


def test_to_dataframe_shape():
    radar = _radar()
    tagged = [radar._tag(a) for a in synthetic_demo_news()]  # pylint: disable=protected-access
    df = radar.to_dataframe(tagged)
    assert {"الوقت (دمشق)", "العنوان", "الفئة", "الشدة", "رابط", "المصدر"} <= set(df.columns)
    assert len(df) == len(tagged)