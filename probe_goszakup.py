"""Диагностика Goszakup GraphQL (только чтение): справочник статусов и свежие лоты."""
import json, os, requests
from collections import Counter
import collector_goszakup as c
tok = os.environ["TRKZ_TEST_GOSZAKUP_TOKEN"]
H = {"Content-Type": "application/json", "Authorization": f"Bearer {tok}"}
def q(query, variables=None):
    r = requests.post(c.GRAPHQL_URL, headers=H, json={"query": query, "variables": variables or {}}, timeout=(20, 90))
    return r.json()
t = q('{ __schema { queryType { fields { name } } } }')
names = [f["name"] for f in t["data"]["__schema"]["queryType"]["fields"]]
print("PROBE queries " + ",".join(n for n in names if "tatus" in n or n.startswith("Lots") or n.startswith("TrdBuy")))
for n in names:
    if "LotStatus" in n or "LotsStatus" in n or "BuyStatus" in n:
        print("PROBE ref " + n + " " + json.dumps(q("{ %s { id nameRu } }" % n), ensure_ascii=False)[:1500])
def stat(label, f):
    d = q("query($f:LotsFiltersInput){Lots(limit:200, filter:$f){id refLotStatusId nameRu TrdBuy{RefBuyStatus{nameRu} endDate}}}", {"f": f})
    lots = (d.get("data") or {}).get("Lots") or []
    cnt = Counter((l.get("refLotStatusId"), ((l.get("TrdBuy") or {}).get("RefBuyStatus") or {}).get("nameRu")) for l in lots)
    print(f"PROBE {label} n={len(lots)} err={json.dumps(d.get('errors'), ensure_ascii=False)[:300]} " + json.dumps([[list(k), v] for k, v in cnt.most_common()], ensure_ascii=False))
    return lots
stat("fresh", {"lastUpdateDate": ["2026-11-14", "2026-11-17"]})
for sid in ([210], [220], [230], [240], [250]):
    lots = stat(f"osv_status{sid}", {"nameDescriptionRu": "освещение", "refLotStatusId": sid})
    for l in lots[:3]:
        print("PROBE sample " + json.dumps(l, ensure_ascii=False)[:300])
