"""Поиск закупок для писем (только чтение, ничего не пишет в базу).
Источник: открытый API zakup.gov.kz. Печатает строки PROSPECT_LOT {json}:
и открытые сейчас лоты, и недавние (любой статус) — чтобы видеть покупателей."""
import argparse, json, time
from datetime import datetime, timezone
import collector_zakup as z

def probe(kw):
    """Разведка: какие поля есть у лота и есть ли данные о победителе/договоре."""
    page = z._get({"q": kw, "limit": 50, "offset": 0})
    res = page.get("results") or []
    print("PROBE_PAGE_KEYS", sorted(page.keys()))
    if res:
        print("PROBE_LOT_KEYS", sorted(res[0].keys()))
        print("PROBE_LOT_SAMPLE", json.dumps(res[0], ensure_ascii=False)[:3000])
    stats = {}
    for lot in res:
        st = lot.get("status") or {}
        stats[f'{st.get("id")}:{st.get("name") or lot.get("status_name")}'] = stats.get(f'{st.get("id")}:{st.get("name") or lot.get("status_name")}', 0) + 1
    print("PROBE_STATUSES", json.dumps(stats, ensure_ascii=False))
    done = [l for l in res if (l.get("status") or {}).get("id") not in z.ACTIVE_STATUS_IDS]
    base = "https://zakup.gov.kz/api/core/api/public"
    for l in done[:2]:
        for path in (f"/lots/{l.get('id')}/", f"/lots/{l.get('id')}/winners/", f"/lots/{l.get('id')}/contracts/"):
            try:
                r = z.SESSION.get(base + path, timeout=30) if hasattr(z, "SESSION") else __import__("requests").get(base + path, timeout=30)
                print("PROBE_GET", path, r.status_code, r.text[:1500].replace("\n", " "))
            except Exception as e:
                print("PROBE_GET", path, "ERR", e)
    import requests
    for params in ({"limit": 2}, {"limit": 2, "search": kw}, {"limit": 2, "name": kw}, {"limit": 2, "lot_id": done[0].get("id") if done else 0}):
        try:
            r = requests.get(base + "/contracts/", params=params, timeout=30)
            print("PROBE_CONTRACTS", json.dumps(params, ensure_ascii=False), r.status_code, r.text[:2500].replace("\n", " "))
        except Exception as e:
            print("PROBE_CONTRACTS", params, "ERR", e)
    try:
        r = requests.options(base + "/contracts/", timeout=30)
        print("PROBE_OPTIONS", r.status_code, r.text[:2000])
    except Exception as e:
        print("PROBE_OPTIONS ERR", e)
    for path in ():
        try:
            r = requests.get(base + path, params={"q": kw, "limit": 2}, timeout=30)
            print("PROBE_LIST", path, r.status_code, r.text[:1500].replace("\n", " "))
        except Exception as e:
            print("PROBE_LIST", path, "ERR", e)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", required=True)
    ap.add_argument("--minus", default="")
    ap.add_argument("--recent", type=int, default=400, help="сколько последних лотов любого статуса брать на слово")
    ap.add_argument("--probe", action="store_true")
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
                rec["system"] = lot.get("system_id") or (lot.get("system") or {}).get("id") if isinstance(lot.get("system"), dict) else lot.get("system_id") or lot.get("system")
                rec["status_id"] = (lot.get("status") or {}).get("id")
                rec["open_now"] = (lot.get("status") or {}).get("id") in z.ACTIVE_STATUS_IDS and z._future(lot.get("offer_end_date"), now)
                seen.setdefault(rec["external_id"], rec)
            time.sleep(z.PAUSE_SECONDS)
            if len(res) < z.PAGE_SIZE:
                break
    keep = ("external_id","title","description","customer_name","customer_bin","region","amount_kzt","quantity",
            "publish_date","end_date","status","status_id","trade_method","public_url","keyword","open_now","system")
    for r in seen.values():
        print("PROSPECT_LOT " + json.dumps({k: r.get(k) for k in keep}, ensure_ascii=False))
    if a.probe:
        probe(kws[0])
    print("SUMMARY " + json.dumps({"lots": len(seen), "open_now": sum(r["open_now"] for r in seen.values())}))

if __name__ == "__main__":
    main()
