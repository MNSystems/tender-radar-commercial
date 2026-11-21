"""Логистика: перевозчики и заказчики перевозок (только чтение).

--mode codes   : по фразам находит лоты и печатает, какие коды ЕНС ТРУ у них встречаются (LG_CODE)
--mode orgprobe: печатает все поля организации (LG_ORG_FIELDS) — чтобы понять, есть ли руководитель и телефон
--mode run     : по префиксам кодов берёт договоры за N месяцев ->
                 исполнители-перевозчики (LG_SUPPLIER, с данными организации) и заказчики (LG_CUSTOMER)
"""
import argparse, json, time
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import requests
import collector_zakup as z

BASE = "https://zakup.gov.kz/api/core/api/public"


def get(path, params=None, attempts=6):
    last = None
    for i in range(attempts):
        try:
            r = requests.get(BASE + path, params=params or {}, headers=z.HEADERS, timeout=(20, 60))
            if r.status_code == 200:
                return r.json()
            last = RuntimeError(f"HTTP {r.status_code} {r.text[:200]}")
            if r.status_code in (400, 404):
                raise last
        except requests.RequestException as e:
            last = e
        time.sleep(4 + i * 6)
    raise last


def mode_codes(phrases):
    cnt = Counter(); names = {}
    for ph in phrases:
        for off in range(0, 1000, 100):
            try:
                res = get("/lots/", {"q": ph, "limit": 100, "offset": off}).get("results") or []
            except Exception as e:
                print("LG_ERR", ph, e); break
            for lot in res:
                for e in lot.get("enstrus") or []:
                    c = e.get("code") or ""
                    cnt[c] += 1
                    names.setdefault(c, e.get("name_ru") or e.get("name") or "")
            time.sleep(0.3)
            if len(res) < 100:
                break
    for c, n in cnt.most_common(80):
        print("LG_CODE " + json.dumps({"code": c, "lots": n, "name": names.get(c, "")}, ensure_ascii=False))


def org_info(oid):
    for path, params in ((f"/organizations/{oid}/", None), ("/organizations/", {"q": oid, "limit": 3})):
        try:
            d = get(path, params)
        except Exception:
            continue
        if isinstance(d, dict) and d.get("results") is not None:
            rs = d.get("results") or []
            d = next((r for r in rs if str(r.get("id")) == str(oid)), rs[0] if rs else None)
        if d:
            return d
    return None


def mode_orgprobe(ids):
    for oid in ids:
        d = org_info(oid)
        print("LG_ORG_FIELDS " + json.dumps(d, ensure_ascii=False)[:4000])
        time.sleep(0.5)


def discover(prefixes, maxn=40):
    codes = []
    for pre in prefixes:
        miss = 0
        for n in range(0, maxn):
            c = f"{pre}.{n:06d}"
            try:
                cnt = get("/contracts/", {"enstru_code": c, "limit": 1}).get("count") or 0
            except Exception:
                cnt = 0
            time.sleep(0.2)
            if cnt:
                codes.append(c); miss = 0
                print("LG_FOUND_CODE " + json.dumps({"code": c, "all_contracts": cnt}))
            else:
                miss += 1
                if miss >= 8 and n > 10:
                    break
    return codes


def mode_run(prefixes, codes_extra, months, cap_per_code, max_orgs):
    since = (datetime.now(timezone.utc) - timedelta(days=30 * months)).date().isoformat()
    codes = discover(prefixes) + [c for c in codes_extra if c]
    cust = defaultdict(lambda: {"n": 0, "sum": 0.0, "last": "", "sup": Counter(), "id": None, "bin": ""})
    supp = defaultdict(lambda: {"n": 0, "sum": 0.0, "last": "", "cust": Counter(), "name": "", "bin": "", "codes": Counter()})
    for c in codes:
        for off in range(0, cap_per_code, 100):
            try:
                res = get("/contracts/", {"enstru_code": c, "sign_date__gte": since, "ordering": "-sign_date", "limit": 100, "offset": off}).get("results") or []
            except Exception as e:
                print("LG_ERR", c, off, e); break
            for k in res:
                cn = k.get("customer_organization_name") or ""; sn = k.get("supplier_organization_name") or ""
                sid = k.get("supplier_organization_id") or sn
                p = float(k.get("contract_price_with_vat") or 0); d = k.get("sign_date") or ""
                x = cust[cn]; x["n"] += 1; x["sum"] += p; x["last"] = max(x["last"], d); x["sup"][sn] += 1
                x["id"] = k.get("customer_organization_id"); x["bin"] = k.get("customer_bin") or k.get("customer_organization_bin") or x["bin"]
                y = supp[sid]; y["n"] += 1; y["sum"] += p; y["last"] = max(y["last"], d); y["cust"][cn] += 1; y["name"] = sn; y["codes"][c] += 1
                y["bin"] = k.get("supplier_bin") or k.get("supplier_organization_bin") or y["bin"]
            time.sleep(0.3)
            if len(res) < 100:
                break
    print("LG_CONTRACT_KEYS_SAMPLE " + json.dumps(sorted(k.keys()) if codes and 'k' in dir() else []))
    for cn, x in sorted(cust.items(), key=lambda kv: -kv[1]["sum"]):
        print("LG_CUSTOMER " + json.dumps({"customer": cn, "id": x["id"], "bin": x["bin"], "n": x["n"], "sum": round(x["sum"]), "last": x["last"],
                                           "suppliers": [s for s, _ in x["sup"].most_common(3)]}, ensure_ascii=False))
    ranked = sorted(supp.items(), key=lambda kv: -kv[1]["n"])
    for i, (sid, y) in enumerate(ranked):
        info = org_info(sid) if (i < max_orgs and isinstance(sid, int)) else None
        if info is not None:
            time.sleep(0.35)
        print("LG_SUPPLIER " + json.dumps({"id": sid, "name": y["name"], "bin": y["bin"], "n": y["n"], "sum": round(y["sum"]), "last": y["last"],
                                           "codes": dict(y["codes"]), "customers": [s for s, _ in y["cust"].most_common(3)], "org": info}, ensure_ascii=False))
    print("SUMMARY " + json.dumps({"codes": codes, "customers": len(cust), "suppliers": len(supp)}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="codes")
    ap.add_argument("--phrases", default="")
    ap.add_argument("--prefixes", default="")
    ap.add_argument("--codes", default="")
    ap.add_argument("--ids", default="")
    ap.add_argument("--months", type=int, default=24)
    ap.add_argument("--cap", type=int, default=3000)
    ap.add_argument("--max_orgs", type=int, default=1500)
    a = ap.parse_args()
    sp = lambda s: [x.strip() for x in s.split(",") if x.strip()]
    if a.mode == "codes":
        mode_codes(sp(a.phrases))
    elif a.mode == "orgprobe":
        mode_orgprobe(sp(a.ids))
    else:
        mode_run(sp(a.prefixes), sp(a.codes), a.months, a.cap, a.max_orgs)


if __name__ == "__main__":
    main()
