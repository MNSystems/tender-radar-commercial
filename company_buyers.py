"""Покупатели для конкретной компании (только чтение).

Вход: id организаций (как в списке победителей) + названия для сверки.
Для каждой: её договоры как поставщика -> чем занимается (коды ЕНС ТРУ, названия),
кто у неё покупал; затем по её главным кодам — кто ещё покупает это же (новые покупатели)
и какие лоты открыты сейчас.
Печатает строки CB_* {json}.
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
            last = RuntimeError(f"HTTP {r.status_code} {r.text[:300]}")
            if r.status_code == 400:
                raise last
        except requests.RequestException as e:
            last = e
        time.sleep(5 + i * 8)
    raise last


def contracts(params, cap):
    out = []
    for off in range(0, cap, 100):
        p = dict(params, limit=100, offset=off, ordering="-sign_date")
        res = get("/contracts/", p).get("results") or []
        out += res
        time.sleep(0.3)
        if len(res) < 100:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", required=True, help="id:название;id:название")
    ap.add_argument("--months", type=int, default=24)
    a = ap.parse_args()
    since = (datetime.now(timezone.utc) - timedelta(days=30 * a.months)).date().isoformat()
    now = datetime.now(timezone.utc)
    for part in a.ids.split(";"):
        if not part.strip():
            continue
        oid, _, name = part.partition(":")
        own = contracts({"supplier_organization_id": oid.strip(), "sign_date__gte": since}, 1500)
        sname = own[0].get("supplier_organization_name") if own else ""
        print("CB_COMPANY " + json.dumps({"id": oid, "expected": name, "found_name": sname, "contracts": len(own)}, ensure_ascii=False))
        if not own:
            continue
        codes = Counter()
        cust = defaultdict(lambda: {"n": 0, "sum": 0.0, "last": ""})
        names = Counter()
        for k in own:
            for c in k.get("enstru_code") or []:
                codes[c] += 1
            cn = k.get("customer_organization_name") or ""
            x = cust[cn]; x["n"] += 1; x["sum"] += float(k.get("contract_price_with_vat") or 0); x["last"] = max(x["last"], k.get("sign_date") or "")
            if k.get("announcement_name"):
                names[k["announcement_name"]] += 1
        print("CB_TOTAL " + json.dumps({"id": oid, "sum": round(sum(float(k.get("contract_price_with_vat") or 0) for k in own)),
                                        "customers": len(cust), "methods": Counter(k.get("purchase_method_name") for k in own).most_common(4)}, ensure_ascii=False))
        for nm, n in names.most_common(12):
            print("CB_WHAT " + json.dumps({"id": oid, "name": nm, "n": n}, ensure_ascii=False))
        for c, n in codes.most_common(8):
            print("CB_CODE " + json.dumps({"id": oid, "code": c, "n": n}, ensure_ascii=False))
        for cn, x in sorted(cust.items(), key=lambda kv: (-kv[1]["sum"]))[:25]:
            print("CB_OWN_CUSTOMER " + json.dumps({"id": oid, "customer": cn, "n": x["n"], "sum": round(x["sum"]), "last": x["last"]}, ensure_ascii=False))
        # новые покупатели по 3 главным кодам за последние 12 мес
        own_c = set(cust)
        since12 = (now - timedelta(days=365)).date().isoformat()
        newc = defaultdict(lambda: {"n": 0, "sum": 0.0, "last": "", "from": Counter()})
        for c, _ in codes.most_common(3):
            for k in contracts({"enstru_code": c, "sign_date__gte": since12}, 1500):
                cn = k.get("customer_organization_name") or ""
                if cn in own_c:
                    continue
                x = newc[cn]; x["n"] += 1; x["sum"] += float(k.get("contract_price_with_vat") or 0); x["last"] = max(x["last"], k.get("sign_date") or "")
                x["from"][k.get("supplier_organization_name") or ""] += 1
        print("CB_NEW_TOTAL " + json.dumps({"id": oid, "new_customers": len(newc)}))
        for cn, x in sorted(newc.items(), key=lambda kv: (-kv[1]["sum"]))[:25]:
            print("CB_NEW_CUSTOMER " + json.dumps({"id": oid, "customer": cn, "n": x["n"], "sum": round(x["sum"]), "last": x["last"],
                                                   "bought_from": x["from"].most_common(1)[0][0]}, ensure_ascii=False))
        # открытые лоты по главным кодам
        for c, _ in codes.most_common(3):
            try:
                res = get("/lots/", {"enstru_key": c, "limit": 100}).get("results") or []
            except Exception as e:
                print("CB_OPEN_ERR " + json.dumps({"code": c, "err": str(e)[:200]}, ensure_ascii=False)); res = []
            for lot in res:
                st = (lot.get("status") or {}).get("id")
                if st in z.ACTIVE_STATUS_IDS and z._future(lot.get("offer_end_date"), now) and lot.get("enstru_key") == c:
                    rec = z.to_record(lot, c)
                    print("CB_OPEN " + json.dumps({"id": oid, "code": c, "customer": rec["customer_name"], "title": rec["title"],
                                                   "amount": rec["amount_kzt"], "end": rec["end_date"], "url": rec["public_url"]}, ensure_ascii=False))
            time.sleep(0.4)


if __name__ == "__main__":
    main()
