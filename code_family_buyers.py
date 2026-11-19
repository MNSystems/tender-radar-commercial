"""Покупатели работ по семейству кодов ЕНС ТРУ (только чтение).

1) перебирает коды-кандидаты по префиксам, оставляет существующие (есть договоры);
2) договоры за N месяцев -> заказчики (CF_CUSTOMER), подрядчики (CF_SUPPLIER), крупные проекты (CF_PROJECT);
3) открытые лоты по фразам, отфильтрованные по этим кодам (CF_OPEN).
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
            r = requests.get(BASE + path, params=params, headers=z.HEADERS, timeout=(20, 60))
            if r.status_code == 200:
                return r.json()
            last = RuntimeError(f"HTTP {r.status_code} {r.text[:200]}")
            if r.status_code == 400:
                raise last
        except requests.RequestException as e:
            last = e
        time.sleep(5 + i * 8)
    raise last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefixes", required=True, help="422123.200,429110.000")
    ap.add_argument("--phrases", default="")
    ap.add_argument("--months", type=int, default=24)
    ap.add_argument("--maxn", type=int, default=30)
    a = ap.parse_args()
    since = (datetime.now(timezone.utc) - timedelta(days=30 * a.months)).date().isoformat()
    now = datetime.now(timezone.utc)
    codes = []
    for pre in [p.strip() for p in a.prefixes.split(",") if p.strip()]:
        miss = 0
        for n in range(0, a.maxn):
            c = f"{pre}.{n:06d}"
            cnt = get("/contracts/", {"enstru_code": c, "limit": 1}).get("count") or 0
            time.sleep(0.2)
            if cnt:
                codes.append(c); miss = 0
                print("CF_CODE " + json.dumps({"code": c, "all_contracts": cnt}))
            else:
                miss += 1
                if miss >= 8 and n > 10:
                    break
    cust = defaultdict(lambda: {"n": 0, "sum": 0.0, "last": "", "sup": Counter()})
    supp = defaultdict(lambda: {"n": 0, "sum": 0.0, "last": "", "cust": Counter()})
    projects = []
    for c in codes:
        for off in range(0, 3000, 100):
            res = get("/contracts/", {"enstru_code": c, "sign_date__gte": since, "ordering": "-sign_date", "limit": 100, "offset": off}).get("results") or []
            for k in res:
                cn = k.get("customer_organization_name") or ""; sn = k.get("supplier_organization_name") or ""
                p = float(k.get("contract_price_with_vat") or 0); d = k.get("sign_date") or ""
                x = cust[cn]; x["n"] += 1; x["sum"] += p; x["last"] = max(x["last"], d); x["sup"][sn] += 1
                y = supp[sn]; y["n"] += 1; y["sum"] += p; y["last"] = max(y["last"], d); y["cust"][cn] += 1; y["id"] = k.get("supplier_organization_id")
                projects.append({"code": c, "customer": cn, "supplier": sn, "sum": round(p), "date": d,
                                 "name": k.get("announcement_name") or "", "type": k.get("contract_type_name")})
            time.sleep(0.3)
            if len(res) < 100:
                break
    for cn, x in sorted(cust.items(), key=lambda kv: -kv[1]["sum"]):
        print("CF_CUSTOMER " + json.dumps({"customer": cn, "n": x["n"], "sum": round(x["sum"]), "last": x["last"],
                                           "suppliers": [s for s, _ in x["sup"].most_common(3)]}, ensure_ascii=False))
    for sn, y in sorted(supp.items(), key=lambda kv: -kv[1]["sum"]):
        print("CF_SUPPLIER " + json.dumps({"supplier": sn, "id": y.get("id"), "n": y["n"], "sum": round(y["sum"]), "last": y["last"],
                                           "customers": [s for s, _ in y["cust"].most_common(3)]}, ensure_ascii=False))
    for p in sorted(projects, key=lambda p: -p["sum"])[:150]:
        print("CF_PROJECT " + json.dumps(p, ensure_ascii=False))
    # открытые лоты
    cs = set(codes); pre = tuple(p.strip() for p in a.prefixes.split(","))
    seen = set()
    for ph in [p.strip() for p in a.phrases.split(",") if p.strip()]:
        for off in range(0, 500, 100):
            res = get("/lots/", {"q": ph, "limit": 100, "offset": off}).get("results") or []
            for lot in res:
                st = (lot.get("status") or {}).get("id")
                ec = [e.get("code") or "" for e in lot.get("enstrus") or []]
                if not (st in z.ACTIVE_STATUS_IDS and z._future(lot.get("offer_end_date"), now)):
                    continue
                if not any(c in cs or c.startswith(pre) for c in ec):
                    continue
                if lot.get("id") in seen:
                    continue
                seen.add(lot.get("id"))
                r = z.to_record(lot, ph)
                print("CF_OPEN " + json.dumps({"customer": r["customer_name"], "title": r["title"], "ann": lot.get("announcement_name_ru"),
                                               "amount": r["amount_kzt"], "end": r["end_date"], "url": r["public_url"],
                                               "system": (lot.get("system") or {}).get("name"), "codes": ec}, ensure_ascii=False))
            time.sleep(0.4)
            if len(res) < 100:
                break
    print("SUMMARY " + json.dumps({"codes": codes, "customers": len(cust), "suppliers": len(supp), "contracts": len(projects), "open": len(seen)}))


if __name__ == "__main__":
    main()
