"""verify_telegram.py — فاحص اتصال سريع للبوت.

Usage:
    python scripts/verify_telegram.py

يقوم بـ: (1) التحقق من صلاحية التوكن عبر getMe، (2) إرسال رسالة تجريبية إلى chat_id.
إن ظهر "chat not found": افتح https://t.me/thlel_mazot_radar_bot واضغط /start أولًا.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

from src.config import load_settings  # noqa: E402
from src.analysis.alerts import AlertEngine  # noqa: E402


def main() -> int:
    engine = AlertEngine(load_settings())
    if not engine.configured:
        print("configured: False — ضع token/chat_id في .streamlit/secrets.toml أو متغيرات البيئة")
        return 2

    print(f"configured: True | enabled: {engine.enabled}")
    try:
        me = requests.get(f"https://api.telegram.org/bot{engine.bot_token}/getMe", timeout=10).json()
        print("getMe ok:", me.get("ok"), "| bot:", (me.get("result") or {}).get("username"))
    except requests.RequestException as exc:
        print("getMe error:", type(exc).__name__, exc)
        return 3

    ok = engine.send_message(
        "🧪 اختبار الاتصال — ثُلَّ المازوت 🛢️\n"
        "البوت يعمل ووصلت انت الاعتمادات بشكل آمن. 🟢"
    )
    if ok:
        print("DELIVERY: OK ✅")
        return 0
    print("DELIVERY: FAILED ❌")
    print("إن كان السبب 'chat not found': افتح https://t.me/thlel_mazot_radar_bot واضغط /start، ثم أعد التشغيل.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())