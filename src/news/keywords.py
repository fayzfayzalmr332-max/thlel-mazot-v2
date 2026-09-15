"""Keyword taxonomy + stopwords for the open-ended geopolitical news scanner.

Each *group* describes a real-world event family that matters for Syrian fuel
supply & pricing. Weight feeds the severity model. ``boost`` terms escalate an
already-matched article (reported outage/attack etc.).

NOVELTY: the scanner also mines terms that appear frequently but are NOT in
this taxonomy, surfacing "emerging topics" for analyst review — this is the
open-ended extension hook of the system.
"""
from __future__ import annotations

MATCH_GROUPS = [
    {
        "group": "SUPPLY_CRUNCH",
        "label_ar": "أزمة/انقطاع إمدادات",
        "weight": 0.95,
        "color": "#ef4444",
        "terms": [
            "supply disruption", "shortage", "halted", "halt", "shutdown",
            "outage", "blockade", "disruption", "shortfall", "crisis",
            "نقص", "أزمة", "انقطاع", "توقف", "إضراب", "حظر", "عجز",
        ],
        "boost": ["attack", "explosion", "fire", "قصف", "هجوم", "حريق", "تفجير", "احتراق"],
    },
    {
        "group": "MARITIME_HORMUZ",
        "label_ar": "مضيق هرمز/الملاحة البحرية",
        "weight": 0.90,
        "color": "#f97316",
        "terms": [
            "hormuz", "strait of hormuz", "tanker", "tankers", "maritime",
            "shipping lane", "suez", "red sea", "bab el-mandeb",
            "مضيق هرمز", "مضيق", "ناقلات", "الملاحة", "السفن", "البحر الأحمر", "قناة السويس",
        ],
        "boost": ["seized", "attacked", "struck", "أوقف", "احتُجز", "قصف", "هجوم"],
    },
    {
        "group": "REFINERY_OPS",
        "label_ar": "عمليات المصافي (بانياس/حمص)",
        "weight": 0.75,
        "color": "#f5c04a",
        "terms": [
            "baniyas", "banias", "homs refinery", "refinery", "refining",
            "maintenance", "catalyst", "crude unit", "mazot production",
            "بانياس", "مصفاة", "مصفاة بانياس", "مصفاة حمص", "حمص", "صيانة", "تشغيل", "توقفت المصافي",
        ],
        "boost": ["broken", "destroyed", "halted", "fire", "تعطلت", "حريق", "دُمّر", "توقفت"],
    },
    {
        "group": "PRICE_DECREE",
        "label_ar": "قرارات/تسعيرة محروقات رسمية",
        "weight": 0.85,
        "color": "#a78bfa",
        "terms": [
            "price decree", "fuel prices", "price adjustment", "mazot price",
            "diesel price", "petroleum ministry", "price hike", "raise prices", "subsidy",
            "سعر المازوت", "أسعار المحروقات", "تسعيرة", "قرار رفع", "وزارة النفط",
            "المازوت", "الدفعة", "الدعم", "رفع الأسعار", "تعديل الأسعار",
        ],
        "boost": [],
    },
    {
        "group": "SANCTIONS_FINANCE",
        "label_ar": "عقوبات/تمويل",
        "weight": 0.70,
        "color": "#6366f1",
        "terms": [
            "sanctions", "ofac", "embargo", "blacklist", "transaction ban",
            "funding", "cash", "reserves",
            "عقوبات", "الحظر", "الحجز", "التجميد", "سيولة", "المصرف المركزي",
        ],
        "boost": ["onega", "imposed", "added to", "فرضت", "أُضيفت"],
    },
    {
        "group": "FX_INFLATION",
        "label_ar": "سعر الصرف/التضخم",
        "weight": 0.55,
        "color": "#22d3ee",
        "terms": [
            "syrian pound", "exchange rate", "lira", "inflation",
            "الليرة", "سعر الصرف", "التضخم", "ارتفاع الدولار", "سعر الدولار",
        ],
        "boost": ["plunge", "record low", "انهيار", "قفزة"],
    },
    {
        "group": "DEMAND_SEASON",
        "label_ar": "الطلب الموسمي/التدفئة",
        "weight": 0.40,
        "color": "#34d399",
        "terms": [
            "heating season", "winter demand", "cold snap", "consumption",
            "demand", "stockpile", "inventories",
            "موسم التدفئة", "الطلب", "الشتاء", "البرودة", "المخزون", "الاستهلاك",
        ],
        "boost": [],
    },
]

# Words that escalate the severity of ANY matched article.
SEVERITY_BOOSTERS = [
    "halted", "shutdown", "explosion", "attacked", "fire", "strike",
    "blockade", "emergency", "seized", "destroyed", "crash",
    "توقف", "حريق", "قصف", "هجوم", "تفجير", "إغلاق", "تعطل", "انفجار", "احتجاز", "دُمّر",
]

# Stopwords for the emerging-topic engine.
STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "over", "after",
    "before", "during", "report", "reports", "news", "new", "said", "says", "syria",
    "syrian", "fuel", "oil", "prices", "price", "minister", "ministry", "against",
    "amid", "week", "year", "today", "latest", "update", "watch", "video", "biden",
    "trump", "pompeo", "g7", "opec", "iea", "eia",
    "com", "org", "net", "www", "http", "https", "rss", "html",
    "مازوت", "المازوت", "محروقات", "النفط", "سوريا", "لطرق", "بأن", "التي", "الذي",
    "مصدر", "حسب", "وأكد", "أكد", "قال", "ذكر", "أمس", "اليوم", "بشأن", "الأسعار",
}

# Arabic/non-informative single tokens filtered from topic mining.
NON_WORDS = re_compile = None  # placeholder keeps imports light
import re as _re

ARABIC_RE = _re.compile(r"[\u0600-\u06FF]{3,}")
LATIN_RE = _re.compile(r"[A-Za-z]{3,}")