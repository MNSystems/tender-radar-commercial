"""Поиск открытых закупок Госзакупа по ключевым словам для письма потенциальному клиенту.
Только чтение: ничего не пишет в Supabase, не трогает клиентов, профили и Telegram."""
import argparse, json, os, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

import collector_goszakup as collector
import auto_collect_and_sync_commercial as mapper


def eligible(row, now):
    status = str(row.get("status_name") or "").lower()
    if not ("прием" in status or "приём" in status):
        return False
    try:
        end = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
        return end.tzinfo is not None and end > now
    except (ValueError, TypeError, KeyError):
        return False


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--keywords", required=True, help="Ключевые слова через запятую")
    p.add_argument("--minus", default="", help="Минус-слова через запятую")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--out", default="prospect_result.json")
    a = p.parse_args()
    token = os.environ.get("TRKZ_TEST_GOSZAKUP_TOKEN", "")
    if not token:
        raise ValueError("TRKZ_TEST_GOSZAKUP_TOKEN required")
    words = [w.strip() for w in a.keywords.split(",") if w.strip()]
    minus = [w.strip().lower() for w in a.minus.split(",") if w.strip()]
    collected, failed = [], []
    for w in words:
        try:
            collected.extend(collector.collect_keyword(token, w, a.limit))
        except Exception as exc:
            failed.append(w)
            print(f"WARNING {w}: {exc!r}", file=sys.stderr)
    with tempfile.TemporaryDirectory(prefix="prospect-") as d:
        collector.OUTPUT_DIR = mapper.OUT = Path(d)
        collector.save_json(collector.deduplicate(collected))
        rows = mapper.make_goszakup()
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        if not eligible(r, now):
            continue
        text = " ".join(str(r.get(k) or "") for k in ("title", "description", "customer_name")).lower()
        if minus and any(m in text for m in minus):
            continue
        out.append({k: r.get(k) for k in ("source_lot_id", "title", "description", "amount", "expires_at",
                                          "status_name", "customer_name", "region", "public_url")})
    out.sort(key=lambda r: -(r.get("amount") or 0))
    res = {"keywords": words, "minus": minus, "failed": failed, "collected": len(rows), "open": len(out),
           "generated_at": now.isoformat(), "tenders": out}
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "tenders"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
