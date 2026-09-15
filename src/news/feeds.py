"""Feed registry builder — Google News RSS (primary) + optional static feeds.

Google News is dependable and key-less; its RSS queries return both global and
Arabic coverage for our geo key phrases. The registry is data-driven from
``config/settings.yaml`` (``news.google_queries`` + ``news.static_feeds``), so
adding a feed never requires code changes.
"""
from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import quote_plus


def google_news_url(query: str, hl: str = "en-US", gl: str = "US") -> str:
    lang = (hl or "en-US").split("-")[0]
    ceid = f"{gl}:{lang}"
    base = "https://news.google.com/rss/search"
    return f"{base}?q={quote_plus(query)}&hl={hl}&gl={gl}&ceid={ceid}"


def build_feed_registry(settings: Dict[str, Any]) -> List[Dict[str, str]]:
    news_cfg = settings.get("news", {})
    hl = news_cfg.get("google_news_hl", "en-US")
    gl = news_cfg.get("google_news_gl", "US")

    feeds = []
    for query in news_cfg.get("google_queries", []):
        feeds.append(
            {
                "url": google_news_url(query, hl=hl, gl=gl),
                "label": f"بحث: {query[:48]}",
                "kind": "google",
            }
        )
    # Arabic-language mirrors of the same themes (config-driven, lean fallback).
    ar_queries = news_cfg.get(
        "ar_queries",
        [
            "سعر المازوت سوريا",
            "مصفاة بانياس",
            "مضيق هرمز ناقلات النفط",
        ],
    )
    for query in ar_queries:
        feeds.append(
            {
                "url": google_news_url(query, hl="ar", gl="US"),
                "label": f"بحث عربي: {query}",
                "kind": "google-ar",
            }
        )

    for item in news_cfg.get("static_feeds", []):
        feeds.append(
            {
                "url": item["url"],
                "label": item.get("label", "خلاصة إخبارية"),
                "kind": "static",
            }
        )
    return feeds