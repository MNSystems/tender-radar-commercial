"""Есть ли закупки Самрука на zakup.gov.kz (только чтение)."""
import json, requests, time
from collections import Counter
B="https://zakup.gov.kz/api/core/api/public/lots/"
H={"User-Agent":"Mozilla/5.0","Accept":"application/json"}
def g(p): return requests.get(B,params=p,headers=H,timeout=(20,60)).json()
c=Counter(); ex={}
for off in range(0,2000,100):
    for x in g({"limit":100,"offset":off}).get("results",[]):
        s=x.get("system") or {}; k=(s.get("id"),s.get("name")); c[k]+=1; ex.setdefault(k,x)
    time.sleep(0.1)
print("SK systems newest2000", json.dumps([[list(k),v] for k,v in c.most_common()],ensure_ascii=False))
for k,x in ex.items():
    if k[0]!=1: print("SK sample", k, json.dumps({kk:x.get(kk) for kk in ["lot_number","name_ru","organization_name","status","status_name","offer_end_date","external_id","announcement_external_id","announcement_number","purchase_method_name","total_price"]},ensure_ascii=False)[:900])
for sid in [2,3,4,5]:
    j=g({"system_id":sid,"limit":2})
    print("SK filter system_id",sid,"count",j.get("count"), "first", (j.get("results") or [{}])[0].get("system"))
j=g({"q":"картридж","system_id":2,"limit":5})
print("SK q картридж sys2 count", j.get("count"), [ (x.get("name_ru"),x.get("status_name"),x.get("offer_end_date")) for x in j.get("results",[])][:5])
