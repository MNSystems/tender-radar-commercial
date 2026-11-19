"""Поиск покупателей товара (только чтение, ничего не пишет в базу).

Источник: открытый API zakup.gov.kz (Госзакуп, Mitwork, Самрук и др.).
По ключевым словам:
  1) открытые сейчас лоты  -> BUYER_OPEN {json}
  2) коды товара (ЕНС ТРУ) из найденных лотов
  3) договоры по этим кодам за N месяцев -> агрегаты:
       BUYER_REGULAR {json}  - заказчики: сколько раз покупали, на сколько, когда последний раз
       BUYER_SUPPLIER {json} - поставщики, выигравшие такие договоры (они сами закупают товар для поставки)
"""
import argparse, json, time
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import requests
import collector_zakup as z

BASE = "https://zakup.gov.kz/api/core/api/public"


def get(path, params, attempts=7):
    last = None
    for i in range(attempts):
        try:
            r = requests.get(BASE + path, params=params, timeout=40)
            if r.status_code == 200:
                return r.json()
            last = RuntimeError(f"HTTP {r.status_code} {r.text[:200]}")
        except Exception as e:  # сеть
            last = e
        time.sleep(5 + i * 10)
    raise last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", required=True)
    ap.add_argument("--minus", default="")
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--max_codes", type=int, default=6)
    ap.add_argument("--max_contracts", type=int, default=3000)
    a = ap.parse_args()
    kws = [k.strip() for k in a.keywords.split(",") if k.strip()]
    minus = [m.strip().lower() for m in a.minus.split(",") if m.strip()]
    stems = [z.stem(k.lower()) for k in kws]
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=30 * a.months)).date().isoformat()

    # 1-2. лоты: открытые сейчас + коды товара
    codes = Counter()
    code_names = {}
    open_rows = {}
    for kw in kws:
        for off in range(0, 600, 100):
            page = get("/lots/", {"q": kw, "limit": 100, "offset": off})
            res = page.get("results") or []
            for lot in res:
                rec = z.to_record(lot, kw)
                text = z.text_of(rec)
                if any(m in text for m in minus):
                    continue
                for e in lot.get("enstrus") or []:
                    nm = (e.get("name_ru") or "").lower()
                    if any(s in nm for s in stems) and not any(m in nm for m in minus):
                        codes[e.get("code")] += 1
                        code_names[e.get("code")] = f'{e.get("name_ru")} ({e.get("short_description_ru") or ""})'
                st = (lot.get("status") or {}).get("id")
                if st in z.ACTIVE_STATUS_IDS and z._future(lot.get("offer_end_date"), now):
                    rec["system"] = (lot.get("system") or {}).get("name")
                    open_rows[rec["external_id"]] = rec
            time.sleep(0.5)
            if len(res) < 100:
                break
    keep = ("title", "customer_name", "customer_bin", "region", "amount_kzt", "quantity",
            "publish_date", "end_date", "status", "trade_method", "public_url", "keyword", "system")
    for r in open_rows.values():
        print("BUYER_OPEN " + json.dumps({k: r.get(k) for k in keep}, ensure_ascii=False))
    top = [c for c, _ in codes.most_common(a.max_codes) if c]
    for c in top:
        print("BUYER_CODE " + json.dumps({"code": c, "name": code_names.get(c), "lots": codes[c]}, ensure_ascii=False))

    # 3. договоры по кодам
    cust = defaultdict(lambda: {"n": 0, "sum": 0.0, "last": "", "suppliers": Counter(), "codes": set()})
    supp = defaultdict(lambda: {"n": 0, "sum": 0.0, "last": "", "customers": Counter()})
    total = 0
    for c in top:
        got = 0
        for off in range(0, a.max_contracts, 100):
            page = get("/contracts/", {"enstru_code": c, "sign_date__gte": since,
                                       "ordering": "-sign_date", "limit": 100, "offset": off})
            res = page.get("results") or []
            for k in res:
                cn = k.get("customer_organization_name") or ""
                sn = k.get("supplier_organization_name") or ""
                price = float(k.get("contract_price_with_vat") or 0)
                d = k.get("sign_date") or ""
                x = cust[cn]; x["n"] += 1; x["sum"] += price; x["last"] = max(x["last"], d)
                x["suppliers"][sn] += 1; x["codes"].add(c)
                y = supp[sn]; y["n"] += 1; y["sum"] += price; y["last"] = max(y["last"], d)
                y["customers"][cn] += 1
                y["id"] = k.get("supplier_organization_id")
            got += len(res)
            time.sleep(0.4)
            if len(res) < 100:
                break
        total += got
        print("BUYER_CODE_CONTRACTS " + json.dumps({"code": c, "contracts": got}))
    for cn, x in sorted(cust.items(), key=lambda kv: (-kv[1]["n"], -kv[1]["sum"])):
        print("BUYER_REGULAR " + json.dumps({"customer": cn, "contracts": x["n"], "sum": round(x["sum"]),
                                             "last": x["last"], "top_supplier": x["suppliers"].most_common(1)[0][0] if x["suppliers"] else ""},
                                            ensure_ascii=False))
    for sn, y in sorted(supp.items(), key=lambda kv: (-kv[1]["n"], -kv[1]["sum"])):
        print("BUYER_SUPPLIER " + json.dumps({"supplier": sn, "supplier_id": y.get("id"), "contracts": y["n"], "sum": round(y["sum"]),
                                              "last": y["last"], "customers": len(y["customers"])}, ensure_ascii=False))
    print("SUMMARY " + json.dumps({"open": len(open_rows), "codes": top, "contracts": total,
                                   "customers": len(cust), "suppliers": len(supp), "since": since}, ensure_ascii=False))


if __name__ == "__main__":
    main()
