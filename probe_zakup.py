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
for p in [{"q":"освещение","status_id":6},{"q":"освещение","status":6},{"q":"освещение","is_active":"true"},{"q":"освещение","status_id":"6,7,8"},{"q":"освещение","ordering":"-announcement_publish_date"},{"q":"освещение","offset":100},{"q":"освещение","status_id":6,"limit":100}]:
    p.setdefault("limit",5); show("lots/", p)
