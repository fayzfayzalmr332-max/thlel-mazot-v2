"""Open-ended geopolitical news radar for global energy & the Syrian fuel chain.

Design notes
------------
* Fetch layer  : Google News RSS (key-less) + static feeds via feedparser.
* Fusion layer : de-duplication by normalized-title digest, persisted across
  runs through a DiskCache ("news_seen" + "news_articles").
* Tagging layer: keyword taxonomy (EN+AR) -> event families, severity 0-1,
  escalation boosters. The taxonomy is data, not code (``keywords.py``).
* Novelty hook : frequent terms that are NOT in the taxonomy are surfaced as
  *emerging topics* — this makes the mechanism open-ended.
* Pressure map : recency-decayed saturating sum -> Geopolitical Stress Index
  0-100 feeding the sentiment oracle.
"""
from __future__ import annotations

import calendar
import hashlib
import logging
import math
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import feedparser
import pandas as pd
import requests

from ..utils.disk_cache import DiskCache
from .feeds import build_feed_registry
from .keywords import MATCH_GROUPS, SEVERITY_BOOSTERS, STOPWORDS, ARABIC_RE, LATIN_RE

logger = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _norm_key(title: str) -> str:
    flat = re.sub(r"[^a-z0-9\u0600-\u06FF]+", "", title.lower())
    return hashlib.sha1(flat.encode("utf-8")).hexdigest()


def _as_epoch(published_parsed, published: Optional[str]) -> Optional[float]:
    if published_parsed:
        try:
            return float(calendar.timegm(published_parsed))
        except Exception:  # pylint: disable=broad-except
            pass
    if published:
        import datetime as _dt
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%a, %d %b %Y %H:%M:%S %z"):
            try:
                return _dt.datetime.strptime(published, fmt).timestamp()
            except ValueError:
                continue
    return None


