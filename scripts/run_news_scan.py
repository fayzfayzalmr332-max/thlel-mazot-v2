"""CLI news scan — cron-friendly background refresh of the geopolitical radar.

Usage:
    python scripts/run_news_scan.py [--force] [--out-dir data/reports]

Writes a CSV snapshot of tagged headlines plus a tiny machine-readable
``news_metrics.json`` (stress index / mode / timestamp) that other tooling
(e.g. dashboards, alerters) can consume.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_settings  # noqa: E402
from src.news.scanner import NewsRadar  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="force a fresh fetch")
    parser.add_argument("--out-dir", default=str(ROOT / "data" / "reports"))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    settings = load_settings()
    radar = NewsRadar(settings)
    t0 = time.time()
    result = radar.scan(force=args.force)
    elapsed = time.time() - t0

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    df = result["df"]
    csv_path = out_dir / f"news_snapshot_{stamp}.csv"
    if len(df):
        df.to_csv(csv_path, index=False)

    metrics_path = out_dir / "news_metrics.json"
    metrics_prev = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
    metrics_prev.update({
        "stress_index": result["stress_index"],
        "mode": result["mode"],
        "count": result["count"],
        "emerging_topics": [t["topic"] for t in result["emerging"]],
        "ts": time.time(),
    })
    metrics_path.write_text(json.dumps(metrics_prev, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.quiet:
        print(f"[news-scan] mode={result['mode']} stress={result['stress_index']}/100 "
              f"items={result['count']} feeds={result['feeds_scanned']} in {elapsed:.1f}s")
        if result["emerging"]:
            print("[news-scan] emerging:", ", ".join(t["topic"] for t in result["emerging"][:6]))
        if result["errors"]:
            print("[news-scan] feed errors:", "; ".join(result["errors"][:5]))
        if len(df):
            print(f"[news-scan] csv -> {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())