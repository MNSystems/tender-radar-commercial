"""Пробный запрос к открытому API zakup.gov.kz (только чтение, без токена)."""
import json, requests
B = "https://zakup.gov.kz/api/core/api/public/"
H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
def show(path, params=None, full=False):
    try:
        r = requests.get(B + path, params=params, headers=H, timeout=(20, 60))
        j = r.json()
        if r.status_code != 200:
            print(f"ZAKUP {params} -> {r.status_code} {json.dumps(j, ensure_ascii=False)[:300]}"); return
        res = j.get("results") or []
        print(f"ZAKUP {params} -> 200 count={j.get('count')}")
        if full: print("ZAKUP facets " + json.dumps(j.get("facets"), ensure_ascii=False)[:2500])
        for x in res[:5]:
            print("ZAKUP   ", x.get("lot_number"), "|", x.get("status_name"), "|", (x.get("name_ru") or x.get("announcement_name_ru") or "")[:70], "|", x.get("total_price"), "|", x.get("offer_end_date") or x.get("announcement_publish_date"))
    except Exception as e:
        print(f"ZAKUP {params} ERROR {e!r}"[:300])
from collections import Counter
r=requests.get(B+"lots/",params={"status_id":6,"limit":1},headers=H,timeout=60).json(); print("ZAKUP active6 count", r.get("count"))
c=Counter(); ends=[]
import time
for off in range(0,1000,100):
    j=requests.get(B+"lots/",params={"limit":100,"offset":off},headers=H,timeout=60).json()
    for x in j.get("results",[]):
        st=x.get("status") or {}; c[(st.get("id"),st.get("name"),st.get("is_active"))]+=1
    time.sleep(0.1)
print("ZAKUP newest1000 statuses", json.dumps([[list(k),v] for k,v in c.most_common()],ensure_ascii=False))
t=time.time(); j=requests.get(B+"lots/",params={"status_id":6,"limit":100,"offset":5000},headers=H,timeout=60); print("ZAKUP deep page", j.status_code, round(time.time()-t,1), len(j.json().get("results",[])))
x=j.json().get("results",[{}])[0]; print("ZAKUP deep sample", x.get("lot_number"), x.get("announcement_publish_date"), x.get("offer_end_date"), sorted(x.keys()))