class NewsRadar:
    def __init__(self, settings: Dict[str, Any], cache_dir: str | None = None):
        self.settings = settings
        news_cfg = settings.get("news", {})
        self.max_per_feed = int(news_cfg.get("max_items_per_feed", 6))
        self.timeout = float(news_cfg.get("request_timeout", 12))
        self.half_life_hours = float(news_cfg.get("half_life_hours", 36))
        self.seen_ttl_hours = float(news_cfg.get("seen_cache_max_hours", 48))
        app_cfg = settings.get("app", {})
        self.disk = DiskCache(cache_dir or app_cfg.get("cache_dir", ".cache"))
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA})
        self._group_map = {g["group"]: g for g in MATCH_GROUPS}

    def scan(self, force: bool = False) -> Dict[str, Any]:
        """Fetch, fuse, tag and score the news flows. Never raises."""
        feeds = build_feed_registry(self.settings)
        raw, errors = self._fetch_all(feeds)
        merged = self._merge(raw)
        tagged = [self._tag(art) for art in merged]

        if len(tagged) == 0:
            cached = self.disk.get("news_articles", max_age_hours=self.seen_ttl_hours)
            if cached:
                tagged = cached
                mode = "ttl-cache"
            else:
                tagged = synthetic_demo_news()
                mode = "demo"
        else:
            mode = "live"
            self.disk.set("news_articles", tagged)

        index = self.stress_index(tagged)
        emerging = self.emerging_topics(tagged)
        df = self.to_dataframe(tagged)

        return {
            "items": tagged,
            "df": df,
            "stress_index": round(index, 1),
            "emerging": emerging,
            "errors": errors,
            "count": len(tagged),
            "mode": mode,
            "feeds_scanned": len(feeds),
            "ts": time.time(),
        }

    # ---------------------------------------------------------------- fetch

    def _fetch_all(self, feeds: List[Dict[str, str]]) -> Tuple[List[Dict[str, Any]], List[str]]:
        items: List[Dict[str, Any]] = []
        errors: List[str] = []
        for feed in feeds:
            try:
                resp = self.session.get(feed["url"], timeout=self.timeout)
                if resp.status_code != 200:
                    errors.append(f"{feed['label']} -> HTTP {resp.status_code}")
                    continue
                parsed = feedparser.parse(resp.content)
                for entry in parsed.entries[: self.max_per_feed]:
                    title = (entry.get("title") or "").strip()
                    if not title:
                        continue
                    summary = re.sub(r"<[^>]+>", "", entry.get("summary") or "")[:400]
                    ts = _as_epoch(entry.get("published_parsed"), entry.get("published"))
                    items.append({
                        "title": title,
                        "link": entry.get("link") or "",
                        "summary": summary,
                        "published": entry.get("published") or "",
                        "ts": ts,
                        "source": feed["label"],
                        "kind": feed["kind"],
                    })
            except Exception as exc:  # pylint: disable=broad-except
                errors.append(f"{feed['label']} -> {type(exc).__name__}: {exc}")
        return items, errors

    def _merge(self, raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = self.disk.get("news_seen", max_age_hours=self.seen_ttl_hours) or {}
        out: List[Dict[str, Any]] = []
        for art in raw:
            key = _norm_key(art["title"])
            known_ts = seen.get(key)
            if known_ts and (time.time() - float(known_ts)) < self.seen_ttl_hours * 3600:
                continue  # already covered recently
            seen[key] = art["ts"] or time.time()
            out.append(art)
            if len(out) >= 400:
                break
        self.disk.set("news_seen", dict(list(seen.items())[-3000:]))
        return out

    # ------------------------------------------------------------------- tag

    def _tag(self, art: Dict[str, Any]) -> Dict[str, Any]:
        text = f"{art.get('title', '')} {art.get('summary', '')}".lower()
        matched: List[Dict[str, Any]] = []
        for group in MATCH_GROUPS:
            if any(term.lower() in text for term in group["terms"]):
                matched.append(group)
        severity = float(max((g["weight"] for g in matched), default=0.35))
        boosted = False
        if any(b.lower() in text for b in SEVERITY_BOOSTERS):
            severity = min(1.0, severity + 0.18)
            boosted = True
        return {
            **art,
            "group_codes": [g["group"] for g in matched],
            "labels_ar": [g["label_ar"] for g in matched] or ["عام/مراقبة"],
            "severity": round(severity, 3),
            "boosted": boosted,
        }

    # -------------------------------------------------------------- pressure

    def stress_index(self, tagged: List[Dict[str, Any]], half_life_hours: Optional[float] = None) -> float:
        half_life = half_life_hours or self.half_life_hours
        now = time.time()
        total = 0.0
        for art in tagged:
            ts = art.get("ts")
            if ts:
                age_h = max(0.0, (now - float(ts)) / 3600.0)
            else:
                age_h = 0.0
            decay = 0.5 ** (age_h / half_life)
            total += float(art.get("severity", 0.35)) * decay
        score = 100.0 * (1.0 - math.exp(-0.22 * total))
        return float(min(100.0, max(0.0, score)))

    # ------------------------------------------------------- emerging topics

    def emerging_topics(self, tagged: List[Dict[str, Any]], min_freq: int = 2) -> List[Dict[str, Any]]:
        """Terms appearing often but absent from the taxonomy => open-ended hook."""
        known = {t.lower() for g in MATCH_GROUPS for t in g["terms"]}
        known |= STOPWORDS
        freq: Dict[str, int] = {}
        for art in tagged:
            title = art.get("title") or ""
            for tok in LATIN_RE.findall(title.lower()):
                if tok in known or tok in STOPWORDS:
                    continue
                freq[tok] = freq.get(tok, 0) + 1
            for tok in ARABIC_RE.findall(title):
                if tok in known or tok in STOPWORDS:
                    continue
                freq[tok] = freq.get(tok, 0) + 1
        ranked = sorted(
            ({"topic": t, "freq": c} for t, c in freq.items() if c >= min_freq),
            key=lambda r: (-r["freq"], r["topic"]),
        )
        return ranked[:12]

    # ------------------------------------------------------------- dataframe

    def to_dataframe(self, tagged: List[Dict[str, Any]]) -> pd.DataFrame:
        rows = []
        for art in tagged:
            ts = art.get("ts")
            when = pd.to_datetime(ts, unit="s", utc=True).tz_convert("Asia/Damascus").strftime("%d/%m %H:%M") if ts else (art.get("published") or "—")
            rows.append({
                "الوقت (دمشق)": when,
                "المصدر": art.get("source", "—"),
                "العنوان": art.get("title", "—"),
                "الفئة": "، ".join(art.get("labels_ar", ["عام/مراقبة"])),
                "الشدة": art.get("severity", 0.0),
                "رابط": art.get("link", ""),
                "_ts": ts,
            })
        df = pd.DataFrame(rows)
        if len(df):
            df = df.sort_values("_ts", ascending=False, na_position="last").drop(columns=["_ts"])
        return df


def synthetic_demo_news() -> List[Dict[str, Any]]:
    """Curated scenario headlines (DEMO mode) so the radar stays alive offline."""
    now = time.time()
    hour = 3600.0

    def art(title, summary, link, age_h, labels, severity, boost=True):
        return {
            "title": title,
            "link": link,
            "summary": summary,
            "published": "",
            "ts": now - age_h * hour,
            "source": "DEMO — سيناريو تدريبي",
            "kind": "demo",
            "group_codes": [],
            "labels_ar": labels,
            "severity": severity,
            "boosted": boost,
        }

    return [
        art("تذبذب أسعار الغازويل الآجلة في لندن قبيل موسم التدفئة",
            "سجلت عقود الغازويل الآجلة حركة متقلبة مدفوعة بتوقعات الطلب الشتوي وآفاق الإمداد.",
            "https://example.invalid/demo-1", 3,
            ["الطلب الموسمي/التدفئة"], 0.45),
        art("أعمال صيانة في مصفاة بانياس تؤثر على توفر المازوت محليًا",
            "أعلنت إدارة المصفاة خفض الإنتاج مؤقتًا لصيانة خطوط الإنتاج بعد توقف جزئي للوحدات، ما يضغط على العرض المحلي.",
            "https://example.invalid/demo-2", 8,
            ["عمليات المصافي (بانياس/حمص)"], 0.85, boost=True),
        art("قرار تسعير رسمي جديد للمحروقات في سوريا يدخل حيز التنفيذ",
            "صدر قرار بتعديل أسعار المازوت والبنزين وفق معادلة التسعير الجديدة اعتبارًا من بداية الشهر.",
            "https://example.invalid/demo-3", 26,
            ["قرارات/تسعيرة محروقات رسمية"], 0.80),
        art("تقارير عن توتر في مضيق هرمز وسط تنقل مكثف للناقلات",
            "أشارت بيانات ملاحية إلى إعادة توجيه ناقلات وتصعيد احتمالي في مضيق هرمز قد يرفع أقساط التأمين.",
            "https://example.invalid/demo-4", 12,
            ["مضيق هرمز/الملاحة البحرية"], 0.92, boost=True),
        art("السوق الموازي: الليرة السورية تتراجع وسط ضغوط الطلب على الدولار",
            "سجل سعر الصرف في السوق الموازية ارتفاعًا جديدًا مقابل الليرة، ما يرفع تكلفة الاستيراد.",
            "https://example.invalid/demo-5", 18,
            ["سعر الصرف/التضخم"], 0.62),
        art("تحديثات العقوبات تشمل تأمين الشحنات الموجهة لموانئ المنطقة",
            "أعلن مسؤولون عن إجراءات إضافية تتعلق بالتأمين والتحويلات المالية لتجارة الطاقة الإقليمية.",
            "https://example.invalid/demo-6", 30,
            ["عقوبات/تمويل"], 0.70),
    ]