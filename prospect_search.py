"""Поиск закупок для писем (только чтение, ничего не пишет в базу).
Источник: открытый API zakup.gov.kz. Печатает строки PROSPECT_LOT {json}:
и открытые сейчас лоты, и недавние (любой статус) — чтобы видеть покупателей."""
import argparse, json, time
from datetime import datetime, timezone
import collector_zakup as z

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", required=True)
    ap.add_argument("--minus", default="")
    ap.add_argument("--recent", type=int, default=400, help="сколько последних лотов любого статуса брать на слово")
    a = ap.parse_args()
    kws = [k.strip() for k in a.keywords.split(",") if k.strip()]
    minus = [m.strip().lower() for m in a.minus.split(",") if m.strip()]
    now = datetime.now(timezone.utc)
    seen = {}
    for kw in kws:
        for off in range(0, a.recent, z.PAGE_SIZE):
            page = z._get({"q": kw, "limit": z.PAGE_SIZE, "offset": off})
            res = page.get("results") or []
            for lot in res:
                rec = z.to_record(lot, kw)
                text = z.text_of(rec)
                if any(m in text for m in minus):
                    continue
                rec["open_now"] = (lot.get("status") or {}).get("id") in z.ACTIVE_STATUS_IDS and z._future(lot.get("offer_end_date"), now)
                seen.setdefault(rec["external_id"], rec)
            time.sleep(z.PAUSE_SECONDS)
            if len(res) < z.PAGE_SIZE:
                break
    keep = ("external_id","title","description","customer_name","customer_bin","region","amount_kzt","quantity",
            "publish_date","end_date","status","trade_method","public_url","keyword","open_now")
    for r in seen.values():
        print("PROSPECT_LOT " + json.dumps({k: r.get(k) for k in keep}, ensure_ascii=False))
    print("SUMMARY " + json.dumps({"lots": len(seen), "open_now": sum(r["open_now"] for r in seen.values())}))

if __name__ == "__main__":
    main()
