"""Диагностика Goszakup GraphQL (только чтение): фильтры Lots и коды статусов."""
import json, os, requests
from collections import Counter
import collector_goszakup as c
tok = os.environ["TRKZ_TEST_GOSZAKUP_TOKEN"]
H = {"Content-Type": "application/json", "Authorization": f"Bearer {tok}"}
def q(query, variables=None):
    r = requests.post(c.GRAPHQL_URL, headers=H, json={"query": query, "variables": variables or {}}, timeout=(20, 90))
    return r.json()
intro = q('{ __type(name:"LotsFiltersInput"){ inputFields { name type { name kind ofType { name } } } } }')
print("PROBE filters " + json.dumps(intro, ensure_ascii=False)[:3000])
d = q("query($f:LotsFiltersInput){Lots(limit:200, filter:$f){id refLotStatusId lastUpdateDate TrdBuy{refBuyStatusId RefBuyStatus{nameRu} endDate}}}",
      {"f": {"nameDescriptionRu": "освещение"}})
lots = (d.get("data") or {}).get("Lots") or []
print("PROBE errors " + json.dumps(d.get("errors"), ensure_ascii=False)[:800])
cnt = Counter((l.get("refLotStatusId"), (l.get("TrdBuy") or {}).get("refBuyStatusId"), ((l.get("TrdBuy") or {}).get("RefBuyStatus") or {}).get("nameRu")) for l in lots)
print("PROBE status_codes " + json.dumps([[list(k), v] for k, v in cnt.most_common()], ensure_ascii=False))
ids = [l["id"] for l in lots]
print("PROBE ids " + (f"{min(ids)} .. {max(ids)} first={ids[0]} last={ids[-1]}" if ids else "-"))
