"""Пробный запрос к открытому API zakup.gov.kz (только чтение, без токена)."""
import json, requests, time
from datetime import datetime, timezone
B = "https://zakup.gov.kz/api/core/api/public/"
H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
def get(p):
    for a in range(3):
        try:
            r = requests.get(B + "lots/", params=p, headers=H, timeout=(20, 60)); return r.status_code, r.json()
        except Exception as e: err = e; time.sleep(2)
    return 0, {"err": repr(err)}
now = datetime.now(timezone.utc)
for kw in ["освещение", "светильник", "уборка", "картридж"]:
    for st in [6, 7, 9]:
        c, j = get({"q": kw, "status_id": st, "limit": 100})
        res = j.get("results", []) if isinstance(j, dict) else []
        fut = [x for x in res if x.get("offer_end_date") and datetime.fromisoformat(x["offer_end_date"]) > now]
        print(f"ZAKUP q={kw} st={st} -> {c} count={j.get('count')} got={len(res)} open_future={len(fut)}")
        for x in fut[:2]: print("ZAKUP    ", x.get("name_ru","")[:60], "|", x.get("status_name"), "|", x.get("total_price"), "|", x.get("offer_end_date"), "| ext", x.get("external_id"), x.get("announcement_external_id"))
# rate of new lots
c, j = get({"limit": 100, "offset": 0}); a = j["results"][0]["announcement_publish_date"]
c, j = get({"limit": 100, "offset": 2000}); b = j["results"][0]["announcement_publish_date"]
print("ZAKUP newest", a, "offset2000", b)
x = get({"limit": 1, "status_id": 7})[1]["results"][0]; print("ZAKUP sample7 " + json.dumps(x, ensure_ascii=False)[:2500])
