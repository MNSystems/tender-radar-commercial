"""Самрук (system_id=3, SKK) на zakup.gov.kz: свежесть и открытые лоты (только чтение)."""
import json, requests, time
from collections import Counter
from datetime import datetime, timezone
B="https://zakup.gov.kz/api/core/api/public/lots/"
H={"User-Agent":"Mozilla/5.0","Accept":"application/json"}
def g(p): return requests.get(B,params=p,headers=H,timeout=(20,60)).json()
now=datetime.now(timezone.utc)
def fut(v):
    try: return datetime.fromisoformat(str(v)) > now
    except Exception: return False
for sys_id in [3,2]:
    j=g({"system_id":sys_id,"limit":100})
    res=j.get("results",[])
    st=Counter(((x.get("status") or {}).get("id"),x.get("status_name")) for x in res)
    print("SK sys",sys_id,"newest publish", res[0].get("announcement_publish_date") if res else None, "statuses", json.dumps([[list(k),v] for k,v in st.most_common(8)],ensure_ascii=False))
    print("SK sample", json.dumps({k:res[0].get(k) for k in ["lot_number","name_ru","organization_name","customers","offer_end_date","external_id","announcement_external_id","announcement_number","purchase_method_name","total_price","delivery_addresses"]},ensure_ascii=False)[:1200])
    for kw in ["картридж","освещение","светильник","стеллаж"]:
        j=g({"q":kw,"system_id":sys_id,"limit":100}); res=j.get("results",[])
        op=[x for x in res if fut(x.get("offer_end_date"))]
        sc=Counter(((x.get("status") or {}).get("id"),x.get("status_name")) for x in op)
        print("SK sys",sys_id,kw,"count",j.get("count"),"open_in_first100",len(op), json.dumps([[list(k),v] for k,v in sc.most_common()],ensure_ascii=False))
        time.sleep(0.15)
